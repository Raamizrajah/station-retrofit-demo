#!/usr/bin/env python3
"""Format JSON review output as GitHub PR comment markdown."""

import argparse
import json
import sys
from pathlib import Path


STATUS_ICON = {"PASS": "✅", "FAIL": "❌", "N/A": "⏭️"}
SEVERITY_ICON = {"breaking": "🔴", "warning": "🟡", "safe": "🟢", "clean": "🟢", "critical": "🔴"}


def format_migration_review(data: dict) -> str:
    """Format migration review JSON as a PR comment body."""
    filename = Path(data.get("file", "unknown")).name
    lines = [f"## 🔍 Migration Review: `{filename}`\n"]

    # Deterministic checks
    det = data.get("deterministic", [])
    if det:
        lines.append("<details>")
        lines.append("<summary>Deterministic Checks</summary>\n")
        for c in det:
            icon = STATUS_ICON.get(c.get("status", ""), "❓")
            lines.append(f"| {icon} | **{c.get('check', '?')}** | {c.get('detail', '')} |")
        lines.append("\n</details>\n")

    # LLM review
    llm = data.get("llm")
    if llm:
        severity = llm.get("severity", "unknown")
        sev_icon = SEVERITY_ICON.get(severity, "⚪")
        lines.append(f"### LLM Review — {sev_icon} {severity.upper()}\n")

        for rule in llm.get("rules", []):
            icon = STATUS_ICON.get(rule.get("status", ""), "❓")
            lines.append(f"- {icon} **{rule.get('name', '?')}** — {rule.get('detail', '')}")

        summary = llm.get("summary", "")
        if summary:
            lines.append(f"\n> {summary}")
    else:
        lines.append("> ℹ️ LLM review was not performed.")

    return "\n".join(lines)


def format_contract_drift(data: dict) -> str:
    """Format contract drift JSON as a PR comment body."""
    changes = data.get("changes", [])
    frontend = data.get("frontend_matches", [])
    llm = data.get("llm_assessment")

    breaking = [c for c in changes if c.get("severity") == "breaking"]
    warnings = [c for c in changes if c.get("severity") == "warning"]
    safe = [c for c in changes if c.get("severity") == "safe"]

    lines = ["## 📋 API Contract Drift Report\n"]

    if not changes:
        lines.append("> ✅ No contract changes detected.")
        return "\n".join(lines)

    lines.append(f"**{len(breaking)} breaking** · {len(warnings)} warnings · {len(safe)} safe\n")

    if breaking:
        lines.append("### 🔴 Breaking Changes\n")
        lines.append("| Change | Item | Detail |")
        lines.append("|--------|------|--------|")
        for c in breaking:
            lines.append(f"| `{c.get('change_type', '?')}` | `{c.get('item', '?')}` | {c.get('detail', '')} |")

    if warnings:
        lines.append("\n### 🟡 Warnings\n")
        for c in warnings:
            lines.append(f"- `{c.get('item', '?')}` — {c.get('detail', '')}")

    if frontend:
        lines.append("\n<details>")
        lines.append("<summary>Frontend Impact</summary>\n")
        for m in frontend[:50]:
            lines.append(f"- `{m.get('file', '?')}:{m.get('line', '?')}` — {m.get('related_change', '')}")
        if len(frontend) > 50:
            lines.append(f"\n… and {len(frontend) - 50} more matches.")
        lines.append("\n</details>")

    if llm:
        lines.append(f"\n### LLM Assessment\n")
        lines.append(f"> {llm.get('summary', 'N/A')}\n")
        for item in llm.get("changes", []):
            icon = SEVERITY_ICON.get(item.get("severity", ""), "⚪")
            suggestion = item.get("suggestion", "")
            lines.append(f"- {icon} **{item.get('item', '?')}** — {suggestion}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Format review JSON as a GitHub PR comment.")
    parser.add_argument("--type", required=True, choices=["migration", "drift"], help="Review type.")
    parser.add_argument("--input", required=True, help="Path to JSON file (or - for stdin).")
    args = parser.parse_args()

    if args.input == "-":
        data = json.load(sys.stdin)
    else:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)

    if args.type == "migration":
        print(format_migration_review(data))
    else:
        print(format_contract_drift(data))

    return 0


if __name__ == "__main__":
    sys.exit(main())
