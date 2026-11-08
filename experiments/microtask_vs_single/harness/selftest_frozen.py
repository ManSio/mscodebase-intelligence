"""Prove the frozen corpus can fail and can pass.

Negative control: the planted defects must fail hidden tests.
Positive control: a known-good patch must pass the same hidden tests.
Both runs use the real pytest parser, not a hand-built assertion.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXPERIMENT = Path(__file__).resolve().parents[1]
REPO = EXPERIMENT / "frozen" / "repo"
HIDDEN = EXPERIMENT / "frozen" / "hidden"

GOOD_CORE = """\
from decimal import Decimal, ROUND_HALF_UP


def mean(values):
    if not values:
        raise ValueError("mean of empty input")
    return sum(values) / len(values)


def round_money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
"""

GOOD_FORMATTING = """\
from decimal import Decimal

from .core import round_money


def format_total(items):
    total = sum(round_money(Decimal(str(price)) * qty) for price, qty in items)
    return f"${total:.2f}"
"""


def run_pytest(repo: Path, tests: list[Path]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo)
    env["TARGET_REPO"] = str(repo)
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *map(str, tests), "-q"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def main() -> int:
    negative = run_pytest(REPO, sorted(HIDDEN.glob("test_*.py")))
    if negative.returncode == 0:
        print("SELFTEST FAIL: negative control passed; hidden tests cannot detect the planted defects")
        return 1
    print(f"NEGATIVE: planted defects fail hidden tests (exit={negative.returncode})")

    with tempfile.TemporaryDirectory(prefix="microtask-positive-") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(REPO, work)
        (work / "tinycalc" / "core.py").write_text(GOOD_CORE, encoding="utf-8")
        (work / "tinycalc" / "formatting.py").write_text(GOOD_FORMATTING, encoding="utf-8")
        positive = run_pytest(
            work,
            [*sorted(HIDDEN.glob("test_*.py")), work / "tests" / "test_public.py"],
        )
        if positive.returncode != 0:
            print("SELFTEST FAIL: known-good patch does not pass hidden tests")
            print(positive.stdout[-3000:])
            print(positive.stderr[-1000:])
            return 1

    print("POSITIVE: known-good patch passes hidden tests")
    print("SELFTEST: PASS (negative fails, positive passes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

