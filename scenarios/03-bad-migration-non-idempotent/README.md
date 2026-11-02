# Scenario 3: Non-Idempotent Backfill SQL

## What's wrong
The backfill SQL uses a plain `INSERT INTO ... SELECT` without any `WHERE NOT EXISTS`
guard or `ON CONFLICT` clause. If the migration is retried (e.g., after a partial failure
and re-run), duplicate rows will be inserted into `price_audit_log`.

## The migration
See `BadMigration.cs` — it creates a `price_audit_log` table and backfills it from
`price_entries`, but the INSERT has no duplicate protection.

## What the AI should catch
- "Non-idempotent backfill: INSERT without WHERE NOT EXISTS or ON CONFLICT"
- "Running this migration twice will create duplicate audit log entries"
- "Add idempotency guard to prevent data duplication on retry"

## How to test
```bash
python tools/review_migration.py scenarios/03-bad-migration-non-idempotent/BadMigration.cs
```
