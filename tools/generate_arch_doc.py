#!/usr/bin/env python3
"""Generate architecture documentation from one or more repositories using deterministic analysis and LLM synthesis."""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from llm_utils import add_tone_arg, apply_tone


# ---------------------------------------------------------------------------
# Layer 1 — Deterministic inventory
# ---------------------------------------------------------------------------

SKIP_DIRS = {".git", "node_modules", "target", "build", ".gradle", "__pycache__", ".idea", "vendor"}
BINARY_EXTENSIONS = {".jar", ".class", ".png", ".jpg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".gif", ".pdf"}


def _read_text(path: Path, max_bytes: int = 64_000) -> str | None:
    """Read a text file safely, returning None on binary/error."""
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    except (OSError, UnicodeDecodeError):
        return None


def _extract_lines(text: str, pattern: str) -> list[str]:
    """Return all lines matching a regex pattern."""
    return [line.strip() for line in text.splitlines() if re.search(pattern, line)]


def detect_stack(repo: Path) -> list[dict]:
    """Detect technology stack from build files. Returns list of {type, detail}."""
    stacks: list[dict] = []

    # Gradle / Groovy
    build_gradle = repo / "build.gradle"
    if build_gradle.is_file():
        content = _read_text(build_gradle) or ""
        if "ratpack" in content.lower():
            stacks.append({"type": "Ratpack", "detail": "Groovy/Ratpack application"})
        elif "grails-" in content.lower() or "grails" in content.lower():
            stacks.append({"type": "Grails", "detail": "Grails application"})
        else:
            stacks.append({"type": "Gradle", "detail": "Gradle project"})

    # Rust
    cargo_toml = repo / "Cargo.toml"
    if cargo_toml.is_file():
        content = _read_text(cargo_toml) or ""
        frameworks = []
        if "axum" in content:
            frameworks.append("Axum")
        if "actix" in content:
            frameworks.append("Actix")
        if "tokio" in content:
            frameworks.append("Tokio")
        detail = f"Rust ({', '.join(frameworks)})" if frameworks else "Rust"
        stacks.append({"type": "Rust", "detail": detail})

    # Helm chart
    chart_yaml = repo / "Chart.yaml"
    chart_dir = repo / "chart"
    if chart_yaml.is_file() or chart_dir.is_dir():
        chart_file = chart_yaml if chart_yaml.is_file() else (chart_dir / "Chart.yaml")
        detail = "Helm chart"
        if chart_file.is_file():
            content = _read_text(chart_file) or ""
            for line in content.splitlines():
                if line.strip().startswith("description:"):
                    detail = line.split(":", 1)[1].strip().strip('"').strip("'")
                    break
        stacks.append({"type": "Helm", "detail": detail})

    # Dockerfile
    for dockerfile in repo.glob("Dockerfile*"):
        if dockerfile.is_file():
            content = _read_text(dockerfile) or ""
            from_lines = _extract_lines(content, r"^\s*FROM\s+")
            base_images = [re.sub(r"^\s*FROM\s+", "", l).split()[0] for l in from_lines]
            stacks.append({"type": "Docker", "detail": f"Base: {', '.join(base_images)}" if base_images else "Dockerfile present"})
            break

    # Node.js
    pkg_json = repo / "package.json"
    if pkg_json.is_file():
        stacks.append({"type": "Node.js", "detail": "Node.js application"})

    if not stacks:
        stacks.append({"type": "Unknown", "detail": "No recognized build files"})

    return stacks


def find_entry_points(repo: Path, stacks: list[dict]) -> list[dict]:
    """Find application entry points based on detected stack."""
    entries: list[dict] = []
    stack_types = {s["type"] for s in stacks}

    if "Grails" in stack_types:
        for f in _walk_files(repo, "*.groovy"):
            if f.name.endswith("Controller.groovy"):
                entries.append({"type": "Grails controller", "file": str(f.relative_to(repo))})

    if "Ratpack" in stack_types:
        for f in _walk_files(repo, "*.groovy"):
            content = _read_text(f)
            if content and ("ratpack" in content.lower() or "handler" in content.lower()):
                if "Handler" in f.name or "Ratpack" in f.name or "chain" in content.lower():
                    entries.append({"type": "Ratpack handler", "file": str(f.relative_to(repo))})

    if "Rust" in stack_types:
        for name in ("main.rs", "api.rs", "lib.rs"):
            for f in _walk_files(repo, name):
                entries.append({"type": "Rust entry", "file": str(f.relative_to(repo))})

    if "Helm" in stack_types:
        for f in _walk_files(repo, "*.yaml"):
            rel = str(f.relative_to(repo))
            if "templates/" in rel:
                entries.append({"type": "K8s template", "file": rel})

    return entries


def find_domain_models(repo: Path, stacks: list[dict]) -> list[dict]:
    """Find domain model classes/structs."""
    models: list[dict] = []
    stack_types = {s["type"] for s in stacks}

    if "Grails" in stack_types or "Ratpack" in stack_types:
        for f in _walk_files(repo, "*.groovy"):
            rel = str(f.relative_to(repo))
            if "/domain/" in rel or "/model/" in rel:
                models.append({"name": f.stem, "file": rel, "lang": "Groovy"})

    if "Rust" in stack_types:
        for f in _walk_files(repo, "*.rs"):
            content = _read_text(f)
            if not content:
                continue
            # Find structs with Serialize/Deserialize (pub or private)
            for match in re.finditer(r"#\[derive\([^)]*(?:Serialize|Deserialize)[^)]*\)\]\s*(?:pub\s+)?struct\s+(\w+)", content):
                models.append({"name": match.group(1), "file": str(f.relative_to(repo)), "lang": "Rust"})

    return models


def find_api_endpoints(repo: Path, stacks: list[dict]) -> list[dict]:
    """Extract API endpoints from controllers and route definitions."""
    endpoints: list[dict] = []
    stack_types = {s["type"] for s in stacks}

    if "Grails" in stack_types:
        for f in _walk_files(repo, "*Controller.groovy"):
            content = _read_text(f)
            if not content:
                continue
            controller_name = f.stem.replace("Controller", "").lower()
            # Find action methods (def methodName)
            for match in re.finditer(r"def\s+(\w+)\s*[\({]", content):
                action = match.group(1)
                if action not in ("__", "init"):
                    endpoints.append({
                        "method": "GET/POST",
                        "path": f"/{controller_name}/{action}",
                        "source": str(f.relative_to(repo)),
                    })

    if "Ratpack" in stack_types:
        for f in _walk_files(repo, "*.groovy"):
            content = _read_text(f)
            if not content:
                continue
            for match in re.finditer(r'(?:get|post|put|delete|path)\s*\(\s*["\']([^"\']+)', content):
                endpoints.append({
                    "method": "HTTP",
                    "path": match.group(1),
                    "source": str(f.relative_to(repo)),
                })

    if "Rust" in stack_types:
        for f in _walk_files(repo, "*.rs"):
            content = _read_text(f)
            if not content:
                continue
            # Axum-style routes: .route("/path", get(handler))
            for match in re.finditer(r'\.route\s*\(\s*"([^"]+)"\s*,\s*(get|post|put|delete|patch)', content):
                endpoints.append({
                    "method": match.group(2).upper(),
                    "path": match.group(1),
                    "source": str(f.relative_to(repo)),
                })

    return endpoints


def parse_dependencies(repo: Path, stacks: list[dict]) -> list[dict]:
    """Parse dependency declarations from build files."""
    deps: list[dict] = []
    stack_types = {s["type"] for s in stacks}

    if "Grails" in stack_types or "Ratpack" in stack_types or "Gradle" in stack_types:
        build_gradle = repo / "build.gradle"
        if build_gradle.is_file():
            content = _read_text(build_gradle) or ""
            for match in re.finditer(r"['\"]([^'\"]+:[^'\"]+:[^'\"]+)['\"]", content):
                deps.append({"source": "build.gradle", "dependency": match.group(1)})

    if "Rust" in stack_types:
        cargo_toml = repo / "Cargo.toml"
        if cargo_toml.is_file():
            content = _read_text(cargo_toml) or ""
            in_deps = False
            for line in content.splitlines():
                if re.match(r"\[dependencies\]", line) or re.match(r"\[dev-dependencies\]", line):
                    in_deps = True
                    continue
                if line.startswith("[") and in_deps:
                    in_deps = False
                    continue
                if in_deps:
                    match = re.match(r"(\w[\w-]*)\s*=", line)
                    if match:
                        deps.append({"source": "Cargo.toml", "dependency": match.group(1)})

    if "Docker" in stack_types:
        for dockerfile in repo.glob("Dockerfile*"):
            content = _read_text(dockerfile) or ""
            for line in _extract_lines(content, r"^\s*FROM\s+"):
                image = re.sub(r"^\s*FROM\s+", "", line).split()[0]
                deps.append({"source": "Dockerfile", "dependency": image})
            break

    return deps


def find_infrastructure(repo: Path, stacks: list[dict]) -> list[dict]:
    """Find infrastructure configuration: ports, databases, storage, K8s resources."""
    infra: list[dict] = []
    stack_types = {s["type"] for s in stacks}

    # Dockerfile ports
    for dockerfile in repo.glob("Dockerfile*"):
        content = _read_text(dockerfile) or ""
        for match in re.finditer(r"EXPOSE\s+(\d+)", content):
            infra.append({"type": "port", "value": match.group(1), "source": "Dockerfile"})
        break

    # Helm values
    if "Helm" in stack_types:
        for values_file in [repo / "values.yaml", repo / "chart" / "values.yaml"]:
            if values_file.is_file():
                content = _read_text(values_file) or ""
                infra.append({"type": "helm_values", "value": _summarize_yaml(content), "source": str(values_file.name)})
                break
        # K8s resource types from templates
        for f in _walk_files(repo, "*.yaml"):
            rel = str(f.relative_to(repo))
            if "templates/" in rel:
                content = _read_text(f) or ""
                for match in re.finditer(r"kind:\s*(\w+)", content):
                    kind = match.group(1)
                    if kind not in ("NOTES",):
                        infra.append({"type": "k8s_resource", "value": kind, "source": rel})

    # Database references
    for f in _walk_files(repo, "*.groovy"):
        content = _read_text(f)
        if not content:
            continue
        if "dataSource" in content or "postgresql" in content.lower() or "jdbc:" in content:
            for match in re.finditer(r'url\s*=\s*["\']([^"\']+)["\']', content):
                infra.append({"type": "database", "value": match.group(1), "source": str(f.relative_to(repo))})
            for match in re.finditer(r'driverClassName\s*=\s*["\']([^"\']+)["\']', content):
                infra.append({"type": "db_driver", "value": match.group(1), "source": str(f.relative_to(repo))})

    for f in _walk_files(repo, "*.yaml"):
        content = _read_text(f) or ""
        if "postgresql" in content.lower() or "postgres" in content.lower():
            for match in re.finditer(r"(?:version|image):\s*[\"']?(\S*postgres\S*)[\"']?", content, re.IGNORECASE):
                infra.append({"type": "database", "value": match.group(1), "source": str(f.relative_to(repo))})
            # KubeDB-style: kind: Postgres + version: "X.Y"
            if re.search(r"kind:\s*Postgres", content):
                ver_match = re.search(r'version:\s*["\']?([\d.]+)["\']?', content)
                if ver_match:
                    infra.append({"type": "database", "value": f"PostgreSQL {ver_match.group(1)} (KubeDB)", "source": str(f.relative_to(repo))})

    return infra


def _walk_files(repo: Path, pattern: str) -> list[Path]:
    """Walk repo for files matching a glob pattern, skipping SKIP_DIRS."""
    results: list[Path] = []
    for f in repo.rglob(pattern):
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        if f.is_file():
            results.append(f)
    return results


def _summarize_yaml(content: str, max_lines: int = 30) -> str:
    """Extract top-level keys and notable values from YAML content."""
    lines = content.splitlines()[:max_lines]
    summary_parts: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            summary_parts.append(stripped)
    return "; ".join(summary_parts[:15])


def cross_reference(inventories: list[dict]) -> dict:
    """Find cross-repo references: shared models, DB links, port/service refs."""
    xref: dict = {"shared_models": [], "db_refs": [], "service_refs": []}

    # Shared model names
    model_map: dict[str, list[str]] = {}
    for inv in inventories:
        for m in inv.get("models", []):
            model_map.setdefault(m["name"], []).append(inv["repo_name"])
    xref["shared_models"] = [
        {"model": name, "repos": repos}
        for name, repos in model_map.items()
        if len(repos) > 1
    ]

    # Database references
    for inv in inventories:
        for inf in inv.get("infra", []):
            if inf["type"] in ("database", "db_driver"):
                xref["db_refs"].append({"repo": inv["repo_name"], "ref": inf["value"]})

    # Port references
    for inv in inventories:
        for inf in inv.get("infra", []):
            if inf["type"] == "port":
                xref["service_refs"].append({"repo": inv["repo_name"], "port": inf["value"]})

    return xref


def build_inventory(repo_path: str) -> dict:
    """Build complete structural inventory for a single repository."""
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        return {"repo_name": repo.name, "error": f"Directory not found: {repo_path}"}

    stacks = detect_stack(repo)
    return {
        "repo_name": repo.name,
        "repo_path": str(repo),
        "stack": stacks,
        "entry_points": find_entry_points(repo, stacks),
        "models": find_domain_models(repo, stacks),
        "endpoints": find_api_endpoints(repo, stacks),
        "dependencies": parse_dependencies(repo, stacks),
        "infra": find_infrastructure(repo, stacks),
    }


def run_deterministic_inventory(repo_paths: list[str]) -> dict:
    """Run Layer 1 across all repos and return combined inventory."""
    inventories = [build_inventory(p) for p in repo_paths]
    xref = cross_reference(inventories)
    return {"repositories": inventories, "cross_references": xref}


# ---------------------------------------------------------------------------
# Layer 2 — LLM documentation generation
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a software architect generating ARCHITECTURE documentation.
You receive a structured inventory of one or more repositories and produce a
technical architecture document in Markdown.

Do NOT cover business rules, validation logic, or domain requirements — \
a separate Business Intelligence tool handles those.

Focus on HOW the system is built, not what business logic it implements.

Your document MUST include these sections in order:

## System Overview
One paragraph: what this system is and its high-level architecture style.

## Architecture Diagram
A Mermaid flowchart (`graph TD` or `graph LR`) showing all services/components \
and their interactions. Use descriptive node labels and edge labels for protocols.

## Service Inventory
For each service/repository: name, role, technology stack (language, framework, \
versions), key endpoints, and communication patterns. Use a subsection (###) per service.

## Data Flow
How a typical request flows through the system end to end. Include sequence or \
data flow where helpful.

## Infrastructure & Deployment
Deployment topology, databases, container images, Helm charts, ports, storage, \
CI/CD pipelines, and environment configuration.

## Cross-Service Dependencies
Shared libraries, common data formats, inter-service contracts, and coupling points.

## Architectural Risks & Recommendations
Structural concerns: single points of failure, missing observability, \
tight coupling, scalability bottlenecks, upgrade blockers.

Output ONLY the markdown document. Do not wrap it in code fences."""


def run_llm_generation(inventory: dict, api_key: str, context: str = "", tone: str = "technical") -> str | None:
    """Send structural inventory to Claude and get architecture documentation."""
    try:
        import anthropic
    except ImportError:
        print("⚠️  anthropic package not installed. Run: pip install anthropic", file=sys.stderr)
        return None

    user_message = (
        "Generate a comprehensive architecture document for the following system.\n\n"
        "## Structural Inventory\n\n"
        f"```json\n{json.dumps(inventory, indent=2)}\n```"
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
        max_tokens=4096,
        system=apply_tone(SYSTEM_PROMPT, tone),
        messages=[{"role": "user", "content": user_message}],
    )

    text = response.content[0].text.strip()
    # Strip wrapping code fences if the model added them
    text = re.sub(r"^```(?:markdown)?\s*\n?", "", text)
    text = re.sub(r"\n?\s*```$", "", text)
    return text


# ---------------------------------------------------------------------------
# Layer 3 — Output formatting
# ---------------------------------------------------------------------------

def format_inventory_summary(inventory: dict) -> str:
    """Format the deterministic inventory as a markdown summary."""
    lines = ["# Architecture Documentation\n", "## Deterministic Inventory Summary\n"]

    for repo in inventory.get("repositories", []):
        name = repo.get("repo_name", "unknown")
        stacks = ", ".join(s["detail"] for s in repo.get("stack", []))
        lines.append(f"### {name}")
        lines.append(f"- **Stack:** {stacks}")
        lines.append(f"- **Entry points:** {len(repo.get('entry_points', []))}")
        lines.append(f"- **Domain models:** {len(repo.get('models', []))}")
        lines.append(f"- **Endpoints:** {len(repo.get('endpoints', []))}")
        lines.append(f"- **Dependencies:** {len(repo.get('dependencies', []))}")
        lines.append(f"- **Infrastructure items:** {len(repo.get('infra', []))}")

        if repo.get("models"):
            model_names = [m["name"] for m in repo["models"]]
            lines.append(f"- **Model names:** {', '.join(model_names)}")

        if repo.get("endpoints"):
            for ep in repo["endpoints"][:5]:
                lines.append(f"  - `{ep.get('method', '?')} {ep.get('path', '?')}`")
            if len(repo["endpoints"]) > 5:
                lines.append(f"  - ... and {len(repo['endpoints']) - 5} more")

        lines.append("")

    xref = inventory.get("cross_references", {})
    if xref.get("shared_models"):
        lines.append("### Cross-Repository References")
        for sm in xref["shared_models"]:
            lines.append(f"- **{sm['model']}** found in: {', '.join(sm['repos'])}")
        lines.append("")

    if xref.get("db_refs"):
        lines.append("### Database References")
        for ref in xref["db_refs"]:
            lines.append(f"- **{ref['repo']}**: `{ref['ref']}`")
        lines.append("")

    return "\n".join(lines)


def format_output(inventory: dict, llm_document: str | None) -> str:
    """Combine inventory summary and LLM document into final output."""
    parts = [format_inventory_summary(inventory)]

    if llm_document:
        parts.append("---\n")
        parts.append(llm_document)
    else:
        parts.append("> ℹ️ LLM documentation generation skipped (no API key or error).")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate architecture documentation from one or more repositories.",
    )
    parser.add_argument(
        "repo_paths",
        nargs="+",
        help="Paths to repository directories to analyze.",
    )
    parser.add_argument("--api-key", default=None, help="Anthropic API key (or set ANTHROPIC_API_KEY).")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown.")
    parser.add_argument("--context", default="", help="Focus area to sharpen analysis scope.")
    add_tone_arg(parser)
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")

    # Layer 1
    inventory = run_deterministic_inventory(args.repo_paths)

    # Layer 2
    llm_document = None
    if api_key:
        llm_document = run_llm_generation(inventory, api_key, args.context, args.tone)
    else:
        print("⚠️  No API key provided — skipping LLM documentation generation.", file=sys.stderr)

    # Layer 3
    if args.json:
        output = {
            "inventory": inventory,
            "document": llm_document,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_output(inventory, llm_document))

    return 0


if __name__ == "__main__":
    sys.exit(main())
