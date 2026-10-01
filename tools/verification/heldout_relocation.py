"""Held-out: the verification suite must be REPRODUCIBLE from a fresh location.

The move into the repo could have passed locally and failed anywhere else. These
checks assert the properties that make a committed guard meaningful:

  1. every path is derived from __file__, never from an absolute machine path
  2. the suite actually runs from a directory that is NOT the repo root
  3. a deliberately wrong PROJECTS_ROOT produces exit 2, not a smaller number
  4. no file contains the developer's absolute paths

(3) is the important one: it is the negative control for the whole relocation. If
a missing dependency silently yields a smaller population, the gate becomes a
quiet liar again — the exact failure class this suite exists to prevent.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PY = sys.executable
results = []

print("=" * 92)
print("RELOCATION HELD-OUT — the suite must work outside its author's machine")
print("=" * 92)

# --- 1. no absolute machine paths ----------------------------------------------
print("\n-- 1. no developer-specific absolute paths in any gate")
LEAK = re.compile(r"[A-Za-z]:\\Users\\|[A-Za-z]:\\\\Users\\\\")
files = sorted(p for p in HERE.glob("*.py"))
for p in files:
    txt = p.read_text(encoding="utf-8", errors="replace")
    hits = LEAK.findall(txt)
    ok = not hits
    results.append(ok)
    print(f"  [{'OK ' if ok else 'XX '}] {p.name:34} {len(txt):>6} chars")
    if not ok:
        for h in hits[:3]:
            print(f"        LEAK: {h}")

# --- 2. run from an unrelated cwd ----------------------------------------------
# NOTE: this must NOT invoke run_all.py — run_all invokes THIS file, so calling it
# here recurses until the 600s timeout. Portability is proven by running the GATES
# themselves from elsewhere, which is what actually depends on __file__.
print("\n-- 2. the gates run from a directory that is not the repo root")
GATES = [("gates.py", ["--selftest"]),
         ("g5_denominator.py", []),
         ("heldout_rt6_reasons.py", []),
         ("heldout_g2_publishable.py", [])]
with tempfile.TemporaryDirectory() as td:
    for script, extra in GATES:
        p = subprocess.run([PY, "-B", str(HERE / script), *extra], cwd=td,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
        ok = p.returncode == 0
        results.append(ok)
        print(f"  [{'OK ' if ok else 'XX '}] {script:28} from temp cwd -> rc={p.returncode}")
        if not ok:
            print(f"        {(p.stderr or p.stdout or '').strip().splitlines()[-1][:100]}")

# --- 3. NEGATIVE CONTROL: wrong PROJECTS_ROOT must be exit 2, not a number -------
print("\n-- 3. negative control: a wrong MSCB_PROJECTS_ROOT yields exit 2")
import os  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    env = dict(os.environ, MSCB_PROJECTS_ROOT=td)
    p = subprocess.run([PY, str(HERE / "g5_denominator.py")], env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
ok = p.returncode == 2
results.append(ok)
out = (p.stdout or "") + (p.stderr or "")
reported_number = bool(re.search(r"coverage\s+\d", out))
ok = ok and not reported_number
results.append(ok - 1 if False else ok)
print(f"  [{'OK ' if ok else 'XX '}] rc={p.returncode} (want 2); reported a coverage number: {reported_number}")
for line in out.strip().splitlines()[-3:]:
    print(f"        {line[:88]}")

# --- 4. and with the CORRECT root it still reports a number --------------------
print("\n-- 4. control: the real root still produces a number (not stuck refusing)")
p = subprocess.run([PY, str(HERE / "g5_denominator.py")], capture_output=True,
                   text=True, encoding="utf-8", errors="replace", timeout=300)
out = p.stdout or ""
# the summary row is the ALL line; assert it carries an integer candidate count
m = re.search(r"^ALL\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)", out, re.MULTILINE)
ok = p.returncode == 0 and m is not None and int(m.group(1)) > 0
results.append(ok)
print(f"  [{'OK ' if ok else 'XX '}] rc={p.returncode}, ALL row: "
      f"{m.group(0)[:60] if m else 'ABSENT'}")
if p.returncode != 0:
    print("        stderr:", (p.stderr or "")[:120])

print("\n" + "=" * 92)
bad = results.count(False)
if bad:
    print(f"RELOCATION HELD-OUT FAILED: {bad} of {len(results)}")
    sys.exit(1)
print(f"RELOCATION HELD-OUT PASSED — {len(results)}/{len(results)}: portable, and still refuses honestly")
