"""A11: out-of-tree reproduction of the vacuous-test scan.

`experiments/misc_probes/exp_vacuous_scan.py` hardcodes TESTS_DIR =
experiments/../tests = experiments/tests, which does not exist. Run today it
reports 0/0/0 and exits 0 — a silent no-op (same class as the drift-gate in
A14). This copy reuses the ORIGINAL scanning logic verbatim, only repointing
the directory, so the published 1133/1143 claim is measured before the script
is fixed.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[2]
ORIG = ROOT / "experiments" / "misc_probes" / "exp_vacuous_scan.py"
REPO_TESTS = ROOT / "tests"

spec = importlib.util.spec_from_file_location("orig_vacuous", ORIG)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)  # main() is guarded, so import does not run it

print(f"[A11] original TESTS_DIR = {mod.TESTS_DIR}")
print(f"[A11] original dir exists? {mod.TESTS_DIR.exists()}  "
      f"<- run today silently reports 0 tests, exit 0")
print(f"[A11] repointed scan dir = {REPO_TESTS} (exists={REPO_TESTS.exists()})")

total = proven = skipped = 0
unproven: list[str] = []
for py in sorted(REPO_TESTS.rglob("test_*.py")):
    if py.name in mod.SKIP_FILES:
        continue
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    except SyntaxError as e:
        print(f"  SyntaxError {py.name}: {e}")
        continue
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        total += 1
        if mod.is_skipped(node):
            skipped += 1
            continue
        if mod.has_failing_construct(node):
            proven += 1
        else:
            unproven.append(f"{py.relative_to(ROOT).as_posix()}:{node.lineno}")

print("\n[A11] ==== recomputed (repo root) ====")
print(f"[A11] total={total} proven={proven} vacuous={len(unproven)} skip={skipped} "
      f"vacuous_share={len(unproven) / max(total, 1) * 100:.2f}%")
print(f"[A11] published (2026-08-11): total=1143 proven=1133 vacuous=3 skip=7")
for loc in unproven:
    print(f"[A11] vacuous: {loc}")
print(f"[A11] total delta vs published: {total - 1143:+d} (W4: suite grew -> expected)")
print(f"[A11] vacuous delta vs published: {len(unproven) - 3:+d}")
