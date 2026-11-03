#!/usr/bin/env python3
"""Detect domain model drift by comparing the same entity across two repositories."""

import argparse
import json
import os
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Layer 1 — Deterministic checks
# ---------------------------------------------------------------------------

SEARCHABLE_EXTENSIONS = {".groovy", ".java", ".kt", ".cs"}


def find_entity_files(repo_path: str, entity_name: str) -> list[Path]:
    """Find files containing `class <entity_name>` in supported file types."""
    results = []
    root = Path(repo_path)
    if not root.is_dir():
        return results
    for ext in SEARCHABLE_EXTENSIONS:
        for filepath in root.rglob(f"*{ext}"):
            try:
                text = filepath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if re.search(rf"\bclass\s+{re.escape(entity_name)}\b", text):
                results.append(filepath)
    return results


def parse_groovy_constraints(source: str) -> dict[str, dict]:
    """Parse the `static constraints` block from a Groovy/GORM source file.

    Returns a dict keyed by field name, each value a dict of constraints:
    {nullable, blank, unique, maxSize, validator_present}.
    """
    # Extract the constraints block body
    match = re.search(r"static\s+constraints\s*=\s*\{", source)
    if not match:
        return {}

    start = match.end()
    depth = 1
    pos = start
    while pos < len(source) and depth > 0:
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
        pos += 1
    block = source[start : pos - 1]

    constraints: dict[str, dict] = {}
    # Process the block line-by-line, joining continuation lines
    lines = block.split("\n")
    merged: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # A new field line starts with a word followed by a constraint keyword
        if merged and re.match(r"^[a-zA-Z_]\w*\s+\w+\s*:", stripped):
            merged.append(stripped)
        elif merged:
            merged[-1] += " " + stripped
        else:
            merged.append(stripped)

    for line in merged:
        m = re.match(r"^([a-zA-Z_]\w*)\s+(.+)$", line)
        if not m:
            continue
        field_name = m.group(1)
        rest = m.group(2)
        c = _parse_constraint_pairs(rest)
        if c:
            constraints[field_name] = c

    return constraints


def _parse_constraint_pairs(text: str) -> dict:
    """Parse constraint key-value pairs from a single field's constraint text."""
    c: dict = {}

    # nullable
    m = re.search(r"\bnullable\s*:\s*(true|false)", text)
    if m:
        c["nullable"] = m.group(1) == "true"

    # blank
    m = re.search(r"\bblank\s*:\s*(true|false)", text)
    if m:
        c["blank"] = m.group(1) == "true"

    # maxSize
    m = re.search(r"\bmaxSize\s*:\s*(\d+)", text)
    if m:
        c["maxSize"] = int(m.group(1))

    # unique — either `true`/`false` or `['field', ...]`
    m = re.search(r"\bunique\s*:\s*(true|false|\[.*?\])", text)
    if m:
        raw = m.group(1)
        if raw == "true":
            c["unique"] = True
        elif raw == "false":
            c["unique"] = False
        else:
            # Parse list like ['domain']
            items = re.findall(r"'([^']*)'", raw)
            c["unique"] = items if items else raw

    # validator — detect presence (may be multi-line closure)
    if re.search(r"\bvalidator\s*:", text):
        c["validator_present"] = True

    return c


def parse_field_declarations(source: str, entity_name: str) -> dict[str, str]:
    """Extract field declarations (type + name) from a class body."""
    # Find class body
    m = re.search(rf"\bclass\s+{re.escape(entity_name)}\b[^{{]*\{{", source)
    if not m:
        return {}

    start = m.end()
    depth = 1
    pos = start
    while pos < len(source) and depth > 0:
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
        pos += 1
    body = source[start : pos - 1]

    fields: dict[str, str] = {}
    for line in body.split("\n"):
        stripped = line.strip()
        # Match simple field declarations: Type name
        fm = re.match(r"^([A-Z]\w*(?:<[^>]+>)?)\s+([a-z]\w*)\s*$", stripped)
        if fm:
            fields[fm.group(2)] = fm.group(1)
    return fields


def compare_fields(fields_a: dict[str, str], fields_b: dict[str, str]) -> list[dict]:
    """Compare field declarations between two files."""
    diffs = []
    all_fields = sorted(set(fields_a) | set(fields_b))
    for name in all_fields:
        type_a = fields_a.get(name)
        type_b = fields_b.get(name)
        if type_a and not type_b:
            diffs.append({
                "field": name,
                "constraint": "declaration",
                "repo_a_value": type_a,
                "repo_b_value": "not declared",
                "severity": "critical",
            })
        elif type_b and not type_a:
            diffs.append({
                "field": name,
                "constraint": "declaration",
                "repo_a_value": "not declared",
                "repo_b_value": type_b,
                "severity": "critical",
            })
        elif type_a != type_b:
            diffs.append({
                "field": name,
                "constraint": "type",
                "repo_a_value": type_a,
                "repo_b_value": type_b,
                "severity": "critical",
            })
    return diffs


def _severity_for(constraint_key: str) -> str:
    """Determine severity for a constraint mismatch."""
    if constraint_key in ("nullable", "unique"):
        return "critical"
    if constraint_key == "blank":
        return "critical"
    if constraint_key == "validator_present":
        return "warning"
    if constraint_key == "maxSize":
        return "info"
    return "info"


def _format_value(val) -> str:
    """Format a constraint value for display."""
    if val is None:
        return "not set"
    if isinstance(val, bool):
        return str(val).lower()
    return str(val)


def compare_constraints(
    constraints_a: dict[str, dict],
    constraints_b: dict[str, dict],
) -> list[dict]:
    """Compare constraints field-by-field between two repos."""
    diffs = []
    all_fields = sorted(set(constraints_a) | set(constraints_b))

    for field in all_fields:
        ca = constraints_a.get(field, {})
        cb = constraints_b.get(field, {})
        all_keys = sorted(set(ca) | set(cb))

        for key in all_keys:
            val_a = ca.get(key)
            val_b = cb.get(key)
            if val_a != val_b:
                diffs.append({
                    "field": field,
                    "constraint": key,
                    "repo_a_value": _format_value(val_a),
                    "repo_b_value": _format_value(val_b),
                    "severity": _severity_for(key),
                })

    return diffs


def run_deterministic_checks(
    repo_a: str,
    repo_b: str,
    entity_name: str,
) -> dict:
    """Run all deterministic checks. Returns structured result."""
    files_a = find_entity_files(repo_a, entity_name)
    files_b = find_entity_files(repo_b, entity_name)

    if not files_a:
        return {"error": f"Entity '{entity_name}' not found in repo A: {repo_a}"}
    if not files_b:
        return {"error": f"Entity '{entity_name}' not found in repo B: {repo_b}"}

    # Use the first match in each repo
    file_a, file_b = files_a[0], files_b[0]
    source_a = file_a.read_text(encoding="utf-8", errors="replace")
    source_b = file_b.read_text(encoding="utf-8", errors="replace")

    fields_a = parse_field_declarations(source_a, entity_name)
    fields_b = parse_field_declarations(source_b, entity_name)
    field_diffs = compare_fields(fields_a, fields_b)

    constraints_a = parse_groovy_constraints(source_a)
    constraints_b = parse_groovy_constraints(source_b)
    constraint_diffs = compare_constraints(constraints_a, constraints_b)

    return {
        "file_a": str(file_a),
        "file_b": str(file_b),
        "source_a": source_a,
        "source_b": source_b,
        "fields_a": fields_a,
        "fields_b": fields_b,
        "constraints_a": {k: _serialize_constraints(v) for k, v in constraints_a.items()},
        "constraints_b": {k: _serialize_constraints(v) for k, v in constraints_b.items()},
        "field_diffs": field_diffs,
        "constraint_diffs": constraint_diffs,
    }


def _serialize_constraints(c: dict) -> dict:
    """Make constraint values JSON-serializable."""
    out = {}
    for k, v in c.items():
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Layer 2 — LLM review
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a domain model consistency reviewer. You are given two versions of the same \
entity from different repositories (e.g., an admin service and a lookup service) and a \
structured diff of their constraint mismatches.

Analyze each mismatch and provide:
1. Behavioral impact — what happens at runtime in each repo (e.g., "admin rejects empty path but lookup accepts it")
2. Data integrity risk — could this cause data corruption, silent failures, or inconsistencies
3. Risk level — critical / warning / info
4. Recommendation — what to align and in which direction

Respond with JSON:
{
  "mismatches": [
    {
      "field": "fieldName",
      "constraint": "constraintName",
      "behavioral_impact": "description of runtime difference",
      "data_risk": "description of data integrity risk",
      "risk": "critical|warning|info",
      "recommendation": "what to do"
    }
  ],
  "overall_risk": "critical|warning|clean",
  "summary": "overall assessment and recommended actions"
}

Respond ONLY with valid JSON, no markdown fences."""


def run_llm_review(det_result: dict, api_key: str) -> dict | None:
    """Send both model sources and the structured diff to Claude for review."""
    try:
        import anthropic
    except ImportError:
        print("⚠️  anthropic package not installed. Run: pip install anthropic", file=sys.stderr)
        return None

    source_a = det_result["source_a"]
    source_b = det_result["source_b"]
    diffs = det_result["field_diffs"] + det_result["constraint_diffs"]

    if not diffs:
        return {"mismatches": [], "overall_risk": "clean", "summary": "No mismatches found."}

    user_message = (
        f"## Repo A — {det_result['file_a']}\n```groovy\n{source_a}\n```\n\n"
        f"## Repo B — {det_result['file_b']}\n```groovy\n{source_b}\n```\n\n"
        f"## Structured Diff\n```json\n{json.dumps(diffs, indent=2)}\n```"
    )

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
    response = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "eu.anthropic.claude-sonnet-4-6"),
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    text = response.content[0].text.strip()
    # Strip markdown fences if the model added them despite instructions
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"⚠️  Could not parse LLM response as JSON:\n{text}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Layer 3 — Output formatting
# ---------------------------------------------------------------------------

SEVERITY_ICON = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}


def format_deterministic(entity_name: str, det_result: dict) -> str:
    """Format deterministic check results as markdown."""
    lines = [
        "## Deterministic Checks\n",
        f"**Repo A:** `{det_result['file_a']}`  ",
        f"**Repo B:** `{det_result['file_b']}`\n",
    ]

    field_diffs = det_result["field_diffs"]
    constraint_diffs = det_result["constraint_diffs"]
    all_diffs = field_diffs + constraint_diffs

    if not all_diffs:
        lines.append("✅ **No mismatches found** — constraints are identical in both repos.")
        return "\n".join(lines)

    # Summary counts
    crit = sum(1 for d in all_diffs if d["severity"] == "critical")
    warn = sum(1 for d in all_diffs if d["severity"] == "warning")
    info = sum(1 for d in all_diffs if d["severity"] == "info")
    lines.append(f"Found **{len(all_diffs)}** mismatch(es): 🔴 {crit} critical, 🟡 {warn} warning, ℹ️ {info} info\n")

    # Constraint comparison table
    lines.append("| Field | Constraint | Repo A | Repo B | Severity |")
    lines.append("|-------|-----------|--------|--------|----------|")
    for d in all_diffs:
        icon = SEVERITY_ICON.get(d["severity"], "❓")
        lines.append(
            f"| `{d['field']}` | `{d['constraint']}` "
            f"| {d['repo_a_value']} | {d['repo_b_value']} "
            f"| {icon} {d['severity']} |"
        )

    return "\n".join(lines)


def format_llm_review(data: dict) -> str:
    """Format LLM review results as markdown."""
    lines = ["## LLM Behavioral Impact Assessment\n"]
    overall = data.get("overall_risk", "unknown")
    icon = SEVERITY_ICON.get(overall, "⚪")
    lines.append(f"**Overall Risk: {icon} {overall}**\n")

    for m in data.get("mismatches", []):
        mi = SEVERITY_ICON.get(m.get("risk", ""), "❓")
        lines.append(f"### {mi} `{m['field']}.{m['constraint']}`")
        lines.append(f"- **Impact:** {m.get('behavioral_impact', 'N/A')}")
        lines.append(f"- **Data risk:** {m.get('data_risk', 'N/A')}")
        lines.append(f"- **Recommendation:** {m.get('recommendation', 'N/A')}")
        lines.append("")

    lines.append(f"**Summary:** {data.get('summary', 'No summary.')}")
    return "\n".join(lines)


def format_output(
    entity_name: str,
    repo_a: str,
    repo_b: str,
    det_result: dict,
    llm_result: dict | None,
) -> str:
    """Combine all results into a single markdown report."""
    parts = [
        f"# Model Drift Report: `{entity_name}`\n",
        f"Comparing **{repo_a}** ↔ **{repo_b}**\n",
        format_deterministic(entity_name, det_result),
    ]
    if llm_result:
        parts.append("")
        parts.append(format_llm_review(llm_result))
    else:
        parts.append("\n> ℹ️ LLM review skipped (no API key or error).")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect domain model drift between two repositories.",
    )
    parser.add_argument("repo_a", help="Path to the first repository.")
    parser.add_argument("repo_b", help="Path to the second repository.")
    parser.add_argument("entity", help="Entity class name to compare (e.g. DnsRedirect).")
    parser.add_argument("--api-key", default=None, help="Anthropic API key (or set ANTHROPIC_API_KEY).")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of markdown.")
    args = parser.parse_args()

    for label, path in [("Repo A", args.repo_a), ("Repo B", args.repo_b)]:
        if not Path(path).is_dir():
            print(f"Error: {label} path not found: {path}", file=sys.stderr)
            return 1

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")

    # Layer 1
    det_result = run_deterministic_checks(args.repo_a, args.repo_b, args.entity)
    if "error" in det_result:
        print(f"Error: {det_result['error']}", file=sys.stderr)
        return 1

    # Layer 2
    llm_result = None
    all_diffs = det_result["field_diffs"] + det_result["constraint_diffs"]
    if api_key and all_diffs:
        llm_result = run_llm_review(det_result, api_key)
    elif not api_key and all_diffs:
        print("⚠️  No API key provided — skipping LLM review.", file=sys.stderr)

    # Layer 3
    if args.json:
        output = {
            "entity": args.entity,
            "repo_a": args.repo_a,
            "repo_b": args.repo_b,
            "file_a": det_result["file_a"],
            "file_b": det_result["file_b"],
            "field_diffs": det_result["field_diffs"],
            "constraint_diffs": det_result["constraint_diffs"],
            "llm": llm_result,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_output(args.entity, args.repo_a, args.repo_b, det_result, llm_result))

    # Exit code: 1 if any critical mismatches
    has_critical = any(d["severity"] == "critical" for d in all_diffs)
    if llm_result and llm_result.get("overall_risk") == "critical":
        has_critical = True
    return 1 if has_critical else 0


if __name__ == "__main__":
    sys.exit(main())
