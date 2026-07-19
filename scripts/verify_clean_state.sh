#!/usr/bin/env bash
# verify_clean_state.sh — проверка проекта с нуля (clean state)
# Вывод: EXIT_CODE + число passed/failed тестов
set -uo pipefail

REPO_URL="https://github.com/ManSio/mscodebase-intelligence"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== VERIFY CLEAN STATE ===${NC}"
echo "Temp dir: $TMPDIR"

echo "Cloning $REPO_URL ..."
git clone --depth 1 "$REPO_URL" "$TMPDIR/repo" -q 2>&1
cd "$TMPDIR/repo"

echo "Creating venv..."
python3 -m venv venv -q

echo "Installing package + test deps..."
venv/bin/pip install -q -e ".[dev]" 2>&1 | tail -3

echo "Running full test suite (no filters)..."
RESULT=$(venv/bin/python -m pytest tests/ -q --tb=short 2>&1)
EXIT_CODE=$?

PASSED=$(echo "$RESULT" | grep -oE '[0-9]+ passed' | head -1 | grep -oE '[0-9]+' || echo "0")
FAILED=$(echo "$RESULT" | grep -oE '[0-9]+ failed' | head -1 | grep -oE '[0-9]+' || echo "0")

echo ""
echo -e "${YELLOW}=== RESULT ===${NC}"
echo "Exit code: $EXIT_CODE"
echo "Passed: $PASSED"
echo "Failed: $FAILED"
echo "$RESULT" | tail -5

if [ "$EXIT_CODE" -eq 0 ]; then
    echo -e "${GREEN}CLEAN STATE VERIFICATION: PASSED${NC}"
else
    echo -e "${RED}CLEAN STATE VERIFICATION: FAILED${NC}"
fi

exit $EXIT_CODE
