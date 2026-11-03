# AI Review Tools

8 AI-powered tools for brownfield system analysis. Each tool follows a 3-layer architecture:
deterministic checks → LLM review (Claude) → formatted markdown output.

All tools support `--context "focus area"` and `--tone technical|business|childlike`.

## Understand Layer

### Business Intelligence (`extract_requirements.py`)

Extracts business rules, domain models, validation logic, and implicit requirements from code.

```bash
python tools/extract_requirements.py /path/to/repo1 /path/to/repo2
python tools/extract_requirements.py /path/to/repo --context "authentication" --tone business
```

### Architecture Doc Generator (`generate_arch_doc.py`)

Generates architecture documentation with Mermaid diagrams, service inventory, data flow, and infrastructure details.

```bash
python tools/generate_arch_doc.py /path/to/repo1 /path/to/repo2
```

### Scenario Planner (`scenario_planner.py`)

Analyses the impact of a proposed change across one or more repositories.

```bash
python tools/scenario_planner.py /path/to/repo1 /path/to/repo2 --scenario "Add Redis caching layer"
```

## Secure Layer

### Secret Scanner (`scan_secrets.py`)

Scans for hardcoded secrets (AWS keys, API tokens, passwords) using entropy analysis and pattern matching.

```bash
python tools/scan_secrets.py /path/to/repo
```

### Dependency & Infrastructure Auditor (`audit_deps.py`)

Flags EOL versions, known CVEs, deprecated K8s APIs, and risky infrastructure patterns.

```bash
python tools/audit_deps.py /path/to/repo
```

### Migration Reviewer (`review_migration.py`)

Reviews EF Core migrations for data loss, incomplete rollbacks, and non-idempotent SQL.

```bash
python tools/review_migration.py path/to/Migration.cs
```

## Monitor Layer

### Domain Model Drift (`check_model_drift.py`)

Detects constraint mismatches when the same entity exists across multiple repositories.

```bash
python tools/check_model_drift.py /path/to/repo-a /path/to/repo-b EntityName
```

### Contract Drift Detector (`check_contract_drift.py`)

Detects breaking OpenAPI changes and their frontend impact.

```bash
python tools/check_contract_drift.py \
  --old-spec backend/Api/specs/api-spec.yaml \
  --spec path/to/modified-spec.yaml \
  --frontend frontend/src
```

## Shared Utilities

- **`llm_utils.py`** — Tone instructions, `apply_tone()`, `add_tone_arg()` shared across all tools
- **`format_pr_comment.py`** — Formats tool output as GitHub PR review comments

## GitHub Actions

Migration review and contract drift run automatically on PRs via `.github/workflows/`.
