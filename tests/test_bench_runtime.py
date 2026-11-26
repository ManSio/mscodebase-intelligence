"""Runtime provenance for the commit-localization benchmark (E74's open item).

The capture guard now refuses a mixed capture only when the differing component
was actually used. These tests pin the two sides of that rule: a text-only row
with `embed_calls=0` may differ in the daemon that was up, a row that called the
embedder may not be stitched to one that did not.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "experiments" / "bench_2026_11"
REV = "a" * 40
CORPUS = "7c2c7a3c6417"
PANEL = ["t1", "t2", "t3"]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _runtime(**overrides):
    base = {
        "embedder": "text_only",
        "embed_calls": 0,
        "rerank_modes": ["sqlite_fts5"],
        "dense_off": True,
        "ondemand_rerank": False,
    }
    base.update(overrides)
    return base


def _row(task_id: str, **overrides) -> dict:
    return {
        "id": task_id,
        "rev": REV,
        "corpus_head": CORPUS,
        "runtime": _runtime(**overrides),
    }


def _check(rows: list[dict], *, done: set[str] | None = None,
           allow_mixed: bool = False):
    capture = _load("bench_capture_runtime", BENCH / "capture.py")
    done = done if done is not None else {row["id"] for row in rows}
    return capture.check_capture_before_run(
        rows, done, PANEL, rev=REV, corpus_head=CORPUS,
        allow_mixed=allow_mixed,
    )


# ── capture guard ────────────────────────────────────────────────────────────


def test_same_runtime_is_accepted() -> None:
    executed, resumed, refusal = _check([_row("t1"), _row("t2")])
    assert (executed, resumed, refusal) == (1, 2, None)


def test_daemon_flap_without_embedder_calls_is_inert() -> None:
    rows = [
        _row("t1", embedder="llama_cpp"),
        _row("t2", embedder="onnx"),
    ]
    _, _, refusal = _check(rows)
    assert refusal is None, "a text-only row did not use the daemon, so the flap is inert"


def test_runtime_mismatch_is_refused_when_the_embedder_was_used() -> None:
    rows = [
        _row("t1", embedder="llama_cpp", embed_calls=3),
        _row("t2", embedder="onnx"),
    ]
    _, _, refusal = _check(rows)
    assert refusal is not None
    assert "runtime provenance" in refusal
    assert "differing component was used" in refusal


def test_rerank_mode_change_is_refused() -> None:
    rows = [
        _row("t1"),
        _row("t2", rerank_modes=["ondemand"]),
    ]
    _, _, refusal = _check(rows)
    assert refusal is not None
    assert "runtime provenance" in refusal


def test_missing_runtime_stamp_is_refused() -> None:
    rows = [
        _row("t1"),
        {"id": "t2", "rev": REV, "corpus_head": CORPUS},
    ]
    _, _, refusal = _check(rows)
    assert refusal is not None
    assert "no complete runtime stamp" in refusal


def test_incomplete_runtime_stamp_is_refused() -> None:
    rows = [
        _row("t1"),
        {"id": "t2", "rev": REV, "corpus_head": CORPUS, "runtime": {}},
    ]
    _, _, refusal = _check(rows)
    assert refusal is not None
    assert "no complete runtime stamp" in refusal


def test_malformed_runtime_is_refused() -> None:
    """A negative count, a string, a bool, an empty list — none of these is "inert"."""
    bad_values = [
        {"embed_calls": -1},
        {"embed_calls": "0"},
        {"embed_calls": True},
        {"rerank_modes": []},
        {"rerank_modes": [1]},
        {"embedder": ""},
        {"dense_off": "false"},
        {"ondemand_rerank": 0},
    ]
    for bad in bad_values:
        rows = [_row("t1"), _row("t2", **bad)]
        _, _, refusal = _check(rows)
        assert refusal is not None, f"malformed runtime was accepted: {bad}"
        assert "no complete runtime stamp" in refusal


def test_allow_mixed_skips_the_runtime_check() -> None:
    rows = [
        _row("t1", embedder="llama_cpp", embed_calls=3),
        _row("t2", embedder="onnx"),
    ]
    _, _, refusal = _check(rows, allow_mixed=True)
    assert refusal is None


def test_rev_mismatch_is_still_refused() -> None:
    rows = [_row("t1"), {**_row("t2"), "rev": "b" * 40}]
    _, _, refusal = _check(rows)
    assert refusal is not None
    assert "another revision" in refusal


def test_replay_is_still_refused() -> None:
    rows = [_row(task_id) for task_id in PANEL]
    _, _, refusal = _check(rows, done=set(PANEL))
    assert refusal is not None
    assert "0 tasks executed" in refusal


# ── measurement helpers ──────────────────────────────────────────────────────


class _FakeEmbedder:
    def __init__(self) -> None:
        self.sync_calls = 0
        self.async_calls = 0

    def get_model_info(self) -> dict:
        return {"provider": "text_only"}

    def embed_batch(self, texts, is_query: bool = False):
        self.sync_calls += 1
        return [[0.0] for _ in texts]

    async def embed_batch_async(self, texts, is_query: bool = False):
        self.async_calls += 1
        return [[0.0] for _ in texts]


class _FakeSearcher:
    _dense_off = True
    _ondemand_rerank = False


def test_counter_counts_both_entry_points_and_restores_them() -> None:
    runtime = _load("bench_runtime", BENCH / "runtime.py")
    embedder = _FakeEmbedder()

    with runtime.EmbedderCounter(embedder) as counter:
        assert inspect.iscoroutinefunction(embedder.embed_batch_async), (
            "the async wrapper must stay a coroutine function; the search pipeline "
            "checks this before awaiting"
        )
        embedder.embed_batch(["a"])
        asyncio.run(embedder.embed_batch_async(["b"]))
        assert counter.calls == 2

    assert embedder.embed_batch(["c"]) == [[0.0]]
    assert embedder.sync_calls == 2, "the original method must be restored"
    assert embedder.async_calls == 1


def test_async_fallback_counts_one_logical_call() -> None:
    """`embed_batch_async` delegates to `embed_batch` outside lm_studio."""
    runtime = _load("bench_runtime", BENCH / "runtime.py")

    class _Delegating(_FakeEmbedder):
        async def embed_batch_async(self, texts, is_query: bool = False):
            return self.embed_batch(texts, is_query=is_query)

    embedder = _Delegating()
    with runtime.EmbedderCounter(embedder) as counter:
        asyncio.run(embedder.embed_batch_async(["a"]))
    assert counter.calls == 1, "one logical call, not the async entry plus its sync fallback"
    assert embedder.sync_calls == 1


def test_runtime_stamp_has_the_five_fields() -> None:
    runtime = _load("bench_runtime", BENCH / "runtime.py")
    stamp = runtime.runtime_stamp(
        _FakeEmbedder(), _FakeSearcher(), calls=0, rerank_modes={"sqlite_fts5", ""},
    )
    assert stamp == {
        "embedder": "text_only",
        "embed_calls": 0,
        "rerank_modes": ["sqlite_fts5"],
        "dense_off": True,
        "ondemand_rerank": False,
    }


def test_an_empty_rerank_list_becomes_unknown_not_inert() -> None:
    runtime = _load("bench_runtime", BENCH / "runtime.py")
    stamp = runtime.runtime_stamp(_FakeEmbedder(), _FakeSearcher(), calls=0,
                                  rerank_modes=set())
    assert stamp["rerank_modes"] == ["unknown"]


def test_runtime_stamp_survives_a_broken_status_call() -> None:
    runtime = _load("bench_runtime", BENCH / "runtime.py")

    class _Broken(_FakeEmbedder):
        def get_model_info(self) -> dict:
            raise RuntimeError("status unavailable")

    stamp = runtime.runtime_stamp(_Broken(), _FakeSearcher(), calls=1,
                                  rerank_modes=["ondemand"])
    assert stamp["embedder"] == "unknown"
    assert stamp["embed_calls"] == 1
    assert stamp["rerank_modes"] == ["ondemand"]


def test_a_missing_embedder_is_stamped_as_unavailable() -> None:
    runtime = _load("bench_runtime", BENCH / "runtime.py")
    stamp = runtime.runtime_stamp(None, _FakeSearcher(), calls=0,
                                  rerank_modes={"sqlite_fts5"})
    assert stamp["embedder"] == "unavailable"
    assert stamp["embed_calls"] == 0
