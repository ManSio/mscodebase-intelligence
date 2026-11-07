"""Phase 3: статус индекса обязан читать АКТИВНЫЙ store (SQLite/FTS5).

Регресс 2026-11-07: dense_off=true → чанки лежат в `<project>/.mscodebase/chunks.db`,
LanceDB пуст, `IndexStatusReporter` возвращал total_chunks=0 → `require_ready_project`
блокировал search_code/get_symbol_info/LSP/write-тулы навсегда.

Контроли (AGENTS.md §19.3): положительный — заполненный store даёт >0,
отрицательный — пустой store остаётся 0 (тест умеет различать).
"""

from __future__ import annotations

from pathlib import Path

from src.core.indexing.chunk_store import SQLiteChunkStore
from src.core.indexing.index_status import IndexStatusReporter


class _EmptyTable:
    """LanceDB-таблица Phase 3: существует, но пуста."""

    def count_rows(self) -> int:
        return 0


class _PopulatedTable:
    def count_rows(self) -> int:
        return 5


def _record(file_path: str, idx: int, text: str) -> dict:
    return {
        "file_path": file_path,
        "chunk_index": idx,
        "text": text,
        "chunk_id": f"{file_path}:{idx}",
    }


def _reporter(tmp_path: Path, store: SQLiteChunkStore, table=None) -> IndexStatusReporter:
    return IndexStatusReporter(
        table=table if table is not None else _EmptyTable(),
        project_path=tmp_path,
        file_guard=None,
        watchdog_callback=None,
        chunk_store=store,
    )


def test_sqlite_store_counts_when_lancedb_empty(tmp_path: Path):
    """Positive control: 3 чанка в SQLite при пустом LanceDB → статус active."""
    store = SQLiteChunkStore(tmp_path / ".mscodebase" / "chunks.db")
    store.upsert_records(
        [
            _record("src/a.py", 0, "alpha"),
            _record("src/a.py", 1, "beta"),
            _record("src/b.py", 0, "gamma"),
        ]
    )

    status = _reporter(tmp_path, store).get_status()

    assert status["total_chunks"] == 3
    assert status["unique_files"] == 2
    assert status["status"] == "active"
    assert status["store"] == "sqlite"
    # Ровно условие гейта из src/mcp/tools/base.py:428 — должно пройти.
    assert status["total_chunks"] > 0
    store.close()


def test_empty_store_stays_empty(tmp_path: Path):
    """Negative control: пусто и там, и там → empty (не «активно»)."""
    store = SQLiteChunkStore(tmp_path / ".mscodebase" / "chunks.db")
    store.upsert_records([])  # создаёт схему, строк нет

    status = _reporter(tmp_path, store).get_status()

    assert status["total_chunks"] == 0
    assert status["status"] == "empty"
    assert status["store"] == "none"
    store.close()


def test_lancedb_wins_when_populated(tmp_path: Path):
    store = SQLiteChunkStore(tmp_path / ".mscodebase" / "chunks.db")
    store.upsert_records([])

    status = _reporter(tmp_path, store, table=_PopulatedTable()).get_status()

    assert status["total_chunks"] == 5
    assert status["store"] == "lancedb"
    store.close()


def test_without_store_the_gate_would_block(tmp_path: Path):
    """Контроль «тест умеет падать»: без chunk_store тот же store даёт 0.

    Это ровно старое поведение 2026-11-07 → require_ready_project блокировал
    все инструменты. Если фикс убрать — этот тест останется зелёным, а первый
    покраснеет, то есть тест различает исправленное и сломанное состояние.
    """
    store = SQLiteChunkStore(tmp_path / ".mscodebase" / "chunks.db")
    store.upsert_records([_record("src/a.py", 0, "alpha")])

    reporter = IndexStatusReporter(
        table=_EmptyTable(),
        project_path=tmp_path,
        file_guard=None,
        watchdog_callback=None,
    )
    status = reporter.get_status()

    assert status["total_chunks"] == 0
    assert status["status"] == "empty"
    store.close()
