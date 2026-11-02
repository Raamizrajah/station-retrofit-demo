# Scenario 1: Column Drop Without Backfill

## What's wrong
This migration drops columns from `price_entries` without first migrating the data to a new table.
The data in `description` and `price_type` columns will be permanently lost.

## The migration
See `BadMigration.cs` — it creates a `price_metadata` table but drops the source columns
WITHOUT copying data first.

## What the AI should catch
- "Data loss: columns dropped before data migrated to new table"
- "Missing backfill SQL between CreateTable and DropColumn"

## How to test
```bash
python tools/review_migration.py scenarios/01-bad-migration-no-backfill/BadMigration.cs
```
