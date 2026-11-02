# Scenario 4: Removed Enum Value

## What's wrong
The `ProductStatus` enum had `Discontinued` (value `3`) removed from the OpenAPI spec.
The frontend uses `ProductStatus.Discontinued` as a runtime value in 3 components:

| File | Line | Usage |
|------|------|-------|
| `StatusBadge.tsx` | 12 | Color mapping for Discontinued status |
| `ProductList.tsx` | 11 | Included in ALL_STATUSES filter array |
| `ProductDetail.tsx` | 34-36 | `canDiscontinue` logic check |

## The spec change
See `modified-spec.yaml` — `Discontinued` removed from the `ProductStatus` enum.
Compare with `backend/Api/specs/api-spec.yaml` (original).

## What the AI should catch
- "Breaking: enum value 'Discontinued' (3) removed from ProductStatus"
- "Frontend impact: StatusBadge.tsx:12, ProductList.tsx:11, ProductDetail.tsx:34"
- "Products currently in Discontinued status will have an unmapped status value"
- "Suggest: deprecate before removing, or add migration path for existing data"

## How to test
```bash
python tools/check_contract_drift.py \
  --spec scenarios/04-spec-removed-enum-value/modified-spec.yaml \
  --frontend frontend/src \
  --old-spec backend/Api/specs/api-spec.yaml
```
