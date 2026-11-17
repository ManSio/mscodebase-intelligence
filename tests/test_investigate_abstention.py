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
from src.mcp.tools.investigate_tool import (
    _abstains,
    _exact_note,
    _literal_abstain_reason,
    _should_abstain,
)

# ── profiles ────────────────────────────────────────────────────────────────

def test_profiles_are_two_and_intent_driven():
    """`exploratory` was measured and removed (top10 0.750 vs 0.875, rank1 0.344
    vs 0.656); a dead profile that is strictly worse must not be selectable."""
    from src.mcp.tools.investigate_tool import _PROFILES

    assert set(_PROFILES) == {"def_first", "references"}
    assert _PROFILES["def_first"]["definition"] > _PROFILES["def_first"]["search"]
    assert _PROFILES["def_first"]["symbol"] > _PROFILES["def_first"]["search"]
    assert _PROFILES["references"]["grep"] > _PROFILES["references"]["search"]


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

# ── scope=code отбросил литералы: это не «имени нет» ──────────────────────

def test_literal_only_hit_does_not_abstain():
    """infrawise 2026-11-17: implemented_by = 0 в scope=code, 9 в scope=all."""
    assert not _should_abstain(
        {"implemented_by": 0}, {"implemented_by": 9}, known=False, include_neighbours=False
    )


def test_no_filtered_hits_keeps_the_old_rule():
    assert _should_abstain({"ghost": 0}, {}, known=False, include_neighbours=False)
    assert _should_abstain({"ghost": 0}, {"ghost": 0}, known=False, include_neighbours=False)


def test_note_names_scope_as_the_reason():
    note = _exact_note({"implemented_by": 0}, {"implemented_by": 9}, 0)
    assert 'scope="all"' in note
    assert "does not occur" not in note
    assert "9 occurrence" in note


def test_note_keeps_the_neighbour_wording_when_nothing_was_filtered():
    note = _exact_note({"ghost": 0}, {}, 3)
    assert "no identifier occurs in the indexed code" in note
    assert 'scope="all"' not in note


def test_note_is_silent_without_counts():
    assert _exact_note({}, {}, 0) == ""


def test_abstain_reason_names_the_literals():
    """«no verified candidate» при совпадениях только в литералах читается как «нет имени»."""
    reason = _literal_abstain_reason({"implemented_by": 9})
    assert "9 occurrence(s) only inside comments/strings" in reason
    assert 'scope="all"' in reason


def test_abstain_reason_is_empty_without_filtered_hits():
    assert _literal_abstain_reason({}) == ""
    assert _literal_abstain_reason({"x": 0}) == ""


def test_foreign_literals_do_not_suppress_abstention():
    """Литералы ЧУЖОГО идентификатора — не доказательство по субъекту."""
    assert _should_abstain(
        {"ghost": 0}, {"other_name": 5}, known=False, include_neighbours=False
    )


def test_own_literals_suppress_abstention():
    assert not _should_abstain(
        {"implemented_by": 0}, {"implemented_by": 9}, known=False, include_neighbours=False
    )


def test_reason_counts_only_the_subject():
    assert _literal_abstain_reason({"ghost": 0, "other": 5}, "ghost") == ""
    assert "3 occurrence" in _literal_abstain_reason({"ghost": 3, "other": 5}, "ghost")
