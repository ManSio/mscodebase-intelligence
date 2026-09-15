"""Exp 7 follow-up (C): Tarantula-анализ trace_result.json.

Считаем для каждого теста: какие src-функции он выполняет, и насколько они
«специфичны» (вызываются только этим тестом). Кандидат = функция с max
специфичностью. Проверяем гипотезу: >=60-70% тестов имеют однозначного
кандидата без мутаций.
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
TRACE = ROOT / "experiments" / "bootstrap" / "trace_result.json"

with open(TRACE, encoding="utf-8") as f:
    data = json.load(f)

print(f"total tests: {len(data)}")
param = sum(1 for k in data if "[" in k)
print(f"parametrized tests: {param}")
empty = sum(1 for v in data.values() if not v)
print(f"tests w/o src funcs: {empty}")

counts = [len(v) for v in data.values() if v]
print(f"per-test funcs (with >=1): min={min(counts)} max={max(counts)} "
      f"mean={statistics.mean(counts):.1f} median={int(statistics.median(counts))}")

# что реально вызвано тестами, с мета-файлом (src-относительный путь)
func_tests = defaultdict(set)
for tid, flist in data.items():
    for sym in flist:
        func_tests[sym].add(tid)

tot = len(func_tests)
excl = sum(1 for s in func_tests.values() if len(s) == 1)
print(f"unique src symbols: {tot}, exclusive (called by exactly 1 test): {excl} ({100.0*excl/max(tot,1):.1f}%)")

# Тарантула: специфичность = вызывается данным тестом / (сколько всего тестов вызывают)
# специфичность(sc,t)=1/|func_tests[func]| (максимум если только этот тест)
# кандидат для теста = функция с min |func_tests| среди его набора.
candidates = {}
for tid, flist in data.items():
    if not flist:
        continue
    best = None
    best_rank = 10**9
    for sym in flist:
        rank = len(func_tests[sym])
        if rank < best_rank:
            best_rank = rank
            best = [(sym, rank)]
        elif rank == best_rank:
            best.append((sym, rank))
    candidates[tid] = (best, best_rank)

uniq = sum(1 for (b, r) in candidates.values() if r == 1 and len(b) == 1)
r2 = sum(1 for (b, r) in candidates.values() if r == 2 and len(b) == 1)
untied = sum(1 for (b, r) in candidates.values() if len(b) == 1)
tied = sum(1 for (b, r) in candidates.values() if len(b) > 1)
ntsc = len(candidates)
print(f"tests with candidate set: {ntsc}")
print(f"  unique best (exclusive, single): {uniq} ({100.0*uniq/max(ntsc,1):.1f}%)")
print(f"  rank2 single: {r2}")
print(f"  unambiguous candidate total (single best): {untied} ({100.0*untied/max(ntsc,1):.1f}%)")
print(f"  tied best (>1 same rank): {tied}")

# Топ «тяжёлых» shared-функций (вызывается многими тестами) — шум для ранжирования
noisy = sorted(((len(s), sym) for sym, s in func_tests.items()), reverse=True)[:10]
print("noisiest shared src symbols:")
for n, s in noisy:
    print(f"   {n:>4}  {s}")