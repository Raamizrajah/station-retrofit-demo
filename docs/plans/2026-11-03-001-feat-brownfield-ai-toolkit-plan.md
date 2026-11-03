---
title: "feat: AI brownfield toolkit for ClutchPower repos"
type: feat
status: active
date: 2026-11-03
---

# AI Brownfield Toolkit for ClutchPower Repos

## Summary

Add 4 new AI-powered analysis tools to station-retrofit-demo that run against the 4 real ClutchPower repositories (admin, database, lookup, school-search) by path. Each tool follows the proven 3-layer architecture: deterministic checks → LLM review → formatted markdown output. All tools are callable via CLI and exposed through the existing demo UI. Combined with the 2 existing tools (migration reviewer + contract drift detector), this delivers a 6-tool brownfield AI suite covering prevention, understanding, and monitoring layers.

---

## Problem Frame

The ClutchPower domain-redirect system is a live brownfield system with 4 repos spanning Grails, Ratpack, Rust/Axum, and KubeDB Helm charts. It has hardcoded AWS credentials committed in git, domain model drift between repos, zero documentation, zero tests in the admin service, and EOL infrastructure (Postgres 11.2, KubeDB v1alpha1). No automated tooling catches any of these problems today.

---

## Requirements

- R1. Secret scanner detects hardcoded credentials in any file type (YAML, Groovy, Rust, TOML, Dockerfile)
- R2. Domain model drift detector compares the same entity across two repos and reports constraint mismatches
- R3. Architecture doc generator reads multiple repos and produces a system-level architecture document
- R4. Dependency/infra auditor flags EOL versions, deprecated APIs, and known-vulnerable dependencies
- R5. All tools follow the 3-layer pattern: deterministic checks → LLM analysis → markdown output
- R6. All tools callable via CLI (`python tools/<tool>.py <args>`)
- R7. All tools accessible through the demo UI at `localhost:8080`
- R8. Tools work against any local repo path (not hardcoded to ClutchPower)

---

## Scope Boundaries

- Tools live in `station-retrofit-demo` only — no changes to ClutchPower repos
- No GitLab CI pipeline integration (deferred post-meetup)
- No characterization test generator, runbook generator, health check analyzer, config drift detector, or log pattern analyzer (deferred)
- No GitHub Actions workflows for the new tools (demo is UI + CLI only)

### Deferred to Follow-Up Work

- GitLab CI integration for ClutchPower repos: post-meetup adoption
- Remaining 7 tools from the full 11-tool plan: future iterations

---

## Context & Research

### Relevant Code and Patterns

- `tools/review_migration.py` — reference architecture for all new tools (3-layer, Anthropic SDK, CLI + JSON output)
- `tools/check_contract_drift.py` — reference for multi-file analysis and diff-based detection
- `ui/server.py` — HTTP server pattern for tool API endpoints
- `ui/index.html` — demo UI with tool cards and markdown rendering

### Target Repositories

| Repo | Path | Stack | Key Files |
|------|------|-------|-----------|
| admin | `clutchpower-domain-redirect-admin-master` | Grails 3.2 / Groovy | `grails-app/domain/*/DnsRedirect.groovy`, `DnsDomain.groovy` |
| database | `clutchpower-domain-redirect-database-master` | KubeDB Helm | `chart/templates/database.yaml` |
| lookup | `clutchpower-domain-redirect-lookup-master` | Ratpack 1.4.5 / Groovy | `src/main/groovy/*/domain/DnsRedirect.groovy`, `DnsDomain.groovy` |
| school-search | `clutchpower-school-search-rs-master` | Rust / Axum 0.4 / Tantivy | `Cargo.toml`, `src/api.rs`, `Dockerfile` |

### Key Findings from Analysis

- **database.yaml** contains Base64-encoded `AWS_ACCESS_KEY_ID` (`AKIAWEUXX2N664JHS6NM`) and `AWS_SECRET_ACCESS_KEY`
- **DnsRedirect.path** constraint mismatch: admin has `blank: false, unique: ['domain']` + complex custom validator; lookup has `nullable: true`, no unique constraint, no validator
- **DnsDomain** is consistent across both repos (same constraints)
- **EOL versions**: Postgres 11.2 (EOL 2023-11), KubeDB `v1alpha1`, Ratpack 1.4.5, axum 0.4, Hibernate 5.1.16, Selenium 2.47.1, `extensions/v1beta1` K8s API

---

## Key Technical Decisions

- **3-layer architecture for all tools**: proven pattern from existing tools — deterministic checks catch obvious things fast (no LLM cost), LLM provides judgment, markdown output works everywhere
- **Path-based input**: tools accept repo paths as CLI args, making them portable beyond ClutchPower
- **Anthropic SDK via LEGO GenAI gateway**: same as existing tools (`ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL` env vars)
- **No new Python dependencies**: only `anthropic`, `pyyaml` (already in `requirements.txt`) plus `base64` and `re` from stdlib
- **Secret scanner uses entropy + pattern matching before LLM**: high-entropy Base64 strings + known key prefixes (`AKIA`, `sk-`, etc.) as deterministic layer

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

```
Each tool follows this pipeline:

  CLI args (repo path, options)
       │
       ▼
  ┌─ Layer 1: Deterministic ─┐
  │ Pattern matching           │
  │ File scanning              │
  │ Structural comparison      │  ← No LLM cost, fast
  │ Returns findings[]         │
  └────────────┬───────────────┘
               │
               ▼
  ┌─ Layer 2: LLM Review ─────┐
  │ Send findings + context    │
  │ to Claude via GenAI GW     │  ← Judgment, prioritization,
  │ Returns JSON assessment    │    actionable recommendations
  └────────────┬───────────────┘
               │
               ▼
  ┌─ Layer 3: Output ──────────┐
  │ Markdown report             │
  │ JSON (--json flag)          │  ← Consumed by UI + CI
  └─────────────────────────────┘
```

---

## Implementation Units

### U1. Secret Scanner (`tools/scan_secrets.py`)

**Goal:** Scan a repository for hardcoded secrets (API keys, passwords, tokens, AWS credentials) using entropy analysis + pattern matching + LLM verification.

**Requirements:** R1, R5, R6, R8

**Dependencies:** None

**Files:**
- Create: `tools/scan_secrets.py`

**Approach:**
- Layer 1 (deterministic):
  - Walk all files in repo (skip `.git/`, binary files, `node_modules/`, `target/`)
  - Pattern match: AWS key prefix `AKIA[A-Z0-9]{16}`, Base64 strings > 20 chars in YAML/config, common key patterns (`sk-`, `ghp_`, `xox[bpas]-`)
  - Shannon entropy check on candidate strings (threshold ~4.5 for hex, ~3.5 for Base64)
  - Decode Base64 values and check decoded content for key patterns
  - Return: list of `{file, line, pattern_type, value_preview, confidence}`
- Layer 2 (LLM): send findings with surrounding file context, ask Claude to classify each as `secret | likely_secret | false_positive` with remediation advice
- Layer 3: markdown report with severity icons, file:line references, remediation steps

**Patterns to follow:**
- `tools/review_migration.py` — CLI structure, Anthropic client setup, JSON/markdown dual output

**Test scenarios:**
- Happy path: scan `clutchpower-domain-redirect-database-master` → finds AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in `chart/templates/database.yaml`
- Happy path: decoded Base64 value `AKIAWEUXX2N664JHS6NM` matches AWS key pattern
- Edge case: scan repo with no secrets → clean report, exit code 0
- Edge case: `.env.example` with placeholder values (`YOUR_KEY_HERE`) → not flagged as secrets
- Error path: nonexistent repo path → clear error message, exit code 1
- Error path: no API key → deterministic-only results, LLM section skipped

**Verification:**
- Running against database repo produces a report identifying both AWS credentials with file:line references
- Exit code is 1 when secrets found, 0 when clean

---

### U2. Domain Model Drift Detector (`tools/check_model_drift.py`)

**Goal:** Compare the same domain entity (by class name) across two repositories and report constraint, field, and validation mismatches.

**Requirements:** R2, R5, R6, R8

**Dependencies:** None

**Files:**
- Create: `tools/check_model_drift.py`

**Approach:**
- Layer 1 (deterministic):
  - Accept two repo paths + entity name (e.g., `DnsRedirect`)
  - Find matching files by class name pattern across both repos (support Groovy `.groovy`, Java `.java`, Kotlin `.kt`, C# `.cs`)
  - Parse `static constraints` blocks (Groovy/GORM), extract field-level constraint maps
  - Diff constraints field-by-field: nullable, blank, unique, maxSize, validator presence
  - Also compare field declarations (type + name)
  - Return structured diff: `{field, constraint, repo_a_value, repo_b_value, severity}`
- Layer 2 (LLM): send both model source files + structured diff, ask Claude to assess behavioral impact (e.g., "admin rejects empty path but lookup accepts it — data written by admin is always valid for lookup, but data from other sources may break lookup assumptions")
- Layer 3: markdown report with side-by-side comparison table, severity, and recommendations

**Patterns to follow:**
- `tools/check_contract_drift.py` — multi-file comparison pattern, diff-based analysis

**Test scenarios:**
- Happy path: compare DnsRedirect across admin + lookup → reports `path` constraint mismatch (blank: false vs nullable: true, unique constraint missing in lookup, validator missing in lookup)
- Happy path: compare DnsDomain across admin + lookup → reports clean (identical constraints)
- Edge case: entity exists in only one repo → clear report saying "entity not found in repo B"
- Edge case: entity has fields in one repo but not the other → reports missing fields
- Error path: invalid repo paths → error message
- Error path: no matching entity files → "no files matching 'EntityName' found"

**Verification:**
- Running against admin + lookup with `DnsRedirect` produces a report showing the path constraint mismatch
- Running with `DnsDomain` produces a clean report

---

### U3. Architecture Doc Generator (`tools/generate_arch_doc.py`)

**Goal:** Read one or more repositories and generate a system architecture document covering services, data flow, APIs, domain models, and deployment topology.

**Requirements:** R3, R5, R6, R8

**Dependencies:** None

**Files:**
- Create: `tools/generate_arch_doc.py`

**Approach:**
- Layer 1 (deterministic):
  - For each repo path, detect stack (Grails, Ratpack, Rust/Cargo, Helm chart) from build files
  - Extract: entry points (controllers, handlers, main.rs), domain models, API endpoints (from controllers/routes/OpenAPI specs), dependencies (build.gradle, Cargo.toml), infrastructure (Dockerfile, Helm values, K8s templates)
  - Build a structural inventory: `{repo, stack, services[], models[], endpoints[], infra[]}`
  - Cross-reference: find shared model names across repos, shared DB references, service-to-service relationships
- Layer 2 (LLM): send structural inventory to Claude, ask it to generate:
  - System overview (what the system does, how services interact)
  - Architecture diagram description (Mermaid-compatible)
  - Per-service summary (role, stack, key endpoints, domain models)
  - Data flow description (how a request travels through the system)
  - Deployment topology (from Helm/Dockerfile analysis)
  - Key risks and recommendations
- Layer 3: full markdown architecture document with Mermaid diagrams

**Patterns to follow:**
- `tools/review_migration.py` — Anthropic client, structured LLM output parsing

**Test scenarios:**
- Happy path: pass all 4 ClutchPower repo paths → generates complete architecture doc with system overview, per-service sections, data flow, Mermaid diagram
- Happy path: single repo → generates focused single-service doc
- Edge case: repo with only Dockerfile + Helm chart (database repo) → describes infra role, not application logic
- Error path: one repo path invalid → skips it with warning, generates doc for remaining repos

**Verification:**
- Generated doc for all 4 repos includes: system overview, Mermaid architecture diagram, per-service breakdowns, data flow description
- Generated doc identifies the admin → database → lookup service chain correctly

---

### U4. Dependency/Infra Auditor (`tools/audit_deps.py`)

**Goal:** Scan a repository's dependency manifests, Dockerfiles, and infrastructure templates for EOL versions, deprecated APIs, and known-risky patterns.

**Requirements:** R4, R5, R6, R8

**Dependencies:** None

**Files:**
- Create: `tools/audit_deps.py`

**Approach:**
- Layer 1 (deterministic):
  - Parse dependency manifests: `build.gradle` (Groovy deps), `Cargo.toml` (Rust deps), `package.json` (Node), `requirements.txt` (Python)
  - Parse infra files: Dockerfile (`FROM` base images), Helm `Chart.yaml` (apiVersion), K8s templates (`apiVersion` fields)
  - Check against known-EOL database:
    - Postgres: 11.x EOL 2023-11, 12.x EOL 2024-11, 13.x EOL 2025-11
    - KubeDB: `v1alpha1` deprecated (current: `v1`)
    - K8s APIs: `extensions/v1beta1` removed in K8s 1.22 (June 2021)
    - Rust: flag axum < 0.6 (0.4 is 3 major versions behind)
    - Docker: flag Alpine < 3.18 (EOL)
  - Pattern match for risky configs: resource limits without requests, no health probes, `terminationPolicy: DoNotTerminate` without backup verification
  - Return: `{file, line, finding, severity, current_version, recommended_version}`
- Layer 2 (LLM): send findings + context, ask Claude to prioritize by risk and provide upgrade path recommendations specific to the stack
- Layer 3: markdown report with severity table, per-finding detail, upgrade recommendations

**Patterns to follow:**
- `tools/review_migration.py` — CLI, Anthropic client, output formatting

**Test scenarios:**
- Happy path: scan database repo → flags Postgres 11.2 EOL, KubeDB v1alpha1 deprecated
- Happy path: scan lookup repo → flags Ratpack 1.4.5 outdated, PostgreSQL JDBC 9.4 ancient, Logback 1.2.6 (CVE-2021-42550)
- Happy path: scan school-search repo → flags axum 0.4, Rust 1.67.0 in Dockerfile, Alpine 3.17 EOL
- Happy path: scan admin repo → flags Hibernate 5.1.16, Selenium 2.47.1, Grails 3.2 EOL
- Edge case: repo with all current versions → clean report
- Error path: unsupported manifest format → skips with warning

**Verification:**
- Running against all 4 repos produces findings for each
- Database repo report includes Postgres 11.2 and KubeDB v1alpha1 findings

---

### U5. Demo UI Integration

**Goal:** Add the 4 new tools to the demo UI with dedicated API endpoints and tool cards.

**Requirements:** R7

**Dependencies:** U1, U2, U3, U4

**Files:**
- Modify: `ui/server.py`
- Modify: `ui/index.html`

**Approach:**
- Add 4 new POST endpoints to `server.py`:
  - `/api/scan-secrets` — accepts `{repoPath: string}`
  - `/api/check-model-drift` — accepts `{repoA: string, repoB: string, entity: string}`
  - `/api/generate-arch-doc` — accepts `{repoPaths: string[]}`
  - `/api/audit-deps` — accepts `{repoPath: string}`
- Each endpoint follows the existing pattern: subprocess call to tool, capture stdout, return `{markdown, exit_code, duration}`
- Add 4 tool cards to `index.html` with input forms matching each tool's parameters
- Include pre-filled example paths pointing to ClutchPower repos for instant demo
- Organize UI into sections: "Existing Tools" (migration + contract) and "Brownfield Tools" (new 4)

**Patterns to follow:**
- `_handle_migration_review()` and `_handle_drift_check()` in `ui/server.py`
- Existing tool card HTML/CSS pattern in `ui/index.html`

**Test scenarios:**
- Happy path: click "Scan Secrets" with database repo path → shows markdown report with AWS key findings
- Happy path: click "Check Model Drift" with admin + lookup paths + "DnsRedirect" → shows constraint mismatch report
- Happy path: click "Generate Architecture Doc" with all 4 paths → shows full architecture document
- Happy path: click "Audit Dependencies" with any repo path → shows version findings
- Error path: empty repo path → shows user-friendly error
- Integration: all 4 new endpoints respond with `{markdown, exit_code, duration}` structure

**Verification:**
- All 6 tools visible and runnable from `localhost:8080`
- Each tool produces markdown output rendered correctly in the UI

---

### U6. README and Documentation Update

**Goal:** Update README.md to document the full 6-tool suite and ClutchPower demo setup.

**Requirements:** R5, R6, R7

**Dependencies:** U1, U2, U3, U4, U5

**Files:**
- Modify: `README.md`
- Modify: `tools/README.md`

**Approach:**
- Update main README with:
  - Updated tool list (6 tools, grouped by layer)
  - ClutchPower repos setup instructions (clone paths)
  - Quick-start commands for each new tool
  - Demo walkthrough for meetup
- Update tools README with per-tool usage docs

**Test expectation:** none — documentation only

**Verification:**
- README accurately describes all 6 tools with working CLI examples

---

## System-Wide Impact

- **UI server**: 4 new API endpoints added, same subprocess pattern
- **Dependencies**: no new pip packages required (yaml, base64, re are stdlib; anthropic already installed)
- **Environment**: same 3 env vars (`ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`)
- **File scanning**: tools walk local filesystem — must handle symlinks, binary files, and large repos gracefully

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| LLM response quality varies for architecture doc generation | Strong structured prompts + deterministic inventory as grounding |
| Groovy constraint parsing is fragile (regex-based) | Support the specific patterns found in ClutchPower; test against actual files |
| EOL version database goes stale | Embed known versions for demo; note this needs maintenance for production use |
| Large repos could timeout LLM calls | Set 120s timeout, truncate context if needed |

---

## Sources & References

- Existing tools: `tools/review_migration.py`, `tools/check_contract_drift.py`
- ClutchPower repos: local clones from `gitlab.legogroup.io/clutchpower/`
- LEGO GenAI gateway: `https://api.genai.thelegogroup.com/anthropic`
