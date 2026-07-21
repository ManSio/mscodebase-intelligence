"""SQLite FTS5 3-Index search engine.

Inspired by srclight/srclight (52★, MIT) — validated on MSCodeBase data:
- 6.6x faster than in-memory BM25 for symbol name queries
- Complementary results (10% overlap = 90% unique finds)

Architecture (4 tiers):
  Tier 1: names_fts  — porter tokenizer + split_identifier preprocessing
  Tier 2: LIKE on chunks table — substring fallback
  Tier 3: content_fts — trigram tokenizer for code body search
  Tier 4: docs_fts   — porter + unicode61 for natural language docstrings

Thread-safety: SQLite in WAL mode, one connection per Searcher instance.
"""

import logging
import re
import sqlite3
import threading
from typing import Any, Dict, List, Optional

__all__ = ["FTS5IndexManager"]
logger = logging.getLogger(__name__)

# ── srclight's split_identifier() — exact copy ────────────────

_SPLIT_IDENT_RE1 = re.compile(r"([a-z0-9])([A-Z])")
_SPLIT_IDENT_RE2 = re.compile(r"([A-Z]+)([A-Z][a-z])")


def split_identifier(name: str) -> str:
    """Split a code identifier into searchable tokens.

    Handles CamelCase, snake_case, :: qualifiers, and mixed styles.
    Returns both original-case and lowercased tokens for case-insensitive matching.

    Examples:
        "SQLiteDictionary"  → "SQLite Dictionary sqlite dictionary"
        "get_callers"       → "get callers"
        "OCRManager"        → "OCR Manager ocr manager"
        "hybridSearchAsync" → "hybrid Search Async search async"
        "BM25Mixin"         → "BM25 Mixin bm25 mixin"
    """
    if not name:
        return ""
    parts = re.split(r"::|->|\.", name)
    tokens: list[str] = []
    for part in parts:
        sub_parts = part.split("_")
        for sp in sub_parts:
            if not sp:
                continue
            s = _SPLIT_IDENT_RE1.sub(r"\1 \2", sp)
            s = _SPLIT_IDENT_RE2.sub(r"\1 \2", s)
            tokens.extend(t for t in s.split() if t)
    result_parts: list[str] = list(tokens)
    lower_parts = [t.lower() for t in tokens if t.lower() != t]
    result_parts.extend(lower_parts)
    return " ".join(result_parts)


# ── FTS5 Index Manager ────────────────────────────────────────

class FTS5IndexManager:
    """SQLite FTS5 manager with 3 specialized indexes.

    Thread-safety: each instance owns its own sqlite3.Connection.
    SQLite WAL mode allows concurrent reads during writes.
    """

    def __init__(self, in_memory: bool = True, db_path: str = ""):
        self._in_memory = in_memory
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._indexed_count = 0

    def _ensure_conn(self) -> sqlite3.Connection:
        """Lazy-init SQLite connection (must be called under _lock)."""
        if self._conn is not None:
            return self._conn
        if self._in_memory:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()
        return self._conn

    def _create_tables(self) -> None:
        """Create 3 FTS5 virtual tables + metadata table."""
        conn = self._conn

        # Tier 1: Symbol names (porter tokenizer, preprocessed with split_identifier)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS names_fts USING fts5(
                symbol_name, name_tokens, symbol_kind, file_path,
                tokenize='porter'
            )
        """)

        # Tier 2: Code content (trigram for substring matching)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
                chunk_text, file_path, symbol_name,
                tokenize='trigram'
            )
        """)

        # Tier 3: Docstrings (porter + unicode61 for natural language)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
                docstring, file_path, symbol_name,
                tokenize='porter unicode61'
            )
        """)

        # Metadata table for full-text retrieval
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                file_path TEXT,
                chunk_index INTEGER,
                text TEXT,
                symbol_name TEXT,
                symbol_kind TEXT,
                docstring TEXT,
                layer TEXT,
                line_start INTEGER,
                line_end INTEGER,
                indexed_at TEXT
            )
        """)
        conn.commit()

    # ── Index building ────────────────────────────────────────

    def build_index(self, chunks: List[dict]) -> Dict[str, Any]:
        """Build all 3 FTS5 indexes from chunks.

        Args:
            chunks: List of dicts with keys: file_path, chunk_index, text,
                    symbol_name (optional), symbol_kind (optional),
                    docstring (optional), layer (optional),
                    line_start (optional), line_end (optional)

        Returns:
            Dict with build metrics.
        """
        import time
        start = time.perf_counter()

        with self._lock:
            conn = self._ensure_conn()
            n_names = n_content = n_docs = 0

            for ch in chunks:
                chunk_id = f"{ch['file_path']}:{ch.get('chunk_index', 0)}"
                symbol_name = ch.get("symbol_name", "")
                symbol_kind = ch.get("symbol_kind", "")
                file_path = ch.get("file_path", "")
                text = ch.get("text", "")
                docstring = ch.get("docstring", "")
                layer = ch.get("layer", "")
                line_start = ch.get("line_start", 0)
                line_end = ch.get("line_end", 0)

                # Metadata
                conn.execute(
                    "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (chunk_id, file_path, ch.get("chunk_index", 0), text,
                     symbol_name, symbol_kind, docstring, layer,
                     line_start, line_end, ""),
                )

                # Tier 1: Names (split_identifier preprocessing)
                if symbol_name:
                    name_tokens = split_identifier(symbol_name)
                    if name_tokens.strip():
                        conn.execute(
                            "INSERT INTO names_fts VALUES (?,?,?,?)",
                            (symbol_name, name_tokens, symbol_kind, file_path),
                        )
                        n_names += 1

                # Tier 2: Content (trigram — full text)
                conn.execute(
                    "INSERT INTO content_fts VALUES (?,?,?)",
                    (text, file_path, symbol_name),
                )
                n_content += 1

                # Tier 3: Docs (porter + unicode61)
                if docstring and docstring.strip():
                    conn.execute(
                        "INSERT INTO docs_fts VALUES (?,?,?)",
                        (docstring, file_path, symbol_name),
                    )
                    n_docs += 1

            conn.commit()
            self._indexed_count = len(chunks)

        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "build_ms": round(elapsed_ms, 1),
            "total_chunks": len(chunks),
            "names_indexed": n_names,
            "content_indexed": n_content,
            "docs_indexed": n_docs,
        }

    def add_chunks(self, new_chunks: List[dict]) -> int:
        """Incrementally add new chunks to all 3 FTS5 indexes.

        Returns: number of chunks added.
        """
        if not new_chunks:
            return 0

        with self._lock:
            conn = self._ensure_conn()
            added = 0

            for ch in new_chunks:
                chunk_id = f"{ch['file_path']}:{ch.get('chunk_index', 0)}"

                # Skip if already exists
                exists = conn.execute(
                    "SELECT 1 FROM chunks WHERE chunk_id=?", (chunk_id,)
                ).fetchone()
                if exists:
                    continue

                symbol_name = ch.get("symbol_name", "")
                symbol_kind = ch.get("symbol_kind", "")
                file_path = ch.get("file_path", "")
                text = ch.get("text", "")
                docstring = ch.get("docstring", "")
                layer = ch.get("layer", "")

                conn.execute(
                    "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (chunk_id, file_path, ch.get("chunk_index", 0), text,
                     symbol_name, symbol_kind, docstring, layer,
                     ch.get("line_start", 0), ch.get("line_end", 0), ""),
                )

                if symbol_name:
                    name_tokens = split_identifier(symbol_name)
                    if name_tokens.strip():
                        conn.execute(
                            "INSERT INTO names_fts VALUES (?,?,?,?)",
                            (symbol_name, name_tokens, symbol_kind, file_path),
                        )

                conn.execute(
                    "INSERT INTO content_fts VALUES (?,?,?)",
                    (text, file_path, symbol_name),
                )

                if docstring and docstring.strip():
                    conn.execute(
                        "INSERT INTO docs_fts VALUES (?,?,?)",
                        (docstring, file_path, symbol_name),
                    )

                added += 1

            conn.commit()
            self._indexed_count += added
            return added

    def remove_file(self, file_path: str) -> int:
        """Remove all chunks for a given file from all indexes.

        Returns: number of chunks removed.
        """
        with self._lock:
            if self._conn is None:
                return 0
            conn = self._conn

            # Count before delete
            before = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE file_path=?", (file_path,)
            ).fetchone()[0]

            # Delete from metadata + all FTS5 tables
            conn.execute("DELETE FROM chunks WHERE file_path=?", (file_path,))
            # FTS5 delete uses the same DELETE syntax
            try:
                conn.execute(
                    "DELETE FROM names_fts WHERE file_path=?", (file_path,)
                )
            except Exception:
                pass  # FTS5 delete may fail if table is empty
            try:
                conn.execute(
                    "DELETE FROM content_fts WHERE file_path=?", (file_path,)
                )
            except Exception:
                pass
            try:
                conn.execute(
                    "DELETE FROM docs_fts WHERE file_path=?", (file_path,)
                )
            except Exception:
                pass

            conn.commit()
            self._indexed_count -= before
            return before

    # ── Search methods ────────────────────────────────────────

    def search_names(self, query: str, limit: int = 10) -> List[dict]:
        """Tier 1: Search symbol names with porter + split_identifier."""
        tokens = split_identifier(query)
        if not tokens.strip():
            return []

        terms = tokens.split()
        # OR query: match any token
        fts_q = " OR ".join(f'"{t}"' for t in terms)

        with self._lock:
            if self._conn is None:
                return []
            try:
                rows = self._conn.execute(
                    """SELECT symbol_name, file_path, symbol_kind, rank
                       FROM names_fts WHERE names_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (fts_q, limit),
                ).fetchall()
                return [
                    {"name": r[0], "file": r[1], "kind": r[2], "rank": r[3], "tier": "names"}
                    for r in rows
                ]
            except Exception as e:
                logger.debug(f"FTS5 names search error: {e}")
                return []

    def search_substring(self, query: str, limit: int = 10) -> List[dict]:
        """Tier 2: LIKE-based substring search (fallback)."""
        with self._lock:
            if self._conn is None:
                return []
            try:
                like_q = f"%{query}%"
                rows = self._conn.execute(
                    """SELECT symbol_name, file_path, symbol_kind, chunk_id
                       FROM chunks WHERE symbol_name LIKE ? OR text LIKE ?
                       LIMIT ?""",
                    (like_q, like_q, limit),
                ).fetchall()
                return [
                    {"name": r[0], "file": r[1], "kind": r[2], "rank": 0, "tier": "substring"}
                    for r in rows
                ]
            except Exception as e:
                logger.debug(f"FTS5 substring search error: {e}")
                return []

    def search_content(self, query: str, limit: int = 10) -> List[dict]:
        """Tier 3: Trigram search for code body substring matching."""
        with self._lock:
            if self._conn is None:
                return []
            try:
                rows = self._conn.execute(
                    """SELECT symbol_name, file_path, rank
                       FROM content_fts WHERE content_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (f'"{query}"', limit),
                ).fetchall()
                return [
                    {"name": r[0], "file": r[1], "kind": "", "rank": r[2], "tier": "content"}
                    for r in rows
                ]
            except Exception as e:
                logger.debug(f"FTS5 content search error: {e}")
                return []

    def search_docs(self, query: str, limit: int = 10) -> List[dict]:
        """Tier 4: Porter-stemmed docstring search."""
        # Tokenize query for porter index
        terms = query.lower().split()
        if not terms:
            return []
        fts_q = " OR ".join(f'"{t}"' for t in terms)

        with self._lock:
            if self._conn is None:
                return []
            try:
                rows = self._conn.execute(
                    """SELECT symbol_name, file_path, rank
                       FROM docs_fts WHERE docs_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (fts_q, limit),
                ).fetchall()
                return [
                    {"name": r[0], "file": r[1], "kind": "", "rank": r[2], "tier": "docs"}
                    for r in rows
                ]
            except Exception as e:
                logger.debug(f"FTS5 docs search error: {e}")
                return []

    def hybrid_search_rrf(
        self,
        query: str,
        limit: int = 10,
        rrf_k: int = 60,
    ) -> List[dict]:
        """4-tier search with Reciprocal Rank Fusion.

        Combines: names + substring + content + docs.
        Returns top-N results sorted by RRF score.
        """
        scores: Dict[str, float] = {}
        data: Dict[str, dict] = {}

        tier_fns = [
            ("names", self.search_names),
            ("substring", self.search_substring),
            ("content", self.search_content),
            ("docs", self.search_docs),
        ]

        for tier_name, search_fn in tier_fns:
            try:
                results = search_fn(query, limit=limit * 2)
            except Exception:
                results = []
            for rank, r in enumerate(results):
                chunk_key = f"{r['name']}:{r['file']}"
                rrf_score = 1.0 / (rrf_k + rank + 1)
                scores[chunk_key] = scores.get(chunk_key, 0.0) + rrf_score
                if chunk_key not in data:
                    data[chunk_key] = r
                    data[chunk_key]["rrf_detail"] = {}
                data[chunk_key]["rrf_detail"][tier_name] = rrf_score

        # Sort by RRF score
        sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)[:limit]

        final = []
        for key in sorted_keys:
            r = data[key]
            # Get full text from metadata
            full_text = ""
            with self._lock:
                if self._conn is not None:
                    try:
                        row = self._conn.execute(
                            "SELECT text FROM chunks WHERE symbol_name=? AND file_path=?",
                            (r["name"], r["file"]),
                        ).fetchone()
                        if row:
                            full_text = row[0]
                    except Exception:
                        pass

            final.append({
                "text": full_text,
                "metadata": {
                    "file": r["file"],
                    "symbol_name": r["name"],
                    "symbol_kind": r.get("kind", ""),
                    "rrf_detail": r.get("rrf_detail", {}),
                },
                "final_score": scores[key],
                "source": "fts5_hybrid",
            })

        return final

    def get_full_text(self, symbol_name: str, file_path: str) -> str:
        """Retrieve full text for a chunk from metadata."""
        with self._lock:
            if self._conn is None:
                return ""
            try:
                row = self._conn.execute(
                    "SELECT text FROM chunks WHERE symbol_name=? AND file_path=?",
                    (symbol_name, file_path),
                ).fetchone()
                return row[0] if row else ""
            except Exception:
                return ""

    # ── Lifecycle ─────────────────────────────────────────────

    def reset(self) -> None:
        """Drop and recreate all indexes."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
            self._indexed_count = 0

    @property
    def is_empty(self) -> bool:
        return self._indexed_count == 0

    @property
    def chunk_count(self) -> int:
        return self._indexed_count

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
