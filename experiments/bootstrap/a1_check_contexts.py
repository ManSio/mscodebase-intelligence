# -*- coding: utf-8 -*-
"""A1: проверить контексты coverage dynamic_context (sysmon).
Сколько src-файлов, сколько контекстов, пустые ли, context-by-lineno пример."""
import sys
from pathlib import Path
import coverage

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path.cwd()
DATA = ROOT / ".coverage"

d = coverage.CoverageData(str(DATA))
d.read()
ctxs = d.measured_contexts()
files = d.measured_files()

def norm(p):
    return p.replace("\\", "/")

src_files = [f for f in files if "/src/" in norm(f)]
test_files = [f for f in files if "test_" in norm(f)]
nonempty = [c for c in ctxs if c]

print(f"data_file: {DATA}")
print(f"contexts: {len(ctxs)} (non-empty {len(nonempty)}, empty={len(ctxs)-len(nonempty)})")
print(f"files: {len(files)} (src {len(src_files)}, test {len(test_files)})")
print(f"sample contexts: {sorted(nonempty)[:5]}")

if src_files:
    f0 = src_files[0]
    cbl = d.contexts_by_lineno(f0)
    print(f"\ncontexts_by_lineno for {norm(f0).split('/src/')[1]}: {len(cbl)} lines")
    for ln, c in sorted(cbl.items())[:4]:
        print(f"  L{ln}: {sorted(c)[:2]}")
    # сколько src-файлов имеют хоть один покрытый-контекстной строкой
    with_ctx = sum(1 for f in src_files if d.contexts_by_lineno(f))
    print(f"src files with any context-lines: {with_ctx}/{len(src_files)}")
else:
    print("NO src files found")