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
    unique = {}
    for row in rows:
        unique.setdefault(row["id"], row)
    if len(unique) != len(rows):
        print(f"capture {path.name}: {len(rows) - len(unique)} duplicate rows ignored",
              flush=True)
        rows = list(unique.values())
    print(f"resuming: {len(rows)} tasks already captured", flush=True)
    return rows, {row["id"] for row in rows}


def check_capture_before_run(
    rows: list[dict], done: set[str], panel_ids: list[str], allow_replay: bool = False
) -> tuple[int, int, str | None]:
    """Refuse a capture that cannot describe this panel.

    Returns `(executed, resumed, refusal)`. The caller prints the counters: a
    score is only trustworthy next to the number of tasks this run executed.
    """
    panel = set(panel_ids)
    executed = len(panel - done)
    resumed = len(rows)
    foreign = sorted({row["id"] for row in rows} - panel)
    if foreign:
        return executed, resumed, f"{len(foreign)} capture rows are not in this panel: {foreign[:3]}"
    if executed == 0 and panel and not allow_replay:
        return executed, resumed, "0 tasks executed: this is a replay, pass --allow-replay to score it"
    return executed, resumed, None


def check_denominator_after_run(rows: list[dict], panel_ids: list[str]) -> str | None:
    """Refuse to write a score whose denominator is not the panel."""
    missing = sorted(set(panel_ids) - {row["id"] for row in rows})
    if missing:
        return f"{len(missing)} panel tasks have no row: {missing[:3]}"
    return None
