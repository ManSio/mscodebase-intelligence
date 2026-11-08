"""CLI wrapper for tools/verification/gates.py — pre-commit integration.

Exposes the four verification gates (G1 population, G2 referent,
G3 generalization, G4 control) through the same --gate/--input interface
as gates.py, plus env-var configuration for hook use.

Exit codes (passthrough from gates.run):
  0 — ALLOW / OUT_OF_SCOPE  (gate did not block; commit proceeds)
  1 — BLOCK                 (gate found a violation; commit is blocked)
  2 — UNKNOWN               (not enough input to judge; advisory only,
                            does NOT block — per §19.6 a silent zero is worse
                            than a crash, but rc=2 is not a violation)

Environment variables (alternatives to CLI flags):
  GATE_ACTION   gate name: population | referent | generalization | control
  GATE_INPUT    JSON object of kwargs for the gate
  GATE_SELFTEST "1" → run --selftest instead of a single gate

Usage (pre-commit):
    python scripts/gate_cli.py               # selftest only (rc 0/1)
    GATE_ACTION=referent GATE_INPUT='{"claim":"..."}' python scripts/gate_cli.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.verification.gates import main as gates_main  # noqa: E402


def _build_argv() -> list[str]:
    """Map env vars / flags to gates.py argv (script path + flags only).

    sys.executable and -B are NOT included — gates.py's argparse does not
    know about them.
    """
    script = str(ROOT / "tools" / "verification" / "gates.py")
    argv = [script]

    action = os.environ.get("GATE_ACTION", "")
    gate_in = os.environ.get("GATE_INPUT", "")
    selftest = os.environ.get("GATE_SELFTEST", "")

    # CLI flags override env vars.
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--selftest":
            selftest = "1"
        elif a == "--gate" and i + 1 < len(args):
            action = args[i + 1]
            i += 1
        elif a == "--input" and i + 1 < len(args):
            gate_in = args[i + 1]
            i += 1
        i += 1

    if selftest == "1":
        argv.append("--selftest")
    elif action:
        argv.extend(["--gate", action])
        if gate_in:
            argv.extend(["--input", gate_in])
    else:
        # Default: selftest — proves the gates can block for their own reasons.
        argv.append("--selftest")

    return argv


def main() -> int:
    argv = _build_argv()
    # Replace sys.argv so gates.py's argparse sees its own flags.
    old_argv = sys.argv
    sys.argv = argv
    try:
        return gates_main()
    except SystemExit as e:
        return int(e.code or 0)
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())
