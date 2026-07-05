#!/usr/bin/env bash
# ============================================================================
# sync_to_installed.sh — Sync source to installed extension (Linux/macOS)
# ============================================================================
set -euo pipefail

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${HOME}/.local/share/Zed/extensions/mscodebase-intelligence"

if [ ! -d "$DEST" ]; then
    DEST="${HOME}/Library/Application Support/Zed/extensions/mscodebase-intelligence"
fi

if [ ! -d "$DEST" ]; then
    echo "[ERROR] Extension directory not found at $DEST"
    echo "[INFO]  Install the extension first via install.sh"
    exit 1
fi

echo "================================================"
echo " MSCodeBase Intelligence — Sync to Installed"
echo " Source: $SOURCE"
echo " Dest:   $DEST"
echo "================================================"

# Sync directories (exclude venv, __pycache__, .codebase_indices)
rsync -av --delete \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='.codebase_indices' \
    --exclude='node_modules' \
    "$SOURCE/src" "$DEST/"
rsync -av --delete "$SOURCE/docs" "$DEST/"
[ -d "$SOURCE/.agents" ] && rsync -av --delete "$SOURCE/.agents" "$DEST/"
rsync -av "$SOURCE/"*.py "$SOURCE/"*.md "$SOURCE/"*.toml "$SOURCE/"*.cfg "$SOURCE/"*.txt "$DEST/"

echo ""
echo "[OK] Sync complete. Restart Zed to apply changes."
