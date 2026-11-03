#!/usr/bin/env python3
"""Review EF Core migration files using deterministic checks and LLM analysis."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from llm_utils import add_tone_arg, apply_tone


# ---------------------------------------------------------------------------
# Layer 1 — Deterministic checks
# ---------------------------------------------------------------------------

def check_exists_on_main(filepath: str) -> dict:
    """Check whether the migration file already exists on the main branch."""
    name = Path(filepath).name
    try:
        result = subprocess.run(
            ["git", "log", "--all", "--oneline", "--diff-filter=A", "--", f"*/{name}"],
            capture_output=True, text=True, timeout=10,
        )
        already_tracked = bool(result.stdout.strip())
    except (subprocess.SubprocessError, FileNotFoundError):
        already_tracked = False

    if already_tracked:
        return {
            "check": "Not already on main",
            "status": "FAIL",
            "detail": f"{name} appears in git history — this migration may already be applied.",
        }
    return {
        "check": "Not already on main",
        "status": "PASS",
        "detail": "Migration file is new.",
    }


def check_timestamp_ordering(filepath: str) -> dict:
    """Verify the migration timestamp is the latest in its directory."""
    path = Path(filepath)
    directory = path.parent
    migration_files = sorted(
        f.name for f in directory.glob("*.cs")
        if not f.name.endswith(".Designer.cs")
        and re.match(r"^\d{14}_", f.name)
    )
    if not migration_files:
        return {
            "check": "Timestamp ordering",
            "status": "N/A",
            "detail": "No sibling migration files found.",
        }

    if migration_files[-1] == path.name:
        return {
            "check": "Timestamp ordering",
            "status": "PASS",
            "detail": f"Migration is the latest ({path.name}).",
        }
    return {
        "check": "Timestamp ordering",
        "status": "FAIL",
        "detail": (
            f"Migration {path.name} is NOT the latest. "
            f"Latest is {migration_files[-1]}."
        ),
    }


def check_designer_file(filepath: str) -> dict:
    """Check that the .Designer.cs companion file exists."""
    designer = Path(filepath).with_suffix("").with_suffix(".Designer.cs")
    # Handle names like Foo.cs → Foo.Designer.cs
    if not designer.exists():
        stem = Path(filepath).stem  # e.g. 20260615_Foo
        designer = Path(filepath).parent / f"{stem}.Designer.cs"

    if designer.exists():
        return {
            "check": "Designer file exists",
            "status": "PASS",
            "detail": f"Found {designer.name}.",
        }
    return {
        "check": "Designer file exists",
        "status": "FAIL",
        "detail": "Missing .Designer.cs companion file — EF Core requires it.",
    }


def run_deterministic_checks(filepath: str) -> list[dict]:
    """Run all deterministic checks and return results."""
    return [
        check_exists_on_main(filepath),
        check_timestamp_ordering(filepath),
        check_designer_file(filepath),
    ]


# ---------------------------------------------------------------------------
# Layer 2 — LLM review
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a database migration reviewer for EF Core (.NET / PostgreSQL).
Review this migration against these rules:

1. Down() must fully reverse Up() — every table created must be dropped, every column added must be removed, and vice versa
2. Column drops must happen AFTER data backfill — never drop a column before its data is migrated elsewhere
3. Backfill SQL must be idempotent — use WHERE NOT EXISTS or ON CONFLICT DO NOTHING
4. Correct ordering in Up(): create table → backfill data → drop columns
5. Down() must restore ALL dropped columns with correct types and defaults
6. Down() must copy data back from new tables before dropping them

For each rule, respond with JSON:
{
  "rules": [
    {"id": 1, "name": "Down reverses Up", "status": "PASS|FAIL|N/A", "detail": "explanation"},
    {"id": 2, "name": "Drop after backfill", "status": "PASS|FAIL|N/A", "detail": "explanation"},
    {"id": 3, "name": "Idempotent backfill", "status": "PASS|FAIL|N/A", "detail": "explanation"},
    {"id": 4, "name": "Up ordering", "status": "PASS|FAIL|N/A", "detail": "explanation"},
    {"id": 5, "name": "Down restores columns", "status": "PASS|FAIL|N/A", "detail": "explanation"},
    {"id": 6, "name": "Down copies data back", "status": "PASS|FAIL|N/A", "detail": "explanation"}
  ],
  "summary": "overall assessment",
  "severity": "clean|warning|critical"
}

Respond ONLY with valid JSON, no markdown fences."""


def extract_method_body(source: str, method_name: str) -> str | None:
    """Extract the body of a method like Up() or Down() from C# source."""
    pattern = rf"protected\s+override\s+void\s+{method_name}\s*\("
    match = re.search(pattern, source)
    if not match:
        return None

    # Find the opening brace after the method signature
    brace_start = source.find("{", match.end())
    if brace_start == -1:
        return None

    depth = 1
    pos = brace_start + 1
    while pos < len(source) and depth > 0:
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
        pos += 1

    return source[brace_start:pos]


def run_llm_review(filepath: str, api_key: str, context: str = "", tone: str = "technical") -> dict | None:
    """Send migration Up()/Down() to Claude for review."""
    try:
        import anthropic
    except ImportError:
        print("⚠️  anthropic package not installed. Run: pip install anthropic", file=sys.stderr)
        return None

    source = Path(filepath).read_text(encoding="utf-8")
    up_body = extract_method_body(source, "Up") or "(Up method not found)"
    down_body = extract_method_body(source, "Down") or "(Down method not found)"

    user_message = f"## Up() method\n```csharp\n{up_body}\n```\n\n## Down() method\n```csharp\n{down_body}\n```"

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
    # Cap prompt to ~80K chars (~20K tokens) to avoid 413 from API gateway
    if len(user_message) > 80_000:
        user_message = user_message[:80_000] + "\n\n> ⚠️ Prompt truncated to fit API limits."
    if context:
        user_message = f"## 🎯 Focus Area: {context}\nONLY include information relevant to this focus area. OMIT entire sections that have no relevant findings — do not show empty sections or unrelated information. If a section has a mix, include only the relevant items.\n\n" + user_message
    response = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "eu.anthropic.claude-sonnet-4-6"),
        max_tokens=2048,
        system=apply_tone(SYSTEM_PROMPT, tone),
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

STATUS_ICON = {"PASS": "✅", "FAIL": "❌", "N/A": "⏭️"}


def format_deterministic(checks: list[dict]) -> str:
    """Format deterministic check results as markdown."""
    lines = ["## Deterministic Checks\n"]
    for c in checks:
        icon = STATUS_ICON.get(c["status"], "❓")
        lines.append(f"- {icon} **{c['check']}** — {c['detail']}")
    return "\n".join(lines)


def format_llm_review(data: dict) -> str:
    """Format LLM review results as markdown."""
    lines = ["## LLM Migration Review\n"]
    severity = data.get("severity", "unknown")
    sev_icon = {"clean": "🟢", "warning": "🟡", "critical": "🔴"}.get(severity, "⚪")
    lines.append(f"**Severity: {sev_icon} {severity}**\n")

    for rule in data.get("rules", []):
        icon = STATUS_ICON.get(rule.get("status", ""), "❓")
        lines.append(f"- {icon} **Rule {rule['id']}: {rule['name']}** — {rule.get('detail', '')}")

    lines.append(f"\n**Summary:** {data.get('summary', 'No summary.')}")
    return "\n".join(lines)


def format_output(filepath: str, det_checks: list[dict], llm_result: dict | None) -> str:
    """Combine all results into a single markdown report."""
    parts = [
        f"# Migration Review: `{Path(filepath).name}`\n",
        format_deterministic(det_checks),
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
    parser = argparse.ArgumentParser(description="Review an EF Core migration file.")
    parser.add_argument("migration_file", help="Path to the .cs migration file.")
    parser.add_argument("--api-key", default=None, help="Anthropic API key (or set ANTHROPIC_API_KEY).")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of markdown.")
    parser.add_argument("--context", default="", help="Focus area to sharpen analysis scope.")
    add_tone_arg(parser)
    args = parser.parse_args()

    filepath = args.migration_file
    if not Path(filepath).is_file():
        print(f"Error: {filepath} not found.", file=sys.stderr)
        return 1

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")

    # Layer 1
    det_checks = run_deterministic_checks(filepath)

    # Layer 2
    llm_result = None
    if api_key:
        llm_result = run_llm_review(filepath, api_key, args.context, args.tone)
    else:
        print("⚠️  No API key provided — skipping LLM review.", file=sys.stderr)

    # Layer 3
    if args.json:
        output = {
            "file": filepath,
            "deterministic": det_checks,
            "llm": llm_result,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_output(filepath, det_checks, llm_result))

    # Exit code: 1 if any FAIL
    has_failure = any(c["status"] == "FAIL" for c in det_checks)
    if llm_result and llm_result.get("severity") == "critical":
        has_failure = True
    return 1 if has_failure else 0


if __name__ == "__main__":
    sys.exit(main())
