#!/usr/bin/env bash
# ============================================================================
# install.sh — Установка MSCodeBase Intelligence для Linux/macOS
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "================================================"
echo " MSCodeBase Intelligence — Install"
echo "================================================"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 not found. Install Python 3.10+ from https://python.org"
    exit 1
fi

PY_VER=$(python3 --version 2>&1)
echo "[1/3] ✅ $PY_VER"

# Run installer
echo "[2/3] Running installer..."
cd "$SCRIPT_DIR"
python3 install.py

echo ""
echo "================================================"
echo " ✅ Installation complete!"
echo ""
echo " Next steps:"
echo "  1. Restart Zed IDE"
echo "  2. Open your project"
echo "  3. Open Agent Panel (Ctrl+Shift+P → 'Agent Panel: Toggle')"
echo "  4. Run: get_index_status()"
echo ""
echo " To uninstall:"
echo "   $APPDATA/Zed/extensions/mscodebase-intelligence/uninstall.sh"
echo "================================================"
