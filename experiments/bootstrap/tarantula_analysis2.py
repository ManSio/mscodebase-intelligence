"""Exp 7 follow-up (C): распределение рангов Tarantula + ручная валидация.

Дополнительно к tarantula_analysis.py: гистограмма минимального ранга
best-кандидата; топ тестов с 'тяжёлыми' shared-функциями; контекст для
ручной разметки (тест → top-3 кандидата с их рангами и файлом импорта).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
TRACE = ROOT / "experiments" / "bootstrap" / "trace_result.json"

with open(TRACE, encoding="utf-8") as f:
    data = json.load(f)

func_tests = defaultdict(set)
for tid, flist in data.items():
    for sym in flist:
        func_tests[sym].add(tid)

# распределение рангов best-кандидата по всем тестам
rank_hist = defaultdict(int)
for tid, flist in data.items():
    if not flist:
        continue
    best_rank = min(len(func_tests[sym]) for sym in flist)
    rank_hist[best_rank] += 1

print("histogram: best-candidate min-rank per test")
for r in sorted(rank_hist):
    print(f"   rank={r:>3}: {rank_hist[r]:>4} tests ({100.0*rank_hist[r]/max(len(data),1):.1f}%)")

# доля тестов, где rank best<=3
cum = sum(n for r, n in rank_hist.items() if r <= 3)
print(f"tests with best-rank <=3: {cum} ({100.0*cum/max(len(data),1):.1f}%)")

# для ручной валидации: выбор тестов (ранг1, ранг2, ra
# nk3, tied>1) — по 2 каждого, с top-3 кандидатами и импортом файла
def pick(cond, n=2):
    out = []
    for tid, flist in data.items():
        if not flist:
            continue
        syms = sorted(flist, key=lambda s: len(func_tests[s]))
        if cond(syms):
            out.append((tid, syms))
            if len(out) >= n:
                break
    return out

print("\n-- top-3 кандидатов для ручной разметки --")
for label, cond in [
    ("exclusive rank1 single", lambda s: len(func_tests[s[0]]) == 1 and len(s) == 1),
    ("rank2 single", lambda s: len(func_tests[s[0]]) == 2 and len(s) == 1),
    ("tied (ambiguous)", lambda s: len(s) > 1),
]:
    print(f"\n[{label}]")
    for tid, syms in pick(cond, 2):
        b = syms[:3]
        show = [f"{x} (rank {len(func_tests[x])})" for x in b]
        print(f"   {tid}\n      -> {show}")