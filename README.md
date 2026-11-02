# 🏗️ Station Retrofit — AI for Brownfield Systems

> **LEGO Engineering Meetup 2026** — Mission: Space Station Retrofit
>
> Most teams operate existing systems rather than greenfield projects. This demo shows how AI can turn tribal knowledge — the migration rules, API contract conventions, and code review checklists that every developer must memorize — into automated guardrails that catch mistakes before they ship.

Built from real patterns observed in the LEGO B2B pricing platform: EF Core migration pitfalls, OpenAPI contract drift between backend and frontend repos, and the gap between "rules written in AGENTS.md" and "rules enforced in CI".

## What This Does

Two AI-powered review tools that run on every pull request:

| Tool | Checks | Catches |
|---|---|---|
| **🗄️ Migration Reviewer** | EF Core migrations against 6 codified rules | Data loss, incomplete rollbacks, non-idempotent SQL |
| **📋 Contract Drift Detector** | OpenAPI spec changes against frontend usage | Breaking enum removals, renamed properties, required field changes |

Both tools work in 3 layers:
1. **Deterministic checks** — fast, no LLM needed, catches structural issues
2. **LLM review** — Claude analyzes the actual code/spec for semantic issues
3. **PR comment** — posts findings directly on the pull request

## Demo UI

A web interface for running scenarios interactively:

```bash
# Load env vars and start the UI server
export $(grep -v '^#' .env | xargs)
source .venv/bin/activate
python ui/server.py
```

Open **http://localhost:8080** — select a scenario, click "Run AI Review", see the results.

## Quick Start

### 1. Set up Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r tools/requirements.txt
```

### 2. Configure the LLM (optional — deterministic checks work without it)

```bash
# Create .env file (already gitignored)
cat > .env << 'EOF'
ANTHROPIC_API_KEY=your-key-here
ANTHROPIC_BASE_URL=https://api.genai.thelegogroup.com/anthropic
ANTHROPIC_MODEL=eu.anthropic.claude-sonnet-4-6
EOF
```

### 3. Run scenarios from CLI

```bash
export $(grep -v '^#' .env | xargs)

# Migration review
python tools/review_migration.py scenarios/01-bad-migration-no-backfill/BadMigration.cs
python tools/review_migration.py scenarios/02-bad-migration-incomplete-down/BadMigration.cs
python tools/review_migration.py scenarios/03-bad-migration-non-idempotent/BadMigration.cs

# Contract drift detection
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

## Breaking Scenarios

Each scenario in `scenarios/` demonstrates a real-world mistake based on patterns from the LEGO pricing platform:

### Migration Scenarios (based on real AGENTS.md rules)

| # | Scenario | Severity | What's Wrong |
|---|---|---|---|
| 01 | No backfill | 🔴 Critical | Columns dropped before data migrated — permanent data loss |
| 02 | Incomplete Down() | 🔴 Critical | Down() doesn't reverse all of Up() — orphaned columns on rollback |
| 03 | Non-idempotent SQL | 🟡 Warning | INSERT without WHERE NOT EXISTS — duplicates on retry |

### Contract Drift Scenarios (based on real cross-repo architecture)

| # | Scenario | Severity | What's Wrong |
|---|---|---|---|
| 04 | Removed enum value | 🔴 Breaking | `ProductStatus.Discontinued` removed — 3 frontend files break |
| 05 | Renamed property | 🔴 Breaking | `sku` → `skuCode` — 10 frontend file references break silently |
| 06 | Optional → required | 🟡 Warning | `validTo` now required — frontend form sends undefined, API returns 400 |

## Project Structure

```
station-retrofit-demo/
├── backend/                    .NET 8 API + EF Core + PostgreSQL
│   ├── Api/                    Controllers, Models, DTOs, Swagger
│   ├── Database/Migrations/    6 pre-seeded EF Core migrations
│   └── docker-compose.yml      PostgreSQL 16
│
├── frontend/                   React + TypeScript
│   ├── src/api/                Generated API client (typescript-fetch pattern)
│   ├── src/pages/              Components using enums as runtime values
│   └── generate-api-types.sh   OpenAPI Generator script
│
├── tools/                      AI review tools (Python)
│   ├── review_migration.py     Migration reviewer (deterministic + LLM)
│   ├── check_contract_drift.py Contract drift detector (diff + scan + LLM)
│   └── format_pr_comment.py    PR comment formatter
│
├── ui/                         Demo web interface
│   ├── index.html              Single-page app
│   └── server.py               Python HTTP server wrapping the tools
│
├── scenarios/                  6 pre-built breaking examples
│   ├── 01-bad-migration-no-backfill/
│   ├── 02-bad-migration-incomplete-down/
│   ├── 03-bad-migration-non-idempotent/
│   ├── 04-spec-removed-enum-value/
│   ├── 05-spec-renamed-property/
│   └── 06-spec-optional-to-required/
│
└── .github/workflows/          CI automation
    ├── migration-review.yml    AI migration review on PR
    ├── contract-drift.yml      AI contract drift check on PR
    └── pr-check-migration-order.yml  Deterministic timestamp check
```

## Architecture

```
┌─────────────────────┐         ┌─────────────────────┐
│   Backend (.NET 8)  │         │  Frontend (React/TS) │
│                     │         │                      │
│  EF Core Migrations │◄────────│  Generated API Client│
│  OpenAPI Spec       │  spec   │  Enum runtime values │
│  PostgreSQL 16      │         │                      │
└────────┬────────────┘         └──────────┬───────────┘
         │                                 │
         │    PR opened                    │
         ▼                                 ▼
┌─────────────────────────────────────────────────────┐
│              AI Review Pipeline                      │
│                                                      │
│  Layer 1: Deterministic     Layer 1: Spec diff       │
│  Layer 2: LLM rule review   Layer 2: Frontend scan   │
│  Layer 3: PR comment         Layer 3: LLM impact     │
│                              Layer 4: PR comment     │
└──────────────────────────────────────────────────────┘
```

## The Story

> *"We took tribal knowledge — the migration rules in AGENTS.md that every developer has to memorize, the implicit contract between backend specs and frontend generated clients — and turned them into AI guardrails that review every PR automatically."*
>
> **Before:** Developer memorizes 15+ rules. Code review catches ~60% of issues. Some slip through to production.
>
> **After:** AI catches 100% of rule violations deterministically, plus semantic issues via LLM. Every PR gets reviewed against the full ruleset in seconds.

## Tech Stack

| Layer | Technology | Version |
|---|---|---|
| Backend | .NET 8 Minimal API | 8.0 |
| ORM | EF Core + Npgsql | 8.0.11 |
| Database | PostgreSQL | 16 |
| Frontend | React + TypeScript + Vite | 18.3 / 5.6 / 6.0 |
| API Client | openapi-generator-cli | 7.11.0 |
| AI Tools | Python + Anthropic SDK | 3.12+ |
| CI | GitHub Actions | — |

## Requirements

- Python 3.12+
- `ANTHROPIC_API_KEY` for LLM review (deterministic checks work without it)
- .NET 8 SDK (only if running the backend API)
- Docker (only if running PostgreSQL)
- Node.js 20+ (only if running the frontend)

## Team

🚀 Mission Space Station Retrofit — LEGO Engineering Meetup 2026
