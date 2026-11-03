#!/usr/bin/env python3
"""Audit dependencies and infrastructure for EOL versions, deprecated APIs, and risky patterns."""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from llm_utils import add_tone_arg, apply_tone


# ---------------------------------------------------------------------------
# Known-EOL database (hardcoded for demo)
# ---------------------------------------------------------------------------

EOL_DATABASE: list[dict[str, Any]] = [
    {"component": "postgresql", "eol_below": (14, 0), "eol_date": "2025-11-13", "recommended": "16.x",
     "note_11": "EOL 2023-11-09", "note_12": "EOL 2024-11-14", "note_13": "EOL 2025-11-13"},
    {"component": "kubedb_api", "eol_version": "v1alpha1", "recommended": "v1"},
    {"component": "k8s_extensions", "eol_version": "extensions/v1beta1", "removed": "K8s 1.22 (2021-06)", "recommended": "apps/v1"},
    {"component": "ratpack", "outdated_below": (2, 0), "recommended": "2.0+"},
    {"component": "axum", "outdated_below": (0, 6), "recommended": "0.7+"},
    {"component": "alpine", "eol_below": (3, 18), "recommended": "3.19+"},
    {"component": "rust_docker", "outdated_below": (1, 75), "recommended": "1.82+"},
    {"component": "hibernate", "outdated_below": (6, 0), "recommended": "6.4+"},
    {"component": "selenium", "outdated_below": (4, 0), "recommended": "4.x"},
    {"component": "logback", "cve_range": (1, 2), "cve_id": "CVE-2021-42550", "recommended": "1.4.x+"},
    {"component": "postgresql_jdbc", "ancient_below": (42, 0), "recommended": "42.7+"},
    {"component": "helm_chart_api", "outdated_version": "v1", "recommended": "v2"},
]

SKIP_DIRS = {".git", "node_modules", "target", "build", "__pycache__", ".gradle"}

SEVERITY_ICON = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_version_tuple(version_str: str) -> tuple[int, ...] | None:
    """Parse a version string like '1.67.0' into a tuple of ints."""
    match = re.match(r"(\d+(?:\.\d+)*)", version_str)
    if not match:
        return None
    return tuple(int(p) for p in match.group(1).split("."))


def version_below(version_str: str, threshold: tuple[int, ...]) -> bool:
    """Return True if version_str parses to a version below threshold."""
    vt = parse_version_tuple(version_str)
    if vt is None:
        return False
    # Pad shorter tuple with zeros for comparison
    max_len = max(len(vt), len(threshold))
    a = vt + (0,) * (max_len - len(vt))
    b = threshold + (0,) * (max_len - len(threshold))
    return a < b


def finding(file: str, line: int, component: str, current_version: str,
            detail: str, severity: str, recommended: str) -> dict:
    """Create a standardised finding dict."""
    return {
        "file": file,
        "line": line,
        "component": component,
        "current_version": current_version,
        "finding": detail,
        "severity": severity,
        "recommended": recommended,
    }


# ---------------------------------------------------------------------------
# Layer 1 — Deterministic checks
# ---------------------------------------------------------------------------

def scan_build_gradle(filepath: Path, rel: str) -> list[dict]:
    """Parse Gradle dependency lines and flag known-risky libraries."""
    findings: list[dict] = []
    text = filepath.read_text(encoding="utf-8", errors="replace")
    dep_pattern = re.compile(
        r"""(compile|runtime|testCompile|testRuntime|implementation|api|compileOnly|runtimeOnly|testImplementation)\s*"""
        r"""[\(\s]*['"]([^'"]+)['"]""",
    )
    uses_compile = False

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        m = dep_pattern.search(stripped)
        if m:
            config_name = m.group(1)
            coord = m.group(2)
            parts = coord.split(":")
            if len(parts) < 3:
                continue
            group, artifact, version = parts[0], parts[1], parts[2]

            # Deprecated compile configuration
            if config_name in ("compile", "testCompile", "runtime"):
                if not uses_compile:
                    uses_compile = True
                    findings.append(finding(
                        rel, lineno, f"gradle:{config_name}", config_name,
                        f"Deprecated Gradle configuration '{config_name}' — use 'implementation'/'testImplementation'",
                        "warning", "implementation / testImplementation",
                    ))

            # Ratpack
            if "ratpack" in group.lower() or "ratpack" in artifact.lower():
                if version_below(version, (2, 0)):
                    findings.append(finding(
                        rel, lineno, f"ratpack ({artifact})", version,
                        "Ratpack < 2.0 is outdated", "warning", "2.0+",
                    ))

            # PostgreSQL JDBC
            if "postgresql" in artifact.lower() or artifact == "postgresql":
                if version_below(version, (42, 0)):
                    findings.append(finding(
                        rel, lineno, "PostgreSQL JDBC", version,
                        "Ancient PostgreSQL JDBC driver (9.x era)", "critical", "42.7+",
                    ))

            # Logback
            if artifact.startswith("logback"):
                vt = parse_version_tuple(version)
                if vt and len(vt) >= 2 and vt[0] == 1 and vt[1] == 2 and (len(vt) < 3 or vt[2] < 9):
                    findings.append(finding(
                        rel, lineno, f"logback ({artifact})", version,
                        "Logback 1.2.x has CVE-2021-42550 (JNDI RCE)", "critical", "1.4.x+",
                    ))

            # Hibernate
            if "hibernate" in artifact.lower():
                if version_below(version, (6, 0)):
                    findings.append(finding(
                        rel, lineno, f"hibernate ({artifact})", version,
                        "Hibernate < 6.0 is outdated", "warning", "6.4+",
                    ))

            # Selenium
            if "selenium" in artifact.lower():
                if version_below(version, (4, 0)):
                    findings.append(finding(
                        rel, lineno, f"selenium ({artifact})", version,
                        "Selenium < 4.0 is outdated", "warning", "4.x",
                    ))

            # Spock (informational)
            if "spock" in artifact.lower():
                if "rc" in version.lower() or version_below(version, (2, 0)):
                    findings.append(finding(
                        rel, lineno, f"spock ({artifact})", version,
                        "Spock is outdated or a release candidate", "warning", "2.x+",
                    ))

    return findings


def scan_cargo_toml(filepath: Path, rel: str) -> list[dict]:
    """Parse Cargo.toml [dependencies] and flag known-risky crates."""
    findings: list[dict] = []
    text = filepath.read_text(encoding="utf-8", errors="replace")
    in_deps = False
    dep_line_re = re.compile(r'^(\S+)\s*=\s*"([^"]+)"')
    dep_table_re = re.compile(r'^(\S+)\s*=\s*\{.*version\s*=\s*"([^"]+)"')
    section_re = re.compile(r"^\[(.+)]")

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        sec = section_re.match(stripped)
        if sec:
            section_name = sec.group(1).strip()
            in_deps = section_name in ("dependencies", "dev-dependencies", "build-dependencies")
            continue
        if not in_deps:
            continue

        m = dep_line_re.match(stripped) or dep_table_re.match(stripped)
        if not m:
            continue
        crate, version = m.group(1), m.group(2)

        # axum
        if crate == "axum":
            if version_below(version, (0, 6)):
                findings.append(finding(
                    rel, lineno, "axum", version,
                    "axum < 0.6 is outdated (3 major versions behind)", "warning", "0.7+",
                ))

    return findings


def scan_package_json(filepath: Path, rel: str) -> list[dict]:
    """Parse package.json dependencies."""
    findings: list[dict] = []
    try:
        data = json.loads(filepath.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return findings

    for section in ("dependencies", "devDependencies"):
        deps = data.get(section, {})
        if not isinstance(deps, dict):
            continue
        # Placeholder: add known-risky npm package checks here
    return findings


def scan_requirements_txt(filepath: Path, rel: str) -> list[dict]:
    """Parse requirements.txt package==version lines."""
    findings: list[dict] = []
    text = filepath.read_text(encoding="utf-8", errors="replace")
    req_re = re.compile(r"^([A-Za-z0-9_-]+)==(.+)")

    for lineno, line in enumerate(text.splitlines(), start=1):
        m = req_re.match(line.strip())
        if not m:
            continue
        # Placeholder: add known-risky Python package checks here
    return findings


def scan_dockerfile(filepath: Path, rel: str) -> list[dict]:
    """Extract FROM base image + tag and check for EOL/outdated images."""
    findings: list[dict] = []
    text = filepath.read_text(encoding="utf-8", errors="replace")
    from_re = re.compile(r"^FROM\s+(\S+)", re.IGNORECASE)

    for lineno, line in enumerate(text.splitlines(), start=1):
        m = from_re.match(line.strip())
        if not m:
            continue
        image_ref = m.group(1)
        # Parse image:tag
        if ":" in image_ref:
            image, tag = image_ref.rsplit(":", 1)
        else:
            image, tag = image_ref, "latest"

        image_base = image.split("/")[-1]  # handle registry prefixes

        # Rust image
        if image_base == "rust":
            rust_ver = tag.split("-")[0]  # e.g. '1.67.0-alpine3.17' → '1.67.0'
            if version_below(rust_ver, (1, 75)):
                findings.append(finding(
                    rel, lineno, "Rust Docker image", rust_ver,
                    "Rust < 1.75 is outdated", "warning", "1.82+",
                ))

            # Check for alpine suffix
            alpine_match = re.search(r"alpine(\d+\.\d+)", tag)
            if alpine_match:
                alpine_ver = alpine_match.group(1)
                if version_below(alpine_ver, (3, 18)):
                    findings.append(finding(
                        rel, lineno, "Alpine (in Rust image)", alpine_ver,
                        f"Alpine {alpine_ver} is EOL", "warning", "3.19+",
                    ))

        # Alpine image
        elif image_base == "alpine":
            if version_below(tag, (3, 18)):
                findings.append(finding(
                    rel, lineno, "Alpine base image", tag,
                    f"Alpine {tag} is EOL", "warning", "3.19+",
                ))

    return findings


def scan_chart_yaml(filepath: Path, rel: str) -> list[dict]:
    """Check Helm Chart.yaml apiVersion."""
    findings: list[dict] = []
    text = filepath.read_text(encoding="utf-8", errors="replace")

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("apiVersion:"):
            version = stripped.split(":", 1)[1].strip()
            if version == "v1":
                findings.append(finding(
                    rel, lineno, "Helm Chart apiVersion", "v1",
                    "Helm Chart apiVersion v1 is outdated (v2 is current)", "warning", "v2",
                ))

    return findings


def scan_k8s_template(filepath: Path, rel: str) -> list[dict]:
    """Scan K8s YAML templates for deprecated APIs and risky patterns."""
    findings: list[dict] = []
    text = filepath.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    has_resource_limits = False
    has_health_probes = False
    has_termination_policy = False

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()

        # KubeDB v1alpha1
        if re.match(r"apiVersion:\s*kubedb\.com/v1alpha1", stripped):
            findings.append(finding(
                rel, lineno, "KubeDB API", "v1alpha1",
                "KubeDB v1alpha1 is deprecated", "critical", "v1",
            ))

        # extensions/v1beta1
        if re.match(r"apiVersion:\s*extensions/v1beta1", stripped):
            findings.append(finding(
                rel, lineno, "K8s extensions API", "extensions/v1beta1",
                "extensions/v1beta1 removed in K8s 1.22 (2021-06)", "critical", "apps/v1",
            ))

        # PostgreSQL version detection
        pg_match = re.match(r'.*version:\s*["\']?(\d+\.\d+(?:\.\d+)?)["\']?', stripped)
        if pg_match and ("postgres" in text.lower() or "Postgres" in filepath.name.lower()):
            pg_ver = pg_match.group(1)
            if version_below(pg_ver, (14, 0)):
                # Determine specific EOL note
                major = parse_version_tuple(pg_ver)
                if major and major[0] <= 11:
                    detail = f"PostgreSQL {pg_ver} is EOL (since 2023-11-09)"
                elif major and major[0] == 12:
                    detail = f"PostgreSQL {pg_ver} is EOL (since 2024-11-14)"
                elif major and major[0] == 13:
                    detail = f"PostgreSQL {pg_ver} is EOL (since 2025-11-13)"
                else:
                    detail = f"PostgreSQL {pg_ver} is outdated"
                findings.append(finding(
                    rel, lineno, "PostgreSQL", pg_ver,
                    detail, "critical", "16.x",
                ))

        # Track resource limits and probes
        if "limits:" in stripped or "resources:" in stripped:
            has_resource_limits = True
        if "livenessProbe:" in stripped or "readinessProbe:" in stripped:
            has_health_probes = True
        if "terminationPolicy:" in stripped:
            has_termination_policy = True

    # Risk patterns — only flag on resources that should have them
    kind_match = re.search(r"kind:\s*(\S+)", text)
    kind = kind_match.group(1) if kind_match else ""

    if kind in ("Deployment", "StatefulSet", "DaemonSet"):
        if not has_resource_limits:
            findings.append(finding(
                rel, 1, f"K8s {kind}", "n/a",
                "No memory/CPU resource limits defined", "info", "Set resources.limits",
            ))
        if not has_health_probes:
            findings.append(finding(
                rel, 1, f"K8s {kind}", "n/a",
                "No health/liveness probes defined", "info", "Add livenessProbe/readinessProbe",
            ))

    if kind in ("Postgres", "MongoDB", "MySQL", "Redis"):
        if not has_termination_policy:
            findings.append(finding(
                rel, 1, f"KubeDB {kind}", "n/a",
                "No terminationPolicy defined — risky for stateful workloads", "warning",
                "terminationPolicy: DoNotTerminate",
            ))

    return findings


def scan_values_yaml(filepath: Path, rel: str) -> list[dict]:
    """Scan Helm values.yaml for version-related fields and deprecated references."""
    findings: list[dict] = []
    text = filepath.read_text(encoding="utf-8", errors="replace")

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()

        # extensions/v1beta1 in values
        if "extensions/v1beta1" in stripped:
            findings.append(finding(
                rel, lineno, "K8s extensions API (values)", "extensions/v1beta1",
                "extensions/v1beta1 removed in K8s 1.22 (2021-06)", "critical", "apps/v1",
            ))

        # deploymentApiVersion referencing deprecated APIs
        if stripped.startswith("deploymentApiVersion:"):
            value = stripped.split(":", 1)[1].strip().strip("'\"")
            if value == "extensions/v1beta1":
                findings.append(finding(
                    rel, lineno, "deploymentApiVersion (values)", value,
                    "extensions/v1beta1 removed in K8s 1.22 (2021-06)", "warning", "apps/v1",
                ))

    return findings


def collect_files(repo_path: Path) -> dict[str, list[Path]]:
    """Walk the repo and collect files by type, skipping ignored directories."""
    result: dict[str, list[Path]] = {
        "build.gradle": [],
        "Cargo.toml": [],
        "package.json": [],
        "requirements.txt": [],
        "Dockerfile": [],
        "Chart.yaml": [],
        "k8s_templates": [],
        "values.yaml": [],
    }

    for root, dirs, files in os.walk(repo_path):
        # Prune skipped directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        root_path = Path(root)
        for fname in files:
            fpath = root_path / fname
            if fname == "build.gradle":
                result["build.gradle"].append(fpath)
            elif fname == "Cargo.toml":
                result["Cargo.toml"].append(fpath)
            elif fname == "package.json":
                result["package.json"].append(fpath)
            elif fname == "requirements.txt":
                result["requirements.txt"].append(fpath)
            elif fname == "Dockerfile":
                result["Dockerfile"].append(fpath)
            elif fname == "Chart.yaml":
                result["Chart.yaml"].append(fpath)
            elif fname == "values.yaml":
                result["values.yaml"].append(fpath)
            elif fname.endswith(".yaml") and "templates" in str(root_path):
                result["k8s_templates"].append(fpath)

    return result


def run_deterministic_checks(repo_path: Path) -> list[dict]:
    """Run all deterministic checks across the repo and return findings."""
    findings: list[dict] = []
    files = collect_files(repo_path)

    for fpath in files["build.gradle"]:
        findings.extend(scan_build_gradle(fpath, str(fpath.relative_to(repo_path))))
    for fpath in files["Cargo.toml"]:
        findings.extend(scan_cargo_toml(fpath, str(fpath.relative_to(repo_path))))
    for fpath in files["package.json"]:
        findings.extend(scan_package_json(fpath, str(fpath.relative_to(repo_path))))
    for fpath in files["requirements.txt"]:
        findings.extend(scan_requirements_txt(fpath, str(fpath.relative_to(repo_path))))
    for fpath in files["Dockerfile"]:
        findings.extend(scan_dockerfile(fpath, str(fpath.relative_to(repo_path))))
    for fpath in files["Chart.yaml"]:
        findings.extend(scan_chart_yaml(fpath, str(fpath.relative_to(repo_path))))
    for fpath in files["k8s_templates"]:
        findings.extend(scan_k8s_template(fpath, str(fpath.relative_to(repo_path))))
    for fpath in files["values.yaml"]:
        findings.extend(scan_values_yaml(fpath, str(fpath.relative_to(repo_path))))

    return findings


# ---------------------------------------------------------------------------
# Layer 2 — LLM review
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an infrastructure and dependency auditor for brownfield repositories.
You receive a list of findings from a deterministic scan of dependency manifests
and infrastructure files (Gradle, Cargo.toml, Dockerfile, Helm charts, K8s YAML).

Your job:
1. Prioritize findings by ACTUAL risk — not just version age. A CVE is worse than
   being one minor version behind.
2. Suggest specific upgrade paths for the detected stack (e.g. Ratpack 1.x→2.x
   breaking changes, Hibernate 5→6 Jakarta EE namespace migration).
3. Identify breaking-change risks in each suggested upgrade.
4. Assess overall infrastructure health (0-100 score).

Respond ONLY with valid JSON (no markdown fences):
{
  "prioritized_findings": [
    {
      "component": "name",
      "risk_level": "critical|high|medium|low",
      "reasoning": "why this priority",
      "upgrade_path": "specific steps",
      "breaking_changes": "what could break"
    }
  ],
  "overall_health_score": 0-100,
  "summary": "overall assessment",
  "recommended_order": ["component1", "component2"]
}"""


def run_llm_review(findings: list[dict], api_key: str, context: str = "", tone: str = "technical") -> dict | None:
    """Send deterministic findings to Claude for risk prioritization."""
    try:
        import anthropic
    except ImportError:
        print("⚠️  anthropic package not installed. Run: pip install anthropic", file=sys.stderr)
        return None

    if not findings:
        return {"prioritized_findings": [], "overall_health_score": 100, "summary": "No findings to review."}

    findings_text = json.dumps(findings, indent=2)
    user_message = f"## Deterministic scan findings\n\n```json\n{findings_text}\n```"

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
    # Cap prompt to ~80K chars (~20K tokens) to avoid 413 from API gateway
    if len(user_message) > 80_000:
        user_message = user_message[:80_000] + "\n\n> ⚠️ Prompt truncated to fit API limits."
    if context:
        user_message = f"## 🎯 Focus Area\nFocus your analysis on: {context}\nPrioritize findings related to this area. Still report critical issues outside this scope, but keep the focus tight.\n\n" + user_message
    response = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "eu.anthropic.claude-sonnet-4-6"),
        max_tokens=4096,
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

def format_summary_table(findings: list[dict]) -> str:
    """Format a severity summary table."""
    counts = {"critical": 0, "warning": 0, "info": 0}
    for f in findings:
        sev = f.get("severity", "info")
        counts[sev] = counts.get(sev, 0) + 1

    lines = [
        "| Severity | Count |",
        "|----------|-------|",
        f"| 🔴 Critical | {counts['critical']} |",
        f"| 🟡 Warning  | {counts['warning']} |",
        f"| ℹ️  Info     | {counts['info']} |",
        f"| **Total**   | **{sum(counts.values())}** |",
    ]
    return "\n".join(lines)


def format_findings(findings: list[dict]) -> str:
    """Format individual findings as markdown."""
    if not findings:
        return "> ✅ No issues found."

    lines: list[str] = []
    for f in findings:
        icon = SEVERITY_ICON.get(f["severity"], "❓")
        lines.append(
            f"- {icon} **{f['component']}** `{f['current_version']}` "
            f"→ {f['recommended']}  \n"
            f"  `{f['file']}:{f['line']}` — {f['finding']}"
        )
    return "\n".join(lines)


def format_llm_review(data: dict) -> str:
    """Format LLM risk prioritization as markdown."""
    lines = ["## LLM Risk Analysis\n"]

    score = data.get("overall_health_score", "?")
    lines.append(f"**Infrastructure Health Score: {score}/100**\n")

    lines.append(f"**Summary:** {data.get('summary', 'No summary.')}\n")

    order = data.get("recommended_order", [])
    if order:
        lines.append("**Recommended upgrade order:**")
        for i, comp in enumerate(order, 1):
            lines.append(f"  {i}. {comp}")
        lines.append("")

    risk_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
    for pf in data.get("prioritized_findings", []):
        icon = risk_icon.get(pf.get("risk_level", ""), "⚪")
        lines.append(f"### {icon} {pf['component']}")
        lines.append(f"**Risk:** {pf.get('risk_level', 'unknown')} — {pf.get('reasoning', '')}")
        lines.append(f"**Upgrade path:** {pf.get('upgrade_path', 'N/A')}")
        lines.append(f"**Breaking changes:** {pf.get('breaking_changes', 'None identified')}")
        lines.append("")

    return "\n".join(lines)


def format_output(repo_path: str, findings: list[dict], llm_result: dict | None) -> str:
    """Combine all results into a single markdown report."""
    parts = [
        f"# Dependency & Infrastructure Audit: `{repo_path}`\n",
        "## Summary\n",
        format_summary_table(findings),
        "",
        "## Findings\n",
        format_findings(findings),
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
        description="Audit dependencies and infrastructure for EOL versions, deprecated APIs, and risky patterns.",
    )
    parser.add_argument("repo_path", help="Path to the repository root to audit.")
    parser.add_argument("--api-key", default=None, help="Anthropic API key (or set ANTHROPIC_API_KEY).")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of markdown.")
    parser.add_argument("--context", default="", help="Focus area to sharpen analysis scope.")
    add_tone_arg(parser)
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.is_dir():
        print(f"Error: {repo_path} is not a directory.", file=sys.stderr)
        return 1

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")

    # Layer 1
    findings = run_deterministic_checks(repo_path)

    # Layer 2
    llm_result = None
    if api_key:
        llm_result = run_llm_review(findings, api_key, args.context, args.tone)
    else:
        print("⚠️  No API key provided — skipping LLM review.", file=sys.stderr)

    # Layer 3
    if args.json:
        output = {
            "repo": str(repo_path),
            "findings": findings,
            "llm": llm_result,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_output(str(repo_path), findings, llm_result))

    # Exit code: 1 if any critical findings
    has_critical = any(f["severity"] == "critical" for f in findings)
    if llm_result and llm_result.get("overall_health_score", 100) < 30:
        has_critical = True
    return 1 if has_critical else 0


if __name__ == "__main__":
    sys.exit(main())
