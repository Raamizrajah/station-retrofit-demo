#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# ── 1. Check Python ──
if ! command -v python3 &>/dev/null; then
  echo "❌ python3 not found. Install Python 3.12+."
  exit 1
fi

# ── 2. Create venv if missing ──
if [ ! -d .venv ]; then
  echo "📦 Creating Python virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate

# ── 3. Install Python deps ──
python3 -m pip install -q -r tools/requirements.txt

# ── 4. Load .env ──
if [ ! -f .env ]; then
  echo ""
  echo "⚠️  No .env file found."
  echo "   Copy the template and add your API key:"
  echo ""
  echo "   cp .env.example .env"
  echo "   # Edit .env with your ANTHROPIC_API_KEY"
  echo ""
  echo "   Then run ./start.sh again."
  exit 1
fi
set -a
source .env
set +a

if [ -z "$ANTHROPIC_API_KEY" ] || [ "$ANTHROPIC_API_KEY" = "your-key-here" ]; then
  echo "⚠️  ANTHROPIC_API_KEY not set in .env — deterministic checks will work, but LLM review won't."
fi

# ── 5. Start server ──
echo ""
echo "🚀 Starting Station Retrofit at http://localhost:8080"
echo "   Press Ctrl+C to stop."
echo ""
python -c "from ui.server import main; main()"
