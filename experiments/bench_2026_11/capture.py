"""Capture cache for the commit-localization benchmark.

`run.py` writes one JSON row per finished task to `results_<split>.partial.jsonl`
so a run that dies at task 16 does not start over. That convenience produced a
bug worth more than the feature: the capture was committed to git, every later
run resumed from it, and the benchmark reprinted November's numbers for four
days after the gate under test had changed (E74).

Rule enforced here: **reuse requires an explicit `--resume`**. Without it the
stale capture is dropped and the panel is executed from scratch, because an
appended run on top of old rows would silently mix two products.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_capture(path: Path, resume: bool) -> tuple[list[dict], set[str]]:
    """Return (rows, ids) from a previous capture, or nothing.

    `resume=False` also deletes the stale file: `run.py` appends to it, so
    keeping it would mix the new run with the old one.
    """
    path = Path(path)
    if not path.is_file():
        return [], set()
    if not resume:
        print(
            f"stale capture {path.name} ignored and dropped: "
            "pass --resume to reuse it, otherwise the panel runs from scratch",
            flush=True,
        )
        path.unlink(missing_ok=True)
        return [], set()

    rows: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(
                f"capture {path.name} is corrupt at line {number} ({exc.msg}): "
                "dropping it and running the panel from scratch",
                flush=True,
            )
            path.unlink(missing_ok=True)
            return [], set()
    print(f"resuming: {len(rows)} tasks already captured", flush=True)
    return rows, {row["id"] for row in rows}
