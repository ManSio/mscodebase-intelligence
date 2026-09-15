"""Exp 7 follow-up (C): фильтрация глобального шума в Tarantula-ранжировании.

Гипотеза: тесты неспособны дать специфичного кандидата только из-за общих
утилит (safe_mkdir, get_data_root...) — исключение глобального шума
(функции, вызываемые >cutoff тестами) должно поднять покрытие до ~60-70%.
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
    for s in flist:
        func_tests[s].add(tid)

print(f"total tests: {len(data)}")
print("\ncutoff  tests_with_cand  specific_single<=3 (всех)  (с-канд)  unambig_single (всех)")
for cutoff in [0, 1, 2, 3, 5, 10, 20, 30]:
    good = 0
    unambig = 0
    total = 0
    for tid, flist in data.items():
        if not flist:
            continue
        cands = [s for s in flist if cutoff == 0 or len(func_tests[s]) <= cutoff]
        if not cands:
            continue
        total += 1
        bs = sorted(cands, key=lambda s: len(func_tests[s]))
        ranks = [len(func_tests[s]) for s in bs]
        if len(bs) == 1:
            unambig += 1
        if ranks[0] <= 3 and (len(bs) == 1 or ranks[1] > ranks[0]):
            good += 1
    print(f"{cutoff or 'ALL':>6}  {total:>13}  {good:>15}  {100.0*good/max(len(data),1):>6.1f}%  {100.0*good/max(total,1):>7.1f}%  {100.0*unambig/max(len(data),1):>6.1f}%")