#!/usr/bin/env python3
"""Simple HTTP server that wraps the AI review tools with a REST API for the demo UI."""

import json
import os
import subprocess
import sys
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# Project root — one level up from ui/
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ReviewHandler(SimpleHTTPRequestHandler):
    """Serves the UI and provides API endpoints for running reviews."""

    def __init__(self, *args, **kwargs):
        # Serve static files from ui/ directory
        super().__init__(*args, directory=str(PROJECT_ROOT / "ui"), **kwargs)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/review-migration":
            self._handle_migration_review()
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
        else:
            self.send_error(404, "Not Found")

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        return json.loads(raw) if raw else {}

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _handle_migration_review(self):
        body = self._read_body()
        filepath = body.get("file", "")

        full_path = PROJECT_ROOT / filepath
        if not full_path.is_file():
            self._send_json({"error": f"File not found: {filepath}"}, 404)
            return

        start = time.time()
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "review_migration.py"), str(full_path)],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            cwd=str(PROJECT_ROOT),
        )

        duration = round(time.time() - start, 1)
        output = result.stdout or result.stderr

        self._send_json({
            "markdown": output,
            "exit_code": result.returncode,
            "duration": duration,
        })

    def _handle_drift_check(self):
        body = self._read_body()
        spec = body.get("spec", "")
        old_spec = body.get("oldSpec", "")
        frontend = body.get("frontend", "")

        for f in [spec, old_spec]:
            if f and not (PROJECT_ROOT / f).is_file():
                self._send_json({"error": f"File not found: {f}"}, 404)
                return

        start = time.time()
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "check_contract_drift.py"),
            "--spec", str(PROJECT_ROOT / spec),
            "--frontend", str(PROJECT_ROOT / frontend),
        ]
        if old_spec:
            cmd.extend(["--old-spec", str(PROJECT_ROOT / old_spec)])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            cwd=str(PROJECT_ROOT),
        )

        duration = round(time.time() - start, 1)
        output = result.stdout or result.stderr

        self._send_json({
            "markdown": output,
            "exit_code": result.returncode,
            "duration": duration,
        })


    def _run_tool(self, tool_name: str, args: list[str]) -> dict:
        """Run a tool script and return {markdown, exit_code, duration}."""
        start = time.time()
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / tool_name)] + args,
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
            cwd=str(PROJECT_ROOT),
        )

        duration = round(time.time() - start, 1)
        output = result.stdout or result.stderr

        return {
            "markdown": output,
            "exit_code": result.returncode,
            "duration": duration,
        }

    def _handle_scan_secrets(self):
        body = self._read_body()
        repo_path = body.get("repoPath", "")
        if not repo_path or not Path(repo_path).is_dir():
            self._send_json({"error": f"Directory not found: {repo_path}"}, 404)
            return
        self._send_json(self._run_tool("scan_secrets.py", [repo_path]))

    def _handle_model_drift(self):
        body = self._read_body()
        repo_a = body.get("repoA", "")
        repo_b = body.get("repoB", "")
        entity = body.get("entity", "")
        if not entity:
            self._send_json({"error": "Entity name required"}, 400)
            return
        for p in [repo_a, repo_b]:
            if not p or not Path(p).is_dir():
                self._send_json({"error": f"Directory not found: {p}"}, 404)
                return
        self._send_json(self._run_tool("check_model_drift.py", [repo_a, repo_b, entity]))

    def _handle_arch_doc(self):
        body = self._read_body()
        repo_paths = body.get("repoPaths", [])
        if not repo_paths:
            self._send_json({"error": "At least one repo path required"}, 400)
            return
        for p in repo_paths:
            if not Path(p).is_dir():
                self._send_json({"error": f"Directory not found: {p}"}, 404)
                return
        self._send_json(self._run_tool("generate_arch_doc.py", repo_paths))

    def _handle_audit_deps(self):
        body = self._read_body()
        repo_path = body.get("repoPath", "")
        if not repo_path or not Path(repo_path).is_dir():
            self._send_json({"error": f"Directory not found: {repo_path}"}, 404)
            return
        self._send_json(self._run_tool("audit_deps.py", [repo_path]))


def main():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), ReviewHandler)
    print(f"🏗️  Station Retrofit UI running at http://localhost:{port}")
    print(f"   Project root: {PROJECT_ROOT}")
    print(f"   API key: {'✅ configured' if os.environ.get('ANTHROPIC_API_KEY') else '⚠️  not set (deterministic checks only)'}")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
