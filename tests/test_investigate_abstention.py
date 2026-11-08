"""Guards for the two 2026-11-08 behaviours: abstention and cooperative cancel.

Abstention (measured: 4/4 frozen negative tasks printed 8 neighbour rows):
"no exact hit for the subject" must yield "not found", not eight confident
`file:line` rows. The decision is a small truth table, so it is tested directly.

Cancellation (measured: `asyncio.wait_for(to_thread(...))` leaves the thread
running, and the abandoned parser competes with the next query): the search loop
checks a `threading.Event` between files.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from src.core.di_container import ServiceCollection
from src.mcp.tools.grep_tool import GrepCodeTool
from src.mcp.tools.investigate_tool import _abstains

# ── abstention truth table ──────────────────────────────────────────────────

def test_abstains_when_subject_is_absent_and_unknown():
    assert _abstains({"ghost": 0}, known=False, include_neighbours=False)


def test_known_symbol_keeps_its_neighbours():
    assert not _abstains({"widget": 0}, known=True, include_neighbours=False)


def test_exact_hits_never_abstain():
    assert not _abstains({"widget": 3}, known=False, include_neighbours=False)


def test_degraded_channel_is_unknown_not_absent():
    """`per` is empty when grep did not run: silence must not become 'absent'."""
    assert not _abstains({}, known=False, include_neighbours=False)


def test_explicit_flag_overrides_abstention():
    assert not _abstains({"ghost": 0}, known=False, include_neighbours=True)


# ── cooperative cancellation ────────────────────────────────────────────────

def _project(tmp_path: Path, files: int = 300) -> Path:
    for i in range(files):
        (tmp_path / f"m{i:03d}.py").write_text(
            f"value_{i} = {i}\nresult = needle + {i}\n", encoding="utf-8"
        )
    return tmp_path


def _run(project: Path, cancel=None) -> dict:
    tool = GrepCodeTool(ServiceCollection())
    regex = __import__("re").compile(b"needle")
    return tool._search(project, None, regex, "all", 10, 0, cancel=cancel)


def test_cancel_before_the_scan_returns_immediately(tmp_path: Path):
    project = _project(tmp_path)
    cancel = threading.Event()
    cancel.set()
    started = time.perf_counter()
    result = _run(project, cancel)
    elapsed = time.perf_counter() - started
    assert result["cancelled"] is True
    assert result["scanned"] == 0
    assert elapsed < 0.5, f"cancel did not stop the scan: {elapsed:.2f}s"


def test_without_cancel_the_whole_tree_is_scanned(tmp_path: Path):
    project = _project(tmp_path)
    result = _run(project)
    assert result["cancelled"] is False
    assert result["scanned"] == 300
    assert result["total"] == 300


def test_cancel_during_the_scan_stops_early(tmp_path: Path):
    project = _project(tmp_path, files=2000)
    cancel = threading.Event()

    def stop_soon():
        time.sleep(0.02)
        cancel.set()

    thread = threading.Thread(target=stop_soon)
    thread.start()
    result = _run(project, cancel)
    thread.join()
    assert result["cancelled"] is True
    assert result["scanned"] < 2000
