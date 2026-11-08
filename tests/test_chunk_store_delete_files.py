from src.core.indexing.chunk_store import SQLiteChunkStore


def _rec(file_path, idx, text):
    return {
        "chunk_id": f"{file_path}:{idx}",
        "file_path": file_path,
        "chunk_index": idx,
        "text": text,
        "text_full": text,
        "symbol_name": "",
        "symbol_kind": "",
        "docstring": "",
        "layer": "",
        "start_line": 1,
        "end_line": 1,
        "indexed_at": "",
        "chunk_hash": "h",
        "file_hash": "h",
        "file_mtime_ns": 0,
        "file_size": 1,
    }


def test_delete_files_prunes_and_keeps_fts_in_sync(tmp_path):
    db = tmp_path / "chunks.db"
    store = SQLiteChunkStore(db)
    store.upsert_records([
        _rec("src/a.py", 0, "alpha"),
        _rec("experiments/x/frozen/q.md", 0, "beta"),
        _rec("docs/a.md", 0, "gamma"),
    ])
    assert store.count() == 3

    store.delete_files(["experiments/x/frozen/q.md"])
    assert store.count() == 2
    assert store.search("beta", limit=10) == []

    store.delete_files(["src/a.py", "docs/a.md"])
    assert store.count() == 0
