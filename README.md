# 🏗️ Station Retrofit Demo — AI for Brownfield Systems

> Engineering Meetup Mission: Apply AI to improve maintenance, onboarding, debugging, monitoring, or support in an existing system.

This is a simplified pricing system that demonstrates two AI-powered review tools for brownfield .NET + React codebases:

1. **Migration Reviewer** — AI reviews EF Core migrations against codified rules
2. **Contract Drift Detector** — AI detects breaking OpenAPI spec changes and their frontend impact

## Architecture

```
┌─────────────────────┐         ┌─────────────────────┐
│   Backend (.NET 8)  │         │  Frontend (React/TS) │
│                     │         │                      │
│  EF Core Migrations │◄────────│  Generated API Client│
│  OpenAPI Spec       │  spec   │  (typescript-fetch)  │
│  PostgreSQL 16      │         │  Enum runtime values │
└────────┬────────────┘         └──────────┬───────────┘
         │                                 │
         │    PR opened                    │
         ▼                                 ▼
┌─────────────────────────────────────────────────────┐
│              GitHub Actions CI                       │
│                                                      │
│  🤖 Migration Reviewer    🤖 Contract Drift Detector │
│  ├─ Deterministic checks  ├─ YAML spec diff          │
│  ├─ LLM rule review       ├─ Frontend usage scan     │
│  └─ PR comment            ├─ LLM impact assessment   │
│                           └─ PR comment              │
└──────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Run the backend

```bash
cd backend
docker compose up -d          # Start PostgreSQL
dotnet run --project Api      # Start the API (http://localhost:5000)
```

### 2. Try the AI tools locally

```bash
# Install Python dependencies
pip install -r tools/requirements.txt

# Review a migration (deterministic checks only — no API key needed)
python tools/review_migration.py backend/Database/Migrations/20260615100000_SeparatePriceHistory.cs

# Review a migration with LLM (needs API key)
ANTHROPIC_API_KEY=sk-... python tools/review_migration.py backend/Database/Migrations/20260615100000_SeparatePriceHistory.cs

# Check contract drift
python tools/check_contract_drift.py \
  --spec backend/Api/specs/api-spec.yaml \
  --frontend frontend/src \
  --old-spec scenarios/04-spec-removed-enum-value/modified-spec.yaml
```

### 3. Try the breaking scenarios

Each scenario in `scenarios/` demonstrates a real-world mistake:

| # | Scenario | Type | What's Wrong |
|---|---|---|---|
| 01 | No backfill | Migration | Columns dropped before data migrated |
| 02 | Incomplete Down() | Migration | Down() doesn't reverse all of Up() |
| 03 | Non-idempotent SQL | Migration | INSERT without WHERE NOT EXISTS |
| 04 | Removed enum value | Spec drift | `Discontinued` removed — 3 frontend files break |
| 05 | Renamed property | Spec drift | `sku` → `skuCode` — generated client breaks |
| 06 | Optional → required | Spec drift | `validTo` now required — forms don't send it |

```bash
# Test scenario 1
python tools/review_migration.py scenarios/01-bad-migration-no-backfill/BadMigration.cs

# Test scenario 4
python tools/check_contract_drift.py \
  --spec scenarios/04-spec-removed-enum-value/modified-spec.yaml \
  --frontend frontend/src \
  --old-spec backend/Api/specs/api-spec.yaml
```

### 4. GitHub Actions (on push)

When PRs touch migration files or the OpenAPI spec, the AI tools run automatically and post review comments.

## Project Structure

```
station-retrofit-demo/
├── backend/                    .NET 8 API + EF Core + PostgreSQL
│   ├── Api/                    Controllers, Models, DTOs, Swagger
│   ├── Database/Migrations/    6 pre-seeded EF Core migrations
│   └── docker-compose.yml      PostgreSQL 16
│
├── frontend/                   React + TypeScript
│   ├── src/api/                Generated API client (typescript-fetch)
│   ├── src/pages/              Components using enums as runtime values
│   └── generate-api-types.sh   OpenAPI Generator script
│
├── tools/                      AI review tools (Python)
│   ├── review_migration.py     Migration reviewer (deterministic + LLM)
│   ├── check_contract_drift.py Contract drift detector (diff + scan + LLM)
│   └── format_pr_comment.py    PR comment formatter
│
├── scenarios/                  Pre-built breaking examples
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

## The Demo Story

> *"We took tribal knowledge — migration rules every developer must memorize — and turned them into AI guardrails that review every PR automatically."*

**Demo 1:** Open a PR with a bad migration → AI comments with specific rule violations and fixes.

**Demo 2:** Open a PR that removes an enum value → AI reports exactly which frontend files will break.

## Tech Stack

| Layer | Technology | Version |
|---|---|---|
| Backend | .NET 8 Minimal API | 8.0 |
| ORM | EF Core + Npgsql | 8.0.11 |
| Database | PostgreSQL | 16 |
| Frontend | React + TypeScript + Vite | 18.3 / 5.6 / 6.0 |
| API Client | openapi-generator-cli | 7.11.0 |
| AI Tools | Python + Anthropic SDK | 3.12 / 0.40+ |
| CI | GitHub Actions | — |

## Requirements

- .NET 8 SDK
- Docker (for PostgreSQL)
- Python 3.12+
- Node.js 20+ (for frontend)
- `ANTHROPIC_API_KEY` (for LLM review — deterministic checks work without it)
