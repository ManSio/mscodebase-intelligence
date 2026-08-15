#!/usr/bin/env bash
# EXP-5: verify_clean_state.sh — falsifiability-проверка гейта.
# Часть A: drift-гейт (строки 55-71 скрипта) — контроль, гейт УМЕЕТ падать.
# Часть B: вакуумная сюита — гейт НЕ МОЖЕТ отличить «тесты не проверяют ничего»
#          от «всё проверено». Reproducibility без falsifiability (ANP2).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

PY="${PYTHON:-python}"
command -v "$PY" >/dev/null 2>&1 || PY="/c/Users/misha/AppData/Local/Zed/extensions/mscodebase-intelligence/venv/Scripts/python.exe"

echo "PY=$PY"
echo "=== EXP-5: verify_clean_state.sh — falsifiability ==="

# ---------- Часть A: drift-гейт (код дословно из скрипта, строки 55-71) ----------
TMP_A=$(mktemp -d)
trap 'rm -rf "$TMP_A" "$TMP_B"' EXIT
cat > "$TMP_A/pyproject.toml" <<'EOF'
[project]
name = "mini"
version = "0.1.0"
dependencies = ["lancedb==0.12.0"]
EOF
cat > "$TMP_A/requirements-lock.txt" <<'EOF'
lancedb==0.13.0
EOF

echo ""
echo "--- Часть A: lockfile drift (lancedb pinned 0.12.0 vs locked 0.13.0) ---"
DRIFT=0
for pkg in lancedb mcp tree-sitter; do
    PINNED=$(grep -iE "^\"?${pkg}==" "$TMP_A/pyproject.toml" | head -1 | grep -oE '[0-9][0-9.]*' | head -1)
    LOCKED=$(grep -iE "^${pkg}==" "$TMP_A/requirements-lock.txt" | head -1 | grep -oE '[0-9][0-9.]*' | head -1)
    if [ -n "$PINNED" ] && [ -n "$LOCKED" ] && [ "$PINNED" != "$LOCKED" ]; then
        echo "DRIFT: ${pkg} pinned ${PINNED} in pyproject but ${LOCKED} in lock"
        DRIFT=1
    fi
done
if [ "$DRIFT" -ne 0 ]; then
    echo "A-РЕЗУЛЬТАТ: drift DETECTED → exit 1 (гейт УМЕЕТ падать) ✅"
else
    echo "A-РЕЗУЛЬТАТ: drift НЕ обнаружен → exit 0 ❌ гейт не поймал"
fi

# ---------- Часть B: вакуумная сюита ----------
TMP_B=$(mktemp -d)
mkdir -p "$TMP_B/tests"
cat > "$TMP_B/tests/test_vacuous.py" <<'EOF'
"""Вакуумная сюита: тесты проходят, но НЕ МОГУТ упасть (ANP2/Max)."""

def test_always_passes():
    pass

def test_returns_none():
    x = 1 + 1

def test_docstring_only():
    """Нет ни одного assert."""
EOF

echo ""
echo "--- Часть B: вакуумная сюита (3 теста без единого assert) ---"
"$PY" -m pytest "$TMP_B/tests" -q --tb=short 2>&1 | tail -4
EXIT_B=$?
PASSED=$(cd "$TMP_B" && "$PY" -m pytest tests -q 2>&1 | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo 0)
echo "B-РЕЗУЛЬТАТ: pytest exit=$EXIT_B, passed=$PASSED"
if [ "$EXIT_B" -eq 0 ]; then
    echo "→ Гейт напечатал бы: CLEAN STATE VERIFICATION: PASSED для сюиты,"
    echo "  которая не проверяет НИЧЕГО (0 asserts). Reproducibility без falsifiability ✅"
else
    echo "→ гейт упал (неожиданно)"
fi

echo ""
echo "=== EXP-5 ИТОГ ==="
echo "A (drift): гейт может упасть — контроль подтверждён."
echo "B (vacuous): гейт НЕ может отличить пустую сюиту от настоящей — семантическая слепота."
echo "Решение (дискуссия): negative control (мутант, обязан упасть) как Arm 2 в гейте."
