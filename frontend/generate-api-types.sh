#!/bin/bash
# Generate types from the API OpenAPI spec.
source .env 2>/dev/null || true

rm -rf src/api/apis
rm -rf src/api/models

docker network create --driver bridge station_retrofit_default || true

if docker run \
  --user "$(id -u):$(id -g)" \
  --network station_retrofit_default \
  --rm -v "${PWD}:/local" openapitools/openapi-generator-cli:v7.11.0 generate \
  -i "${API_SPEC_URL:-http://api}/swagger/v1/swagger.json" \
  -g typescript-fetch \
  -o local/src/api \
  --openapi-normalizer SET_TAGS_FOR_ALL_OPERATIONS=StationRetrofit; then
  echo "✅ Generated the client library successfully"
else 
  echo "❌ Failed to generate the client library"
  exit 1
fi
