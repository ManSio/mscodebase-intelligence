"""Индекс по file_path: без него DELETE сканирует всю таблицу на каждый файл."""
from __future__ import annotations

from pathlib import Path

from src.core.indexing.chunk_store import SQLiteChunkStore


def test_chunk_store_has_file_path_index(tmp_path: Path):
    store = SQLiteChunkStore(tmp_path / "chunks.db")
    conn = store._ensure_conn()

    names = {
        row[0]
        for row in conn.execute("select name from sqlite_master where type='index'")
    }
    assert "idx_chunks_file_path" in names, names

    plan = conn.execute(
        "explain query plan delete from chunks where file_path = 'x'"
    ).fetchall()
    assert any("idx_chunks_file_path" in str(row) for row in plan), plan


def test_index_is_created_on_an_existing_database(tmp_path: Path):
    """Старые БД (без индекса) получают его при следующем открытии."""
    import sqlite3

    db = tmp_path / "legacy.db"
    con = sqlite3.connect(str(db))
    con.execute(
        "create table chunks (rowid integer primary key, file_path text not null, text text)"
    )
    con.commit()
    con.close()

    store = SQLiteChunkStore(db)
    conn = store._ensure_conn()
    names = {
        row[0]
        for row in conn.execute("select name from sqlite_master where type='index'")
    }
    assert "idx_chunks_file_path" in names, names
