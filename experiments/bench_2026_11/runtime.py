"""Per-row runtime provenance for the commit-localization benchmark.

A row must say what the scoring path *used*, not what the machine had installed.
`rev` and `corpus_head` prove which product and corpus produced a row; they do not
prove that the embedder/reranker did not change between two resumed chunks (E74's
open item: a flaky ONNX daemon timed out at 60s while the score was printed).

What is recorded:

- `embedder`  — the provider mode the embedder reported (`text_only`, `onnx`, ...);
- `embed_calls` — entry calls to the embedder's batch API during this task;
- `rerank_modes` — what the searcher reported after each of the three calls;
- `dense_off` / `ondemand_rerank` — the resolved flags of the path.

The capture guard (`capture._runtime_conflict`) refuses a mixed capture only when
a differing component was actually used. A text-only panel with `embed_calls=0`
may survive a daemon flap; the row still says so, instead of the author's memory.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any

_BATCH_METHODS = ("embed_batch", "embed_batch_async")


class EmbedderCounter:
    """Count embedder batch calls made inside one benchmark task.

    Only the batch entry points are wrapped: the single-text helpers delegate to
    them, and wrapping all four would count one logical call twice. `embed_batch_async`
    also delegates to `embed_batch` outside lm_studio, so the nested sync call is
    not counted again. Async methods keep being coroutine functions, because the
    search pipeline checks `inspect.iscoroutinefunction` before awaiting the result.
    """

    def __init__(self, embedder: Any) -> None:
        self.embedder = embedder
        self.calls = 0
        self._inside_async = 0
        self._saved: dict[str, Any] = {}

    def __enter__(self) -> "EmbedderCounter":
        if self.embedder is None:
            return self
        for name in _BATCH_METHODS:
            original = getattr(self.embedder, name, None)
            if not callable(original):
                continue
            self._saved[name] = original
            setattr(self.embedder, name, self._wrap(original))
        return self

    def _wrap(self, original: Any) -> Any:
        if inspect.iscoroutinefunction(original):
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                self.calls += 1
                self._inside_async += 1
                try:
                    return await original(*args, **kwargs)
                finally:
                    self._inside_async -= 1

            return async_wrapper

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # `embed_batch_async` delegates to `embed_batch` outside lm_studio.
            # That is one logical call, not two; count it at the async entry.
            if self._inside_async == 0:
                self.calls += 1
            return original(*args, **kwargs)

        return wrapper

    def __exit__(self, *exc_info: Any) -> None:
        for name, original in self._saved.items():
            setattr(self.embedder, name, original)
        self._saved.clear()


def runtime_stamp(
    embedder: Any,
    searcher: Any,
    *,
    calls: int,
    rerank_modes: Iterable[str],
) -> dict[str, Any]:
    """The provenance of one row, from the objects that produced it."""
    provider = "unavailable"
    if embedder is not None:
        try:
            info = embedder.get_model_info()
            provider = str(info.get("provider") or "unknown")
        except Exception:  # noqa: BLE001 — a broken status call must not lose the row
            provider = "unknown"
    modes = sorted({str(mode) for mode in rerank_modes if mode})
    return {
        "embedder": provider,
        "embed_calls": max(0, int(calls)),
        # An empty list would read as "not used"; unknown is not inert.
        "rerank_modes": modes or ["unknown"],
        "dense_off": bool(getattr(searcher, "_dense_off", False)),
        "ondemand_rerank": bool(getattr(searcher, "_ondemand_rerank", False)),
    }


__all__ = ["EmbedderCounter", "runtime_stamp"]
