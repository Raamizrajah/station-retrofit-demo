# Scenario 5: Renamed Property on DTO

## What's wrong
The `sku` property on `ProductDto` was renamed to `skuCode`. This is a breaking change
because the generated API client will expose `skuCode` instead of `sku`, but the frontend
references `product.sku` in multiple components.

## Affected frontend files

| File | Line | Usage |
|------|------|-------|
| `ProductList.tsx` | 71 | `{product.sku}` in table cell |
| `ProductDetail.tsx` | 45 | `{product.sku}` in detail view |
| `CreateProduct.tsx` | (form field) | Form field name bound to `sku` |

## The spec change
See `modified-spec.yaml` — `sku` renamed to `skuCode` on `ProductDto`, `CreateProductRequest`,
and `UpdateProductRequest`.

## What the AI should catch
- "Breaking: property 'sku' renamed to 'skuCode' on ProductDto"
- "Breaking: property 'sku' renamed to 'skuCode' on CreateProductRequest"
- "Frontend references to `.sku` will fail at compile time (TypeScript) or silently return undefined"
- "Suggest: keep `sku` as alias or update all consumers simultaneously"

## How to test
```bash
python tools/check_contract_drift.py \
  --spec scenarios/05-spec-renamed-property/modified-spec.yaml \
  --frontend frontend/src \
  --old-spec backend/Api/specs/api-spec.yaml
```
