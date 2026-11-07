"""Phase 3: hot-reload must read the SQLite store, not the empty LanceDB table.

Observation 2026-11-07: a symbol added while the server was down
(`_read_head_sha` in scripts/verify_diary.py) was invisible to search and
`get_symbol_info`, because FreshnessChecker read `table.to_lance()` (empty
under dense_off) and treated the index as empty, so it never reindexed
anything.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.core.indexing.chunk_store import SQLiteChunkStore
from src.core.indexing.freshness import FreshnessChecker


class _ChunkState:
    def __init__(self, paths):
        self._state = {"_has_stat": True, "_paths": paths}

    def count(self):
        return len(self._state["_paths"])

    def indexed_state(self):
        return self._state


def _stat(path: Path) -> dict:
    st = path.stat()
    data = path.read_bytes()
    return {
        "hash": hashlib.sha256(data).hexdigest(),
        "mtime_ns": int(st.st_mtime_ns),
        "size": int(st.st_size),
    }


def _checker(project: Path, state: _ChunkState, calls: list):
    def _index_single_file(full_path, rel_path):
        calls.append(rel_path)
        return True

    def _hash(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    return FreshnessChecker(
        table=object(),
        file_guard=None,
        index_single_file=_index_single_file,
        calculate_file_hash=_hash,
        interval_sec=0,
        chunk_store=state,
    )


def test_unchanged_file_is_not_reindexed(tmp_path):
    src = tmp_path / "a.py"
    src.write_text("print(1)\n", encoding="utf-8")
    state = _ChunkState({"a.py": _stat(src)})
    calls: list[str] = []

    assert _checker(tmp_path, state, calls).verify(tmp_path, force=True) == 0
    assert calls == []


def test_modified_file_is_reindexed(tmp_path):
    src = tmp_path / "a.py"
    src.write_text("print(1)\n", encoding="utf-8")
    state = _ChunkState({"a.py": _stat(src)})
    src.write_text("print(1)\nprint(2)\n", encoding="utf-8")  # содержимое изменилось
    calls: list[str] = []

    assert _checker(tmp_path, state, calls).verify(tmp_path, force=True) == 1
    assert calls == ["a.py"]


def test_new_file_is_picked_up(tmp_path):
    (tmp_path / "known.py").write_text("print(0)\n", encoding="utf-8")
    (tmp_path / "new.py").write_text("print(2)\n", encoding="utf-8")
    state = _ChunkState({"known.py": _stat(tmp_path / "known.py")})
    calls: list[str] = []

    assert _checker(tmp_path, state, calls).verify(tmp_path, force=True) == 1
    assert calls == ["new.py"]


def test_store_indexed_state_matches_written_records(tmp_path):
    store = SQLiteChunkStore(tmp_path / ".mscodebase" / "chunks.db")
    store.upsert_records(
        [
            {
                "file_path": "src/a.py",
                "chunk_index": 0,
                "text": "alpha",
                "file_hash": "deadbeef",
                "file_mtime_ns": 123,
                "file_size": 456,
            }
        ]
    )
    state = store.indexed_state()
    assert state["_has_stat"] is True
    assert state["_paths"]["src/a.py"] == {
        "hash": "deadbeef",
        "mtime_ns": 123,
        "size": 456,
    }
    store.close()
