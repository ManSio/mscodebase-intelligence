"""FileMoveManager — meta-patching for file rename without re-embedding."""
from __future__ import annotations

import logging

__all__ = [
    "FileMoveManager",
]
logger = logging.getLogger("mscodebase_server.file_move")


class FileMoveManager:
    """Manages file rename across index layers (LanceDB meta-patching)."""

    def __init__(self, table, searcher=None):
        self.table = table
        self.searcher = searcher

    def move_chunks_metadata(self, old_path: str, new_path: str) -> int:
        """Update file_path in LanceDB WITHOUT re-embedding."""
        escaped_old = old_path.replace("'", "''")
        try:
            old_df = (
                self.table.search()
                .where(f"file_path = '{escaped_old}'", prefilter=True)
                .limit(1)
                .to_pandas()
            )
            if old_df.empty:
                logger.debug(f"move: no chunks for {old_path}")
                return 0
            old_hash = str(old_df["file_hash"].iloc[0])
            old_chunk_count = self.table.count_rows(filter=f"file_path = '{escaped_old}'")
            self.table.delete(f"file_path = '{escaped_old}'")
            logger.info(f"Deleted {old_chunk_count} chunks for {old_path}")
            new_chunk_count = 0
            rows = self.table.search().where(f"file_hash = '{old_hash.replace(chr(39), chr(39)*2)}'", prefilter=True).limit(old_chunk_count).to_pandas()
            if not rows.empty:
                for _, row in rows.iterrows():
                    row["file_path"] = new_path
                self.table.add(rows.to_dict("records"))
                new_chunk_count = len(rows)
            logger.info(f"Moved {new_chunk_count} chunks: {old_path} -> {new_path}")
            return new_chunk_count
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
