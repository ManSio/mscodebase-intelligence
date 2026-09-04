#!/usr/bin/env bash
# negative_control_drift_gate.sh — Negative control (правило Тома, fintech 2026-08-11):
# каждый guard обязан ДЕКЛАРИРОВАТЬ отрицательный контроль, который ОБЯЗАН дать
# exit≠0. Иначе зелёные результаты guard-а ничего не значат (класс ln.strip():
# «проверка, структурно неспособная упасть, неотличима от рабочей»).
#
# Двухрукавная проверка (dual-arm, ANP2):
#   Arm 1 (мутант): заведомый дрейф pin vs lock → check_lock_drift.sh ОБЯЗАН дать
#                   exit 1 И напечатать DRIFT (не crash, не exit 0).
#   Arm 2 (контроль): синхронные файлы → обязан дать exit 0 (гейт не даёт
#                   ложных срабатываний; «crash ≠ catch» — финтех: SyntaxError-крах
#                   читался как proven).
# Exit 0 = guard доказан; 1 = guard сломан.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$HERE/check_lock_drift.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fail() { echo "NEGATIVE CONTROL: FAILED — $1"; exit 1; }

# ── Arm 1: мутант — заведомый дрейф ──
mkdir -p "$TMP/drift"
cat > "$TMP/drift/pyproject.toml" <<'EOF'
[project]
name = "drift-fixture"
dependencies = [
    # Pinned: мутант дрейфа (заведомо расходится с lock)
    "lancedb==0.99.0",
    "pylance==9.0.0",
]
EOF
cat > "$TMP/drift/requirements-lock.txt" <<'EOF'
lancedb==0.34.0
pylance==9.0.0
EOF
OUT=$("$GATE" "$TMP/drift" 2>&1); RC=$?
if [ "$RC" -ne 1 ]; then
    fail "мутант-дрейф: гейт НЕ упал (rc=$RC, ожидался 1). Вывод: $OUT"
fi
if ! echo "$OUT" | grep -q "DRIFT"; then
    fail "мутант-дрейф: exit 1, но это НЕ обнаружение дрейфа (crash?). Вывод: $OUT"
fi
echo "Arm1 (мутант-дрейф): ✅ exit 1 + DRIFT найден — гейт УМЕЕТ падать"

# ── Arm 2: контроль — синхрон обязан пройти ──
mkdir -p "$TMP/sync"
cat > "$TMP/sync/pyproject.toml" <<'EOF'
[project]
name = "sync-fixture"
dependencies = [
    "lancedb==0.34.0",
    "pylance==9.0.0",
]
EOF
cp "$TMP/drift/requirements-lock.txt" "$TMP/sync/requirements-lock.txt"
OUT=$("$GATE" "$TMP/sync" 2>&1); RC=$?
if [ "$RC" -ne 0 ]; then
    fail "sync-контроль: гейт дал ложный дрейф (rc=$RC, ожидался 0). Вывод: $OUT"
fi
if ! echo "$OUT" | grep -q "Lockfile in sync"; then
    fail "sync-контроль: нет 'Lockfile in sync' (rc=$RC). Вывод: $OUT"
fi
echo "Arm2 (sync-контроль): ✅ exit 0 — гейт не даёт ложных срабатываний"

# ── Arm 3: мутант — пакет декларирован в pyproject, но ОТСУТСТВУЕТ в lock ──
# (2026-09-04: реальный дрейф tree-sitter-c/ruby прошёл = «pinned, absent in lock».
#  Старый гейт сверял только версию двоих (lancedb/pylance) при обоих присутствующих —
#  отсутствие пакета детектирующим был структурно слеп. Arm 3 закрепляет ловлю общей дыры.)
mkdir -p "$TMP/absent"
cat > "$TMP/absent/pyproject.toml" <<'EOF'
[project]
name = "absent-fixture"
dependencies = [
    "lancedb==0.34.0",
    "tree-sitter-c==0.24.2",
]
EOF
cat > "$TMP/absent/requirements-lock.txt" <<'EOF'
lancedb==0.34.0
EOF
OUT=$("$GATE" "$TMP/absent" 2>&1); RC=$?
if [ "$RC" -ne 1 ]; then
    fail "absent-мутант: гейт НЕ упал (rc=$RC, ожидался 1) — отсутствие пакета в lock недетектируемо. Вывод: $OUT"
fi
if ! echo "$OUT" | grep -q "absent in lock"; then
    fail "absent-мутант: exit 1, но не 'absent in lock'. Вывод: $OUT"
fi
echo "Arm3 (absent-мутант): ✅ exit 1 + 'absent in lock' — гейт ловит отсутствие пакета"

echo "NEGATIVE CONTROL: PASSED (drift-gate может упасть; crash ≠ catch)"
exit 0
