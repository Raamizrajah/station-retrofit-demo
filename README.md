# 🏗️ Station Retrofit — AI for Brownfield Systems

> **LEGO Engineering Meetup 2026** — Mission: Space Station Retrofit
>
> Most teams operate existing systems rather than greenfield projects. This toolkit shows how AI can turn tribal knowledge — the migration rules, API contract conventions, and code review checklists that every developer must memorize — into automated guardrails that catch mistakes before they ship.

## What This Does

**8 AI-powered tools** covering 3 layers of brownfield system health:

### 📖 Understand Layer
| Tool | What it produces |
|---|---|
| **💡 Business Intelligence** | Business rules, domain models, validation logic, and implicit requirements extracted from code |
| **📝 Architecture Doc Generator** | System architecture docs — stacks, endpoints, data flow, Mermaid diagrams rendered as SVG |
| **🔮 Scenario Planner** | Impact analysis for proposed changes — what files, services, and contracts are affected |

### 🛡️ Secure Layer
| Tool | What it catches |
|---|---|
| **🔐 Secret Scanner** | Hardcoded AWS keys, API tokens, passwords in any repo (YAML, Groovy, Rust, etc.) |
| **📊 Dependency/Infra Auditor** | EOL versions, CVEs, deprecated K8s APIs, risky infrastructure patterns |
| **🗄️ Migration Reviewer** | Data loss, incomplete rollbacks, non-idempotent SQL in EF Core migrations |

### 👁️ Monitor Layer
| Tool | What it flags |
|---|---|
| **🔄 Domain Model Drift** | Constraint mismatches when the same entity exists in multiple repos |
| **📋 Contract Drift Detector** | Breaking enum removals, renamed properties, required field changes in OpenAPI |

All tools work in 3 layers:
1. **Deterministic checks** — fast, no LLM needed, catches structural issues
2. **LLM review** — Claude analyzes context for semantic issues and recommendations
3. **Formatted output** — markdown reports for CLI, UI, or CI comments

## Demo UI

A React + TypeScript web interface at `localhost:8080` with LEGO Connect design system components:

- **8 tabs** ordered by brownfield lifecycle (Understand → Secure → Monitor)
- **Filterable repo picker** — keyword filter with Enter-to-select-matches, Select all / Deselect all
- **Multi-repo support** — all panels use checkbox grids with all repos pre-selected by default
- **Focus area** — optional text field that restricts LLM output to only relevant information (irrelevant sections omitted entirely)
- **Output style** — switch between Technical, Business, and Kid-friendly tones
- **Mermaid diagrams** — architecture diagrams rendered as interactive SVGs
- **Auto-discovery** — sibling repos detected automatically by project markers

## Live Demo: ClutchPower Repos

The tools run against 4 real LEGO Education brownfield repositories:

| Repo | Stack | AI Findings |
|---|---|---|
| `domain-redirect-admin` | Grails 3.2 / Groovy | 🟡 Hibernate 5.1 EOL, Selenium 2.47, deprecated Gradle config |
| `domain-redirect-database` | KubeDB Helm | 🔴 **Real AWS keys in git**, Postgres 11.2 EOL, KubeDB v1alpha1 |
| `domain-redirect-lookup` | Ratpack 1.4.5 / Groovy | 🔴 Logback CVE, ancient JDBC driver, model drift vs admin |
| `school-search-rs` | Rust / Axum 0.4 | 🟡 axum 3 versions behind, Alpine EOL, Rust 1.67 outdated |

## Quick Start

### 1. Set up Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r tools/requirements.txt
```

### 2. Configure the LLM (optional — deterministic checks work without it)

```bash
cat > .env << 'EOF'
ANTHROPIC_API_KEY=your-key-here
ANTHROPIC_BASE_URL=https://your-llm-gateway.example.com/anthropic
ANTHROPIC_MODEL=eu.anthropic.claude-sonnet-4-6
EOF
```

### 3. Run tools from CLI

All tools support `--context "focus area"` to restrict output and `--tone technical|business|childlike` for output style.

```bash
export $(grep -v '^#' .env | xargs)

# 💡 Business Intelligence — extract business rules from code
python tools/extract_requirements.py /path/to/repo1 /path/to/repo2

# 📝 Architecture Doc — generates system map with Mermaid diagrams
python tools/generate_arch_doc.py /path/to/repo1 /path/to/repo2 /path/to/repo3

# 🔮 Scenario Planner — impact analysis for a proposed change
python tools/scenario_planner.py /path/to/repo1 /path/to/repo2 --scenario "Add Redis caching"

# 🔐 Secret Scanner — finds real AWS keys
python tools/scan_secrets.py /path/to/repo

# 📊 Dependency Audit — flags EOL versions and CVEs
python tools/audit_deps.py /path/to/repo

# 🗄️ Migration Review (demo scenarios)
python tools/review_migration.py scenarios/01-bad-migration-no-backfill/BadMigration.cs

# 🔄 Domain Model Drift — finds constraint mismatches across repos
python tools/check_model_drift.py /path/to/repo-a /path/to/repo-b DnsRedirect

# 📋 Contract Drift (demo scenarios)
python tools/check_contract_drift.py \
  --old-spec backend/Api/specs/api-spec.yaml \
  --spec scenarios/04-spec-removed-enum-value/modified-spec.yaml \
  --frontend frontend/src

# With focus area and tone
python tools/extract_requirements.py /path/to/repo --context "authentication" --tone business
```

### 4. Or use the demo UI

```bash
python -c "from ui.server import main; main()"
# Open http://localhost:8080
```

## Breaking Scenarios

Each scenario in `scenarios/` demonstrates a real-world mistake:

### Migration Scenarios

| # | Scenario | Severity | What's Wrong |
|---|---|---|---|
| 01 | No backfill | 🔴 Critical | Columns dropped before data migrated — permanent data loss |
| 02 | Incomplete Down() | 🔴 Critical | Down() doesn't reverse all of Up() — orphaned columns on rollback |
| 03 | Non-idempotent SQL | 🟡 Warning | INSERT without WHERE NOT EXISTS — duplicates on retry |

### Contract Drift Scenarios

| # | Scenario | Severity | What's Wrong |
|---|---|---|---|
| 04 | Removed enum value | 🔴 Breaking | `ProductStatus.Discontinued` removed — 3 frontend files break |
| 05 | Renamed property | 🔴 Breaking | `sku` → `skuCode` — 10 frontend file references break silently |
| 06 | Optional → required | 🟡 Warning | `validTo` now required — frontend form sends undefined, API returns 400 |

## Project Structure

```
station-retrofit-demo/
├── tools/                         AI review tools (Python)
│   ├── extract_requirements.py    💡 Business intelligence extractor
│   ├── generate_arch_doc.py       📝 Architecture doc generator
│   ├── scenario_planner.py        🔮 Scenario impact planner
│   ├── scan_secrets.py            🔐 Secret scanner
│   ├── audit_deps.py              📊 Dependency/infra auditor
│   ├── review_migration.py        🗄️ Migration reviewer
│   ├── check_model_drift.py       🔄 Domain model drift detector
│   ├── check_contract_drift.py    📋 Contract drift detector
│   ├── llm_utils.py               Shared LLM utilities (tone, context)
│
├── ui-app/                        React + TypeScript + Vite (source)
│   └── src/
│       ├── App.tsx                8 tool panels, repo picker, tone selector
│       ├── markdown.ts            Markdown-to-HTML with Mermaid rendering
│       └── index.css              Styles (LEGO Connect design tokens)
│
├── ui/                            Demo web interface
│   ├── dist/                      Built UI assets (served by server)
│   └── server.py                  Python HTTP server (ThreadedHTTPServer,
│                                  auto-discovery, 8 tool endpoints)
│
├── scenarios/                     6 pre-built breaking examples
│   ├── 01-bad-migration-no-backfill/
│   ├── 02-bad-migration-incomplete-down/
│   ├── 03-bad-migration-non-idempotent/
│   ├── 04-spec-removed-enum-value/
│   ├── 05-spec-renamed-property/
│   └── 06-spec-optional-to-required/
│
├── backend/                       .NET 8 API + EF Core + PostgreSQL
├── frontend/                      React + TypeScript
│
├── .github/workflows/             CI automation
│   ├── migration-review.yml       AI migration review on PR
│   ├── contract-drift.yml         AI contract drift check on PR
│   └── pr-check-migration-order.yml
│
└── .env                           API key + model config (not committed)
```

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │        AI Review Pipeline             │
                    │                                       │
 Any repo path ───► │  Layer 1: Deterministic checks        │
                    │  Layer 2: LLM review (Claude)         │
                    │  Layer 3: Formatted report             │
                    └──────────┬───────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
         CLI output      Demo UI          GitHub Actions
                      (localhost:8080)     (PR comments)
```

### UI Architecture

```
Browser ──► Python HTTP Server (ThreadedHTTPServer, port 8080)
               ├── GET  /api/discover     → auto-find sibling repos
               ├── POST /api/extract-requirements  → repoPaths[]
               ├── POST /api/generate-arch-doc     → repoPaths[]
               ├── POST /api/scenario-planner      → repoPaths[] + scenario
               ├── POST /api/scan-secrets          → repoPaths[]
               ├── POST /api/audit-deps            → repoPaths[]
               ├── POST /api/review-migration      → file
               ├── POST /api/check-model-drift     → repoA + repoB + entity
               ├── POST /api/check-contract-drift  → specs + frontend
               ├── POST /api/scan-entities         → repos[]
               └── GET  /*                         → SPA fallback (ui/dist/)
```

## The Story

> *"We took tribal knowledge — the migration rules in AGENTS.md, the implicit API contracts, the security checks no one runs, the dependency versions no one tracks — and turned them into AI guardrails that analyze every brownfield system automatically."*
>
> **Before:** Developer memorizes rules. Code review catches ~60%. Some slip to production. No one checks for secrets, model drift, or EOL versions.
>
> **After:** AI catches rule violations deterministically, analyzes semantic issues via LLM, and surfaces hidden risks across repos in seconds.

## Requirements

- Python 3.12+
- `ANTHROPIC_API_KEY` for LLM review (deterministic checks work without it)
- Node.js 20+ (for UI development only — pre-built UI included in `ui/dist/`)

> **Note:** The UI uses LEGO's private `@lego/connect-*` npm packages. External contributors can run the demo via the pre-built `ui/dist/` but cannot rebuild `ui-app/` without registry access. All 8 CLI tools work independently with no npm dependencies.

## Team

🚀 Mission Space Station Retrofit — LEGO Engineering Meetup 2026
