# 🏗️ Station Retrofit — AI for Brownfield Systems

> **LEGO Engineering Meetup 2026** — Mission: Space Station Retrofit
>
> Most teams operate existing systems rather than greenfield projects. This demo shows how AI can turn tribal knowledge — the migration rules, API contract conventions, and code review checklists that every developer must memorize — into automated guardrails that catch mistakes before they ship.

## What This Does

**6 AI-powered tools** covering 3 layers of brownfield system health:

### 🛡️ Prevention Layer
| Tool | What it catches |
|---|---|
| **🗄️ Migration Reviewer** | Data loss, incomplete rollbacks, non-idempotent SQL in EF Core migrations |
| **📋 Contract Drift Detector** | Breaking enum removals, renamed properties, required field changes in OpenAPI |
| **🔐 Secret Scanner** | Hardcoded AWS keys, API tokens, passwords in any repo (YAML, Groovy, Rust, etc.) |
| **🔄 Domain Model Drift** | Constraint mismatches when the same entity exists in multiple repos |

### 📖 Understanding Layer
| Tool | What it produces |
|---|---|
| **📝 Architecture Doc Generator** | System architecture docs from code — stacks, endpoints, data flow, Mermaid diagrams |

### 👁️ Monitoring Layer
| Tool | What it flags |
|---|---|
| **📊 Dependency/Infra Auditor** | EOL versions, CVEs, deprecated K8s APIs, risky infrastructure patterns |

All tools work in 3 layers:
1. **Deterministic checks** — fast, no LLM needed, catches structural issues
2. **LLM review** — Claude analyzes context for semantic issues and recommendations
3. **Formatted output** — markdown reports for CLI, UI, or CI comments

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
ANTHROPIC_BASE_URL=https://api.genai.thelegogroup.com/anthropic
ANTHROPIC_MODEL=eu.anthropic.claude-sonnet-4-6
EOF
```

### 3. Run tools from CLI

```bash
export $(grep -v '^#' .env | xargs)

# 🔐 Secret Scanner — finds real AWS keys
python tools/scan_secrets.py /path/to/clutchpower-domain-redirect-database-master

# 🔄 Domain Model Drift — finds DnsRedirect constraint mismatch
python tools/check_model_drift.py \
  /path/to/clutchpower-domain-redirect-admin-master \
  /path/to/clutchpower-domain-redirect-lookup-master \
  DnsRedirect

# 📝 Architecture Doc — generates system map from 4 repos
python tools/generate_arch_doc.py \
  /path/to/clutchpower-domain-redirect-admin-master \
  /path/to/clutchpower-domain-redirect-database-master \
  /path/to/clutchpower-domain-redirect-lookup-master \
  /path/to/clutchpower-school-search-rs-master

# 📊 Dependency Audit — flags EOL versions and CVEs
python tools/audit_deps.py /path/to/clutchpower-domain-redirect-lookup-master

# 🗄️ Migration Review (demo scenarios)
python tools/review_migration.py scenarios/01-bad-migration-no-backfill/BadMigration.cs

# 📋 Contract Drift (demo scenarios)
python tools/check_contract_drift.py \
  --old-spec backend/Api/specs/api-spec.yaml \
  --spec scenarios/04-spec-removed-enum-value/modified-spec.yaml \
  --frontend frontend/src
```

### 4. Or use the demo UI

```bash
python ui/server.py
# Open http://localhost:8080
```

The UI has 6 tabs — 2 for pre-built demo scenarios (migration + contract drift) and 4 for live brownfield analysis with repo path dropdowns.

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
│   ├── review_migration.py        🗄️ Migration reviewer
│   ├── check_contract_drift.py    📋 Contract drift detector
│   ├── scan_secrets.py            🔐 Secret scanner
│   ├── check_model_drift.py       🔄 Domain model drift detector
│   ├── generate_arch_doc.py       📝 Architecture doc generator
│   ├── audit_deps.py              📊 Dependency/infra auditor
│   └── format_pr_comment.py       PR comment formatter
│
├── ui/                            Demo web interface
│   ├── index.html                 Single-page app (6 tool tabs)
│   └── server.py                  Python HTTP server (10 API endpoints)
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
└── docs/plans/                    Planning docs
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

## The Story

> *"We took tribal knowledge — the migration rules in AGENTS.md, the implicit API contracts, the security checks no one runs, the dependency versions no one tracks — and turned them into AI guardrails that analyze every brownfield system automatically."*
>
> **Before:** Developer memorizes rules. Code review catches ~60%. Some slip to production. No one checks for secrets, model drift, or EOL versions.
>
> **After:** AI catches rule violations deterministically, analyzes semantic issues via LLM, and surfaces hidden risks across repos in seconds.

## Requirements

- Python 3.12+
- `ANTHROPIC_API_KEY` for LLM review (deterministic checks work without it)

## Team

🚀 Mission Space Station Retrofit — LEGO Engineering Meetup 2026
