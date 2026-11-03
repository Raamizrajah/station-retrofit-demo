#!/usr/bin/env python3
"""Analyse what's needed to enable a feature or change in a repository."""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from llm_utils import add_tone_arg, apply_tone

# ---------------------------------------------------------------------------
# Layer 1 — Deterministic code extraction (relevant context for the scenario)
# ---------------------------------------------------------------------------

SKIP_DIRS = {
    ".git", "node_modules", "build", "dist", "target", "out", "__pycache__",
    ".gradle", ".idea", ".vscode", "vendor", "bin", "obj", ".terraform",
}

MAX_FILE_SIZE = 80_000
SCAN_EXTENSIONS = {
    ".java", ".groovy", ".cs", ".rs", ".py", ".go", ".kt",
    ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml", ".json",
    ".xml", ".toml", ".properties", ".gradle", ".tf", ".hcl",
    ".sql", ".graphql", ".proto",
}


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def safe_read(path: Path, max_size: int = MAX_FILE_SIZE) -> str:
    try:
        return path.read_text(errors="ignore")[:max_size]
    except Exception:
        return ""


def find_relevant_files(repo_path: Path, scenario: str) -> list[dict]:
    """Find files relevant to the scenario using keyword matching."""
    keywords = extract_keywords(scenario)
    relevant: list[dict] = []

    for fpath in repo_path.rglob("*"):
        if should_skip(fpath) or not fpath.is_file():
            continue
        if fpath.suffix not in SCAN_EXTENSIONS:
            continue

        rel = str(fpath.relative_to(repo_path))
        rel_lower = rel.lower()

        # Score relevance: filename match + content match
        score = 0
        for kw in keywords:
            if kw in rel_lower:
                score += 3  # filename match is strong signal

        # For high-scoring files or config files, check content
        is_config = any(k in rel_lower for k in [
            "config", "application", "settings", "docker", "helm",
            "chart", "values", "deploy", "ci", "pipeline",
        ])

        if score > 0 or is_config:
            content = safe_read(fpath, 20_000)
            for kw in keywords:
                count = content.lower().count(kw)
                score += min(count, 5)  # cap per-keyword

            if score > 0:
                # Keep a snippet of the most relevant section
                snippet = extract_relevant_snippet(content, keywords)
                relevant.append({
                    "file": rel,
                    "score": score,
                    "snippet": snippet,
                    "is_config": is_config,
                })

    # Sort by relevance, take top files
    relevant.sort(key=lambda x: x["score"], reverse=True)
    return relevant[:25]


def extract_keywords(scenario: str) -> list[str]:
    """Extract search keywords from the scenario description."""
    # Common stop words to exclude
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "need", "want", "like",
        "add", "enable", "implement", "create", "make", "set", "use",
        "for", "to", "in", "on", "at", "by", "with", "from", "of",
        "and", "or", "but", "not", "if", "then", "else", "when", "how",
        "what", "where", "which", "who", "that", "this", "it", "we", "i",
        "up", "so", "no", "new", "also", "feature", "change", "update",
    }
    words = re.findall(r'\b[a-z][a-z0-9_-]{2,}\b', scenario.lower())
    keywords = [w for w in words if w not in stop]
    # Also include multi-word phrases (camelCase/snake_case from scenario)
    phrases = re.findall(r'[A-Z][a-z]+(?:[A-Z][a-z]+)+', scenario)
    for p in phrases:
        keywords.append(p.lower())
    return list(dict.fromkeys(keywords))[:15]  # dedupe, cap


def extract_relevant_snippet(content: str, keywords: list[str]) -> str:
    """Extract a relevant code snippet around keyword matches."""
    lines = content.split("\n")
    best_line = -1
    best_score = 0

    for i, line in enumerate(lines):
        score = sum(1 for kw in keywords if kw in line.lower())
        if score > best_score:
            best_score = score
            best_line = i

    if best_line < 0:
        return ""

    start = max(0, best_line - 5)
    end = min(len(lines), best_line + 15)
    snippet = "\n".join(lines[start:end])
    return snippet[:1500]


def gather_project_structure(repo_path: Path) -> str:
    """Get a summary of the project structure."""
    dirs: list[str] = []
    files: list[str] = []
    for item in sorted(repo_path.iterdir()):
        if item.name.startswith(".") or item.name in SKIP_DIRS:
            continue
        if item.is_dir():
            subdirs = [d.name for d in item.iterdir() if d.is_dir() and d.name not in SKIP_DIRS]
            dirs.append(f"📁 {item.name}/ ({len(subdirs)} subdirs)")
        elif item.is_file():
            files.append(f"📄 {item.name}")
    return "\n".join(dirs + files[:20])


def gather_context(repo_paths: list[Path], scenario: str) -> dict:
    """Gather all relevant context for the scenario analysis."""
    all_files: list[dict] = []
    structures: list[str] = []

    for repo_path in repo_paths:
        relevant = find_relevant_files(repo_path, scenario)
        for f in relevant:
            f["repo"] = repo_path.name
            f["file"] = f"{repo_path.name}/{f['file']}"
        all_files.extend(relevant)

        structure = gather_project_structure(repo_path)
        structures.append(f"### {repo_path.name}\n{structure}")

    return {
        "relevantFiles": all_files,
        "projectStructures": "\n\n".join(structures),
        "repoNames": [p.name for p in repo_paths],
        "scenario": scenario,
    }


# ---------------------------------------------------------------------------
# Layer 2 — LLM analysis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a senior software architect and technical lead. A team wants to enable a new feature \
or make a change in their existing brownfield system. Analyse the codebase context provided \
and produce a structured implementation plan.

Respond in markdown with these sections:

## 📋 Executive Summary
One paragraph: what this change involves, estimated complexity (Low/Medium/High/Very High), \
and the key risk.

## 🔍 Impact Analysis
What parts of the system are affected? List each component/service/file area and how it's impacted.

## 📝 Implementation Plan
Step-by-step plan with concrete tasks. For each step:
- **What**: specific change needed
- **Where**: file(s) to modify
- **How**: brief technical approach
- **Effort**: S/M/L

## ⚙️ Configuration & Setup
What configuration, environment variables, infrastructure, or dependencies need to change?

## ⚠️ Risks & Mitigations
| Risk | Severity | Mitigation |
|------|----------|------------|
| ... | High/Medium/Low | ... |

## 🧪 Testing Strategy
What tests are needed to validate this change? Unit, integration, E2E?

## 📊 Effort Estimate
| Category | Estimate |
|----------|----------|
| Development | X days |
| Testing | X days |
| Config/Deploy | X days |
| **Total** | **X days** |

Be specific and reference actual code from the context. Don't invent files that don't exist. \
If the codebase doesn't have enough context to answer confidently, say so."""


def run_llm_analysis(context: dict, api_key: str, tone: str = "technical") -> str | None:
    """Send gathered context to LLM for scenario analysis."""
    try:
        import anthropic
    except ImportError:
        return None

    # Build prompt
    parts = [
        f"## Scenario\n**{context['scenario']}**\n",
        f"## Repositories\n{', '.join(context['repoNames'])}\n",
        f"## Project Structure\n{context['projectStructures']}\n",
    ]

    if context["relevantFiles"]:
        parts.append("## Relevant Code Files\n")
        for f in context["relevantFiles"]:
            config_tag = " [CONFIG]" if f.get("is_config") else ""
            parts.append(f"### `{f['file']}`{config_tag} (relevance: {f['score']})")
            if f["snippet"]:
                parts.append(f"```\n{f['snippet']}\n```\n")

    user_message = "\n".join(parts)

    # Cap prompt
    if len(user_message) > 80_000:
        user_message = user_message[:80_000] + "\n\n> ⚠️ Prompt truncated to fit API limits."

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)

    try:
        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "eu.anthropic.claude-sonnet-4-6"),
            max_tokens=4096,
            system=apply_tone(SYSTEM_PROMPT, tone),
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"⚠️ LLM analysis failed: {e}"


# ---------------------------------------------------------------------------
# Layer 3 — Output formatting
# ---------------------------------------------------------------------------

def format_deterministic(context: dict) -> str:
    """Format the deterministic findings."""
    lines = [f"# Scenario Analysis: {context['scenario']}\n"]
    lines.append(f"**Repositories:** {', '.join(context['repoNames'])}\n")

    if context["relevantFiles"]:
        lines.append(f"## Relevant Files Found ({len(context['relevantFiles'])})\n")
        for f in context["relevantFiles"][:15]:
            config_tag = " 🔧" if f.get("is_config") else ""
            lines.append(f"- `{f['file']}`{config_tag} (relevance: {f['score']})")
    else:
        lines.append("\n> ⚠️ No files found matching the scenario keywords. "
                     "The LLM will analyse based on project structure alone.")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyse what's needed to enable a feature or change in a repository."
    )
    parser.add_argument("repo_paths", nargs="+", help="Path(s) to repository root(s).")
    parser.add_argument("--scenario", required=True, help="Feature or change to analyse.")
    parser.add_argument("--context", default="", help="Additional context to focus the analysis.")
    add_tone_arg(parser)
    parser.add_argument("--api-key", default=None, help="Anthropic API key.")
    args = parser.parse_args()

    repos = [Path(p) for p in args.repo_paths]
    for repo in repos:
        if not repo.is_dir():
            print(f"Error: {repo} is not a directory.", file=sys.stderr)
            return 1

    scenario = args.scenario
    if args.context:
        scenario += f"\n\nAdditional context: {args.context}"

    # Layer 1: gather relevant context
    context = gather_context(repos, scenario)
    det_output = format_deterministic(context)

    # Layer 2: LLM analysis
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")

    if api_key:
        llm_output = run_llm_analysis(context, api_key, args.tone)
        if llm_output:
            print(llm_output)
            print(f"\n---\n\n{det_output}")
        else:
            print(det_output)
            print("\n> ℹ️ LLM analysis skipped (error).")
    else:
        print(det_output)
        print("\n> ℹ️ LLM analysis skipped (no API key).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
