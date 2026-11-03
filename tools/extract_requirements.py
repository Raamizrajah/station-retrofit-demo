#!/usr/bin/env python3
"""Extract functionality, business rules, and requirements from a repository using code analysis + LLM."""

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from llm_utils import add_tone_arg, apply_tone

# ---------------------------------------------------------------------------
# Layer 1 — Deterministic code extraction
# ---------------------------------------------------------------------------

SKIP_DIRS = {
    ".git", "node_modules", "build", "dist", "target", "out", "__pycache__",
    ".gradle", ".idea", ".vscode", "vendor", "bin", "obj", ".terraform",
}

SKIP_FILE_PATTERNS = {"jquery", ".min.js", ".min.css", "vendor", "polyfill", "bundle"}

MAX_FILE_SIZE = 100_000  # 100KB


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def safe_read(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")[:MAX_FILE_SIZE]
    except Exception:
        return ""


def extract_routes(content: str, filepath: str) -> list[dict]:
    """Extract HTTP route/endpoint definitions."""
    routes = []
    patterns = [
        # Java/Spring: @GetMapping, @PostMapping, etc.
        (r'@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*["\']([^"\']*)["\']', "annotation"),
        # Grails: static allowedMethods or URL mappings
        (r'["\']/([\w/{}:]+)["\']', "string_route"),
        # Ratpack: get/post/put/delete handlers
        (r'\b(get|post|put|delete|patch)\s*\(\s*["\']([^"\']*)["\']', "handler"),
        # Express/Axum/Actix: .get("/path"), .route("/path")
        (r'\.(get|post|put|delete|route)\s*\(\s*["\']([^"\']*)["\']', "framework"),
        # Rust Axum: .route("/path", get(handler))
        (r'\.route\s*\(\s*["\']([^"\']*)["\']', "axum_route"),
    ]
    for pattern, kind in patterns:
        for m in re.finditer(pattern, content):
            route = m.group(2) if m.lastindex >= 2 else m.group(1)
            if route and "/" in route:
                routes.append({"route": route, "kind": kind, "file": filepath})
    return routes


def extract_domain_models(content: str, filepath: str) -> list[dict]:
    """Extract domain/entity classes with their fields and constraints."""
    models = []
    # Class definitions
    class_matches = list(re.finditer(
        r'(?:public\s+)?(?:class|struct|data\s+class)\s+(\w+)',
        content
    ))
    for cm in class_matches:
        name = cm.group(1)
        # Extract a window of code after the class definition
        start = cm.start()
        end = min(start + 3000, len(content))
        body = content[start:end]

        fields = []
        # Java/Groovy fields
        for fm in re.finditer(r'(?:String|int|long|boolean|Integer|Long|Date\w*|UUID|BigDecimal|double|float)\s+(\w+)', body):
            fields.append(fm.group(1))
        # Groovy constraints
        constraints = []
        constraint_block = re.search(r'static\s+constraints\s*=\s*\{([^}]+)\}', body)
        if constraint_block:
            constraints.append(constraint_block.group(1).strip())
        # C# properties
        for fm in re.finditer(r'public\s+\w+\??\s+(\w+)\s*\{\s*get', body):
            fields.append(fm.group(1))

        if fields:
            models.append({
                "name": name,
                "file": filepath,
                "fields": fields[:20],
                "constraints": constraints,
            })
    return models


def extract_validation_rules(content: str, filepath: str) -> list[dict]:
    """Extract validation logic and business rules."""
    rules = []
    patterns = [
        (r'(?:nullable|blank|unique|maxSize|minSize|matches|inList|range|validator)\s*:\s*([^\n,}]+)', "grails_constraint"),
        (r'\[(?:Required|StringLength|Range|MaxLength|MinLength|RegularExpression)\(([^)]*)\)\]', "dotnet_annotation"),
        (r'@(?:NotNull|NotBlank|NotEmpty|Size|Min|Max|Pattern|Valid|Email)\b(?:\(([^)]*)\))?', "java_validation"),
        (r'if\s*\(.*?(?:throw|raise|return\s+(?:bad|error|false|null)|abort|reject)\b', "guard_clause"),
    ]
    for pattern, kind in patterns:
        for m in re.finditer(pattern, content):
            # Get surrounding context
            line_start = content.rfind("\n", 0, m.start()) + 1
            line_end = content.find("\n", m.end())
            line = content[line_start:line_end].strip()
            if len(line) > 200:
                line = line[:200] + "…"
            rules.append({"rule": line, "kind": kind, "file": filepath})
    return rules


def extract_config(content: str, filepath: str) -> list[dict]:
    """Extract configuration that implies business rules (timeouts, limits, feature flags)."""
    configs = []
    patterns = [
        (r'(?:timeout|max_retries|batch_size|limit|threshold|ttl|cache|rate.?limit|max.?size|page.?size)\s*[:=]\s*([^\n,]+)', "config_value"),
        (r'(?:enabled|disabled|feature|flag|toggle)\s*[:=]\s*([^\n,]+)', "feature_flag"),
    ]
    for pattern, _ in patterns:
        for m in re.finditer(pattern, content, re.IGNORECASE):
            line_start = content.rfind("\n", 0, m.start()) + 1
            line_end = content.find("\n", m.end())
            line = content[line_start:line_end].strip()
            if len(line) > 200:
                line = line[:200] + "…"
            configs.append({"config": line, "file": filepath})
    return configs


def extract_error_handling(content: str, filepath: str) -> list[dict]:
    """Extract error messages that reveal business rules."""
    errors = []
    for m in re.finditer(r'(?:message|error|msg|reason)\s*[:=]\s*["\']([^"\']{10,})["\']', content, re.IGNORECASE):
        errors.append({"message": m.group(1)[:200], "file": filepath})
    return errors


CONFIG_READ_LIMIT = 10_000       # config/manifest files
LOCKFILE_READ_LIMIT = 300_000    # Cargo.lock etc. (resolved versions)
MAX_INDEXED_FILES = 50_000
MAX_SCANNED_FILES = 600
_RX_FLAGS = re.IGNORECASE | re.MULTILINE


def _read_config(path: Path, limit: int = CONFIG_READ_LIMIT) -> str:
    try:
        with open(path, "r", errors="ignore") as fh:
            return fh.read(limit)
    except Exception:
        return ""


def _index_repo(root: Path) -> list[str]:
    """List repo files (posix-style relative paths), shallowest first, pruning SKIP_DIRS."""
    files: list[str] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            files.append((Path(current) / n).relative_to(root).as_posix())
            if len(files) >= MAX_INDEXED_FILES:
                break
        if len(files) >= MAX_INDEXED_FILES:
            break
    return sorted(files, key=lambda r: (r.count("/"), r))


class _RepoCtx:
    """Cheap file index + read helpers shared by the detectors."""

    def __init__(self, root: Path):
        self.root = root
        self.files = _index_repo(root)
        self.by_name: dict[str, list[str]] = {}
        for rel in self.files:
            self.by_name.setdefault(rel.rsplit("/", 1)[-1], []).append(rel)
        self.ext_counts = Counter(Path(r).suffix.lower() for r in self.files)
        self.dockerfiles = [
            r for r in self.files
            if (n := r.rsplit("/", 1)[-1].lower()) == "dockerfile"
            or n.startswith("dockerfile.") or n.endswith(".dockerfile")
        ]
        self.images = self._load_images()

    def all(self, *names: str) -> list[str]:
        out: list[str] = []
        for n in names:
            out.extend(self.by_name.get(n, []))
        return sorted(out, key=lambda r: (r.count("/"), r))

    def first(self, *names: str) -> str | None:
        found = self.all(*names)
        return found[0] if found else None

    def read(self, rel: str, limit: int = CONFIG_READ_LIMIT) -> str:
        return _read_config(self.root / rel, limit)

    def _load_images(self) -> list[dict]:
        images = []
        for rel in self.dockerfiles[:10]:
            for m in re.finditer(r"^FROM\s+(?:--\S+\s+)?(\S+)", self.read(rel), _RX_FLAGS):
                ref = m.group(1)
                if ref.lower() == "scratch" or "$" in ref:
                    continue
                name, _, tag = ref.rsplit("/", 1)[-1].partition(":")
                images.append({"ref": ref, "name": name.lower(), "tag": tag, "file": rel})
        return images

    def image(self, *names: str) -> dict | None:
        return next((i for i in self.images if i["name"] in names), None)


def _add(entries: list[dict], name: str, **fields) -> dict:
    """Append an entry (or fill in missing fields on an existing one). Falsy fields are dropped."""
    for e in entries:
        if e["name"] == name:
            for k, v in fields.items():
                if v and not e.get(k):
                    e[k] = v
            return e
    entry = {"name": name, **{k: v for k, v in fields.items() if v}}
    entries.append(entry)
    return entry


def _clean_ver(raw: str | None) -> str | None:
    if not raw:
        return None
    return re.sub(r"^[\^~>=<v\s]+", "", str(raw).strip()) or None


def _tag_ver(tag: str | None) -> str | None:
    """'1.67.0-alpine3.17' -> '1.67.0'; 'lts-slim' -> None."""
    m = re.match(r"v?(\d[\d.]*)", tag or "")
    return m.group(1).rstrip(".") if m else None


def _java_major(raw: str | None) -> str | None:
    """'1.8' / '1_8' / '8u262' -> '8'; '17.0.2' -> '17'."""
    if not raw:
        return None
    m = re.match(r"(?:1[._])?(\d+)", raw.replace("_", "."))
    return m.group(1) if m else None


_JAVA_VERSION_RXS = [
    r"(?:sourceCompatibility|targetCompatibility)\s*=?\s*['\"]?(?:JavaVersion\.VERSION_)?([\d._]+)",
    r"JavaLanguageVersion\.of\(\s*(\d+)",
    r"jvmTarget\s*=\s*['\"]?(?:JavaVersion\.VERSION_)?([\d._]+)",
    r"jvmToolchain\(\s*(\d+)",
    r"<java\.version>\s*([\d.]+)\s*<",
    r"<maven\.compiler\.(?:release|source|target)>\s*([\d.]+)\s*<",
    r"<release>\s*(\d+)\s*<",
]

_JDK_IMAGES = {"openjdk", "adoptopenjdk", "eclipse-temurin", "amazoncorretto", "sapmachine", "ibm-semeru-runtimes"}

# (name, kind, [regexes]) — group(1) of a regex, when present, is the version.
# Versioned patterns come first; the first regex that matches wins.
_JVM_FRAMEWORKS = [
    ("Grails", "web framework", [r"grails-gradle-plugin:([^'\"\s)]+)", r"org\.grails:grails-(?:core|web-boot|plugin-rest)\b"]),
    ("Spring Boot", "framework", [
        r"org\.springframework\.boot['\"]\s*version\s*['\"]([^'\"]+)",
        r"spring-boot-gradle-plugin:([^'\"\s)]+)",
        r"spring-boot-starter-parent</artifactId>\s*<version>([^<]+)",
        r"<spring-boot\.version>([^<]+)<",
        r"org\.springframework\.boot:spring-boot",
        r"org\.springframework\.boot['\"]",
    ]),
    ("Spring Framework", "framework", [
        r"<spring\.version>([^<]+)<",
        r"org\.springframework:spring-(?:core|webmvc|context):([^'\"\s)]+)",
    ]),
    ("Ratpack", "web framework", [r"ratpack-gradle:([^'\"\s)]+)", r"io\.ratpack\.ratpack-groovy", r"ratpack\.dependency\(", r"ratpack-(?:core|groovy)"]),
    ("Micronaut", "framework", [r"io\.micronaut\.application['\"]\s*version\s*['\"]([^'\"]+)", r"io\.micronaut"]),
    ("Quarkus", "framework", [r"io\.quarkus['\"]\s*version\s*['\"]([^'\"]+)", r"io\.quarkus"]),
    ("Ktor", "web framework", [r"io\.ktor:ktor-server-core:([^'\"\s)]+)", r"io\.ktor"]),
    ("Dropwizard", "web framework", [r"io\.dropwizard:dropwizard-core:([^'\"\s)]+)", r"io\.dropwizard"]),
    ("Vert.x", "framework", [r"io\.vertx:vertx-core:([^'\"\s)]+)", r"io\.vertx"]),
    ("Spock", "test framework", [r"spock-core:([^'\"\s)]+)"]),
]


def _resolve_version(version: str | None, name: str, props: dict[str, str]) -> str | None:
    """Resolve '$grailsVersion' style references and fall back to '<name>Version' in gradle.properties."""
    if version:
        version = version.strip()
        m = re.fullmatch(r"\$\{?(\w+)\}?", version)
        if m:
            version = props.get(m.group(1).lower())
    return version or props.get(name.lower().replace(" ", "") + "version")


def _detect_jvm(ctx: _RepoCtx, stack: dict) -> None:
    gradle_files = ctx.all("build.gradle", "build.gradle.kts")
    pom_files = ctx.all("pom.xml")
    if not (gradle_files or pom_files):
        return

    props: dict[str, str] = {}
    for rel in ctx.all("gradle.properties"):
        for m in re.finditer(r"^\s*([\w.]+)\s*=\s*(.+?)\s*$", ctx.read(rel), re.MULTILINE):
            props.setdefault(m.group(1).lower(), m.group(2))

    texts = [(rel, ctx.read(rel)) for rel in gradle_files[:5] + pom_files[:5]]
    build_file = (gradle_files or pom_files)[0]

    # Java version: build file -> .java-version -> base image
    java_version = java_source = None
    for rel, text in texts:
        for rx in _JAVA_VERSION_RXS:
            m = re.search(rx, text)
            if m and _java_major(m.group(1)):
                java_version, java_source = _java_major(m.group(1)), rel
                break
        if java_version:
            break
    if not java_version:
        jv = ctx.first(".java-version")
        if jv and _java_major(ctx.read(jv).strip()):
            java_version, java_source = _java_major(ctx.read(jv).strip()), jv
    if not java_version:
        for im in ctx.images:
            v = None
            if im["name"] in _JDK_IMAGES:
                v = _java_major(im["tag"]) or (re.search(r"(?:jdk|jre)-?(\d+)", im["tag"]) or [None, None])[1]
            elif im["name"] in {"gradle", "maven"}:
                v = (re.search(r"(?:jdk|jre)-?(\d+)", im["tag"]) or [None, None])[1]
            if v:
                java_version, java_source = v, f"{im['file']} ({im['ref']})"
                break

    all_text = "\n".join(t for _, t in texts)
    has_java_src = ctx.ext_counts[".java"] > 0
    _add(stack["languages"], "Java", version=java_version, source=java_source or build_file,
         kind=None if has_java_src else "JVM runtime (no .java sources)")
    if ctx.ext_counts[".groovy"] or re.search(r"apply plugin:\s*['\"]groovy|ratpack-groovy|org\.grails", all_text):
        m = re.search(r"groovy(?:-all)?:(\d[\w.\-]*)", all_text)
        _add(stack["languages"], "Groovy", version=m.group(1) if m else None, source=build_file)
    if ctx.ext_counts[".kt"] or "org.jetbrains.kotlin" in all_text:
        m = re.search(r"kotlin['\"]?\)?\s*version\s*['\"]([\d.]+)|kotlin-gradle-plugin:([\d.]+)", all_text)
        _add(stack["languages"], "Kotlin", version=(m.group(1) or m.group(2)) if m else None, source=build_file)

    # Frameworks
    for rel, text in texts:
        for name, kind, rxs in _JVM_FRAMEWORKS:
            found, version = False, None
            for rx in rxs:
                m = re.search(rx, text)
                if m:
                    found = True
                    if m.groups() and m.group(1):
                        version = m.group(1)
                    break
            if found:
                _add(stack["frameworks"], name, version=_resolve_version(version, name, props), kind=kind, source=rel)

    # Build tools
    if gradle_files:
        wrapper = ctx.first("gradle-wrapper.properties")
        m = re.search(r"gradle-(\d[\d.]*)", ctx.read(wrapper)) if wrapper else None
        _add(stack["build_tools"], "Gradle", version=m.group(1) if m else None,
             source=wrapper if m else gradle_files[0])
    if pom_files:
        wrapper = ctx.first("maven-wrapper.properties")
        m = re.search(r"apache-maven-(\d[\d.]*)", ctx.read(wrapper)) if wrapper else None
        _add(stack["build_tools"], "Maven", version=m.group(1) if m else None,
             source=wrapper if m else pom_files[0])


_RUST_CRATES = [
    ("axum", "web framework"), ("actix-web", "web framework"), ("rocket", "web framework"),
    ("warp", "web framework"), ("poem", "web framework"), ("hyper", "HTTP library"),
    ("tokio", "async runtime"), ("async-std", "async runtime"), ("serde", "serialization"),
    ("tower", "middleware"), ("tower-http", "middleware"),
]


def _cargo_dep(text: str, crate: str) -> tuple[bool, str | None]:
    esc = re.escape(crate)
    m = re.search(rf'^\s*{esc}\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if m:
        return True, m.group(1)
    m = re.search(rf'^\s*{esc}\s*=\s*\{{[^}}\n]*?version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if m:
        return True, m.group(1)
    m = re.search(rf'^\[(?:[\w-]+\.)?dependencies\.{esc}\]\s*\n(?:[^\[]*?)version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if m:
        return True, m.group(1)
    return bool(re.search(rf'^\s*{esc}\s*=\s*\{{|^\[(?:[\w-]+\.)?dependencies\.{esc}\]', text, re.MULTILINE)), None


def _detect_rust(ctx: _RepoCtx, stack: dict) -> None:
    manifests = ctx.all("Cargo.toml")
    if not manifests:
        return
    lock = ctx.first("Cargo.lock")
    lock_text = ctx.read(lock, LOCKFILE_READ_LIMIT) if lock else ""
    texts = [(rel, ctx.read(rel)) for rel in manifests[:5]]

    edition = rust_version = None
    for _, text in texts:
        edition = edition or (re.search(r'^edition\s*=\s*"(\d+)"', text, re.MULTILINE) or [None, None])[1]
        rust_version = rust_version or (re.search(r'^rust-version\s*=\s*"([^"]+)"', text, re.MULTILINE) or [None, None])[1]
    source = manifests[0]
    if not rust_version:
        tc = ctx.first("rust-toolchain.toml", "rust-toolchain")
        if tc:
            m = re.search(r'channel\s*=\s*"([^"]+)"', ctx.read(tc)) or re.match(r"\s*([\w.\-]+)\s*$", ctx.read(tc))
            if m:
                rust_version, source = m.group(1), tc
    if not rust_version:
        im = ctx.image("rust")
        if im and _tag_ver(im["tag"]):
            rust_version, source = _tag_ver(im["tag"]), f"{im['file']} ({im['ref']})"
    _add(stack["languages"], "Rust", version=rust_version, edition=edition, source=source)

    for crate, kind in _RUST_CRATES:
        for rel, text in texts:
            present, spec = _cargo_dep(text, crate)
            if not present:
                continue
            lm = re.search(rf'name = "{re.escape(crate)}"\s*\nversion = "([^"]+)"', lock_text)
            resolved = lm.group(1) if lm else None
            entry = _add(stack["frameworks"], crate, version=resolved or spec, kind=kind, source=rel)
            if resolved and spec and spec != resolved:
                entry.setdefault("constraint", spec)
            break
    _add(stack["build_tools"], "Cargo", source=manifests[0])


_NODE_FRAMEWORKS = [
    ("react", "React", "UI library"), ("next", "Next.js", "web framework"), ("vue", "Vue", "UI framework"),
    ("nuxt", "Nuxt", "web framework"), ("@angular/core", "Angular", "UI framework"),
    ("svelte", "Svelte", "UI framework"), ("express", "Express", "web framework"),
    ("fastify", "Fastify", "web framework"), ("koa", "Koa", "web framework"),
    ("@nestjs/core", "NestJS", "web framework"), ("hono", "Hono", "web framework"),
]


def _detect_node(ctx: _RepoCtx, stack: dict) -> None:
    manifests = ctx.all("package.json")
    if not manifests:
        return
    rel = manifests[0]
    try:
        pkg = json.loads(ctx.read(rel, 50_000))
    except ValueError:
        pkg = {}
    if not isinstance(pkg, dict):
        pkg = {}
    deps: dict = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        if isinstance(pkg.get(key), dict):
            deps.update(pkg[key])

    node_version = source = None
    for nvm in ctx.all(".nvmrc", ".node-version"):
        v = _clean_ver(ctx.read(nvm).strip())
        if v:
            node_version, source = v, nvm
            break
    engines = pkg.get("engines")
    if not node_version and isinstance(engines, dict) and engines.get("node"):
        node_version, source = _clean_ver(engines["node"]), f"{rel} (engines.node)"
    if not node_version:
        im = ctx.image("node")
        if im and _tag_ver(im["tag"]):
            node_version, source = _tag_ver(im["tag"]), f"{im['file']} ({im['ref']})"
    _add(stack["languages"], "Node.js", version=node_version, source=source or rel, kind="runtime")

    if "typescript" in deps or ctx.ext_counts[".ts"] or ctx.ext_counts[".tsx"]:
        _add(stack["languages"], "TypeScript", version=_clean_ver(deps.get("typescript")), source=rel)
    else:
        _add(stack["languages"], "JavaScript", source=rel)

    for pkg_name, display, kind in _NODE_FRAMEWORKS:
        if pkg_name in deps:
            _add(stack["frameworks"], display, version=_clean_ver(deps[pkg_name]), kind=kind, source=rel)

    pm = str(pkg.get("packageManager", ""))
    if ctx.first("pnpm-lock.yaml") or pm.startswith("pnpm"):
        manager = "pnpm"
    elif ctx.first("yarn.lock") or pm.startswith("yarn"):
        manager = "Yarn"
    else:
        manager = "npm"
    _add(stack["build_tools"], manager, version=_clean_ver(pm.split("@", 1)[1]) if "@" in pm else None, source=rel)
    for tool in ("vite", "webpack", "esbuild"):
        if tool in deps:
            _add(stack["build_tools"], tool.capitalize(), version=_clean_ver(deps[tool]), source=rel)


def _detect_python_go_dotnet(ctx: _RepoCtx, stack: dict) -> None:
    py_markers = ctx.all("pyproject.toml", "setup.py", "requirements.txt", "Pipfile", "setup.cfg")
    if py_markers or ctx.ext_counts[".py"]:
        version = source = None
        texts = [(rel, ctx.read(rel)) for rel in py_markers[:5]]
        for rel, text in texts:
            m = re.search(r"requires-python\s*=\s*['\"]([^'\"]+)|python_requires\s*=\s*['\"]([^'\"]+)"
                          r"|^python\s*=\s*['\"]([^'\"]+)|python_version\s*=\s*['\"]([^'\"]+)", text, re.MULTILINE)
            if m:
                version, source = _clean_ver(next(g for g in m.groups() if g)), rel
                break
        if not version and (im := ctx.image("python")) and _tag_ver(im["tag"]):
            version, source = _tag_ver(im["tag"]), f"{im['file']} ({im['ref']})"
        _add(stack["languages"], "Python", version=version, source=source or (py_markers[0] if py_markers else None))
        for pkg, display in (("django", "Django"), ("flask", "Flask"), ("fastapi", "FastAPI")):
            for rel, text in texts:
                m = re.search(rf"^\s*['\"]?{pkg}(?![\w\-.])['\"]?\s*(?:(?:===?|>=|~=|<=|=)\s*['\"]?[\^~]?(\d[\w.]*))?", text, _RX_FLAGS)
                if m:
                    _add(stack["frameworks"], display, version=m.group(1), kind="web framework", source=rel)
                    break
        if any("[tool.poetry]" in t for _, t in texts):
            _add(stack["build_tools"], "Poetry", source=next(r for r, t in texts if "[tool.poetry]" in t))
        elif ctx.first("Pipfile"):
            _add(stack["build_tools"], "Pipenv", source=ctx.first("Pipfile"))
        elif py_markers:
            _add(stack["build_tools"], "pip", source=py_markers[0])

    go_mod = ctx.first("go.mod")
    if go_mod or ctx.ext_counts[".go"]:
        text = ctx.read(go_mod) if go_mod else ""
        m = re.search(r"^go\s+(\d[\d.]*)", text, re.MULTILINE)
        _add(stack["languages"], "Go", version=m.group(1) if m else None, source=go_mod)
        for path, display in (("github.com/gin-gonic/gin", "Gin"), ("github.com/labstack/echo", "Echo"),
                              ("github.com/gofiber/fiber", "Fiber"), ("github.com/go-chi/chi", "chi")):
            m = re.search(rf"{re.escape(path)}\S*\s+v(\d[\w.\-]*)", text)
            if m:
                _add(stack["frameworks"], display, version=m.group(1), kind="web framework", source=go_mod)
        if go_mod:
            _add(stack["build_tools"], "Go modules", source=go_mod)

    csprojs = [r for r in ctx.files if r.endswith(".csproj")]
    if csprojs or ctx.ext_counts[".cs"]:
        text = ctx.read(csprojs[0]) if csprojs else ""
        m = re.search(r"<TargetFrameworks?>\s*(net[\w.\-;]+)\s*<", text)
        _add(stack["languages"], "C#", source=csprojs[0] if csprojs else None)
        _add(stack["frameworks"], ".NET", version=m.group(1) if m else None, kind="runtime/framework",
             source=csprojs[0] if csprojs else None)
        if 'Sdk="Microsoft.NET.Sdk.Web"' in text:
            _add(stack["frameworks"], "ASP.NET Core", kind="web framework", source=csprojs[0])
        _add(stack["build_tools"], "dotnet/MSBuild", source=csprojs[0] if csprojs else None)


# (name, regex, extras). extras: kind, ver (regexes with group(1) = version).
# A match of either the main regex or a ver regex marks the technology as present.
_SIGNATURES: dict[str, list[tuple[str, str, dict]]] = {
    "databases": [
        ("PostgreSQL", r"jdbc:postgresql|org\.postgresql|postgres(?:ql)?://|tokio-postgres|psycopg|asyncpg|^kind:\s*Postgres\b"
                       r"|image:\s*['\"]?postgres[:'\"\s]|PostgreSQLDialect|^\s*['\"]pg['\"]\s*:|npgsql|lib/pq|jackc/pgx",
         {"ver": [r"^kind:\s*Postgres\b[\s\S]{0,600}?^\s*version:\s*['\"]?([\d.]+)", r"image:\s*['\"]?postgres:(\d[\w.\-]*)"]}),
        ("MySQL", r"jdbc:mysql|mysql-connector|mysql://|mysql2|^\s*['\"]mysql['\"]\s*:|image:\s*['\"]?mysql[:'\"\s]", {}),
        ("MariaDB", r"jdbc:mariadb|mariadb-java-client|mariadb://|image:\s*['\"]?mariadb", {}),
        ("H2", r"jdbc:h2|com\.h2database|org\.h2\.Driver", {"kind": "embedded"}),
        ("SQLite", r"jdbc:sqlite|rusqlite|sqlite3", {"kind": "embedded"}),
        ("Oracle", r"jdbc:oracle|ojdbc|oracle\.jdbc", {}),
        ("SQL Server", r"jdbc:sqlserver|mssql-jdbc|Microsoft\.Data\.SqlClient|System\.Data\.SqlClient|^tiberius\s*=", {}),
        ("MongoDB", r"mongodb(?:\+srv)?://|mongo-java-driver|mongodb-driver|mongoose|^\s*['\"]mongodb['\"]\s*:|^mongodb\s*=", {}),
        ("Redis", r"redis://|jedis|lettuce|spring-data-redis|^\s*['\"]i?redis['\"]\s*:|^redis\s*=|image:\s*['\"]?redis", {}),
        ("Cassandra", r"cassandra", {}),
        ("DynamoDB", r"dynamodb", {}),
        ("Elasticsearch/OpenSearch", r"elasticsearch|opensearch", {}),
        ("Tantivy", r"^tantivy\s*=", {"kind": "embedded search index"}),
        ("Hibernate", r"org\.hibernate|hibernate5|hibernate-core", {"kind": "ORM", "ver": [r"hibernate-core:([^'\"\s)]+)"]}),
        ("JPA", r"javax\.persistence|jakarta\.persistence|spring-data-jpa|^\s*@Entity\b", {"kind": "ORM"}),
        ("GORM", r"grails-datastore-gorm|org\.grails\.plugins:hibernate5|grails\.gorm",
         {"kind": "ORM", "ver": [r"grails-datastore-gorm-hibernate5:([^'\"\s)]+)", r"org\.grails\.plugins:hibernate5:([^'\"\s)]+)"]}),
        ("SQLx", r"^sqlx\s*=", {"kind": "ORM"}),
        ("Diesel", r"^diesel\s*=", {"kind": "ORM"}),
        ("Prisma", r"^\s*['\"]@?prisma(?:/client)?['\"]\s*:", {"kind": "ORM"}),
        ("TypeORM", r"^\s*['\"]typeorm['\"]\s*:", {"kind": "ORM"}),
        ("Sequelize", r"^\s*['\"]sequelize['\"]\s*:", {"kind": "ORM"}),
        ("SQLAlchemy", r"sqlalchemy", {"kind": "ORM"}),
        ("Entity Framework", r"Microsoft\.EntityFrameworkCore|EntityFramework", {"kind": "ORM"}),
        ("HikariCP", r"hikari", {"kind": "connection pool"}),
        ("Flyway", r"flyway", {"kind": "migration tool"}),
        ("Liquibase", r"liquibase", {"kind": "migration tool"}),
    ],
    "messaging": [
        ("Kafka", r"\bkafka|rdkafka", {}),
        ("RabbitMQ", r"rabbitmq|spring-rabbit|\bamqp\b|\blapin\b|amqplib", {}),
        ("AWS SQS", r"\bsqs\b|awssdk\.services\.sqs|amazonaws\.services\.sqs|aws-sdk-sqs|client-sqs", {}),
        ("AWS SNS", r"awssdk\.services\.sns|amazonaws\.services\.sns|aws-sdk-sns|client-sns|sns\.amazonaws", {}),
        ("ActiveMQ", r"activemq", {}),
        ("JMS", r"javax\.jms|jakarta\.jms|spring-jms", {}),
        ("NATS", r"\bnats\b|async-nats", {}),
        ("Google Pub/Sub", r"pubsub", {}),
        ("Azure Service Bus", r"servicebus|azure-messaging", {}),
        ("MQTT", r"\bmqtt\b", {}),
    ],
    "cloud": [
        ("AWS", r"com\.amazonaws|software\.amazon\.awssdk|aws-sdk|aws-config|rusoto|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY"
                r"|boto3|\.amazonaws\.com|\bs3://", {}),
        ("GCP", r"com\.google\.cloud|google-cloud|@google-cloud|\bgcloud\b|googleapis\.com|\bgcr\.io", {}),
        ("Azure", r"com\.azure|com\.microsoft\.azure|azure-(?:storage|identity|sdk|core)|@azure/|\.azurecr\.io|\.blob\.core\.windows\.net", {}),
    ],
    "infrastructure": [
        ("KubeDB", r"^apiVersion:\s*kubedb\.com", {"kind": "database operator"}),
        ("Istio", r"^apiVersion:\s*\S*istio\.io", {}),
        ("Argo CD", r"^apiVersion:\s*argoproj\.io", {}),
        ("Terraform", r"^terraform\s*\{|^provider\s+\"", {}),
    ],
}

_SECONDARY_DB_KINDS = {"ORM", "connection pool", "migration tool"}
_YAML_EXTS = {".yml", ".yaml", ".tpl", ".jinfrost"}
_CONFIG_SCAN_EXTS = _YAML_EXTS | {".properties", ".toml", ".gradle", ".kts", ".xml", ".tf", ".csproj", ".env"}
_SOURCE_SCAN_EXTS = {".java", ".groovy", ".kt", ".rs", ".py", ".go", ".ts", ".tsx", ".js", ".jsx", ".cs", ".scala"}
_SKIP_SCAN_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "cargo.lock", "poetry.lock", "go.sum", "npm-shrinkwrap.json"}
_K8S_KIND_RX = re.compile(r"^kind:\s*(\w+)", re.MULTILINE)


def _scan_tier(rel: str) -> int | None:
    """0 = config/manifest, 1 = source, None = don't scan."""
    low = rel.lower()
    name = low.rsplit("/", 1)[-1]
    if name in _SKIP_SCAN_NAMES:
        return None
    ext = Path(name).suffix
    if (name == "package.json" or name.startswith("requirements") or name.startswith("dockerfile")
            or ext in _CONFIG_SCAN_EXTS):
        return 0
    if ext in _SOURCE_SCAN_EXTS and not re.search(r"(^|/)(test|tests|__tests__)(/|$)", low):
        return 1
    return None


def _detect_signatures_and_infra(ctx: _RepoCtx, stack: dict) -> None:
    candidates = [(t, rel) for rel in ctx.files if (t := _scan_tier(rel)) is not None]
    candidates.sort(key=lambda c: (c[0], c[1].count("/"), c[1]))

    k8s_kinds: set[str] = set()
    k8s_source: str | None = None
    for _, rel in candidates[:MAX_SCANNED_FILES]:
        text = ctx.read(rel)
        if not text:
            continue
        if Path(rel).suffix.lower() in _YAML_EXTS and re.search(r"^apiVersion:", text, re.MULTILINE):
            kinds = _K8S_KIND_RX.findall(text)
            if kinds:
                k8s_kinds.update(kinds)
                k8s_source = k8s_source or rel

        for group, sigs in _SIGNATURES.items():
            src_key = "inferred_from" if group == "databases" else "source"
            entries = stack[group]
            for name, pattern, extra in sigs:
                existing = next((e for e in entries if e["name"] == name), None)
                version = None
                for vrx in extra.get("ver", ()):
                    m = re.search(vrx, text, _RX_FLAGS)
                    if m:
                        version = m.group(1)
                        break
                if existing is None:
                    if version is None and not re.search(pattern, text, _RX_FLAGS):
                        continue
                    existing = {"name": name}
                    if extra.get("kind"):
                        existing["kind"] = extra["kind"]
                    existing[src_key] = rel
                    entries.append(existing)
                if version and not existing.get("version"):
                    existing["version"] = version

    stack["databases"].sort(key=lambda e: e.get("kind") in _SECONDARY_DB_KINDS)

    # Helm / Kubernetes
    charts = ctx.all("Chart.yaml")
    if charts:
        text = ctx.read(charts[0])
        name = (re.search(r"^name:\s*(\S+)", text, re.MULTILINE) or [None, None])[1]
        ver = (re.search(r"^version:\s*['\"]?([^'\"\s]+)", text, re.MULTILINE) or [None, None])[1]
        detail = " ".join(p for p in (f"chart {name}" if name else None, ver) if p)
        if len(charts) > 1:
            detail += f" (+{len(charts) - 1} more)"
        _add(stack["infrastructure"], "Helm", source=charts[0], detail=detail or None)
    k8s_path = next((r for r in ctx.files if re.search(r"(^|/)(k8s|kube|kubernetes)/|\.k8s\.", r.lower())), None)
    if k8s_source or k8s_path or charts:
        src = k8s_source or k8s_path or charts[0]
        if k8s_source and "/" in k8s_source:
            src = k8s_source.rsplit("/", 1)[0] + "/"
        _add(stack["infrastructure"], "Kubernetes", source=src,
             detail=", ".join(sorted(k8s_kinds)[:8]) or None)

    # Docker
    if ctx.dockerfiles:
        refs = list(dict.fromkeys(i["ref"] for i in ctx.images))[:4]
        _add(stack["infrastructure"], "Docker", source=ctx.dockerfiles[0],
             detail=("base images: " + ", ".join(refs)) if refs else None)
    compose = ctx.first("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
    if compose:
        _add(stack["infrastructure"], "Docker Compose", source=compose)
    if ctx.ext_counts[".tf"]:
        _add(stack["infrastructure"], "Terraform", source=next(r for r in ctx.files if r.endswith(".tf")))
    skaffold = ctx.first("skaffold.yaml")
    if skaffold:
        _add(stack["infrastructure"], "Skaffold", source=skaffold)


def _detect_ci(ctx: _RepoCtx, stack: dict) -> None:
    workflows = [r for r in ctx.files if r.lower().startswith(".github/workflows/") and r.lower().endswith((".yml", ".yaml"))]
    if workflows:
        _add(stack["ci_cd"], "GitHub Actions", source=".github/workflows/", detail=f"{len(workflows)} workflow(s)")

    for rel in ctx.files:
        name = rel.rsplit("/", 1)[-1].lower()
        low = rel.lower()
        if name.startswith("jenkinsfile"):
            text = ctx.read(rel)
            style = "declarative" if re.search(r"^\s*pipeline\s*\{", text, re.MULTILINE) else "scripted"
            stages = list(dict.fromkeys(re.findall(r"\bstage\s*\(?\s*['\"]([^'\"]+)['\"]", text)))[:6]
            detail = style + (f"; stages: {', '.join(stages)}" if stages else "")
            _add(stack["ci_cd"], "Jenkins", source=rel, detail=detail)
        elif name == ".gitlab-ci.yml":
            m = re.search(r"^stages:\s*\n((?:[ \t]*-[ \t]*\S+[ \t]*\n?)+)", ctx.read(rel), re.MULTILINE)
            stages = re.findall(r"-\s*(\S+)", m.group(1)) if m else []
            _add(stack["ci_cd"], "GitLab CI", source=rel, detail=f"stages: {', '.join(stages[:6])}" if stages else None)
        elif low == ".circleci/config.yml":
            _add(stack["ci_cd"], "CircleCI", source=rel)
        elif name == "azure-pipelines.yml":
            _add(stack["ci_cd"], "Azure Pipelines", source=rel)
        elif name == ".travis.yml":
            _add(stack["ci_cd"], "Travis CI", source=rel)
        elif name == "bitbucket-pipelines.yml":
            _add(stack["ci_cd"], "Bitbucket Pipelines", source=rel)
        elif name in {"cloudbuild.yaml", "cloudbuild.yml"}:
            _add(stack["ci_cd"], "Google Cloud Build", source=rel)
        elif name == ".drone.yml":
            _add(stack["ci_cd"], "Drone CI", source=rel)


def detect_tech_stack(repo_path: Path) -> dict:
    """Detect languages, frameworks (+versions), data stores, messaging, cloud, CI/CD and build tools.

    Returns lists of dicts; every entry has "name" and, where known, "version", "kind",
    "detail" and "source" (or "inferred_from" for databases).
    """
    stack: dict[str, list[dict]] = {
        "languages": [], "frameworks": [], "databases": [], "messaging": [],
        "cloud": [], "infrastructure": [], "ci_cd": [], "build_tools": [],
    }
    ctx = _RepoCtx(repo_path)
    for detector in (_detect_jvm, _detect_rust, _detect_node, _detect_python_go_dotnet,
                     _detect_signatures_and_infra, _detect_ci):
        try:
            detector(ctx, stack)
        except Exception as exc:  # detection is best-effort; never fail the scan
            print(f"warning: {detector.__name__} failed for {repo_path.name}: {exc}", file=sys.stderr)
    # Plain Makefile is a useful hint for legacy repos
    makefile = ctx.first("Makefile")
    if makefile:
        _add(stack["build_tools"], "Make", source=makefile)
    return stack


def scan_repo(repo_path: Path) -> dict:
    """Walk repository and extract all code intelligence."""
    routes: list[dict] = []
    models: list[dict] = []
    rules: list[dict] = []
    configs: list[dict] = []
    errors: list[dict] = []
    key_files: list[dict] = []

    tech_stack = detect_tech_stack(repo_path)

    # Scan source files
    extensions = {".java", ".groovy", ".cs", ".rs", ".py", ".go", ".kt",
                  ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml", ".json",
                  ".xml", ".toml", ".properties", ".gradle"}
    file_count = 0
    for fpath in repo_path.rglob("*"):
        if should_skip(fpath) or not fpath.is_file():
            continue
        if fpath.suffix not in extensions:
            continue
        file_count += 1
        rel = str(fpath.relative_to(repo_path))
        # Skip vendor/minified files — noisy false positives
        rel_lower = rel.lower()
        if any(p in rel_lower for p in SKIP_FILE_PATTERNS):
            continue
        content = safe_read(fpath)
        if not content:
            continue

        # Key files: controllers, services, handlers, domain
        is_key = any(k in rel.lower() for k in [
            "controller", "handler", "service", "domain", "model",
            "entity", "route", "api", "main", "app", "config",
            "application.yml", "application.yaml", "application.properties",
        ])
        if is_key:
            # Keep first 150 lines for LLM context
            lines = content.split("\n")[:150]
            key_files.append({"file": rel, "content": "\n".join(lines)})

        routes.extend(extract_routes(content, rel))
        models.extend(extract_domain_models(content, rel))
        rules.extend(extract_validation_rules(content, rel))
        configs.extend(extract_config(content, rel))
        errors.extend(extract_error_handling(content, rel))

    # Deduplicate rules by (file, rule text)
    seen_rules: set[tuple[str, str]] = set()
    unique_rules: list[dict] = []
    for r in rules:
        key = (r["file"], r["rule"])
        if key not in seen_rules:
            seen_rules.add(key)
            unique_rules.append(r)

    return {
        "repoName": repo_path.name,
        "fileCount": file_count,
        "techStack": tech_stack,
        "routes": routes[:50],
        "models": models[:30],
        "validationRules": unique_rules[:50],
        "configs": configs[:30],
        "errorMessages": errors[:30],
        "keyFiles": key_files[:15],  # Cap for LLM prompt size
    }


_STACK_SECTIONS = [
    ("languages", "Languages & Runtimes"),
    ("frameworks", "Frameworks & Libraries"),
    ("databases", "Databases & Data Access"),
    ("messaging", "Messaging / Queues"),
    ("cloud", "Cloud Providers"),
    ("infrastructure", "Infrastructure"),
    ("ci_cd", "CI/CD"),
    ("build_tools", "Build Tools"),
]


def _format_stack_entry(e: dict) -> str:
    text = f"**{e['name']}**"
    if e.get("version"):
        text += f" {e['version']}"
    if e.get("edition"):
        text += f" (edition {e['edition']})"
    if e.get("constraint"):
        text += f" (requires `{e['constraint']}`)"
    if e.get("kind"):
        text += f" _[{e['kind']}]_"
    if e.get("detail"):
        text += f" — {e['detail']}"
    src = e.get("source") or e.get("inferred_from")
    if src:
        text += f" — `{src}`"
    return text


def format_deterministic(scan: dict) -> str:
    """Format scan results as markdown."""
    lines = [f"# Repository Analysis: `{scan['repoName']}`\n"]
    lines.append(f"**Files scanned:** {scan['fileCount']}\n")

    stack = scan.get("techStack") or {}
    if any(stack.get(key) for key, _ in _STACK_SECTIONS):
        lines.append("## Tech Stack\n")
        for key, title in _STACK_SECTIONS:
            if not stack.get(key):
                continue
            lines.append(f"### {title}\n")
            lines.extend(f"- {_format_stack_entry(e)}" for e in stack[key])
            lines.append("")

    if scan["routes"]:
        lines.append("\n## Endpoints / Routes\n")
        seen = set()
        for r in scan["routes"]:
            key = r["route"]
            if key not in seen:
                seen.add(key)
                lines.append(f"- `{r['route']}` ({r['kind']}) — `{r['file']}`")

    if scan["models"]:
        lines.append("\n## Domain Models\n")
        for m in scan["models"]:
            fields_str = ", ".join(m["fields"][:10])
            lines.append(f"- **{m['name']}** (`{m['file']}`): {fields_str}")
            for c in m.get("constraints", []):
                lines.append(f"  - Constraints: `{c[:150]}`")

    if scan["validationRules"]:
        lines.append("\n## Validation Rules\n")
        kind_labels = {
            "grails_constraint": "Grails constraint",
            "dotnet_annotation": ".NET annotation",
            "java_validation": "Java/Bean validation",
            "guard_clause": "Guard clause",
        }
        # Group by file for cleaner output
        by_file: dict[str, list[dict]] = {}
        for r in scan["validationRules"][:30]:
            by_file.setdefault(r["file"], []).append(r)
        for filepath, file_rules in by_file.items():
            lines.append(f"### `{filepath}`\n")
            lines.append("| Rule | Type |")
            lines.append("|------|------|")
            for r in file_rules:
                rule_text = r["rule"].replace("|", "\\|")
                kind = kind_labels.get(r["kind"], r["kind"])
                lines.append(f"| `{rule_text}` | {kind} |")
            lines.append("")

    if scan["errorMessages"]:
        lines.append("\n## Error Messages (reveal business rules)\n")
        for e in scan["errorMessages"][:15]:
            lines.append(f"- `{e['file']}`: _{e['message']}_")

    if scan["configs"]:
        lines.append("\n## Configuration\n")
        for c in scan["configs"][:15]:
            lines.append(f"- `{c['file']}`: {c['config']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Layer 2 — LLM analysis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a business analyst reverse-engineering a legacy/brownfield system.
Given the extracted code intelligence (routes, models, validation rules, config, and key source files),
produce a BUSINESS-FOCUSED analysis. Do NOT cover architecture, infrastructure, or deployment — \
a separate Architecture tool handles those.

Focus on what the system DOES, not how it's built.

## 1. System Purpose
One paragraph: what business problem does this system solve? Who uses it?

## 2. Business Rules (extracted from code)
List every concrete business rule found in the code. Each rule must reference the source file.
Format: "- **Rule:** [description] (source: `file.ext`)"
Group by domain area (e.g. "User Management", "Pricing", "Redirects").

## 3. Domain Model & Entities
Key entities, their relationships, and business constraints (not technical schema details).

## 4. Validation & Data Integrity Rules
What input is accepted/rejected? What constraints enforce data quality?

## 5. Implicit Requirements
Requirements implied but not documented:
- Performance expectations (timeouts, caching, batch sizes)
- Security rules (auth, roles, input sanitization)
- Data lifecycle (retention, cascading deletes, soft deletes)

## 6. Business Risk & Knowledge Gaps
- Hardcoded business values that should be configurable
- Undocumented decision logic (magic numbers, unexplained conditions)
- Missing validation that could lead to bad data

Be specific and reference actual code. Do not invent rules not supported by evidence."""


def run_llm_analysis(scan: dict, api_key: str, context: str = "", tone: str = "technical") -> str | None:
    """Send extracted intelligence to LLM for business analysis."""
    try:
        import anthropic
    except ImportError:
        return None

    # Build prompt from key files + deterministic findings
    parts = [format_deterministic(scan)]

    if scan["keyFiles"]:
        parts.append("\n\n---\n## Key Source Files\n")
        for kf in scan["keyFiles"]:
            parts.append(f"\n### `{kf['file']}`\n```\n{kf['content']}\n```")

    user_message = "\n".join(parts)

    # Cap prompt size
    if len(user_message) > 80_000:
        user_message = user_message[:80_000] + "\n\n> ⚠️ Prompt truncated to fit API limits."
    if context:
        user_message = f"## 🎯 Focus Area: {context}\nONLY include information relevant to this focus area. OMIT entire sections that have no relevant findings — do not show empty sections or unrelated information. If a section has a mix, include only the relevant items.\n\n" + user_message

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

def merge_scans(scans: list[dict]) -> dict:
    """Merge multiple repo scans into a single combined scan for LLM analysis."""
    merged: dict = {
        "repoName": " + ".join(s["repoName"] for s in scans),
        "fileCount": sum(s["fileCount"] for s in scans),
        "techStack": {},
        "routes": [],
        "models": [],
        "validationRules": [],
        "configs": [],
        "errorMessages": [],
        "keyFiles": [],
    }
    for scan in scans:
        # Prefix tech stack keys with repo name
        for category, items in scan.get("techStack", {}).items():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        item.setdefault("repo", scan["repoName"])
                merged.setdefault("techStack", {}).setdefault(category, []).extend(
                    items if isinstance(items, list) else [items]
                )
            else:
                merged["techStack"][category] = items

        for key in ["routes", "models", "validationRules", "configs", "errorMessages"]:
            for item in scan.get(key, []):
                # Prefix file paths with repo name for clarity
                if isinstance(item, dict) and "file" in item:
                    item["file"] = f"{scan['repoName']}/{item['file']}"
                merged[key].append(item)

        for kf in scan.get("keyFiles", []):
            kf["file"] = f"{scan['repoName']}/{kf['file']}"
            merged["keyFiles"].append(kf)

    # Cap merged lists
    merged["routes"] = merged["routes"][:80]
    merged["models"] = merged["models"][:50]
    merged["validationRules"] = merged["validationRules"][:80]
    merged["configs"] = merged["configs"][:50]
    merged["errorMessages"] = merged["errorMessages"][:50]
    merged["keyFiles"] = merged["keyFiles"][:20]

    return merged


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract functionality, business rules, and requirements from repositories."
    )
    parser.add_argument("repo_paths", nargs="+", help="Path(s) to repository root(s).")
    parser.add_argument("--api-key", default=None, help="Anthropic API key.")
    parser.add_argument("--json", action="store_true", help="Output raw JSON.")
    parser.add_argument("--context", default="", help="Focus area to sharpen analysis scope.")
    add_tone_arg(parser)
    args = parser.parse_args()

    repos = [Path(p) for p in args.repo_paths]
    for repo in repos:
        if not repo.is_dir():
            print(f"Error: {repo} is not a directory.", file=sys.stderr)
            return 1

    # Layer 1: deterministic extraction for each repo
    scans = [scan_repo(repo) for repo in repos]

    # Merge if multiple repos
    combined = scans[0] if len(scans) == 1 else merge_scans(scans)

    if args.json:
        scan_output = {k: v for k, v in combined.items() if k != "keyFiles"}
        print(json.dumps(scan_output, indent=2))
        return 0

    # Layer 2: LLM analysis
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")

    if len(scans) == 1:
        det_output = format_deterministic(combined)
    else:
        # Show per-repo deterministic output then merged summary
        parts = [format_deterministic(s) for s in scans]
        det_output = "\n\n---\n\n".join(parts)

    if api_key:
        llm_output = run_llm_analysis(combined, api_key, args.context, args.tone)
        if llm_output:
            print(f"# Business Intelligence: `{combined['repoName']}`\n")
            print(llm_output)
            print(f"\n---\n\n{det_output}")
        else:
            print(det_output)
            print("\n> ℹ️ LLM analysis skipped (error).")
    else:
        print(det_output)
        print("\n> ℹ️ LLM analysis skipped (no API key or error).")

    has_findings = bool(combined["routes"] or combined["models"] or combined["validationRules"])
    return 0 if has_findings else 1


if __name__ == "__main__":
    sys.exit(main())
