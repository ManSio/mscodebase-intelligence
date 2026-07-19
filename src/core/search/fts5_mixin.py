"""FTS5 search mixin for the Searcher class.

Provides lazy FTS5 index building, incremental updates, and integration
with the hybrid_search pipeline. Mirrors the BM25Mixin pattern.

Usage:
    class Searcher(BM25Mixin, FTS5Mixin, ISearcher, AgenticSearchMixin):
        ...
"""

import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional

from .fts5_index import FTS5IndexManager

__all__ = ["FTS5Mixin"]
logger = logging.getLogger(__name__)


class FTS5Mixin:
    """Mixin that adds FTS5 4-tier search capabilities.

    Expects the host class to provide:
    * ``self.indexer`` — Indexer instance (needs ``.table`` for data loading)
    * ``self._fts5`` — Optional[FTS5IndexManager]
    * ``self._fts5_lock`` — threading.Lock
    """

    # ── Index building ────────────────────────────────────────

    def _build_fts5_index(self) -> None:
        """Lazy-build FTS5 index from the indexer's LanceDB table.

        Thread-safe: uses double-checked locking pattern.
        If the table is empty or unavailable — FTS5 stays empty (degraded mode).
        """
        if self._fts5 is not None and not self._fts5.is_empty:
            return

        with self._fts5_lock:
            # Double-check after acquiring lock
            if self._fts5 is not None and not self._fts5.is_empty:
                return

            # Initialize FTS5 manager (in-memory for now)
            if self._fts5 is None:
                self._fts5 = FTS5IndexManager(in_memory=True)

            # Load data from LanceDB table
            if self.indexer is None or not hasattr(self.indexer, "table"):
                logger.debug("FTS5: no indexer/table available, skipping build")
                return

            try:
                table = self.indexer.table
                if table is None:
                    return
                if table.count_rows() == 0:
                    return
            except Exception as e:
                logger.debug(f"FTS5: table not accessible: {e}")
                return

            try:
                df = table.to_pandas()
                if df is None or df.empty:
                    return

                # Convert LanceDB rows to chunks for FTS5
                chunks = []
                for _, row in df.iterrows():
                    text = str(row.get("text", ""))
                    file_path = str(row.get("file_path", ""))
                    chunk_index = int(row.get("chunk_index", 0))

                    # Extract symbol info from text
                    symbol_name, symbol_kind = self._extract_symbol_from_text(text)

                    # Extract docstring
                    docstring = self._extract_docstring(text)

                    chunks.append({
                        "file_path": file_path,
                        "chunk_index": chunk_index,
                        "text": text,
                        "symbol_name": symbol_name,
                        "symbol_kind": symbol_kind,
                        "docstring": docstring,
                        "layer": str(row.get("layer", "")),
                        "line_start": 0,
                        "line_end": 0,
                    })

                metrics = self._fts5.build_index(chunks)
                logger.info(
                    f"📊 FTS5 index built: {metrics['total_chunks']} chunks, "
                    f"{metrics['names_indexed']} names, "
                    f"{metrics['content_indexed']} content, "
                    f"{metrics['docs_indexed']} docs "
                    f"in {metrics['build_ms']}ms"
                )
            except Exception as e:
                logger.error(f"FTS5 build error: {e}")
                # Reset to allow retry
                self._fts5 = None

    @staticmethod
    def _extract_symbol_from_text(text: str):
        """Extract symbol name and kind from chunk text using regex."""
        import re
        patterns = [
            (r"class\s+(\w+)", "class"),
            (r"async\s+def\s+(\w+)", "async_function"),
            (r"def\s+(\w+)", "function"),
        ]
        for pat, kind in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1), kind
        return "", ""

    @staticmethod
    def _extract_docstring(text: str) -> str:
        """Extract first docstring from chunk text."""
        import re
        m = re.search(r'"""([\s\S]*?)"""', text)
        if m:
            return m.group(1).strip()[:500]
        m = re.search(r"'''([\s\S]*?)'''", text)
        if m:
            return m.group(1).strip()[:500]
        return ""

    # ── Incremental update ────────────────────────────────────

    def incremental_update_fts5(self, new_chunks: List[dict]) -> None:
        """Add new chunks to the FTS5 index incrementally."""
        if self._fts5 is None:
            # No index yet — full rebuild
            self._build_fts5_index()
            return

        try:
            added = self._fts5.add_chunks(new_chunks)
            if added > 0:
                logger.debug(f"📊 FTS5: +{added} chunks added incrementally")
        except Exception as e:
            logger.warning(f"FTS5 incremental update error: {e}")

    def remove_from_fts5(self, file_path: str) -> None:
        """Remove all chunks for a file from FTS5 indexes."""
        if self._fts5 is None:
            return
        try:
            removed = self._fts5.remove_file(file_path)
            if removed > 0:
                logger.debug(f"📊 FTS5: removed {removed} chunks for {file_path}")
        except Exception as e:
            logger.debug(f"FTS5 remove error: {e}")

    # ── Search ────────────────────────────────────────────────

    def _fts5_search(self, query: str, limit: int = 10) -> List[dict]:
        """FTS5 hybrid search — returns results with RRF scores.

        This is the NEW tier that gets added to hybrid_search_async.
        """
        self._build_fts5_index()
        if self._fts5 is None or self._fts5.is_empty:
            return []

        try:
            return self._fts5.hybrid_search_rrf(query, limit=limit)
        except Exception as e:
            logger.debug(f"FTS5 search error: {e}")
            return []

    async def _fts5_search_async(self, query: str, limit: int = 10) -> List[dict]:
        """Async wrapper for FTS5 search (non-blocking)."""
        return await asyncio.to_thread(self._fts5_search, query, limit)

    # ── Reset ─────────────────────────────────────────────────

    def reindex_fts5(self) -> None:
        """Reset FTS5 index, forcing full rebuild on next search."""
        with self._fts5_lock:
            if self._fts5 is not None:
                self._fts5.reset()
                self._fts5 = None
        logger.debug("FTS5 index reset for reindex")
