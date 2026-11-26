"""A score must describe the panel, the product and the corpus it claims (E74 follow-up).

Three holes, in the order they were found:

1. `run.py` printed a table after executing zero tasks (`resuming:` was only a
   line of text).
2. A capture row that was not in the panel raised the denominator (`_stats`
   divides by `len(rows)`, and `rows` came from the file).
3. Found by red-teaming guard 1: a capture with *some* rows from an older
   product passed the counter (`executed=2 resumed=1 of 3`) and mixed two
   products in one table. Rows now carry `rev` and `corpus_head`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "experiments" / "bench_2026_11" / "capture.py"

REV = "r-current"
CORPUS = "c-current"


def _capture_module():
    spec = importlib.util.spec_from_file_location("bench_capture_denominator", CAPTURE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PANEL = ["a1", "b2", "c3"]


def _runtime() -> dict:
    # A complete row carries runtime provenance since the ONNX-flap guard.
    return {
        "embedder": "text_only",
        "embed_calls": 0,
        "rerank_modes": ["sqlite_fts5"],
        "dense_off": True,
        "ondemand_rerank": False,
    }


def _rows(*ids: str, rev: str = REV, corpus_head: str = CORPUS) -> list[dict]:
    return [
        {
            "id": i,
            "rev": rev,
            "corpus_head": corpus_head,
            "runtime": _runtime(),
            "tool_top5": False,
        }
        for i in ids
    ]


def _check(rows, done, panel=PANEL, **kwargs):
    return _capture_module().check_capture_before_run(
        rows, done, panel, rev=REV, corpus_head=CORPUS, **kwargs
    )


def test_zero_executed_is_refused_without_allow_replay() -> None:
    executed, resumed, refusal = _check(_rows(*PANEL), set(PANEL))
    assert (executed, resumed) == (0, 3), "the counters are what the score must be read next to"
    assert refusal is not None, "a replay must not be scored as a run"
    assert "0 tasks executed" in refusal


def test_zero_executed_is_allowed_when_asked_for_explicitly() -> None:
    assert _check(_rows(*PANEL), set(PANEL), allow_replay=True)[2] is None


def test_a_capture_row_outside_the_panel_is_refused() -> None:
    _, resumed, refusal = _check(_rows(*PANEL, "deadbeef"), set(PANEL))
    assert resumed == 4, "four rows were read; the refusal must not silently filter them"
    assert refusal is not None, "a foreign row would inflate the denominator"
    assert "not in this panel" in refusal


def test_a_partial_resume_is_a_normal_run() -> None:
    executed, resumed, refusal = _check(_rows("a1"), {"a1"})
    assert (executed, resumed, refusal) == (2, 1, None)


def test_a_row_from_another_revision_is_refused() -> None:
    rows = _rows(*PANEL, rev="r-old")
    _, _, refusal = _check(rows, set(PANEL), allow_replay=True)
    assert refusal is not None, "mixing two products in one table is the E74 bug at a smaller scale"
    assert "another revision" in refusal


def test_a_row_without_revision_is_refused() -> None:
    rows = _rows(*PANEL)
    for row in rows:
        row.pop("rev")
    _, _, refusal = _check(rows, set(PANEL), allow_replay=True)
    assert refusal is not None, "unknown provenance is not the same as current provenance"
    assert "another revision" in refusal


def test_a_row_from_another_corpus_is_refused() -> None:
    rows = _rows(*PANEL, corpus_head="c-old")
    _, _, refusal = _check(rows, set(PANEL), allow_replay=True)
    assert refusal is not None
    assert "another corpus" in refusal


def test_a_mixture_is_allowed_when_asked() -> None:
    rows = _rows(*PANEL, rev="r-old")
    executed, resumed, refusal = _check(
        rows, set(PANEL), allow_replay=True, allow_mixed=True
    )
    assert (executed, resumed, refusal) == (0, 3, None)


def test_a_missing_row_after_the_run_is_refused() -> None:
    refusal = _capture_module().check_denominator_after_run(_rows("a1", "b2"), PANEL)
    assert refusal is not None, "a panel task without a row is a silent miss"
    assert "no row" in refusal


def test_a_complete_panel_passes() -> None:
    assert _capture_module().check_denominator_after_run(_rows(*PANEL), PANEL) is None
