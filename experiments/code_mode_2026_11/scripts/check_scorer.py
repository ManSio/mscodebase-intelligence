"""Standalone check of the scorer (no server, no re-run). Run before the experiment."""
from __future__ import annotations

import types
from pathlib import Path

P = Path(__file__).resolve().parent / "run_experiment.py"
src = P.read_text(encoding="utf-8").replace(
    'if __name__ == "__main__":\n    raise SystemExit(main())', ""
)
mod = types.ModuleType("exp")
mod.__file__ = str(P)
exec(compile(src, str(P), "exec"), mod.__dict__)
hit, REPO = mod.hit, mod.REPO

g = "src/core/rate_limiter.py"
cases = [
    ("absolute", f"{REPO}\\src\\core\\rate_limiter.py", True),
    ("bare", g, True),
    ("plain", f"Definition: {g} line 3", True),
    ("trailing_colon", f"{g}:180", True),
    ("other_dir", f"tests/{g}", False),
    ("bak", f"{g}.bak", False),
    ("pyc", f"{g}c", False),
    ("basename", "rate_limiter.py", False),
    ("prefixed_word", "mysrc/core/rate_limiter.py", False),
]
failures = [(n, exp, hit(t, g)) for n, t, exp in cases if hit(t, g) is not exp]
print(f"cases={len(cases)} failures={failures}")
raise SystemExit(1 if failures else 0)
