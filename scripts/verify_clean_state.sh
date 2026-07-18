#!/usr/bin/env bash
# verify_clean_state.sh — проверка проекта с нуля (clean state)
# Запускается перед [🏁 ИТОГ] со статусом ✅
# Вывод: EXIT_CODE + число passed/failed тестов

set -e

REPO_URL="https://github.com/ManSio/mscodebase-intelligence"
TMPDIR=$(mktemp -d)
CLEANUP=true

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== VERIFY CLEAN STATE ===${NC}"
echo "Temp dir: $TMPDIR"
echo "Cloning $REPO_URL ..."

git clone --depth 1 "$REPO_URL" "$TMPDIR/repo" 2>&1 | tail -3
cd "$TMPDIR/repo"

echo "Creating venv..."
python3 -m venv venv
source venv/bin/activate

echo "Installing package..."
pip install -e . -q 2>&1 | tail -3

echo "Installing test deps..."
pip install pytest pytest-asyncio -q 2>&1 | tail -2

echo "Running tests..."
venv/bin/python -m pytest tests/ -q --tb=short 2>&1 | tee /tmp/test_output.txt

EXIT_CODE=${PIPESTATUS[0]}
PASSED=$(grep -oP '(\d+) passed' /tmp/test_output.txt | head -1 | cut -d' ' -f1 || echo 0)
FAILED=$(grep -oP '(\d+) failed' /tmp/test_output.txt | head -1 | cut -d' ' -f1 || echo 0)
ERRORS=$(grep -oP '(\d+) error' /tmp/test_output.txt | head -1 | cut -d' ' -f1 || echo 0)

echo ""
echo -e "${YELLOW}=== RESULT ===${NC}"
echo "Exit code: $EXIT_CODE"
echo "Passed: $PASSED"
echo "Failed: $FAILED"
echo "Errors: $ERRORS"

# Cleanup
if [ "$CLEANUP" = true ]; then
    cd /
    rm -rf "$TMPDIR"
fi

# Output for parsing
echo "EXIT_CODE=$EXIT_CODE"
echo "PASSED=$PASSED"
echo "FAILED=$FAILED"
echo "ERRORS=$ERRORS"

exit $EXIT_CODE