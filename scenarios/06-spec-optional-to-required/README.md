# Scenario 6: Optional Field Changed to Required

## What's wrong
The `validTo` field on `CreatePriceRequest` changed from optional to required.
The frontend `CreatePrice.tsx` form sends `validTo: validTo || undefined` — when the user
leaves the "Valid To" field empty, the request body omits `validTo` entirely, which will
now fail server-side validation.

## Affected frontend files

| File | Line | Usage |
|------|------|-------|
| `CreatePrice.tsx` | 32 | `validTo: validTo \|\| undefined` — sends undefined when empty |

## The spec change
See `modified-spec.yaml` — `validTo` added to the `required` array on `CreatePriceRequest`.

## What the AI should catch
- "Breaking: 'validTo' changed from optional to required on CreatePriceRequest"
- "Frontend sends `undefined` for empty validTo — will now fail validation"
- "Existing API consumers that don't send validTo will get 400 errors"
- "Suggest: make validTo required in the form UI, or keep it optional in the spec"

## How to test
```bash
python tools/check_contract_drift.py \
  --spec scenarios/06-spec-optional-to-required/modified-spec.yaml \
  --frontend frontend/src \
  --old-spec backend/Api/specs/api-spec.yaml
```
