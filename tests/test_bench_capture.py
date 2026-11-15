"""The benchmark capture must not replay itself (E74).

`run.py` appends finished tasks to `results_<split>.partial.jsonl`. When that
file was committed to git, every later run reprinted the old numbers without
executing a single task. Reuse is now opt-in.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "experiments" / "bench_2026_11" / "capture.py"


def _capture_module():
    spec = importlib.util.spec_from_file_location("bench_capture", CAPTURE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_capture(path: Path, ids: list[str]) -> None:
    path.write_text(
        "".join(json.dumps({"id": i, "tool_top5": False}) + "\n" for i in ids),
        encoding="utf-8",
    )


def test_missing_capture_is_empty(tmp_path: Path) -> None:
    rows, done = _capture_module().load_capture(tmp_path / "nope.jsonl", resume=True)
    assert rows == []
    assert done == set()


def test_resume_reuses_rows_and_keeps_the_file(tmp_path: Path) -> None:
    path = tmp_path / "results_dev.partial.jsonl"
    _write_capture(path, ["a1", "b2"])

    rows, done = _capture_module().load_capture(path, resume=True)

    assert [row["id"] for row in rows] == ["a1", "b2"]
    assert done == {"a1", "b2"}
    assert path.is_file(), "resume must not destroy the capture it just read"


def test_without_resume_the_stale_capture_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "results_dev.partial.jsonl"
    _write_capture(path, ["a1", "b2"])

    rows, done = _capture_module().load_capture(path, resume=False)

    assert rows == [], "a default run must not reuse captured rows"
    assert done == set()
    assert not path.exists(), "the stale capture must be dropped, not appended to"


def test_corrupt_capture_is_dropped_not_fatal(tmp_path: Path) -> None:
    """A run killed mid-write leaves a half line; that is what resume is for."""
    path = tmp_path / "results_dev.partial.jsonl"
    path.write_text('{"id": "a1", "tool_top5": false}\n{"id": "b2", "tool_top5": tru',
                    encoding="utf-8")

    rows, done = _capture_module().load_capture(path, resume=True)

    assert rows == [], "a half-written capture must not be half-used"
    assert done == set()
    assert not path.exists(), "the corrupt capture must be dropped, not retried forever"


def test_duplicate_rows_are_counted_once(tmp_path: Path) -> None:
    """Appending runs to the same file must not double the denominator."""
    path = tmp_path / "results_dev.partial.jsonl"
    _write_capture(path, ["a1", "a1", "b2"])

    rows, done = _capture_module().load_capture(path, resume=True)

    assert [row["id"] for row in rows] == ["a1", "b2"]
    assert done == {"a1", "b2"}
