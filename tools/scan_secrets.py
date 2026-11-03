#!/usr/bin/env python3
"""Scan a repository directory for hardcoded secrets using deterministic checks and LLM analysis."""

import argparse
import base64
import json
import math
import os
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Layer 1 — Deterministic checks
# ---------------------------------------------------------------------------

SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", "vendor", "__pycache__", ".venv", "venv"}

SCAN_EXTENSIONS = {
    ".yaml", ".yml", ".groovy", ".java", ".kt", ".rs", ".toml",
    ".py", ".js", ".ts", ".json", ".properties", ".env", ".cfg",
    ".conf", ".xml", ".tf", ".dockerfile",
}

SCAN_FILENAMES = {"Dockerfile"}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".svg",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".zip", ".tar", ".gz", ".bz2", ".jar", ".war", ".ear",
    ".exe", ".dll", ".so", ".dylib", ".class", ".pyc", ".pyo",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
}

SECRET_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("aws_key", re.compile(r"AKIA[A-Z0-9]{16}"), "AWS Access Key ID"),
    ("github_pat", re.compile(r"ghp_[A-Za-z0-9]{36,}"), "GitHub Personal Access Token"),
    ("slack_token", re.compile(r"xox[bpas]-[A-Za-z0-9\-]+"), "Slack Token"),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI / Generic sk- Key"),
    ("private_key", re.compile(r"-----BEGIN.*PRIVATE KEY-----"), "Private Key Block"),
]

ENV_SECRET_NAMES = re.compile(
    r"(?:PASSWORD|SECRET|API_KEY|TOKEN|ACCESS_KEY|PRIVATE_KEY|CREDENTIALS)"
    r"\s*[=:]\s*\S+",
    re.IGNORECASE,
)

HIGH_ENTROPY_BASE64 = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
HIGH_ENTROPY_HEX = re.compile(r"[0-9a-fA-F]{20,}")


def shannon_entropy(data: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not data:
        return 0.0
    freq: dict[str, int] = {}
    for ch in data:
        freq[ch] = freq.get(ch, 0) + 1
    length = len(data)
    return -sum(
        (count / length) * math.log2(count / length)
        for count in freq.values()
    )


def mask_value(value: str) -> str:
    """Show first 8 chars + ... + last 4 chars. Never expose full secret."""
    if len(value) <= 16:
        return value[:4] + "..." + value[-2:]
    return value[:8] + "..." + value[-4:]


def is_scannable(path: Path) -> bool:
    """Check whether a file should be scanned based on extension or name."""
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return False
    if path.suffix.lower() in SCAN_EXTENSIONS:
        return True
    if path.name in SCAN_FILENAMES:
        return True
    return False


def decode_base64_safe(value: str) -> str | None:
    """Try to Base64-decode a value, return decoded string or None."""
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
        # Only return if it looks like printable text
        if all(32 <= ord(c) < 127 for c in decoded):
            return decoded
    except Exception:
        pass
    return None


def check_line(
    line: str,
    line_number: int,
    filepath: str,
    in_k8s_data_section: bool,
) -> list[dict]:
    """Check a single line against all secret patterns."""
    findings: list[dict] = []

    # Direct pattern matching
    for pattern_type, pattern, description in SECRET_PATTERNS:
        for match in pattern.finditer(line):
            findings.append({
                "file": filepath,
                "line": line_number,
                "match": description,
                "pattern_type": pattern_type,
                "confidence": "high",
                "value_preview": mask_value(match.group()),
            })

    # Env var assignments with suspicious names
    for match in ENV_SECRET_NAMES.finditer(line):
        # Avoid overlap with already-found patterns
        matched_text = match.group()
        if not any(f["value_preview"] in matched_text for f in findings):
            findings.append({
                "file": filepath,
                "line": line_number,
                "match": "Suspicious env var assignment",
                "pattern_type": "env_secret",
                "confidence": "medium",
                "value_preview": mask_value(matched_text),
            })

    # Base64 values in Kubernetes Secret data: sections — decode and re-check
    if in_k8s_data_section:
        # Match YAML key: value pairs where value is Base64
        kv_match = re.match(r"\s+(\S+):\s+([A-Za-z0-9+/]{16,}={0,2})\s*$", line)
        if kv_match:
            b64_value = kv_match.group(2)
            decoded = decode_base64_safe(b64_value)
            if decoded:
                # Re-check decoded value against secret patterns
                for pattern_type, pattern, description in SECRET_PATTERNS:
                    if pattern.search(decoded):
                        findings.append({
                            "file": filepath,
                            "line": line_number,
                            "match": f"Base64-encoded {description}",
                            "pattern_type": f"b64_{pattern_type}",
                            "confidence": "high",
                            "value_preview": mask_value(decoded),
                        })

                # Entropy check on decoded value
                ent = shannon_entropy(decoded)
                if ent > 3.5 and not any(
                    f["pattern_type"].startswith("b64_") for f in findings
                    if f["line"] == line_number
                ):
                    findings.append({
                        "file": filepath,
                        "line": line_number,
                        "match": f"High-entropy decoded Base64 (entropy={ent:.2f})",
                        "pattern_type": "b64_high_entropy",
                        "confidence": "medium",
                        "value_preview": mask_value(decoded),
                    })

    # High-entropy Base64 strings (outside k8s context)
    if not in_k8s_data_section:
        for match in HIGH_ENTROPY_BASE64.finditer(line):
            value = match.group()
            ent = shannon_entropy(value)
            if ent > 3.5 and not any(
                f["value_preview"] == mask_value(value) for f in findings
            ):
                # Skip common non-secret patterns (e.g. UUIDs, package names)
                if re.fullmatch(r"[A-Za-z]+", value):
                    continue
                findings.append({
                    "file": filepath,
                    "line": line_number,
                    "match": f"High-entropy Base64 string (entropy={ent:.2f})",
                    "pattern_type": "high_entropy_base64",
                    "confidence": "low",
                    "value_preview": mask_value(value),
                })

    # High-entropy hex strings
    for match in HIGH_ENTROPY_HEX.finditer(line):
        value = match.group()
        ent = shannon_entropy(value)
        if ent > 4.5 and not any(
            f["value_preview"] == mask_value(value) for f in findings
        ):
            findings.append({
                "file": filepath,
                "line": line_number,
                "match": f"High-entropy hex string (entropy={ent:.2f})",
                "pattern_type": "high_entropy_hex",
                "confidence": "low",
                "value_preview": mask_value(value),
            })

    return findings


def scan_file(filepath: Path) -> list[dict]:
    """Scan a single file for secrets."""
    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return []

    lines = content.splitlines()
    findings: list[dict] = []
    in_k8s_data_section = False
    is_yaml = filepath.suffix.lower() in {".yaml", ".yml"}

    for i, line in enumerate(lines, start=1):
        # Track Kubernetes Secret data: sections in YAML files
        if is_yaml:
            stripped = line.lstrip()
            if stripped.startswith("data:") and not stripped.startswith("data: |"):
                in_k8s_data_section = True
            elif stripped and not stripped.startswith("#") and not line.startswith(" "):
                # New top-level key resets the section tracking
                in_k8s_data_section = False

        findings.extend(check_line(line, i, str(filepath), in_k8s_data_section))

    return findings


def walk_repo(repo_path: Path) -> list[dict]:
    """Walk the repository and scan all eligible files."""
    all_findings: list[dict] = []
    for root, dirs, files in os.walk(repo_path):
        # Skip ignored directories in-place
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in files:
            fpath = Path(root) / filename
            if is_scannable(fpath):
                all_findings.extend(scan_file(fpath))
    return all_findings


def get_context_lines(filepath: str, line_number: int, context: int = 3) -> list[str]:
    """Return surrounding lines for a finding (for LLM context)."""
    try:
        lines = Path(filepath).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    start = max(0, line_number - context - 1)
    end = min(len(lines), line_number + context)
    return [f"{i + 1}: {lines[i]}" for i in range(start, end)]


def run_deterministic_checks(repo_path: str) -> list[dict]:
    """Run all deterministic checks and return findings."""
    return walk_repo(Path(repo_path))


# ---------------------------------------------------------------------------
# Layer 2 — LLM review
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a security engineer reviewing potential secret findings in a code repository.
For each finding, classify it and provide remediation advice.

Respond with JSON:
{
  "findings": [
    {
      "file": "path/to/file",
      "line": 42,
      "classification": "secret|likely_secret|false_positive",
      "reasoning": "why you classified it this way",
      "remediation": "what the developer should do"
    }
  ],
  "summary": "overall assessment of the repository's secret hygiene"
}

Classification guide:
- "secret": definitely a real credential or key (AWS keys, private keys, API tokens)
- "likely_secret": high probability of being a real secret but cannot be 100% certain
- "false_positive": test data, placeholder, example value, or non-secret high-entropy string

Respond ONLY with valid JSON, no markdown fences."""


def run_llm_review(findings: list[dict], api_key: str) -> dict | None:
    """Send findings with surrounding context to Claude for classification."""
    try:
        import anthropic
    except ImportError:
        print("⚠️  anthropic package not installed. Run: pip install anthropic", file=sys.stderr)
        return None

    if not findings:
        return {"findings": [], "summary": "No findings to review."}

    # Build context for each finding
    parts: list[str] = []
    for i, finding in enumerate(findings, start=1):
        context_lines = get_context_lines(finding["file"], finding["line"])
        context_block = "\n".join(context_lines) if context_lines else "(context unavailable)"
        parts.append(
            f"### Finding {i}\n"
            f"- **File:** `{finding['file']}`\n"
            f"- **Line:** {finding['line']}\n"
            f"- **Pattern:** {finding['match']} ({finding['pattern_type']})\n"
            f"- **Confidence:** {finding['confidence']}\n"
            f"- **Preview:** `{finding['value_preview']}`\n"
            f"\n```\n{context_block}\n```"
        )

    user_message = "## Potential Secret Findings\n\n" + "\n\n".join(parts)

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
    response = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "eu.anthropic.claude-sonnet-4-6"),
        max_tokens=4096,
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

STATUS_ICON = {"secret": "🔴", "likely_secret": "🟡", "false_positive": "⚪"}


def format_deterministic(findings: list[dict]) -> str:
    """Format deterministic scan results as markdown."""
    if not findings:
        return "## Deterministic Scan\n\n✅ No secrets detected."

    lines = [f"## Deterministic Scan\n\n**{len(findings)} potential secret(s) found:**\n"]
    for f in findings:
        icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(f["confidence"], "❓")
        lines.append(
            f"- {icon} `{f['file']}:{f['line']}` — "
            f"**{f['match']}** (confidence: {f['confidence']})\n"
            f"  Preview: `{f['value_preview']}`"
        )
    return "\n".join(lines)


def format_llm_review(data: dict) -> str:
    """Format LLM review results as markdown."""
    lines = ["## LLM Classification\n"]

    for f in data.get("findings", []):
        classification = f.get("classification", "unknown")
        icon = STATUS_ICON.get(classification, "❓")
        lines.append(
            f"- {icon} **{classification}** — `{f['file']}:{f['line']}`\n"
            f"  {f.get('reasoning', '')}\n"
            f"  **Remediation:** {f.get('remediation', 'N/A')}"
        )

    lines.append(f"\n**Summary:** {data.get('summary', 'No summary.')}")
    return "\n".join(lines)


def format_output(
    repo_path: str,
    det_findings: list[dict],
    llm_result: dict | None,
) -> str:
    """Combine all results into a single markdown report."""
    parts = [
        f"# Secret Scan: `{Path(repo_path).name}`\n",
        format_deterministic(det_findings),
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
    parser = argparse.ArgumentParser(description="Scan a repository for hardcoded secrets.")
    parser.add_argument("repo_path", help="Path to the repository directory to scan.")
    parser.add_argument("--api-key", default=None, help="Anthropic API key (or set ANTHROPIC_API_KEY).")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of markdown.")
    args = parser.parse_args()

    repo_path = args.repo_path
    if not Path(repo_path).is_dir():
        print(f"Error: {repo_path} is not a directory.", file=sys.stderr)
        return 1

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")

    # Layer 1
    det_findings = run_deterministic_checks(repo_path)

    # Layer 2
    llm_result = None
    if api_key:
        llm_result = run_llm_review(det_findings, api_key)
    else:
        print("⚠️  No API key provided — skipping LLM review.", file=sys.stderr)

    # Layer 3
    if args.json:
        output = {
            "repo": repo_path,
            "deterministic": det_findings,
            "llm": llm_result,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_output(repo_path, det_findings, llm_result))

    # Exit code: 1 if any secret or likely_secret found
    has_secret = any(f["confidence"] == "high" for f in det_findings)
    if llm_result:
        has_secret = has_secret or any(
            f.get("classification") in {"secret", "likely_secret"}
            for f in llm_result.get("findings", [])
        )
    return 1 if has_secret else 0


if __name__ == "__main__":
    sys.exit(main())
