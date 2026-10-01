"""Held-out negative controls for the two T10 fixes.

Per §19.3 a guard must be able to FAIL. Per T10 a rate tool must refuse an
empty population rather than print 0% with rc=0. These tests inject the empty
population and assert the refusal, and also assert the POSITIVE case still
works — because a check that always fails is worthless (§19.3: the control has
to be able to fail AND the instrument has to work).
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  [{'OK ' if cond else 'XX '}] {name}" + (f"  {detail}" if detail else ""))


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


print("=" * 92)
print("T10 HELD-OUT — empty-population refusal for the two fixed rate tools")
print("=" * 92)

# ---------------------------------------------------------------- compose_eval
print("\ncompose_eval.wrong_ratio")
ce = load(REPO / "experiments/context_engine/compose_eval.py", "_compose_eval_t10")
try:
    ce.wrong_ratio([])
    check("empty list raises rather than returning 0.0", False, "returned a value")
except ValueError as e:
    check("empty list raises ValueError", "undefined" in str(e), f"msg={str(e)[:70]}")
except Exception as e:  # noqa: BLE001
    check("empty list raises ValueError", False, f"raised {type(e).__name__}")

try:
    ce.wrong_ratio([("", ["f"])])
    check("all-zero-token section raises", False, "returned a value")
except ValueError:
    check("all-zero-token section raises", True)

val = ce.wrong_ratio([("a b c d", ["zzz"]), ("e f", ["yy"])])
check("non-empty population still computes", 0.0 < val <= 1.0, f"value={val:.3f}")
results.append(0.0 < val <= 1.0)
print(f"        positive control: wrong_ratio over 2 sections = {val:.3f}")

# ---------------------------------------------------------------- e2e_quality_search
print("\ne2e_quality_search.report")
eq = load(REPO / "scripts/e2e_quality_search.py", "_e2e_quality_t10")
try:
    eq.report("mode=test", [])
    check("empty rows exits 2 instead of printing 0%", False, "returned normally")
except SystemExit as e:
    check("empty rows exits 2", e.code == 2, f"code={e.code}")
except Exception as e:  # noqa: BLE001
    check("empty rows exits 2", False, f"raised {type(e).__name__}: {e}")

try:
    r = eq.report("mode=test", [])
    check("empty rows exits 2", False, "returned normally")
except SystemExit as e:
    check("empty rows exits 2 (second run)", e.code == 2)

# positive control: non-empty rows must still report
rows = [("q1", "exp1", 10.0, "a", "b", "a"), ("q2", "exp2", 20.0, "c", "d", "c")]
try:
    h1, h5, avg = eq.report("mode=pos", rows)
    ok = h1 == 2 and h5 == 2 and avg > 0
    check("non-empty rows still report hit rates", ok, f"h1={h1} h5={h5} avg={avg:.1f}")
except SystemExit as e:
    check("non-empty rows still report hit rates", False, f"unexpected exit {e.code}")

print("\n" + "=" * 92)
bad = results.count(False)
if bad:
    print(f"T10 HELD-OUT FAILED: {bad} of {len(results)}")
    sys.exit(1)
print(f"T10 HELD-OUT PASSED — {len(results)}/{len(results)}: empty refused, non-empty still computes")

# and confirm the real CLI still starts (import-time sanity, no network)
p = subprocess.run([sys.executable, str(REPO / "scripts/e2e_quality_search.py"), "--help"],
                   capture_output=True, text=True, timeout=60)
check("--help works (import-time sanity)", p.returncode == 0, f"rc={p.returncode}")
