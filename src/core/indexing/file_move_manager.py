"""FileMoveManager — meta-patching for file rename without re-embedding."""
from __future__ import annotations

import logging

__all__ = [
    "FileMoveManager",
]
logger = logging.getLogger("mscodebase_server.file_move")


class _NullLock:
    """No-op context manager — fallback, если table_write_lock не передан."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FileMoveManager:
    """Manages file rename across index layers (LanceDB meta-patching)."""

    def __init__(self, table, searcher=None, table_write_lock=None):
        self.table = table
        self.searcher = searcher
        self._table_write_lock = table_write_lock

    def move_chunks_metadata(self, old_path: str, new_path: str) -> int:
        """Update file_path in LanceDB WITHOUT re-embedding.

        Параллельная реализация Indexer.move_chunks_metadata (P1-5):
        - поиск по file_path (НЕ по file_hash — дубликаты контента получали
          чужой file_path, регрессия LOGIC-1 z.ai-ревью)
        - read → delete → add в одном lock-цикле (не транзакционный delete+add
          терял чанки при сбое между ними, LOGIC-2)
        - _escape_sql_value вместо ручного replace (LOGIC-3)
        """
        from src.core.indexing.indexer_table import IndexerTableMixin

        safe_old = IndexerTableMixin._escape_sql_value(old_path.replace(chr(92), "/"))
        safe_new = IndexerTableMixin._escape_sql_value(new_path.replace(chr(92), "/"))
        if safe_old == safe_new:
            return 0

        lock_ctx = self._table_write_lock if self._table_write_lock is not None else _NullLock()
        try:
            with lock_ctx:
                # 1. Read old chunks (все метаданные + векторы)
                old_df = (
                    self.table.search()
                    .where(f"file_path = '{safe_old}'", prefilter=True)
                    .limit(10000)
                    .to_pandas()
                )
                if old_df.empty:
                    logger.debug(f"move: no chunks for {old_path}")
                    return 0

                count = len(old_df)
                logger.info(f"Deleting {count} chunks for {old_path}")

                # 2. Delete old entries
                self.table.delete(f"file_path = '{safe_old}'")

                # 3. Mutate metadata (тот же вектор — без re-embedding)
                old_df["file_path"] = safe_new
                self.table.add(old_df.to_dict("records"))

            logger.info(f"Moved {count} chunks: {old_path} -> {new_path}")
            return count
        except Exception as e:
            logger.error(f"move failed: {old_path} -> {new_path}: {e}")
            return 0

    def apply_file_move(self, old_path: str, new_path: str) -> dict:
        """Coordinate file rename across all index layers."""
        results = {"chunks_moved": 0, "bm25_reset": False}
        chunks = self.move_chunks_metadata(old_path, new_path)
        results["chunks_moved"] = chunks
        if chunks > 0 and self.searcher:
            try:
                bm25 = getattr(self.searcher, "_bm25", None)
                if bm25 and hasattr(bm25, "_reset_bm25"):
                    bm25._reset_bm25()
                results["bm25_reset"] = True
            except Exception as e:
                logger.warning(f"BM25 reset failed: {e}")
        return results
