# AI Review Tools

AI-powered code review tools for brownfield .NET systems.

## Migration Reviewer

Reviews EF Core migrations against codified rules:

```bash
# Review a migration file
python tools/review_migration.py backend/Database/Migrations/20260615100000_SeparatePriceHistory.cs

# With API key for LLM review
ANTHROPIC_API_KEY=sk-... python tools/review_migration.py backend/Database/Migrations/20260615100000_SeparatePriceHistory.cs
```

## Contract Drift Detector

Detects breaking API changes and their frontend impact:

```bash
# Check spec changes against frontend
python tools/check_contract_drift.py \
  --spec backend/Api/specs/api-spec.yaml \
  --frontend frontend/src \
  --old-spec <(git show main:backend/Api/specs/api-spec.yaml)
```

## GitHub Actions

Both tools run automatically on PRs via `.github/workflows/`.
