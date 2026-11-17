"""Text-only индексация: ошибки не глотаются, статус отражает записанное.

Репро аудита engraphis: `try/except Exception` вокруг text-only глушил реальную
ошибку («unable to open database file») и уводил код в dense-конвейер, который
без эмбеддера падал «Embedder returned 0 vectors»; снаружи это выглядело как
«reindexing» и 0 чанков.
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


def test_text_only_failure_is_not_swallowed(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\nversion='0'\n",
                                             encoding="utf-8")
    indexer = _indexer(tmp_path)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("text-only blew up")

    dense_called: list[int] = []
    monkeypatch.setattr(indexer, "_index_text_only_project", _boom)
    monkeypatch.setattr(indexer._project_runner, "run",
                        lambda **_kw: dense_called.append(1) or 0)
    monkeypatch.setenv("MSCODEBASE_DENSE_OFF", "true")

    with pytest.raises(RuntimeError, match="text-only blew up"):
        indexer.index_project(tmp_path)

    assert dense_called == [], "при dense_off ошибка не должна уходить в dense-путь"


def test_text_only_updates_status_cache(tmp_path, monkeypatch):
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    indexer = _indexer(tmp_path)
    indexer._chunk_store = MagicMock()
    indexer._chunk_store.file_hash.return_value = None
    indexer._chunk_store.all_records.return_value = []
    indexer._pipeline = MagicMock()
    indexer._pipeline.process_file.return_value = {"skip_vectors": True}
    indexer._db_writer = MagicMock()
    indexer._db_writer.write_text_records.return_value = [{"chunk_id": "a"}, {"chunk_id": "b"}]
    indexer._cached_total_chunks = 0
    indexer._cached_unique_files = set()
    monkeypatch.setenv("MSCODEBASE_DENSE_OFF", "true")

    files = indexer._index_text_only_project(tmp_path)

    # В каталоге может оказаться не только m.py (на CI — служебные файлы
    # индекса), поэтому проверяем связь «файлов × записей = кэш», а не число 1.
    assert files >= 1
    assert indexer._cached_total_chunks == 2 * files, (
        "каждый записанный файл обязан увеличить кэш на число его чанков"
    )
    assert "m.py" in indexer._cached_unique_files


def test_text_only_saves_symbol_index(tmp_path, monkeypatch):
    """Граф/символы обязаны попасть на диск: иначе get_symbol_info мёртв.

    На реальном корне (engraphis) было 49 558 чанков и 0 узлов в graph.db.
    """
    (tmp_path / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    indexer = _indexer(tmp_path)
    indexer._chunk_store = MagicMock()
    indexer._chunk_store.file_hash.return_value = None
    indexer._chunk_store.all_records.return_value = []
    indexer._pipeline = MagicMock()
    indexer._pipeline.process_file.return_value = {"skip_vectors": True}
    indexer._db_writer = MagicMock()
    indexer._db_writer.write_text_records.return_value = []
    indexer._index_guard = MagicMock()
    indexer._index_guard.save_symbol_index.return_value = True
    indexer._symbol_index = object()
    monkeypatch.setenv("MSCODEBASE_DENSE_OFF", "true")

    indexer._index_text_only_project(tmp_path)

    indexer._index_guard.save_symbol_index.assert_called_once_with(indexer._symbol_index)
