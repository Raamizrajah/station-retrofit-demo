#!/usr/bin/env python3
"""Detect breaking API contract changes between OpenAPI spec versions."""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from llm_utils import add_tone_arg, apply_tone

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Change:
    change_type: str  # enum_removed, property_renamed, endpoint_removed, field_required, safe_addition
    item: str
    severity: str  # breaking, warning, safe
    path: str = ""  # schema or endpoint path in spec
    detail: str = ""


@dataclass
class FrontendMatch:
    file: str
    line: int
    text: str
    related_change: str


@dataclass
class DriftReport:
    changes: list[Change] = field(default_factory=list)
    frontend_matches: list[FrontendMatch] = field(default_factory=list)
    llm_assessment: dict | None = None


# ---------------------------------------------------------------------------
# Layer 1 — Spec diffing
# ---------------------------------------------------------------------------

def load_spec(path_or_content: str, *, is_content: bool = False) -> dict:
    """Load an OpenAPI spec from a file path or raw content string."""
    if is_content:
        text = path_or_content
    else:
        text = Path(path_or_content).read_text(encoding="utf-8")

    if yaml is not None:
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError:
            pass
    return json.loads(text)


def get_old_spec_from_git(spec_path: str) -> str | None:
    """Retrieve the previous version of a spec from git (HEAD~1)."""
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD~1:{spec_path}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def _collect_endpoints(spec: dict) -> dict[str, set[str]]:
    """Return {path: {methods}} from an OpenAPI spec."""
    endpoints: dict[str, set[str]] = {}
    for path, methods in (spec.get("paths") or {}).items():
        if isinstance(methods, dict):
            endpoints[path] = {
                m.upper() for m in methods if m.lower() in
                ("get", "post", "put", "patch", "delete", "options", "head")
            }
    return endpoints


def _collect_schemas(spec: dict) -> dict[str, dict]:
    """Return {schema_name: schema_object} from components/schemas."""
    components = spec.get("components") or {}
    return dict((components.get("schemas") or {}).items())


def _collect_enum_values(schema: dict) -> dict[str, str]:
    """Collect enum values mapped to their display names.

    Returns {display_name: raw_value} using x-enum-varnames when available,
    falling back to raw values as both key and value.
    """
    values: dict[str, str] = {}
    if "enum" in schema:
        raw = schema["enum"]
        varnames = schema.get("x-enum-varnames", [])
        for i, v in enumerate(raw):
            name = varnames[i] if i < len(varnames) else str(v)
            values[name] = str(v)
    for prop in (schema.get("properties") or {}).values():
        if isinstance(prop, dict):
            values.update(_collect_enum_values(prop))
    return values


def _collect_properties(schema: dict) -> set[str]:
    """Return property names for a schema."""
    return set((schema.get("properties") or {}).keys())


def diff_specs(old_spec: dict, new_spec: dict) -> list[Change]:
    """Compare two OpenAPI specs and return categorized changes."""
    changes: list[Change] = []

    # --- Endpoints ---
    old_ep = _collect_endpoints(old_spec)
    new_ep = _collect_endpoints(new_spec)

    for path in old_ep:
        if path not in new_ep:
            changes.append(Change("endpoint_removed", path, "breaking", path, "Entire endpoint removed."))
        else:
            removed_methods = old_ep[path] - new_ep[path]
            for m in removed_methods:
                changes.append(Change("endpoint_removed", f"{m} {path}", "breaking", path, "HTTP method removed."))

    for path in new_ep:
        if path not in old_ep:
            changes.append(Change("safe_addition", path, "safe", path, "New endpoint added."))

    # --- Schemas ---
    old_schemas = _collect_schemas(old_spec)
    new_schemas = _collect_schemas(new_spec)

    for name in old_schemas:
        if name not in new_schemas:
            changes.append(Change("property_renamed", name, "breaking", f"schemas/{name}", "Entire schema removed."))
            continue

        old_s = old_schemas[name]
        new_s = new_schemas[name]

        # Enum values — compare by display name (x-enum-varnames when available)
        old_enums = _collect_enum_values(old_s)
        new_enums = _collect_enum_values(new_s)
        for removed_name in set(old_enums) - set(new_enums):
            changes.append(Change("enum_removed", f"{name}.{removed_name}", "breaking", f"schemas/{name}", f"Enum value '{removed_name}' removed."))

        # Properties
        old_props = _collect_properties(old_s)
        new_props = _collect_properties(new_s)
        removed_props = old_props - new_props
        added_props = new_props - old_props

        # Heuristic: if exactly one removed and one added, flag as rename
        if len(removed_props) == 1 and len(added_props) == 1:
            old_name = removed_props.pop()
            new_name = added_props.pop()
            changes.append(Change(
                "property_renamed",
                f"{name}.{old_name} → {new_name}",
                "breaking",
                f"schemas/{name}",
                f"Property appears renamed from '{old_name}' to '{new_name}'.",
            ))
        else:
            for rp in removed_props:
                changes.append(Change("property_renamed", f"{name}.{rp}", "breaking", f"schemas/{name}", f"Property '{rp}' removed."))
            for ap in added_props:
                changes.append(Change("safe_addition", f"{name}.{ap}", "safe", f"schemas/{name}", f"Property '{ap}' added."))

        # Required changes (optional → required)
        old_req = set(old_s.get("required") or [])
        new_req = set(new_s.get("required") or [])
        newly_required = (new_req - old_req) & old_props  # only flag for existing props
        for nr in newly_required:
            changes.append(Change("field_required", f"{name}.{nr}", "warning", f"schemas/{name}", f"Field '{nr}' changed from optional to required."))

    return changes


# ---------------------------------------------------------------------------
# Layer 2 — Frontend scanning
# ---------------------------------------------------------------------------

SCAN_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte"}


def scan_frontend(frontend_dir: str, changes: list[Change]) -> list[FrontendMatch]:
    """Grep the frontend directory for references to changed items."""
    matches: list[FrontendMatch] = []
    if not changes or not Path(frontend_dir).is_dir():
        return matches

    # Build search terms from changes
    search_terms: dict[str, str] = {}  # term → change item
    for c in changes:
        if c.severity == "safe":
            continue
        # Extract the meaningful token to search for
        item = c.item
        if "→" in item:
            # renamed: search for old name
            old_part = item.split("→")[0].strip()
            token = old_part.split(".")[-1]
        else:
            token = item.split(".")[-1] if "." in item else item
            # Strip HTTP method prefix
            token = re.sub(r"^(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+", "", token)
        if token and len(token) > 2:
            search_terms[token] = c.item

    if not search_terms:
        return matches

    for root, _dirs, files in os.walk(frontend_dir):
        for fname in files:
            if Path(fname).suffix not in SCAN_EXTENSIONS:
                continue
            fpath = Path(root) / fname
            try:
                lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, 1):
                for term, change_item in search_terms.items():
                    if term in line:
                        matches.append(FrontendMatch(
                            file=str(fpath),
                            line=lineno,
                            text=line.strip()[:200],
                            related_change=change_item,
                        ))
    return matches


# ---------------------------------------------------------------------------
# Layer 3 — LLM impact assessment
# ---------------------------------------------------------------------------

LLM_SYSTEM_PROMPT = """\
You are an API contract reviewer. A backend OpenAPI spec has changed.
Assess the impact on the frontend codebase.

For each change, respond with JSON:
{
  "changes": [
    {
      "type": "enum_removed|property_renamed|endpoint_removed|field_required|safe_addition",
      "item": "what changed",
      "severity": "breaking|warning|safe",
      "frontend_impact": ["file:line — description"],
      "suggestion": "what to do"
    }
  ],
  "summary": "overall assessment"
}

Respond ONLY with valid JSON, no markdown fences."""


def run_llm_assessment(changes: list[Change], frontend_matches: list[FrontendMatch], api_key: str, context: str = "", tone: str = "technical") -> dict | None:
    """Send the diff + frontend usage to Claude for impact assessment."""
    try:
        import anthropic
    except ImportError:
        print("⚠️  anthropic package not installed. Run: pip install anthropic", file=sys.stderr)
        return None

    changes_text = "\n".join(
        f"- [{c.severity}] {c.change_type}: {c.item} — {c.detail}" for c in changes
    )
    frontend_text = "\n".join(
        f"- {m.file}:{m.line} — `{m.text}` (relates to: {m.related_change})"
        for m in frontend_matches
    ) or "(no frontend references found)"

    user_message = (
        f"Spec changes:\n{changes_text}\n\n"
        f"Frontend files referencing changed items:\n{frontend_text}"
    )

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
    # Cap prompt to ~80K chars (~20K tokens) to avoid 413 from API gateway
    if len(user_message) > 80_000:
        user_message = user_message[:80_000] + "\n\n> ⚠️ Prompt truncated to fit API limits."
    if context:
        user_message = f"## 🎯 Focus Area\nFocus your analysis on: {context}\nPrioritize findings related to this area. Still report critical issues outside this scope, but keep the focus tight.\n\n" + user_message
    response = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "eu.anthropic.claude-sonnet-4-6"),
        max_tokens=2048,
        system=apply_tone(LLM_SYSTEM_PROMPT, tone),
        messages=[{"role": "user", "content": user_message}],
    )

    text = response.content[0].text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"⚠️  Could not parse LLM response as JSON:\n{text}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

SEVERITY_ICON = {"breaking": "🔴", "warning": "🟡", "safe": "🟢"}


def format_output(report: DriftReport) -> str:
    """Format the drift report as markdown."""
    lines = ["# API Contract Drift Report\n"]

    breaking = [c for c in report.changes if c.severity == "breaking"]
    warnings = [c for c in report.changes if c.severity == "warning"]
    safe = [c for c in report.changes if c.severity == "safe"]

    lines.append(f"**{len(breaking)} breaking** · {len(warnings)} warnings · {len(safe)} safe additions\n")

    if breaking:
        lines.append("## 🔴 Breaking Changes\n")
        for c in breaking:
            lines.append(f"- **{c.change_type}**: `{c.item}` — {c.detail}")

    if warnings:
        lines.append("\n## 🟡 Warnings\n")
        for c in warnings:
            lines.append(f"- **{c.change_type}**: `{c.item}` — {c.detail}")

    if safe:
        lines.append("\n## 🟢 Safe Additions\n")
        for c in safe:
            lines.append(f"- `{c.item}` — {c.detail}")

    if report.frontend_matches:
        lines.append("\n## Frontend Impact\n")
        grouped: dict[str, list[FrontendMatch]] = {}
        for m in report.frontend_matches:
            grouped.setdefault(m.related_change, []).append(m)
        for change_item, file_matches in grouped.items():
            lines.append(f"### `{change_item}`\n")
            for m in file_matches[:20]:  # cap per change
                lines.append(f"- `{m.file}:{m.line}` — `{m.text}`")

    if report.llm_assessment:
        lines.append("\n## LLM Assessment\n")
        llm = report.llm_assessment
        lines.append(f"**Summary:** {llm.get('summary', 'N/A')}\n")
        for item in llm.get("changes", []):
            icon = SEVERITY_ICON.get(item.get("severity", ""), "⚪")
            lines.append(f"- {icon} **{item.get('item', '?')}** ({item.get('type', '?')})")
            if item.get("suggestion"):
                lines.append(f"  - 💡 {item['suggestion']}")
            for impact in item.get("frontend_impact", []):
                lines.append(f"  - {impact}")
    elif not report.changes:
        lines.append("\n> ✅ No contract changes detected.")
    else:
        lines.append("\n> ℹ️ LLM assessment skipped (no API key or error).")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Detect breaking API contract changes.")
    parser.add_argument("--spec", required=True, help="Path to the current OpenAPI spec.")
    parser.add_argument("--frontend", required=True, help="Path to the frontend source directory.")
    parser.add_argument("--old-spec", default=None, help="Path to the old spec (default: git HEAD~1).")
    parser.add_argument("--api-key", default=None, help="Anthropic API key (or set ANTHROPIC_API_KEY).")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of markdown.")
    parser.add_argument("--context", default="", help="Focus area to sharpen analysis scope.")
    add_tone_arg(parser)
    args = parser.parse_args()

    if not Path(args.spec).is_file():
        print(f"Error: spec file not found: {args.spec}", file=sys.stderr)
        return 1

    if yaml is None:
        print("⚠️  pyyaml not installed — YAML specs will fail. Run: pip install pyyaml", file=sys.stderr)

    # Load specs
    new_spec = load_spec(args.spec)

    if args.old_spec:
        if args.old_spec == "-":
            old_content = sys.stdin.read()
            old_spec = load_spec(old_content, is_content=True)
        elif Path(args.old_spec).is_file():
            old_spec = load_spec(args.old_spec)
        else:
            # Treat as raw content (e.g. from process substitution)
            try:
                old_spec = load_spec(args.old_spec)
            except (FileNotFoundError, json.JSONDecodeError):
                print(f"Error: cannot load old spec from {args.old_spec}", file=sys.stderr)
                return 1
    else:
        old_content = get_old_spec_from_git(args.spec)
        if old_content is None:
            print("⚠️  Could not retrieve old spec from git. Comparing against empty spec.", file=sys.stderr)
            old_spec = {"paths": {}, "components": {"schemas": {}}}
        else:
            old_spec = load_spec(old_content, is_content=True)

    # Layer 1: Diff
    changes = diff_specs(old_spec, new_spec)

    # Layer 2: Frontend scan
    frontend_matches = scan_frontend(args.frontend, changes)

    # Layer 3: LLM
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    llm_result = None
    breaking_or_warning = [c for c in changes if c.severity != "safe"]
    if api_key and breaking_or_warning:
        llm_result = run_llm_assessment(changes, frontend_matches, api_key, args.context, args.tone)
    elif not api_key and breaking_or_warning:
        print("⚠️  No API key provided — skipping LLM assessment.", file=sys.stderr)

    report = DriftReport(changes=changes, frontend_matches=frontend_matches, llm_assessment=llm_result)

    if args.json:
        output = {
            "changes": [asdict(c) for c in report.changes],
            "frontend_matches": [asdict(m) for m in report.frontend_matches],
            "llm_assessment": report.llm_assessment,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_output(report))

    has_breaking = any(c.severity == "breaking" for c in changes)
    return 1 if has_breaking else 0


if __name__ == "__main__":
    sys.exit(main())
