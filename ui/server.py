#!/usr/bin/env python3
"""Simple HTTP server that wraps the AI review tools with a REST API for the demo UI."""

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

# Project root — one level up from ui/
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env file into os.environ (no dependency needed for simple KEY=VALUE)
_env_file = PROJECT_ROOT / ".env"
if _env_file.is_file():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            value = value.strip()
            # Strip surrounding quotes (common .env convention)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)

# Serve built React app if available, else fall back to legacy index.html
UI_DIR = PROJECT_ROOT / "ui" / "dist"
if not UI_DIR.is_dir():
    UI_DIR = PROJECT_ROOT / "ui"


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle each request in a new thread so long-running tools don't block the UI."""
    daemon_threads = True


class ReviewHandler(SimpleHTTPRequestHandler):
    """Serves the UI and provides API endpoints for running reviews."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def do_GET(self):
        """Serve static files, discovery APIs, or SPA fallback."""
        path = urlparse(self.path).path

        if path == "/api/discover":
            try:
                self._handle_discover()
            except Exception as exc:
                self._send_json({"error": f"Discovery failed: {type(exc).__name__}"}, 500)
            return

        if path.startswith("/api/"):
            self.send_error(404, "Not Found")
            return

        # Static file or SPA fallback
        local_path = Path(self.directory) / path.lstrip("/")
        if local_path.is_file():
            super().do_GET()
        else:
            self.path = "/index.html"
            super().do_GET()

    def _handle_discover(self):
        """Auto-discover repos, scenarios, migration files, and spec files."""
        # Find repos: sibling directories that are git repos or projects
        parent = PROJECT_ROOT.parent
        project_markers = [
            ".git", "Cargo.toml", "build.gradle", "pom.xml", "package.json",
            "Chart.yaml", "Dockerfile", "go.mod", "setup.py", "pyproject.toml",
        ]
        repos = []
        for d in sorted(parent.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            is_project = any((d / m).exists() for m in project_markers)
            # Also detect by having src/ or grails-app/ or chart/
            if not is_project:
                is_project = any(
                    (d / s).is_dir() for s in ["src", "grails-app", "chart", "lib"]
                )
            if is_project:
                repos.append({"path": str(d), "name": d.name})

        # Find migration scenario files (*.cs under scenarios/)
        scenarios_dir = PROJECT_ROOT / "scenarios"
        migration_scenarios = []
        drift_scenarios = []
        if scenarios_dir.is_dir():
            for scenario_dir in sorted(scenarios_dir.iterdir()):
                if not scenario_dir.is_dir():
                    continue
                readme = scenario_dir / "README.md"
                description = ""
                if readme.is_file():
                    first_line = readme.read_text().strip().split("\n")[0]
                    description = first_line.lstrip("# ").strip()

                # Migration files
                cs_files = list(scenario_dir.glob("*.cs"))
                for f in cs_files:
                    rel = str(f.relative_to(PROJECT_ROOT))
                    mig_label = description or scenario_dir.name
                    # Keep original numbering (already 1-based for migrations)
                    migration_scenarios.append({
                        "file": rel,
                        "label": mig_label,
                        "scenario": scenario_dir.name,
                    })

                # Drift spec files
                spec_files = list(scenario_dir.glob("modified-spec.*"))
                for f in spec_files:
                    rel = str(f.relative_to(PROJECT_ROOT))
                    # Extract "What's wrong" and "What the AI should catch" from README
                    whats_wrong = ""
                    expected_catches: list[str] = []
                    if readme.is_file():
                        readme_text = readme.read_text()
                        wrong_match = re.search(
                            r"## What's wrong\s*\n(.*?)(?=\n## |\Z)",
                            readme_text, re.DOTALL,
                        )
                        if wrong_match:
                            # Keep only prose lines, skip markdown tables
                            prose_lines = [
                                ln for ln in wrong_match.group(1).strip().split("\n")
                                if ln.strip() and not ln.strip().startswith("|")
                                and not ln.strip().startswith("---")
                            ]
                            whats_wrong = " ".join(prose_lines)
                        catch_match = re.search(
                            r"## What the AI should catch\s*\n(.*?)(?=\n## |\Z)",
                            readme_text, re.DOTALL,
                        )
                        if catch_match:
                            for line in catch_match.group(1).strip().split("\n"):
                                line = line.strip().lstrip("- ").strip('"')
                                if line:
                                    expected_catches.append(line)

                    # Determine severity tag from scenario name
                    severity = "breaking"
                    if "optional" in scenario_dir.name or "required" in scenario_dir.name:
                        severity = "warning"

                    # Renumber drift scenarios starting from 1
                    drift_num = len(drift_scenarios) + 1
                    label = re.sub(
                        r"^Scenario \d+:",
                        f"Scenario {drift_num}:",
                        description or scenario_dir.name,
                    )
                    drift_scenarios.append({
                        "spec": rel,
                        "label": label,
                        "scenario": scenario_dir.name,
                        "whatsWrong": whats_wrong,
                        "expectedCatches": expected_catches[:4],
                        "severity": severity,
                    })

        # Find OpenAPI specs in the project (for old-spec reference)
        api_specs: list[dict] = []
        for pattern in ["**/api-spec.yaml", "**/openapi.yaml", "**/swagger.yaml",
                        "**/api-spec.json", "**/openapi.json", "**/swagger.json"]:
            for f in PROJECT_ROOT.glob(pattern):
                if "node_modules" in str(f) or "scenarios" in str(f):
                    continue
                rel = str(f.relative_to(PROJECT_ROOT))
                # Extract title from spec for display
                title = rel
                try:
                    import yaml as _yaml
                    spec_data = _yaml.safe_load(f.read_text()[:4000])
                    if isinstance(spec_data, dict):
                        info = spec_data.get("info", {})
                        spec_title = info.get("title", "")
                        spec_ver = info.get("version", "")
                        if spec_title:
                            title = f"{spec_title} {spec_ver}".strip()
                except Exception:
                    pass
                api_specs.append({"path": rel, "title": title})

        # Find frontend source dirs with descriptions
        frontend_dirs: list[dict] = []
        candidates = {
            "frontend/src": "Frontend app source (React/TS components)",
            "frontend": "Frontend directory",
            "src": "Source root",
            "ui-app/src": "Demo UI source (React + Connect)",
        }
        for candidate, desc in candidates.items():
            if (PROJECT_ROOT / candidate).is_dir():
                # Count files to give a sense of size
                file_count = sum(1 for _ in (PROJECT_ROOT / candidate).rglob("*") if _.is_file())
                frontend_dirs.append({
                    "path": candidate,
                    "label": f"{desc} ({file_count} files)",
                })

        self._send_json({
            "repos": repos,
            "migrationScenarios": migration_scenarios,
            "driftScenarios": drift_scenarios,
            "apiSpecs": api_specs,
            "frontendDirs": frontend_dirs,
        })

    def _scan_entities(self, repo_path: Path) -> dict[str, list[str]]:
        """Scan a repo for entity/domain classes. Returns {name: [files]}."""
        found: dict[str, list[str]] = {}
        # Grails convention
        search_dirs = [
            repo_path / "grails-app" / "domain",
            repo_path / "src" / "main" / "groovy",
            repo_path / "src" / "main" / "java",
        ]
        # Also scan any 'domain', 'model', 'entities' dir at any depth
        for dir_pattern in ["domain", "model", "models", "entities", "Domain", "Models"]:
            for d in repo_path.glob(f"**/{dir_pattern}"):
                if d.is_dir() and "test" not in str(d).lower() and "build" not in str(d).lower():
                    search_dirs.append(d)

        seen_files: set[str] = set()
        for d in search_dirs:
            if not d.is_dir():
                continue
            for ext in ["*.groovy", "*.java", "*.cs", "*.rs", "*.kt"]:
                for f in d.rglob(ext):
                    fstr = str(f)
                    if fstr in seen_files:
                        continue
                    seen_files.add(fstr)
                    try:
                        content = f.read_text(errors="ignore")
                        for m in re.finditer(r"class\s+(\w+)\s", content):
                            cls_name = m.group(1)
                            if cls_name[0].isupper() and not cls_name.startswith("Test"):
                                found.setdefault(cls_name, []).append(
                                    str(f.relative_to(repo_path))
                                )
                        # Rust structs
                        for m in re.finditer(r"(?:pub\s+)?struct\s+(\w+)", content):
                            cls_name = m.group(1)
                            if cls_name[0].isupper():
                                found.setdefault(cls_name, []).append(
                                    str(f.relative_to(repo_path))
                                )
                    except Exception:
                        pass
        return found

    def do_POST(self):
        path = urlparse(self.path).path

        try:
            if path == "/api/review-migration":
                self._handle_migration_review()
            elif path == "/api/scan-entities":
                self._handle_scan_entities()
            elif path == "/api/check-drift":
                self._handle_drift_check()
            elif path == "/api/scan-secrets":
                self._handle_scan_secrets()
            elif path == "/api/check-model-drift":
                self._handle_model_drift()
            elif path == "/api/generate-arch-doc":
                self._handle_arch_doc()
            elif path == "/api/audit-deps":
                self._handle_audit_deps()
            elif path == "/api/extract-requirements":
                self._handle_extract_requirements()
            elif path == "/api/scenario-planner":
                self._handle_scenario_planner()
            else:
                self.send_error(404, "Not Found")
        except Exception as exc:
            self._send_json({"error": f"Internal server error: {type(exc).__name__}"}, 500)

    def _read_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return None
        if length <= 0:
            return {}
        if length > 10 * 1024 * 1024:  # 10 MB cap
            return None
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw) if raw else {}
            if not isinstance(parsed, dict):
                return None
            return parsed
        except json.JSONDecodeError:
            return None

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _validate_str(self, body: dict, key: str) -> str | None:
        """Return a validated string value, or None if missing/invalid."""
        val = body.get(key)
        if not isinstance(val, str) or not val.strip():
            return None
        return val.strip()

    def _run_tool(self, tool_name: str, args: list[str], tone: str | None = None) -> dict:
        """Run a tool script and return {markdown, exit_code, duration}."""
        if tone and tone in ("business", "childlike"):
            args = args + ["--tone", tone]
        start = time.time()
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        try:
            result = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "tools" / tool_name)] + args,
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
                cwd=str(PROJECT_ROOT),
            )
        except subprocess.TimeoutExpired:
            duration = round(time.time() - start, 1)
            return {
                "markdown": "**⏱️ Timeout:** Tool did not complete within 180 seconds.",
                "exit_code": 124,
                "duration": duration,
            }
        except OSError as exc:
            return {
                "markdown": f"**Error:** Failed to run tool: {exc}",
                "exit_code": 1,
                "duration": round(time.time() - start, 1),
            }

        duration = round(time.time() - start, 1)
        output = result.stdout or result.stderr or "(no output)"

        return {
            "markdown": output,
            "exit_code": result.returncode,
            "duration": duration,
        }

    def _handle_migration_review(self):
        body = self._read_body()
        if body is None:
            self._send_json({"error": "Invalid JSON in request body"}, 400)
            return
        filepath = self._validate_str(body, "file")
        if not filepath:
            self._send_json({"error": "Missing 'file' parameter"}, 400)
            return

        full_path = PROJECT_ROOT / filepath
        if not full_path.is_file():
            self._send_json({"error": f"File not found: {filepath}"}, 404)
            return

        context = self._validate_str(body, "context")
        cmd_args = [str(full_path)]
        if context:
            cmd_args += ["--context", context]
        self._send_json(self._run_tool("review_migration.py", cmd_args, self._validate_str(body, "tone")))

    def _handle_drift_check(self):
        body = self._read_body()
        if body is None:
            self._send_json({"error": "Invalid JSON in request body"}, 400)
            return
        spec = self._validate_str(body, "spec")
        old_spec = self._validate_str(body, "oldSpec")
        frontend = self._validate_str(body, "frontend")

        if not spec:
            self._send_json({"error": "Missing 'spec' parameter"}, 400)
            return

        for f in [spec, old_spec]:
            if f and not (PROJECT_ROOT / f).is_file():
                self._send_json({"error": f"File not found: {f}"}, 404)
                return

        cmd_args = ["--spec", str(PROJECT_ROOT / spec)]
        if frontend:
            cmd_args += ["--frontend", str(PROJECT_ROOT / frontend)]
        if old_spec:
            cmd_args += ["--old-spec", str(PROJECT_ROOT / old_spec)]
        context = self._validate_str(body, "context")
        if context:
            cmd_args += ["--context", context]

        self._send_json(self._run_tool("check_contract_drift.py", cmd_args, self._validate_str(body, "tone")))

    def _handle_scan_secrets(self):
        body = self._read_body()
        if body is None:
            self._send_json({"error": "Invalid JSON in request body"}, 400)
            return
        # Support both single repoPath and multiple repoPaths
        repo_paths = body.get("repoPaths") or []
        if not repo_paths:
            single = self._validate_str(body, "repoPath")
            if single:
                repo_paths = [single]
        if not repo_paths:
            self._send_json({"error": "No repositories selected"}, 400)
            return
        for rp in repo_paths:
            if not Path(rp).is_dir():
                self._send_json({"error": f"Directory not found: {rp}"}, 404)
                return
        context = self._validate_str(body, "context")
        tone = self._validate_str(body, "tone")
        combined = self._run_multi_single("scan_secrets.py", repo_paths, context, tone)
        self._send_json(combined)

    def _run_multi_single(self, tool: str, repo_paths: list, context: str | None, tone: str | None) -> dict:
        """Run a single-repo tool for each path, combining results."""
        if len(repo_paths) == 1:
            cmd_args = [repo_paths[0]]
            if context:
                cmd_args += ["--context", context]
            return self._run_tool(tool, cmd_args, tone)
        # Multiple repos — run each and merge markdown
        import time
        t0 = time.time()
        all_md = []
        combined_exit = 0
        for rp in repo_paths:
            cmd_args = [rp]
            if context:
                cmd_args += ["--context", context]
            result = self._run_tool(tool, cmd_args, tone)
            all_md.append(result.get("markdown", ""))
            if result.get("exit_code", 0) != 0:
                combined_exit = result["exit_code"]
        duration = round(time.time() - t0, 1)
        return {
            "markdown": "\n\n---\n\n".join(all_md),
            "exit_code": combined_exit,
            "duration": duration,
        }

    def _handle_model_drift(self):
        body = self._read_body()
        if body is None:
            self._send_json({"error": "Invalid JSON in request body"}, 400)
            return
        repo_a = self._validate_str(body, "repoA")
        repo_b = self._validate_str(body, "repoB")
        entity = self._validate_str(body, "entity")
        if not entity:
            self._send_json({"error": "Entity name required"}, 400)
            return
        for p in [repo_a, repo_b]:
            if not p or not Path(p).is_dir():
                self._send_json({"error": f"Directory not found: {p}"}, 404)
                return
        cmd_args = [repo_a, repo_b, entity]
        context = self._validate_str(body, "context")
        if context:
            cmd_args += ["--context", context]
        cmd_args = ["--"] + cmd_args
        self._send_json(self._run_tool("check_model_drift.py", cmd_args, self._validate_str(body, "tone")))

    def _handle_arch_doc(self):
        body = self._read_body()
        if body is None:
            self._send_json({"error": "Invalid JSON in request body"}, 400)
            return
        repo_paths = body.get("repoPaths", [])
        if not isinstance(repo_paths, list) or not repo_paths:
            self._send_json({"error": "At least one repo path required"}, 400)
            return
        validated = []
        for p in repo_paths:
            if not isinstance(p, str) or not Path(p).is_dir():
                self._send_json({"error": f"Directory not found: {p}"}, 404)
                return
            validated.append(p)
        context = self._validate_str(body, "context")
        if context:
            validated += ["--context", context]
        self._send_json(self._run_tool("generate_arch_doc.py", validated, self._validate_str(body, "tone")))

    def _handle_scan_entities(self):
        """Scan multiple repos and return entities shared across 2+ repos."""
        body = self._read_body()
        if body is None:
            self._send_json({"error": "Invalid JSON"}, 400)
            return

        repo_paths = body.get("repos", [])
        if not isinstance(repo_paths, list) or len(repo_paths) < 2:
            self._send_json({"error": "At least 2 repo paths required"}, 400)
            return

        # Validate and scan each repo
        repo_entities: dict[str, dict[str, list[str]]] = {}
        for p in repo_paths:
            if not isinstance(p, str) or not Path(p).is_dir():
                self._send_json({"error": f"Directory not found: {p}"}, 404)
                return
            repo_entities[p] = self._scan_entities(Path(p))

        # Find entities present in 2+ repos
        all_entity_names: dict[str, set[str]] = {}
        for repo_path, entities in repo_entities.items():
            repo_name = Path(repo_path).name
            for entity_name in entities:
                all_entity_names.setdefault(entity_name, set()).add(repo_name)

        results = []
        for name in sorted(all_entity_names.keys()):
            repo_names = all_entity_names[name]
            shared = len(repo_names) >= 2
            files_by_repo = {}
            for repo_path, entities in repo_entities.items():
                repo_name = Path(repo_path).name
                if name in entities:
                    files_by_repo[repo_name] = entities[name]

            results.append({
                "name": name,
                "shared": shared,
                "repoCount": len(repo_names),
                "repos": sorted(repo_names),
                "filesByRepo": files_by_repo,
            })

        shared_results = [r for r in results if r["shared"]]
        unique_results = [r for r in results if not r["shared"]][:30]

        # Generate pairwise comparisons for the UI
        pairs = []
        repo_names = [Path(p).name for p in repo_paths]
        for i, p_a in enumerate(repo_paths):
            for p_b in repo_paths[i + 1:]:
                name_a = Path(p_a).name
                name_b = Path(p_b).name
                shared_in_pair = sorted(
                    set(repo_entities[p_a].keys()) & set(repo_entities[p_b].keys())
                )
                pairs.append({
                    "repoA": p_a,
                    "repoB": p_b,
                    "nameA": name_a,
                    "nameB": name_b,
                    "sharedEntities": shared_in_pair,
                })

        self._send_json({
            "entities": shared_results + unique_results,
            "sharedCount": len(shared_results),
            "repoCount": len(repo_paths),
            "repos": repo_names,
            "pairs": pairs,
        })

    def _handle_audit_deps(self):
        body = self._read_body()
        if body is None:
            self._send_json({"error": "Invalid JSON in request body"}, 400)
            return
        repo_paths = body.get("repoPaths") or []
        if not repo_paths:
            single = self._validate_str(body, "repoPath")
            if single:
                repo_paths = [single]
        if not repo_paths:
            self._send_json({"error": "No repositories selected"}, 400)
            return
        for rp in repo_paths:
            if not Path(rp).is_dir():
                self._send_json({"error": f"Directory not found: {rp}"}, 404)
                return
        context = self._validate_str(body, "context")
        tone = self._validate_str(body, "tone")
        combined = self._run_multi_single("audit_deps.py", repo_paths, context, tone)
        self._send_json(combined)

    def _handle_extract_requirements(self):
        body = self._read_body()
        if body is None:
            self._send_json({"error": "Invalid JSON in request body"}, 400)
            return

        # Support both single repoPath and multiple repoPaths
        repo_paths = body.get("repoPaths", [])
        if not repo_paths:
            single = self._validate_str(body, "repoPath")
            if single:
                repo_paths = [single]

        if not repo_paths:
            self._send_json({"error": "No repository paths provided"}, 400)
            return

        for p in repo_paths:
            if not isinstance(p, str) or not Path(p).is_dir():
                self._send_json({"error": f"Directory not found: {p}"}, 404)
                return

        context = self._validate_str(body, "context")
        if context:
            repo_paths += ["--context", context]
        self._send_json(self._run_tool("extract_requirements.py", repo_paths, self._validate_str(body, "tone")))

    def _handle_scenario_planner(self):
        body = self._read_body()
        if body is None:
            self._send_json({"error": "Invalid JSON in request body"}, 400)
            return

        scenario = self._validate_str(body, "scenario")
        if not scenario:
            self._send_json({"error": "Scenario description is required"}, 400)
            return

        repo_paths = body.get("repoPaths", [])
        if not isinstance(repo_paths, list) or not repo_paths:
            self._send_json({"error": "At least one repo path required"}, 400)
            return

        for p in repo_paths:
            if not isinstance(p, str) or not Path(p).is_dir():
                self._send_json({"error": f"Directory not found: {p}"}, 404)
                return

        cmd_args = repo_paths + ["--scenario", scenario]
        context = self._validate_str(body, "context")
        if context:
            cmd_args += ["--context", context]
        self._send_json(self._run_tool("scenario_planner.py", cmd_args, self._validate_str(body, "tone")))


def main():
    port = int(os.environ.get("PORT", 8080))
    server = ThreadedHTTPServer(("127.0.0.1", port), ReviewHandler)
    print(f"🏗️  Station Retrofit UI running at http://localhost:{port}")
    print(f"   Project root: {PROJECT_ROOT}")
    print(f"   Serving UI from: {UI_DIR}")
    print(f"   API key: {'✅ configured' if os.environ.get('ANTHROPIC_API_KEY') else '⚠️  not set (deterministic checks only)'}")
    print()

    def handle_signal(signum, _frame):
        print(f"\nReceived signal {signum}, shutting down.")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, handle_signal)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
