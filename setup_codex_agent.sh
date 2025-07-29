#!/usr/bin/env bash
# setup_codex_agent.sh
# Bootstrap a fresh checkout of “Codex-Agent”.
# ------------------------------------------------------------
# 1. Ensure we’re on a recent Bash and exit on error.
set -euo pipefail

echo "🛠  Codex-Agent setup starting…"

# 2. Choose the Python we want (feel free to adjust).
PYTHON_VERSION_MIN="3.12"

# Function to compare Python versions (“sort -V” handles dotted numbers).
version_ge() { [ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" = "$2" ]; }

# 3. Locate an appropriate python executable.
if command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "❌ python3 not found. Install Python ≥ $PYTHON_VERSION_MIN and rerun."
  exit 1
fi

PY_VER="$($PY -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
if ! version_ge "$PY_VER" "$PYTHON_VERSION_MIN"; then
  echo "❌ Python $PYTHON_VERSION_MIN or newer required (found $PY_VER)"
  exit 1
fi
echo "✔️  Using $PY ($PY_VER)"

# 4. Create virtual environment in .venv if absent.
if [ ! -d ".venv" ]; then
  echo "📦 Creating virtual environment (.venv)…"
  $PY -m venv .venv
fi

# 5. Activate it for the remainder of this script.
source .venv/bin/activate
echo "✔️  Virtual env activated"

# 6. Install/upgrade uv (fast PEP-508 resolver) inside the venv if missing.
if ! command -v uv >/dev/null 2>&1; then
  echo "⬇️  Installing uv inside the venv…"
  pip install --upgrade pip >/dev/null
  pip install uv >/dev/null
fi
echo "✔️  uv available: $(uv --version)"

# 7. Sync project dependencies (all optional “extras” included).
echo "📚 Resolving and installing dependencies with uv…"
uv sync --all-extras

echo "✅ Codex-Agent environment ready."

source .venv/bin/activate

echo "👉 Finished activating  source .venv/bin/activate"
