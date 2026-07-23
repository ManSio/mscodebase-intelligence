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
git clone --depth 1 "$REPO_URL" "$TMPDIR/repo" 2>&1
cd "$TMPDIR/repo"

echo "Creating venv..."
python3 -m venv venv

# --- Lockfile drift gate (аналог uv lock --check) ---
# Если requirements-lock.txt не синхронизирован с pyproject.toml,
# установка из lock расходится с декларацией deps -> CI падает.
echo "Checking lockfile drift (pyproject.toml vs requirements-lock.txt)..."
if [ -f requirements-lock.txt ]; then
    # Сравниваем версии ключевых deps из pyproject (exact pins) с lock
    DRIFT=0
    for pkg in lancedb mcp tree-sitter; do
        PINNED=$(grep -iE "^\"?${pkg}==" pyproject.toml | head -1 | grep -oE '[0-9][0-9.]*' | head -1)
        LOCKED=$(grep -iE "^${pkg}==" requirements-lock.txt | head -1 | grep -oE '[0-9][0-9.]*' | head -1)
        if [ -n "$PINNED" ] && [ -n "$LOCKED" ] && [ "$PINNED" != "$LOCKED" ]; then
            echo -e "${RED}DRIFT: ${pkg} pinned ${PINNED} in pyproject but ${LOCKED} in lock${NC}"
            DRIFT=1
        fi
    done
    if [ "$DRIFT" -ne 0 ]; then
        echo -e "${RED}LOCKFILE DRIFT DETECTED — run: pip freeze > requirements-lock.txt${NC}"
        exit 1
    fi
    echo -e "${GREEN}Lockfile in sync.${NC}"
fi

# Ставим из pyproject (с exact pins / upper bounds), а не резолвим заново из PyPI.
# Если платформа совпадает с lock — ставим из lock для битовой воспроизводимости.
echo "Installing package + test deps..."
if [ -f requirements-lock.txt ] && [ "$(uname -s)" = "Linux" ]; then
    # На Linux-CI ставим из lock, фильтруя Windows-only пакеты
    grep -viE "^(pywin32|wmi|pythoncom)=" requirements-lock.txt > /tmp/req_unix.txt
    venv/bin/pip install -q -r /tmp/req_unix.txt 2>&1 | tail -3
    rm -f /tmp/req_unix.txt
    venv/bin/pip install -q -e ".[dev]" --no-deps 2>&1 | tail -3
else
    # Локально / не-Linux — резолвим по bounds (защищено exact pin lancedb)
    venv/bin/pip install -q -e ".[dev]" 2>&1 | tail -3
fi

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
