"""Tests for the protocol guard. The guard is only worth having if it can fail,
so the negative controls come first (P-019: a rule needs an executable check).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "audit_protocol_guards.py"

spec = importlib.util.spec_from_file_location("audit_protocol_guards", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_selftest_passes():
    """The guard's own negative control must be green."""
    p = subprocess.run([sys.executable, str(SCRIPT), "--selftest"],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "SELFTEST PASSED" in p.stdout


def test_falsifier_and_expected_fail_are_independent():
    """Regression: an earlier version matched 'Ожидаем ПРОВАЛ' as a falsifier,
    so a manifest with no falsifier passed. The selftest proved that branch blind."""
    assert not mod.FALSIFIER.search("Ожидаем ПРОВАЛ: гипотеза B")
    assert mod.EXPECTED_FAIL.search("Ожидаем ПРОВАЛ: гипотеза B")
    assert mod.FALSIFIER.search("Фальсификатор: X не воспроизведётся")


def test_max_len_is_not_a_population_guard():
    """max(x, 1) stops a ZeroDivisionError but still prints 0% and exits 0.
    That is the exact silent-zero failure T10 forbids, so it must NOT count as a guard."""
    src = "share = len([i for i in items if i]) / max(len(items), 1) * 100\n"
    assert mod.SILENT_ZERO.search(src)
    assert not mod.POP_GUARD.search(src)
    assert mod.RATE.search(src + "print('доля: 0.0%')\n")


def test_real_refusal_counts_as_a_guard():
    src = ("def rate(items):\n"
           "    if not items:\n"
           "        sys.exit(2)\n"
           "    return len(items) * 100\n"
           "print('доля')\n")
    assert mod.POP_GUARD.search(src)
    assert not mod.SILENT_ZERO.search(src)


def test_a_guarded_file_is_no_longer_flagged():
    """Regression: exp_vacuous_scan.py was fixed (2026-09-30) by adding a real refusal
    (sys.exit(2) on an empty population) while `max(total, 1)` stayed behind as dead
    defensive code. The guard must stop flagging it -- otherwise it trains us to ignore
    it. If the refusal is ever removed, the file is flagged again (see the next test)."""
    offenders = set(mod.check_t10()[1])
    assert "experiments/misc_probes/exp_vacuous_scan.py" not in offenders


def test_removing_the_refusal_makes_it_flagged_again(tmp_path, monkeypatch):
    """The guard must still catch the regression it was written for."""
    src = ("x = len([i for i in items]) / max(len(items), 1) * 100\n"
           "print('доля')\n")
    assert mod.RATE.search(src)
    assert not mod.POP_GUARD.search(src)      # no refusal -> this is the finding


def test_guard_does_not_audit_itself():
    assert SCRIPT.resolve() not in {p.resolve() for p in mod.iter_sources()}


def test_known_finding_was_fixed_not_merely_hidden():
    """2026-09-30 (T-04): exp_vacuous_scan.py pointed at a nonexistent directory and printed
    '0 proven / 0 vacuous, доля 0.0%' with rc=0. It was FIXED (real refusal + repo-root path).
    This test exists so the fix cannot be silently reverted AND so nobody can 'fix' the finding
    by deleting the report instead of the defect -- the count and the guard must both be real."""
    src = (REPO / "experiments/misc_probes/exp_vacuous_scan.py").read_text(encoding="utf-8")
    assert 'parents[2]' in src, "path must resolve from the repo root, not from experiments/"
    assert mod.POP_GUARD.search(src), "must REFUSE on an empty population, not print 0%"
    assert "total == 0" in src, "the empty-result refusal must be explicit"


def test_own_frozen_hypotheses_manifest_satisfies_the_new_rule():
    """Our own manifest must pass our own rule, else the rule is decoration."""
    n, problems = mod.check_191()
    assert n >= 1
    assert problems == []


@pytest.mark.parametrize("path", [
    "experiments/4A_unit_of_return/frozen/f4b/manifest.json",
])
def test_frozen_manifest_files_exist(path):
    assert (REPO / path).exists()
