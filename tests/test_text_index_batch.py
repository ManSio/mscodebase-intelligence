"""Графовый batch и guard нулевого результата (2026-11-17).

Замер: 300 файлов engraphis — 195.1 с при commit на каждый узел/ребро против
28.8 с через PropertyGraph.batch() (6.8x), при идентичных чанках и символах.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.indexing.file_guard import FileGuard
from src.core.indexing.indexer import Indexer
from src.sources.local_fs import LocalFsSource


def _indexer(tmp_path: Path) -> Indexer:
    db = tmp_path / ".mscodebase" / "chunks.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    embedder = MagicMock()
    embedder.embedding_dim = 768
    return Indexer(db, embedder, FileGuard(tmp_path), project_path=tmp_path,
                   source=LocalFsSource(tmp_path))


class _Graph:
    def __init__(self) -> None:
        self.batch_calls = 0

    def batch(self):
        self.batch_calls += 1
        return _Ctx()


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _prepare(tmp_path: Path, indexer: Indexer, graph: _Graph | None) -> None:
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    indexer._chunk_store = MagicMock()
    indexer._chunk_store.file_hash.return_value = None
    indexer._chunk_store.all_records.return_value = []
    indexer._pipeline = MagicMock()
    indexer._pipeline.process_file.return_value = {"skip_vectors": True}
    indexer._db_writer = MagicMock()
    indexer._db_writer.write_text_records.return_value = []
    indexer._index_guard = MagicMock()
    indexer._index_guard.save_symbol_index.return_value = True
    indexer._symbol_index = MagicMock()
    indexer._symbol_index.graph = graph


def test_text_only_writes_graph_in_one_batch_per_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_GRAPH_BATCH", "1")
    indexer = _indexer(tmp_path)
    graph = _Graph()
    _prepare(tmp_path, indexer, graph)

    indexer._index_text_only_project(tmp_path)

    assert graph.batch_calls >= 1, "граф обязан писаться пачкой"


def test_graph_batch_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_GRAPH_BATCH", "0")
    indexer = _indexer(tmp_path)
    graph = _Graph()
    _prepare(tmp_path, indexer, graph)

    indexer._index_text_only_project(tmp_path)

    assert graph.batch_calls == 0


def test_all_files_failing_is_an_error_not_an_empty_success(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_GRAPH_BATCH", "1")
    indexer = _indexer(tmp_path)
    _prepare(tmp_path, indexer, _Graph())
    indexer._pipeline.process_file.side_effect = RuntimeError("parse blew up")

    with pytest.raises(RuntimeError, match="ни один файл"):
        indexer._index_text_only_project(tmp_path)
