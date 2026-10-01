import json
import subprocess
import sys

CASES = [
    ("population", {"population": 0, "computed_rate": 0.0}, 1),
    ("population", {"population": 100, "computed_rate": 0.5}, 0),
    ("referent", {"claim": "valid 10/11, controls 6/6"}, 1),
    ("referent", {"claim": "valid 10/11 per `EXP-1`"}, 0),
    ("control", {"experiment": "e", "negative_control_shown_failing": False,
                 "controls_required": 2}, 1),
    ("generalization", {"verdict": "CONFIRMED", "evidence": "held-out disjoint"}, 0),
]
bad = 0
for gate, payload, want in CASES:
    p = subprocess.run(
        [sys.executable, "-B", "tools/verification/gates.py", "--gate", gate,
         "--input", json.dumps(payload)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        got = json.loads(p.stdout)["verdict"]
    except (ValueError, KeyError, TypeError) as e:
        got = f"UNPARSEABLE ({type(e).__name__}): " + (p.stdout or p.stderr)[:60]
    ok = p.returncode == want
    if not ok:
        bad += 1
    print("[%s] %-14s rc=%s (want %s) verdict=%s  %s"
          % ("OK " if ok else "XX ", gate, p.returncode, want, got, payload))
print("\n%s" % ("every documented invocation works" if not bad else f"{bad} MISMATCH"))
sys.exit(1 if bad else 0)
