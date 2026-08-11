#!/usr/bin/env bash
# verify_clean_state.sh — проверка проекта с нуля (clean state)
# Вывод: EXIT_CODE + число passed/failed тестов
set -uo pipefail

# Корень скрипта (ДО любого cd — BASH_SOURCE относительный, см. clone-режим)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# $1 = repo URL (для ручного запуска с клоном), либо флаг --no-clone [repo URL]
# --no-clone: работать в текущем каталоге (CI: $GITHUB_WORKSPACE = свежий checkout
# раннера) — CI не должна клонировать сам себя (ISSUE.md P0-3).
REPO_URL="${1:-https://github.com/ManSio/mscodebase-intelligence}"
NO_CLONE=0
if [ "${1:-}" = "--no-clone" ]; then
    NO_CLONE=1
    REPO_URL="${2:-}"
fi
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== VERIFY CLEAN STATE ===${NC}"
echo "Temp dir: $TMPDIR"

# venv layout: POSIX (Linux/macOS) → bin/, Windows (GitBash/MSYS2/Cygwin) → Scripts/
# (README заявляет Windows как основную платформу — скрипт обязан работать и там)
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) VENV_BIN="venv/Scripts" ;;
    *) VENV_BIN="venv/bin" ;;
esac

if [ "$NO_CLONE" -eq 1 ]; then
    echo "No-clone mode: verifying current directory"
else
    echo "Cloning $REPO_URL ..."
    git clone --depth 1 "$REPO_URL" "$TMPDIR/repo" 2>&1
    cd "$TMPDIR/repo"
fi

echo "Creating venv..."
python -m venv venv || { echo "venv creation failed, trying with ensurepip"; python -m venv --without-pip venv; source "$VENV_BIN/activate" && python -m ensurepip; }

# Ensure pip is available
if [ ! -f "$VENV_BIN/pip" ]; then
    echo "pip not found in venv, running ensurepip..."
    source "$VENV_BIN/activate"
    python -m ensurepip --default-pip
fi

# --- Lockfile drift gate (аналог uv lock --check) ---
# Если requirements-lock.txt не синхронизирован с pyproject.toml,
# установка из lock расходится с декларацией deps -> CI падает.
# Логика вынесена в scripts/check_lock_drift.sh: negative control
# (scripts/negative_control_drift_gate.sh) обязан тестировать ТУ ЖЕ логику
# (EXP-5A: старый grep "^\"?${pkg}==" не матчил пины TOML-массива — гейт мёртв).
echo "Checking lockfile drift (pyproject.toml vs requirements-lock.txt)..."
if [ -f requirements-lock.txt ]; then
    "$SCRIPT_DIR/check_lock_drift.sh" .
    GATE_RC=$?
    if [ "$GATE_RC" -eq 1 ]; then
        echo -e "${RED}LOCKFILE DRIFT DETECTED — run: pip freeze > requirements-lock.txt${NC}"
        exit 1
    elif [ "$GATE_RC" -ne 0 ]; then
        # exit 2 = нет pyproject.toml (запуск не из корня проекта) — не путать с дрейфом
        echo -e "${RED}LOCKFILE DRIFT CHECK FAILED (exit $GATE_RC)${NC}"
        exit 1
    fi
    # Negative control (правило Тома): guard обязан уметь падать, иначе его
    # зелёные результаты ничего не значат. Мёртвый guard = fail громко.
    "$SCRIPT_DIR/negative_control_drift_gate.sh" || {
        echo -e "${RED}DRIFT GATE NEGATIVE CONTROL FAILED — guard сломан${NC}"
        exit 1
    }
fi

# Ставим из pyproject (с exact pins / upper bounds), а не резолвим заново из PyPI.
# Если платформа совпадает с lock — ставим из lock для битовой воспроизводимости.
# ВАЖНО: pip-фейл = exit 1 сразу (раньше без set -e установка тихо проваливалась,
# и скрипт падал уже на pytest с невнятной ошибкой импорта).
echo "Installing package + test deps..."
if [ -f requirements-lock.txt ] && [ "$(uname -s)" = "Linux" ]; then
    # На Linux-CI ставим из lock, фильтруя Windows-only пакеты
    grep -viE "^(pywin32|wmi|pythoncom)=" requirements-lock.txt > /tmp/req_unix.txt
    "$VENV_BIN/pip" install -q -r /tmp/req_unix.txt 2>&1 | tail -3 \
        || { echo -e "${RED}PIP INSTALL (lock) FAILED${NC}"; rm -f /tmp/req_unix.txt; exit 1; }
    rm -f /tmp/req_unix.txt
    # Dev-зависимости (pytest и др.) в requirements-lock.txt не входят (runtime lock).
    # --no-deps нельзя: он пропускает и dev-инструменты. Уже установленные из lock
    # runtime-пакеты удовлетворяют bounds pyproject — pip их не апгрейдит.
    "$VENV_BIN/pip" install -q -e ".[dev]" 2>&1 | tail -3 \
        || { echo -e "${RED}PIP INSTALL (editable) FAILED${NC}"; exit 1; }
else
    # Локально / не-Linux — резолвим по bounds (защищено exact pin lancedb)
    "$VENV_BIN/pip" install -q -e ".[dev]" 2>&1 | tail -3 \
        || { echo -e "${RED}PIP INSTALL FAILED${NC}"; exit 1; }
fi

echo "Running full test suite (no filters)..."
RESULT=$("$VENV_BIN/python" -m pytest tests/ -q --tb=short 2>&1)
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
