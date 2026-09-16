# -*- coding: utf-8 -*-
"""A1: качество контекстов — распределение пустых (import-time) vs тестовых контекстов."""
import sys
from collections import Counter
from pathlib import Path
import coverage

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path.cwd()
d = coverage.CoverageData(str(ROOT / ".coverage"))
d.read()

def norm(p):
    return p.replace("\\", "/")

src_files = [f for f in d.measured_files() if "/src/" in norm(f)]
total_lines = 0
empty_only = 0
has_test_ctx = 0
for f in src_files:
    cbl = d.contexts_by_lineno(f)
    for ln, ctxs in cbl.items():
        total_lines += 1
        nonempty = [c for c in ctxs if c]
        if not nonempty:
            empty_only += 1
        else:
            has_test_ctx += 1

print(f"src files: {len(src_files)}")
print(f"lines with context data: {total_lines}")
print(f"  only empty ctx (import-time): {empty_only} ({empty_only/total_lines*100:.1f}%)")
print(f"  with real test ctx:           {has_test_ctx} ({has_test_ctx/total_lines*100:.1f}%)")

ctx_line_count = Counter()
for f in src_files:
    cbl = d.contexts_by_lineno(f)
    for ln, ctxs in cbl.items():
        for c in ctxs:
            if c:
                ctx_line_count[c] += 1
print(f"\ntop-5 крупнейшие тест-контексты по числу строк:")
for c, n in ctx_line_count.most_common(5):
    print(f"  {n:5d}  {c}")