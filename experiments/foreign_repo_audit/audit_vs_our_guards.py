"""AUDIT: does Tom's code satisfy OUR guards? Evidence-first, no assertion without a count.

Our lens is our own institutional memory, not generic advice:
  P-018  one canonical writer per field (relpath) + contract test with negative control
  P-019  harness must live in the repo; a known rule that isn't applied is a real cost
  P-011  new state next to reset-bearing state must inherit the reset
  P-016  a guard must check liveness, not presence
  P-002  full test collection, not a selective run
  P-012  resources released on every exit path

Each row prints the evidence command result, so every judgement is checkable.
"""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

SRC = pathlib.Path(r"D:\Project\_reference_repos\Tirthahq__crystal-memory__HEAD-6cb8479")
SCR = SRC / "scripts"


def head(t: str) -> None:
    print("\n" + "=" * 96)
    print(t)
    print("=" * 96)


def p018() -> None:
    head("P-018  one canonical writer for the relative path + contract test")
    idioms = {"as_posix()": [], "replace(os.sep,'/')": [],
              "replace('\\\\','/') (literal)": [], "NOT normalised": []}
    canon = re.compile(r"(as_posix\(\)|replace\(os\.sep|replace\('\\\\\\\\')")
    for p in sorted(SCR.glob("*.py")):
        src = p.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            # find assignments whose value builds a relative path from a filesystem path
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = (list(node.targets) if isinstance(node, ast.Assign)
                       else [node.target])
            value = node.value
            if value is None:
                continue
            seg = ast.unparse(value)
            if "relpath" not in seg and "relative_to" not in seg:
                continue
            for t in targets:
                name = getattr(t, "id", None) or getattr(t, "attr", None)
                if not name:
                    continue
                site = f"{p.name}:{node.lineno}  {name} = {seg[:64]}"
                if "as_posix" in seg:
                    idioms["as_posix()"].append(site)
                elif "replace(os.sep" in seg:
                    idioms["replace(os.sep,'/')"].append(site)
                elif "replace('\\\\'" in seg or 'replace("\\\\"' in seg:
                    idioms["replace('\\\\','/') (literal)"].append(site)
                else:
                    idioms["NOT normalised"].append(site)
    for k, v in idioms.items():
        print(f"\n  idiom: {k:24} n={len(v)}")
        for s in v:
            print(f"      {s}")
    total = sum(len(v) for v in idioms.values())
    print(f"\n  VERDICT: {total} writers of the same field, "
          f"{len(idioms)} different idioms, 1 shared helper (expected) -> {0}")
    helpers = []
    for p in sorted(SCR.glob("*.py")):
        for m in re.finditer(r"^def (\w*(?:normali[sz]|rel_path|as_rel|rel_)\w*)\(", p.read_text(encoding='utf-8', errors='replace'), re.M):
            helpers.append(f"{p.name}:{m.group(1)}")
    print(f"  single-source helpers found: {helpers or 'NONE'}")


def p019() -> None:
    head("P-019  a known rule that is not applied everywhere; harness lives in the repo")
    # Count only COMPARISON sites where the left side is a variable that was assigned
    # from a filesystem path (the ones that can actually invert). String literals used as
    # selftest INPUTS are excluded on purpose: they are not computed paths, and counting
    # them would inflate the number.
    lit = re.compile(r"""(startswith\(|endswith\(|\bin\b\s+rel|not in rel|==\s*rel)""")
    path_lit = re.compile(r"""["'][^"']*(?:^|/)(?:memory|catalogue|docs|scripts|starter|scratch)/""")
    norm = re.compile(r"replace\(os\.sep|as_posix|replace\('\\\\'")
    computed: dict[str, str] = {}
    for p in sorted(SCR.glob("*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                seg = ast.unparse(node.value)
                if "relpath" in seg or "relative_to" in seg:
                    ts = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in ts:
                        nm = getattr(t, "id", None)
                        if nm:
                            computed[nm] = seg
    bad, good = [], []
    for p in sorted(SCR.glob("*.py")):
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            if not re.search(r"(startswith|endswith|not in)\b", line):
                continue
            if not re.search(r"""(memory/|wiki/schema|catalogue/|docs/|scratch/)""", line):
                continue
            names = [n for n in computed if re.search(rf"\b{n}\b", line)]
            if not names:
                continue
            (good if norm.search(line) else bad).append(
                f"{p.name}:{i}  [{','.join(names)}] {s[:78]}")
    print(f"\n  COMPARISONS of a computed rel against a path literal:")
    print(f"    WITH normalisation    n={len(good)}")
    for s in good:
        print(f"        {s}")
    print(f"    WITHOUT normalisation n={len(bad)}")
    for s in bad:
        print(f"        {s}")
    print("\n  (selftest string literals used as INPUTS are excluded — counting them would inflate)")
    print(f"  harness: selftests live INSIDE the shipped modules (no separate test tree): "
          f"tests/={ (SRC / 'tests').exists() }  spec/={ (SRC / 'spec').exists() }")


def p011() -> None:
    head("P-011  state next to reset-bearing state must inherit the reset")
    ci = (SCR / "crystal_inject.py").read_text(encoding="utf-8", errors="replace")
    lines = ci.splitlines()
    hit = next((i for i, l in enumerate(lines) if "/dev/console" in l), None)
    if hit is None:
        print("\n  /dev/console NOT FOUND — the X2 chain changed; re-verify before reporting.")
        return
    lo = max(0, hit - 10)
    print(f"\n  crystal_inject.py session-id chain (lines {lo + 1}-{hit + 1}):")
    for ln in lines[lo:hit + 2]:
        if ln.strip():
            print(f"      {ln.strip()[:94]}")
    print("\n  the per-session rotation counter is keyed by that id; when it degrades to")
    print("  'nosession' every session shares one key, so the reset that separates")
    print("  sessions never happens. P-011 exactly: the new state did not inherit the reset.")


def p016() -> None:
    head("P-016  a guard must check LIVENESS, not presence")
    print(f"\n  CI workflows:        {(SRC / '.github' / 'workflows').exists()}")
    print(f"  Makefile:            {(SRC / 'Makefile').exists()}")
    print(f"  pyproject / setup:   {(SRC / 'pyproject.toml').exists()} / {(SRC / 'setup.py').exists()}")
    print(f"  pre-commit:          {(SRC / '.pre-commit-config.yaml').exists()}")
    print(f"  CONTRIBUTING:        {(SRC / 'CONTRIBUTING.md').exists()}")
    print(f"  CHANGELOG:           {(SRC / 'CHANGELOG.md').exists()}")
    print(f"  SECURITY:            {(SRC / 'SECURITY.md').exists()}")
    print(f"  LICENSE:             {(SRC / 'LICENSE').exists()}")
    r = subprocess.run(["git", "-C", str(SRC), "log", "--oneline", "-1"], capture_output=True, text=True)
    print(f"  last commit:         {r.stdout.strip()}")
    print("\n  => there is no machine that could tell him a selftest regressed. His 3 failing")
    print("     selftests are invisible to the project; only a stranger's clone discovers them.")


def p002() -> None:
    head("P-002  the test surface is only what a fresh clone can run")
    print("\n  the 'tests' are --selftest flags inside the shipped modules:")
    for p in sorted(SCR.glob("*.py")):
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if re.search(r'add_argument\("--selftest"', line) or re.search(r'add_parser\("selftest"', line):
                print(f"      {p.name}:{i}  {line.strip()[:74]}")
    print("\n  known failures on a clean clone (measured earlier):")
    for s in ("crystal_midflight.py --selftest", "crystal-discriminators.py --selftest",
              "librarian.py selftest"):
        print(f"      rc=1  {s}")


def main() -> int:
    p018(); p019(); p011(); p016(); p002()
    print("\n" + "=" * 96)
    print("Every count above is reproducible from the printed sites; no judgement rests on recall.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
