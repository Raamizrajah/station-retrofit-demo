# Scenario 2: Incomplete Down() Method

## What's wrong
The Up() method adds 3 columns and creates an index, but Down() only removes 1 column
and doesn't drop the index. Rolling back this migration leaves the database in an
inconsistent state with orphaned columns and an index referencing one of them.

## The migration
See `BadMigration.cs` — Up() adds `category`, `updated_by`, `updated_at` columns plus
an index on `category`. Down() only removes `updated_at`.

## What the AI should catch
- "Down() doesn't reverse Up(): missing DropColumn for 'category' and 'updated_by'"
- "Down() doesn't reverse Up(): missing DropIndex for 'ix_products_category'"
- "Rollback will leave orphaned columns and index in the schema"

## How to test
```bash
python tools/review_migration.py scenarios/02-bad-migration-incomplete-down/BadMigration.cs
```
