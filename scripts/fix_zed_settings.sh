#!/usr/bin/env bash
# ============================================================================
# fix_zed_settings.sh — Remove current_dir from MSCodeBase Zed settings (Linux/macOS)
# ============================================================================
set -euo pipefail

# Find settings.json
SETTINGS="${HOME}/.config/zed/settings.json"
if [ ! -f "$SETTINGS" ] && [ -d "${HOME}/Library/Application Support/Zed" ]; then
    SETTINGS="${HOME}/Library/Application Support/Zed/settings.json"
fi

if [ ! -f "$SETTINGS" ]; then
    echo "[ERROR] Zed settings.json not found at $SETTINGS"
    exit 1
fi

echo "================================================"
echo " MSCodeBase Intelligence — Fix Zed Settings"
echo " File: $SETTINGS"
echo "================================================"

# Backup
cp "$SETTINGS" "${SETTINGS}.backup.$$"
echo "[1/3] ✅ Backup created: ${SETTINGS}.backup.$$"

# Fix via Python
python3 -c "
import json, sys
p = '$SETTINGS'
with open(p, 'r') as f:
    s = json.load(f)
changed = False
mcp = s.get('context_servers', {}).get('mscodebase-intelligence', {})
if 'current_dir' in mcp:
    print(f'[2/3] Removing current_dir from MCP server (was: {mcp[\"current_dir\"]!r})')
    del mcp['current_dir']
    changed = True
if changed:
    with open(p, 'w') as f:
        json.dump(s, f, indent=4)
    print('[3/3] ✅ Settings updated. Restart Zed.')
else:
    print('[3/3] ✅ current_dir not found, nothing to change.')
"

echo ""
echo "Done. Restart Zed IDE to apply changes."
