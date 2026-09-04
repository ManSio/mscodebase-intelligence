#!/usr/bin/env bash
# check_lock_drift.sh — дрейф-гейт: exact-пины pyproject.toml vs requirements-lock.txt
# Usage: check_lock_drift.sh [project_dir]   (default: .)
# Exit 0 = в синхроне; 1 = дрейф найден; 2 = pyproject.toml отсутствует.
#
# История (EXP-5A, 2026-08-11): старый grep "^\"?${pkg}==" требовал `pkg==`
# в начале строки, но пины лежат в TOML-массиве (`    "lancedb==0.34.0",`) →
# PINNED всегда был пуст → ветка DRIFT недостижима → гейт был структурно мёртв.
# Фикс: матчим `"pkg==x.y.z` ВНУТРИ строки (после фильтра комментариев).
set -uo pipefail

DIR="${1:-.}"
cd "$DIR" 2>/dev/null || { echo "check_lock_drift: cannot cd $DIR"; exit 2; }
if [ ! -f pyproject.toml ]; then
    echo "check_lock_drift: pyproject.toml not found in $DIR"
    exit 2
fi
if [ ! -f requirements-lock.txt ]; then
    echo "check_lock_drift: requirements-lock.txt not found — skip"
    exit 0
fi

# Только exact-пины (==). Диапазоны (>=, <) не сравниваются — нужен semver-парсер.
# Сравниваются ВСЕ exact-пины pyproject против requirements-lock.txt — и версия,
# и НАЛИЧИЕ (раньше сверялись только lancedb/pylance и только когда оба присутствуют,
# поэтому «декларирован в pyproject, но вообще отсутствует в lock» проходил
# незамеченным — дрейф tree-sitter-c/ruby 2026-09-04).
DRIFT=0
while IFS= read -r spec; do
    pkg="${spec%%==*}"
    PINNED="${spec#*==}"
    LOCKED=$(grep -iE "^${pkg}==" requirements-lock.txt | head -1 | sed -E 's/^[[:space:]]*[^=]*==//')
    if [ -z "$LOCKED" ]; then
        echo "DRIFT: ${pkg}==${PINNED} pinned in pyproject but absent in lock"
        DRIFT=1
    elif [ "$PINNED" != "$LOCKED" ]; then
        echo "DRIFT: ${pkg} pinned ${PINNED} in pyproject but ${LOCKED} in lock"
        DRIFT=1
    fi
done < <(grep -oE '"[a-zA-Z0-9_.-]+==[0-9][0-9.a-z+]*"' pyproject.toml | tr -d '"' | sort -u)

if [ "$DRIFT" -ne 0 ]; then
    exit 1
fi
echo "Lockfile in sync."
exit 0
