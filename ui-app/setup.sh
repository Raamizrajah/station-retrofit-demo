#!/usr/bin/env bash
# Load GITHUB_TOKEN from .env and run npm install
set -e

ENV_FILE="$(dirname "$0")/../.env"
if [ -f "$ENV_FILE" ]; then
  export $(grep -v '^#' "$ENV_FILE" | grep -v '^$' | xargs)
fi

if [ -z "$GITHUB_TOKEN" ]; then
  echo "❌ GITHUB_TOKEN not set. Add it to .env or export it." >&2
  exit 1
fi

echo "✅ GITHUB_TOKEN loaded from .env"
cd "$(dirname "$0")"
npm install "$@"
