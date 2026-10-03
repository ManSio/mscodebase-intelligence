"""A14: falsifiability of the verify_clean_state drift-gate — POSIX port.

`exp_verify_gate.sh` needs bash/WSL (unavailable here). This is a verbatim port
of the gate's own matching logic (lines 31-38), not a paraphrase:
    grep -iE "^\"?${pkg}==" pyproject.toml | head -1 | grep -oE '[0-9][0-9.]*'
The claim under audit is that this pattern is STRUCTURALLY unable to fire
because pins live in a TOML array, not at line start.

Part B (vacuous suite -> gate would print PASSED) is reproduced by running the
real pytest on a 0-assert suite.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

PKGS = ("lancedb", "mcp", "tree-sitter")
PIN_RE = lambda pkg: re.compile(rf'^\"?{re.escape(pkg)}==', re.IGNORECASE)
LOCK_RE = lambda pkg: re.compile(rf'^{re.escape(pkg)}==', re.IGNORECASE)
VER_RE = re.compile(r"[0-9][0-9.]*")


def gate(pyproject: pathlib.Path, lock: pathlib.Path) -> int:
    """Verbatim port of the shell loop; returns the gate's DRIFT variable."""
    drift = 0
    for pkg in PKGS:
        pinned = locked = ""
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if PIN_RE(pkg).search(line):
                m = VER_RE.search(line)
                pinned = m.group(0) if m else ""
                break
        for line in lock.read_text(encoding="utf-8").splitlines():
            if LOCK_RE(pkg).search(line):
                m = VER_RE.search(line)
                locked = m.group(0) if m else ""
                break
        if pinned and locked and pinned != locked:
            print(f"DRIFT: {pkg} pinned {pinned} in pyproject but {locked} in lock")
            drift = 1
    return drift


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        pyproject = tmp / "pyproject.toml"
        lock = tmp / "requirements-lock.txt"

        print("=== A14 Part A: lockfile drift detection ===")
        pyproject.write_text(
            '[project]\nname = "mini"\nversion = "0.1.0"\n'
            'dependencies = ["lancedb==0.12.0"]\n', encoding="utf-8")
        lock.write_text("lancedb==0.13.0\n", encoding="utf-8")
        d = gate(pyproject, lock)
        print(f"A-RESULT: real drift injected (0.12.0 vs 0.13.0) -> DRIFT={d}")
        print("  published claim: gate did NOT detect -> exit 0 (structurally blind)")

        print("\n=== A14 Part A2: the repo's REAL files ===")
        root = pathlib.Path(__file__).resolve().parents[2]
        rp, rl = root / "pyproject.toml", root / "requirements-lock.txt"
        print(f"  pyproject exists={rp.exists()}  lock exists={rl.exists()}")
        if rp.exists() and rl.exists():
            d2 = gate(rp, rl)
            print(f"A2-RESULT: DRIFT={d2}  "
                  f"(published: all three PINNED empty -> branch unreachable)")

        print("\n=== A14 Part B: vacuous suite through real pytest ===")
        tdir = tmp / "vac" / "tests"
        tdir.mkdir(parents=True)
        (tdir / "test_vacuous.py").write_text(
            'def test_always_passes():\n    pass\n\n'
            'def test_returns_none():\n    x = 1 + 1\n\n'
            'def test_docstring_only():\n    """No assert."""\n',
            encoding="utf-8")
        p = subprocess.run(
            [sys.executable, "-m", "pytest", str(tdir), "-q", "--tb=short"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = [l for l in (p.stdout or "").splitlines() if l.strip()][-3:]
        for l in tail:
            print(f"  {l}")
        print(f"B-RESULT: pytest exit={p.returncode}")
        print("  published claim: exit 0 -> gate prints CLEAN STATE VERIFICATION: PASSED"
              " for a suite with 0 asserts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
