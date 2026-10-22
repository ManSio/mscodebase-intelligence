"""Contract of scripts/gate_cli.py — pre-commit wrapper over tools/verification/gates.py.

Exit codes are passed through from gates.run:
  0 — ALLOW / OUT_OF_SCOPE (commit proceeds)
  1 — BLOCK (commit is blocked)
  2 — UNKNOWN (advisory warning, never blocks per §19.6)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_CLI = ROOT / "scripts" / "gate_cli.py"
GATES = ROOT / "tools" / "verification" / "gates.py"


def _run_cli(extra_env: dict[str, str] | None = None,
             extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("GATE_ACTION", None)
    env.pop("GATE_INPUT", None)
    env.pop("GATE_SELFTEST", None)
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, "-B", str(GATE_CLI), *(extra_args or [])]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT,
                          env=env, timeout=180)


def test_selftest_passes_rc0():
    """Default behaviour (no env) runs selftest and must pass rc=0."""
    proc = _run_cli()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SELFTEST PASSED" in proc.stdout


def test_env_gate_action_referent_allow_rc0():
    """A valid claim with referent → ALLOW → rc=0."""
    proc = _run_cli(extra_env={
        "GATE_ACTION": "referent",
        "GATE_INPUT": json.dumps({"claim": "valid 10/11 per `EXPERIMENTS_LOG.md:537`"}),
    })
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["verdict"] == "ALLOW"


def test_env_gate_action_population_block_rc1():
    """Empty population → BLOCK → rc=1 (commit blocked)."""
    proc = _run_cli(extra_env={
        "GATE_ACTION": "population",
        "GATE_INPUT": json.dumps({"population": 0, "computed_rate": 0.0,
                                  "label": "vacuous scan"}),
    })
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["verdict"] == "BLOCK"


def test_env_gate_action_missing_input_unknown_rc2():
    """Missing required kwargs → UNKNOWN → rc=2 (advisory, never blocks)."""
    proc = _run_cli(extra_env={
        "GATE_ACTION": "population",
        "GATE_INPUT": json.dumps({"population": 40}),  # computed_rate absent
    })
    assert proc.returncode == 2, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["verdict"] == "UNKNOWN"


def test_cli_flags_override_env():
    """--gate/--input flags override GATE_ACTION/GATE_INPUT env vars."""
    proc = _run_cli(extra_env={
        "GATE_ACTION": "population",
        "GATE_INPUT": json.dumps({"population": 0, "computed_rate": 0.0}),
    }, extra_args=["--gate", "referent",
                   "--input", json.dumps({"claim": "x per `file.py:1`"})])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["gate"] == "G2"
    assert out["verdict"] == "ALLOW"


def test_bad_json_input_rc2():
    """Malformed JSON input → UNKNOWN rc=2, not a traceback."""
    proc = _run_cli(extra_env={
        "GATE_ACTION": "referent",
        "GATE_INPUT": "{not json",
    })
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr


def test_unknown_gate_rc2():
    """Unknown gate name → argparse rejects it with rc=2 (no crash, no JSON)."""
    proc = _run_cli(extra_env={
        "GATE_ACTION": "nonexistent_gate",
    })
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "invalid choice" in proc.stderr
