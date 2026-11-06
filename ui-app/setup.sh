#!/usr/bin/env bash
# Load GITHUB_TOKEN from .env and run npm install
set -e

ENV_FILE="$(dirname "$0")/../.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

if [ -z "$GITHUB_TOKEN" ]; then
  echo "❌ GITHUB_TOKEN not set. Add it to .env or export it." >&2
  exit 1
fi

echo "✅ GITHUB_TOKEN loaded from .env"
cd "$(dirname "$0")"
npm install "$@"
