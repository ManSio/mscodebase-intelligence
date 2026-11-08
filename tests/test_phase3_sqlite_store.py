"""Phase 3: SQLite/FTS5 chunk store + LanceDB-free search path."""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.core.indexing.chunk_store import SQLiteChunkStore, get_chunks_db_path
from src.core.search.engine import Searcher


def _records():
    return [
        {
            "chunk_id": "src/a.py:0",
            "file_path": "src/a.py",
            "chunk_index": 0,
            "text": "def remote_embedder(): return provider",
            "text_full": "def remote_embedder(): return provider",
            "symbol_name": "remote_embedder",
            "symbol_kind": "function",
            "layer": "providers",
            "start_line": 10,
            "end_line": 12,
        },
        {
            "chunk_id": "src/b.py:0",
            "file_path": "src/b.py",
            "chunk_index": 0,
            "text": "class DatabaseLock: pid lock",
            "text_full": "class DatabaseLock: pid lock",
            "symbol_name": "DatabaseLock",
            "symbol_kind": "class",
            "layer": "core",
            "start_line": 1,
            "end_line": 5,
        },
    ]


def test_store_upsert_and_search(tmp_path: Path):
    db = tmp_path / "chunks.db"
    store = SQLiteChunkStore(db)
    try:
        assert store.upsert_records(_records()) == 2
        assert store.count() == 2
        assert store.files_count() == 2
        hits = store.search("remote embedder provider", limit=5)
        assert hits
        assert hits[0]["metadata"]["file"] == "src/a.py"
        assert store.file_hash("src/a.py") is None
    finally:
        store.close()


def test_store_replaces_file_chunks(tmp_path: Path):
    db = tmp_path / "chunks.db"
    store = SQLiteChunkStore(db)
    try:
        store.upsert_records(_records())
        store.upsert_records(
            [
                {
                    "chunk_id": "src/a.py:0",
                    "file_path": "src/a.py",
                    "chunk_index": 0,
                    "text": "def changed(): pass",
                    "text_full": "def changed(): pass",
                }
            ]
        )
        assert store.count() == 2
        hits = store.search("changed", limit=5)
        assert hits and hits[0]["metadata"]["file"] == "src/a.py"
        assert not store.search("remote_embedder", limit=5)
    finally:
        store.close()


class _RaisingTable:
    """Any LanceDB table access in the search path must fail loudly."""

    def __getattr__(self, name):
        raise AssertionError(f"LanceDB table touched: {name}")


class _FakeIndexer:
    db_manager = None
    _symbol_index = None
    table = _RaisingTable()

    def __init__(self, project_path: Path):
        self.project_path = project_path


class _FakeEmbedder:
    def embed_batch(self, texts, is_query=False):
        return [[1.0] * 384 for _ in texts]

    async def embed_batch_async(self, texts, is_query=False):
        return self.embed_batch(texts, is_query=False)


def test_search_uses_sqlite_and_never_touches_lancedb(tmp_path: Path):
    store_path = get_chunks_db_path(tmp_path)
    store = SQLiteChunkStore(store_path)
    store.upsert_records(_records())
    store.close()

    searcher = Searcher(_FakeIndexer(tmp_path), _FakeEmbedder())
    try:
        results = asyncio.run(
            searcher.hybrid_search_async("remote embedder provider", limit=5)
        )
        assert results
        assert results[0]["metadata"]["file"] == "src/a.py"
    finally:
        asyncio.run(searcher.close())
