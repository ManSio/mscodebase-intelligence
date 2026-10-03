"""Contract of the gates.py CLI: a superset of kwargs must reach a verdict.

Reported defect (2026-10-03): the `gate` tool returned `GATE UNAVAILABLE (rc=2)`
for every input. Root cause: `run()` called `fn(**kw)` without selecting the
gate's own parameters, so the superset that one-tool-four-gates makes the caller
send naturally raised TypeError, which the top-level handler reported as an
unavailable gate instead of a verdict.

These tests pin the fixed behaviour AND its failure mode: a key the caller
meant for this gate but misspelled must NOT become a silent pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "tools" / "verification" / "gates.py"

sys.path.insert(0, str(ROOT))
from tools.verification.gates import ALLOW, BLOCK, UNKNOWN, run  # noqa: E402


def _cli(gate: str, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(GATES), "--gate", gate, "--input", json.dumps(payload)],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )


def test_superset_kwargs_reach_a_verdict_instead_of_a_traceback():
    proc = _cli("population", {"population": 40, "computed_rate": 0.075,
                               "claim": "belongs to another gate",
                               "verdict": "CONFIRMED"})
    assert "Traceback" not in proc.stderr
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["verdict"] == ALLOW
    assert out["ignored_kwargs"] == ["claim", "verdict"]


def test_dropped_kwargs_are_named_not_silently_swallowed():
    res, rc = run("population", population=1143, computed_rate=0.0, evidence="x")
    assert res["verdict"] == ALLOW and rc == 0
    assert res["ignored_kwargs"] == ["evidence"]


def test_misspelled_key_does_not_become_a_silent_pass():
    """The dangerous half of filtering: swallow a typo and return ALLOW."""
    res, rc = run("population", populaton=40, computed_rate=0.075)
    assert res["verdict"] == UNKNOWN and rc == 2
    assert "populaton" in res["ignored_kwargs"]
    # the typo is caught as a MISSING required kwarg, which is louder than the
    # gate's own "not supplied" path and names what the caller must supply
    assert "population" in res["required_kwargs"]
    assert "unusable input" in res["why"]


def test_exact_kwargs_carry_no_ignored_field():
    res, _ = run("population", population=0, computed_rate=0.0, label="vacuous scan")
    assert res["verdict"] == BLOCK
    assert "ignored_kwargs" not in res


def test_missing_required_kwarg_is_reported_not_raised():
    res, rc = run("population", population=40)  # computed_rate absent
    assert res["verdict"] == UNKNOWN and rc == 2
    assert "computed_rate" in res["required_kwargs"]
    assert "unusable input" in res["why"]


@pytest.mark.parametrize("gate,payload", [
    ("population", {"population": 40, "computed_rate": 0.075}),
    ("referent", {"claim": "valid 10/11 per EXPERIMENTS_LOG.md:537"}),
    ("generalization", {"verdict": "CONFIRMED", "evidence": "one article only"}),
    ("control", {"experiment": "e", "negative_control_shown_failing": True}),
])
def test_every_gate_is_reachable_through_the_cli(gate, payload):
    proc = _cli(gate, payload)
    assert "Traceback" not in proc.stderr
    out = json.loads(proc.stdout)
    assert out["verdict"] in {ALLOW, BLOCK, UNKNOWN}
    assert proc.returncode == {"ALLOW": 0, "BLOCK": 1, UNKNOWN: 2}[out["verdict"]]


def test_selftest_still_passes():
    proc = subprocess.run([sys.executable, "-B", str(GATES), "--selftest"],
                          capture_output=True, text=True, cwd=ROOT, timeout=180)
    assert proc.returncode == 0, proc.stdout[-2000:]
    assert "SELFTEST PASSED" in proc.stdout