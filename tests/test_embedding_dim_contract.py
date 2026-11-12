"""Embedding width contract between provider, LanceDB schema and writer (G4).

The night failure this pins down (12->13.11.2026): the project's vector table
was `fixed_size_list<float>[384]` with zero rows, the active embedder returned
768-d vectors, and the mismatch surfaced as a LanceDB cast error only after the
build had started. Silent padding/truncation would have stored 768-d answers
under a 384-d promise.

Rules under test:
1. the schema follows the provider's declared width;
2. an empty table with the wrong width is rebuilt (no rows to lose);
3. a non-empty table with the wrong width refuses loudly, naming the provider
   and both numbers;
4. the writer never pads or truncates a vector;
5. retries are bounded and end in `EmbedderUnavailable`, not a restart loop.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from src.core.indexing.db_manager import LanceDBManager
from src.core.indexing.db_writer import LanceDBWriter
from src.core.indexing.dim_contract import (
    EmbedderUnavailable,
    EmbeddingDimMismatch,
    bounded_attempts,
    provider_dim,
    provider_label,
    require_dim_match,
    schema_vector_dim,
)
from src.providers.embedder.remote_embedder import RemoteEmbedder


def _onnx(dim: int = 384) -> SimpleNamespace:
    return SimpleNamespace(
        embedding_dim=dim,
        provider_name="onnx:multilingual-e5-small-int8",
    )


def _manager(tmp_path, dim: int, embedder=None) -> LanceDBManager:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    return LanceDBManager(
        db_path=tmp_path / "index.lancedb",
        embedder=embedder,
        project_path=project,
        embedding_dim=dim,
    )


def _release(mgr: LanceDBManager) -> None:
    mgr.close_for_maintenance()
    if mgr._db_lock is not None:
        mgr._db_lock.release()


# ── 1. helpers ──────────────────────────────────────────────────────────────


def test_provider_dim_and_label():
    emb = _onnx(384)
    assert provider_dim(emb) == 384
    assert provider_label(emb) == "onnx:multilingual-e5-small-int8"
    assert provider_dim(None) is None
    assert provider_label(None) == "no-embedder"


def test_require_dim_match_names_both_numbers():
    with pytest.raises(EmbeddingDimMismatch) as exc:
        require_dim_match(
            provider="llama_cpp:embeddinggemma-2",
            provider_dim=768,
            schema_dim=384,
            where="write_records(a.py)",
        )
    text = str(exc.value)
    assert "llama_cpp:embeddinggemma-2" in text
    assert "768" in text and "384" in text


def test_require_dim_match_refuses_unknown_width():
    with pytest.raises(EmbeddingDimMismatch, match="cannot verify"):
        require_dim_match(
            provider="mystery", provider_dim=None, schema_dim=384, where="x"
        )


# ── 2. schema follows the provider ──────────────────────────────────────────


def test_manager_refuses_schema_width_that_contradicts_the_provider(tmp_path):
    with pytest.raises(EmbeddingDimMismatch, match="container|declares"):
        _manager(tmp_path, dim=768, embedder=_onnx(384))


def test_empty_table_with_other_width_is_rebuilt_for_the_provider(tmp_path):
    """G4 repro: 384-d schema, 0 rows, provider returns 768."""
    old = _manager(tmp_path, dim=384, embedder=_onnx(384))
    assert schema_vector_dim(old.table.schema) == 384
    assert old.table.count_rows() == 0
    _release(old)

    new = _manager(tmp_path, dim=768, embedder=_onnx(768))
    assert schema_vector_dim(new.table.schema) == 768, (
        "empty table kept the old width; the schema must follow the provider"
    )
    assert new.table.count_rows() == 0


def test_non_empty_table_with_other_width_refuses_and_keeps_rows(tmp_path):
    old = _manager(tmp_path, dim=384, embedder=_onnx(384))
    old.table.add(
        [
            {
                "id": "chunk_0",
                "vector": [0.1] * 384,
                "text": "def f(): pass",
                "text_full": "def f(): pass",
                "file_path": "a.py",
                "file_hash": "h",
                "chunk_index": 0,
                "source": "test",
                "indexed_at": "2026-11-12T00:00:00",
                "summary": "",
                "layer": "core",
                "module_name": "a",
                "hierarchy_level": "function",
                "is_public": True,
                "symbol_type": "function",
                "parent_id": "",
                "callees": "",
                "health_score": 0.0,
                "health_band": "",
                "chunk_hash": "c",
                "start_line": 1,
                "end_line": 2,
                "file_mtime_ns": 0,
                "file_size": 0,
            }
        ]
    )
    assert old.table.count_rows() == 1
    _release(old)

    with pytest.raises(EmbeddingDimMismatch) as exc:
        _manager(tmp_path, dim=768, embedder=_onnx(768))
    text = str(exc.value)
    assert "onnx:multilingual-e5-small-int8" in text
    assert "384" in text and "768" in text


# ── 3. the writer never resizes silently ────────────────────────────────────


def test_writer_refuses_short_vector_instead_of_padding(tmp_path):
    mgr = _manager(tmp_path, dim=768, embedder=_onnx(768))
    writer = LanceDBWriter(
        table=mgr.table,
        table_write_lock=threading.RLock(),
        index_lock=None,
        embedder=_onnx(768),
        db_manager=mgr,
    )
    parsed = {
        "rel_path": "a.py",
        "current_hash": "h2",
        "existing_hash": None,
        "escaped_path": "a.py",
        "chunk_texts": ["def f(): pass"],
        "chunk_hashes": ["c2"],
        "chunk_texts_full": ["def f(): pass"],
        "chunk_metadatas": [{}],
        "health": {},
    }

    with pytest.raises(EmbeddingDimMismatch) as exc:
        writer.write_records(parsed=parsed, embeddings=[[0.1] * 384])

    text = str(exc.value)
    assert "onnx:multilingual-e5-small-int8" in text
    assert "384" in text and "768" in text
    assert mgr.table.count_rows() == 0, "a refused write must not reach the table"


# ── 4. bounded retries end in a named BLOCKED ───────────────────────────────


def test_bounded_attempts_stops_and_names_the_provider():
    calls = []

    def _fail(attempt):
        calls.append(attempt)
        raise RuntimeError("WinError 10061")

    with pytest.raises(EmbedderUnavailable) as exc:
        bounded_attempts(
            _fail,
            attempts=3,
            provider="llama_cpp:embeddinggemma-2",
            label="embed_batch",
        )
    assert calls == [0, 1, 2], "retries must be exactly bounded"
    text = str(exc.value)
    assert "llama_cpp:embeddinggemma-2" in text
    assert "3 attempt(s)" in text


def test_bounded_attempts_returns_after_transient_failures():
    calls = []

    def _flaky(attempt):
        calls.append(attempt)
        if attempt < 2:
            raise RuntimeError("temporary")
        return attempt

    assert bounded_attempts(
        _flaky, attempts=3, provider="onnx:x", label="embed_batch"
    ) == 2
    assert calls == [0, 1, 2]


def test_embed_batch_raises_blocked_instead_of_restart_loop(monkeypatch):
    """Red-first: old code raised RuntimeError after an unbounded per-item storm."""

    class _DeadClient:
        def __init__(self):
            self.posts = 0

        def post(self, *args, **kwargs):
            self.posts += 1
            return SimpleNamespace(status_code=500, json=lambda: {})

    emb = RemoteEmbedder.__new__(RemoteEmbedder)
    emb.mode = "llama_cpp"
    emb.model_name = "embeddinggemma-2"
    emb.embedding_dim = 768
    emb._mode_lock = threading.Lock()
    emb._http_client = _DeadClient()
    emb.llama_cpp_url = "http://127.0.0.1:8080/v1/embeddings"
    emb._llama_last_used = 0.0
    emb._truncate_for_llama = lambda texts: texts
    emb._revive_llama_cpp = lambda: False

    import time as time_mod

    monkeypatch.setattr(time_mod, "sleep", lambda _s: None)

    with pytest.raises(EmbedderUnavailable) as exc:
        emb.embed_batch(["a", "b"])

    text = str(exc.value)
    assert "llama_cpp:embeddinggemma-2" in text
    assert "BLOCKED" in text
    # 3 batch attempts + 2 single-item attempts for the first failing text;
    # the loop raises on that text instead of trying the rest.
    assert emb._http_client.posts == 3 + 2
