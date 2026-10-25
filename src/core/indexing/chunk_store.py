"""SQLite/FTS5 chunk store (Phase 3 of the approved stack migration).

Stores chunk text + metadata WITHOUT vectors. Candidate retrieval is done by
SQLite FTS5 (BM25 rank), vectors are recomputed on demand only for the top-N
candidates (see src/core/search/ondemand_rerank.py).

The store is intentionally independent from LanceDB: once populated, the
search path can run with the LanceDB vector table unavailable.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "SQLiteChunkStore",
    "get_chunks_db_path",
    "migrate_from_lancedb",
]

logger = logging.getLogger("mscodebase_server.chunk_store")

_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-я0-9_]+")


def get_chunks_db_path(project_path: Path | str) -> Path:
    """Path to the lightweight chunk DB.

    Default: ``<project>/.mscodebase/chunks.db`` (owner-approved location).
    ``MSCODEBASE_CHUNKS_DB`` overrides it (tests / alternate installations).
    """
    import os

    env = os.getenv("MSCODEBASE_CHUNKS_DB", "").strip()
    if env:
        return Path(env)
    return Path(project_path).resolve() / ".mscodebase" / "chunks.db"


def _fts_query(query: str) -> str:
    """Build a safe FTS5 MATCH expression from a free-form query."""
    terms = _TOKEN_RE.findall(query or "")
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in terms)


class SQLiteChunkStore:
    """Persistent text chunk store backed by SQLite + FTS5."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        # Optional FTS5 column weights: (text, text_full, symbol_name, docstring, file_path)
        self.field_weights: Optional[tuple[float, ...]] = None

    # ── Lifecycle ─────────────────────────────────────────────

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        self._conn = conn
        self._create_schema()
        return conn

    def _create_schema(self) -> None:
        conn = self._conn
        assert conn is not None
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT UNIQUE NOT NULL,
                file_path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                text_full TEXT,
                symbol_name TEXT,
                symbol_kind TEXT,
                docstring TEXT,
                layer TEXT,
                start_line INTEGER,
                end_line INTEGER,
                indexed_at TEXT,
                chunk_hash TEXT,
                file_hash TEXT,
                file_mtime_ns INTEGER,
                file_size INTEGER,
                metadata_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                text, text_full, symbol_name, docstring, file_path,
                content='chunks', content_rowid='rowid',
                tokenize='porter unicode61'
            )
            """
        )
        conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, text, text_full, symbol_name, docstring, file_path)
                VALUES (new.rowid, new.text, new.text_full, new.symbol_name, new.docstring, new.file_path);
            END;
            CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, text, text_full, symbol_name, docstring, file_path)
                VALUES('delete', old.rowid, old.text, old.text_full, old.symbol_name, old.docstring, old.file_path);
            END;
            CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, text, text_full, symbol_name, docstring, file_path)
                VALUES('delete', old.rowid, old.text, old.text_full, old.symbol_name, old.docstring, old.file_path);
                INSERT INTO chunks_fts(rowid, text, text_full, symbol_name, docstring, file_path)
                VALUES (new.rowid, new.text, new.text_full, new.symbol_name, new.docstring, new.file_path);
            END;
            """
        )
        conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except (sqlite3.Error, OSError):
                    pass
                self._conn = None

    # ── Writes ────────────────────────────────────────────────

    def upsert_records(self, records: Iterable[Dict[str, Any]]) -> int:
        """Insert/replace chunk records; stale rows of touched files are removed."""
        rows = list(records)
        if not rows:
            return 0

        files = {str(r.get("file_path", "")) for r in rows if r.get("file_path")}
        with self._lock:
            conn = self._ensure_conn()
            cur = conn.cursor()
            try:
                for fp in files:
                    cur.execute("DELETE FROM chunks WHERE file_path = ?", (fp,))
                for r in rows:
                    fp = str(r.get("file_path", ""))
                    ci = int(r.get("chunk_index", 0) or 0)
                    chunk_id = str(r.get("chunk_id") or r.get("id") or f"{fp}:{ci}")
                    meta = {k: v for k, v in r.items() if k not in {
                        "text", "text_full", "symbol_name", "symbol_kind",
                        "docstring", "file_path", "chunk_index", "layer",
                        "start_line", "end_line", "indexed_at", "chunk_hash",
                        "file_hash", "file_mtime_ns", "file_size", "chunk_id", "id",
                    }}
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO chunks (
                            chunk_id, file_path, chunk_index, text, text_full,
                            symbol_name, symbol_kind, docstring, layer,
                            start_line, end_line, indexed_at, chunk_hash,
                            file_hash, file_mtime_ns, file_size, metadata_json
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            chunk_id,
                            fp,
                            ci,
                            str(r.get("text", "") or ""),
                            str(r.get("text_full", r.get("text", "")) or ""),
                            str(r.get("symbol_name", "") or ""),
                            str(r.get("symbol_kind", r.get("symbol_type", "")) or ""),
                            str(r.get("docstring", "") or ""),
                            str(r.get("layer", "") or ""),
                            int(r.get("start_line", 0) or 0),
                            int(r.get("end_line", 0) or 0),
                            str(r.get("indexed_at", "") or ""),
                            str(r.get("chunk_hash", "") or ""),
                            str(r.get("file_hash", "") or ""),
                            int(r.get("file_mtime_ns", 0) or 0),
                            int(r.get("file_size", 0) or 0),
                            json.dumps(meta, ensure_ascii=False, default=str),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return len(rows)

    def delete_file(self, file_path: str) -> int:
        with self._lock:
            conn = self._ensure_conn()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM chunks WHERE file_path = ?", (file_path,))
            n = int(cur.fetchone()[0])
            if n:
                cur.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
                conn.commit()
            return n

    def delete_files(self, file_paths: Iterable[str]) -> int:
        """Delete all chunks for a set of files (FTS triggers stay in sync)."""
        files = [str(fp) for fp in file_paths if fp]
        if not files:
            return 0
        with self._lock:
            conn = self._ensure_conn()
            cur = conn.cursor()
            for i in range(0, len(files), 500):
                batch = files[i : i + 500]
                placeholders = ",".join("?" for _ in batch)
                cur.execute(
                    f"DELETE FROM chunks WHERE file_path IN ({placeholders})", batch
                )
            conn.commit()
        return len(files)

    # ── Reads ─────────────────────────────────────────────────

    def count(self) -> int:
        with self._lock:
            conn = self._ensure_conn()
            return int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def file_hash(self, file_path: str) -> Optional[str]:
        """Stored content hash for a file (None if the file is absent)."""
        with self._lock:
            conn = self._ensure_conn()
            row = conn.execute(
                "SELECT file_hash FROM chunks WHERE file_path = ? LIMIT 1",
                (file_path,),
            ).fetchone()
            return str(row[0]) if row and row[0] else None

    def files_count(self) -> int:
        with self._lock:
            conn = self._ensure_conn()
            return int(
                conn.execute("SELECT COUNT(DISTINCT file_path) FROM chunks").fetchone()[0]
            )

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """FTS5 candidate retrieval, ranked by BM25.

        Returns the same shape the engine's RRF/rerank steps expect:
        ``{"text": ..., "metadata": {...}, "final_score": ...}``.
        """
        fts_q = _fts_query(query)
        if not fts_q:
            return []

        with self._lock:
            conn = self._ensure_conn()
            try:
                weights = self.field_weights
                if weights:
                    rank_expr = "bm25(chunks_fts, ?, ?, ?, ?, ?)"
                    params = (*[float(w) for w in weights[:5]], fts_q, int(limit))
                else:
                    rank_expr = "bm25(chunks_fts)"
                    params = (fts_q, int(limit))
                rows = conn.execute(
                    f"""
                    SELECT c.chunk_id, c.file_path, c.chunk_index, c.text,
                           c.text_full, c.symbol_name, c.symbol_kind,
                           c.docstring, c.layer, c.start_line, c.end_line,
                           c.indexed_at, c.file_hash, c.chunk_hash,
                           c.metadata_json, {rank_expr} AS rank
                    FROM chunks_fts
                    JOIN chunks c ON c.rowid = chunks_fts.rowid
                    WHERE chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
            except sqlite3.Error as e:
                logger.debug(f"FTS5 query failed ({e}); LIKE fallback")
                like = f"%{query}%"
                rows = conn.execute(
                    """
                    SELECT chunk_id, file_path, chunk_index, text, text_full,
                           symbol_name, symbol_kind, docstring, layer,
                           start_line, end_line, indexed_at, file_hash,
                           chunk_hash, metadata_json, 0.0 AS rank
                    FROM chunks
                    WHERE text LIKE ? OR text_full LIKE ? OR symbol_name LIKE ?
                    LIMIT ?
                    """,
                    (like, like, like, int(limit)),
                ).fetchall()

        out: List[Dict[str, Any]] = []
        for idx, r in enumerate(rows):
            rank = float(r[15] or 0.0)
            meta = {
                "file": r[1],
                "chunk_index": int(r[2] or 0),
                "symbol_name": r[5] or "",
                "symbol_kind": r[6] or "",
                "layer": r[8] or "",
                "start_line": int(r[9] or 0),
                "end_line": int(r[10] or 0),
                "indexed_at": r[11] or "",
                "file_hash": r[12] or "",
                "chunk_hash": r[13] or "",
                "source": "sqlite_fts5",
            }
            try:
                extra = json.loads(r[14] or "{}")
                if isinstance(extra, dict):
                    meta.update({k: v for k, v in extra.items() if k not in meta})
            except (json.JSONDecodeError, TypeError):
                pass
            out.append(
                {
                    "text": r[4] or r[3] or "",
                    "metadata": meta,
                    "final_score": -rank if rank else 1.0 / (idx + 1),
                    "source": "sqlite_fts5",
                }
            )
        return out

    def get_symbol_chunk(
        self, file_path: str, symbol_name: str
    ) -> Optional[Dict[str, Any]]:
        """Return the first chunk for a (file, symbol) pair, or None."""
        if not file_path or not symbol_name:
            return None
        with self._lock:
            conn = self._ensure_conn()
            row = conn.execute(
                """
                SELECT chunk_id, file_path, chunk_index, text, text_full,
                       symbol_name, symbol_kind, docstring, layer,
                       start_line, end_line, indexed_at, file_hash,
                       chunk_hash, metadata_json, 0.0 AS rank
                FROM chunks
                WHERE file_path = ? AND symbol_name = ?
                ORDER BY chunk_index
                LIMIT 1
                """,
                (file_path, symbol_name),
            ).fetchone()
        if not row:
            return None
        meta = {
            "file": row[1],
            "chunk_index": int(row[2] or 0),
            "symbol_name": row[5] or "",
            "symbol_kind": row[6] or "",
            "layer": row[8] or "",
            "start_line": int(row[9] or 0),
            "end_line": int(row[10] or 0),
            "indexed_at": row[11] or "",
            "file_hash": row[12] or "",
            "chunk_hash": row[13] or "",
            "source": "sqlite_graph_expand",
        }
        try:
            extra = json.loads(row[14] or "{}")
            if isinstance(extra, dict):
                meta.update({k: v for k, v in extra.items() if k not in meta})
        except (json.JSONDecodeError, TypeError):
            pass
        return {
            "text": row[4] or row[3] or "",
            "metadata": meta,
            "final_score": 0.0,
            "source": "sqlite_graph_expand",
        }

    def get_file_head(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Return the chunk_index=0 chunk for a file (module head), or None."""
        if not file_path:
            return None
        with self._lock:
            conn = self._ensure_conn()
            row = conn.execute(
                """
                SELECT chunk_id, file_path, chunk_index, text, text_full,
                       symbol_name, symbol_kind, docstring, layer,
                       start_line, end_line, indexed_at, file_hash,
                       chunk_hash, metadata_json, 0.0 AS rank
                FROM chunks
                WHERE file_path = ?
                ORDER BY chunk_index
                LIMIT 1
                """,
                (file_path,),
            ).fetchone()
        if not row:
            return None
        meta = {
            "file": row[1],
            "chunk_index": int(row[2] or 0),
            "symbol_name": row[5] or "",
            "symbol_kind": row[6] or "",
            "layer": row[8] or "",
            "start_line": int(row[9] or 0),
            "end_line": int(row[10] or 0),
            "indexed_at": row[11] or "",
            "file_hash": row[12] or "",
            "chunk_hash": row[13] or "",
            "source": "sqlite_module_head",
        }
        try:
            extra = json.loads(row[14] or "{}")
            if isinstance(extra, dict):
                meta.update({k: v for k, v in extra.items() if k not in meta})
        except (json.JSONDecodeError, TypeError):
            pass
        return {
            "text": row[4] or row[3] or "",
            "metadata": meta,
            "final_score": 0.0,
            "source": "sqlite_module_head",
        }

    def get_chunk_near_line(
        self, file_path: str, line: int
    ) -> Optional[Dict[str, Any]]:
        """Return the nearest chunk at/just before a source line, or None."""
        if not file_path:
            return None
        with self._lock:
            conn = self._ensure_conn()
            row = conn.execute(
                """
                SELECT chunk_id, file_path, chunk_index, text, text_full,
                       symbol_name, symbol_kind, docstring, layer,
                       start_line, end_line, indexed_at, file_hash,
                       chunk_hash, metadata_json, 0.0 AS rank
                FROM chunks
                WHERE file_path = ? AND start_line <= ?
                ORDER BY start_line DESC
                LIMIT 1
                """,
                (file_path, int(line)),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    SELECT chunk_id, file_path, chunk_index, text, text_full,
                           symbol_name, symbol_kind, docstring, layer,
                           start_line, end_line, indexed_at, file_hash,
                           chunk_hash, metadata_json, 0.0 AS rank
                    FROM chunks
                    WHERE file_path = ?
                    ORDER BY start_line ASC
                    LIMIT 1
                    """,
                    (file_path,),
                ).fetchone()
        if not row:
            return None
        meta = {
            "file": row[1],
            "chunk_index": int(row[2] or 0),
            "symbol_name": row[5] or "",
            "symbol_kind": row[6] or "",
            "layer": row[8] or "",
            "start_line": int(row[9] or 0),
            "end_line": int(row[10] or 0),
            "indexed_at": row[11] or "",
            "file_hash": row[12] or "",
            "chunk_hash": row[13] or "",
            "source": "sqlite_graph_line",
        }
        try:
            extra = json.loads(row[14] or "{}")
            if isinstance(extra, dict):
                meta.update({k: v for k, v in extra.items() if k not in meta})
        except (json.JSONDecodeError, TypeError):
            pass
        return {
            "text": row[4] or row[3] or "",
            "metadata": meta,
            "final_score": 0.0,
            "source": "sqlite_graph_line",
        }

    def all_records(self) -> List[Dict[str, Any]]:
        """All chunks (for BM25 compatibility / diagnostics)."""
        with self._lock:
            conn = self._ensure_conn()
            rows = conn.execute(
                """
                SELECT chunk_id, file_path, chunk_index, text, text_full,
                       symbol_name, symbol_kind, docstring, layer,
                       start_line, end_line, indexed_at, chunk_hash,
                       file_hash, file_mtime_ns, file_size, metadata_json
                FROM chunks
                """
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "chunk_id": r[0],
                    "file_path": r[1],
                    "chunk_index": int(r[2] or 0),
                    "text": r[3] or "",
                    "text_full": r[4] or "",
                    "symbol_name": r[5] or "",
                    "symbol_kind": r[6] or "",
                    "docstring": r[7] or "",
                    "layer": r[8] or "",
                    "start_line": int(r[9] or 0),
                    "end_line": int(r[10] or 0),
                    "indexed_at": r[11] or "",
                    "chunk_hash": r[12] or "",
                    "file_hash": r[13] or "",
                    "file_mtime_ns": int(r[14] or 0),
                    "file_size": int(r[15] or 0),
                }
            )
        return out


def migrate_from_lancedb(
    lancedb_path: Path | str,
    sqlite_path: Path | str,
    table_name: str = "codebase_chunks",
    batch_size: int = 500,
) -> Dict[str, Any]:
    """Dump LanceDB chunks into the SQLite store (text + metadata, no vectors)."""
    import lancedb

    db = lancedb.connect(str(lancedb_path))
    table = db.open_table(table_name)
    store = SQLiteChunkStore(sqlite_path)
    try:
        df = table.to_pandas()
        if df is None or df.empty:
            return {"migrated": 0, "files": 0}

        records: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            text = str(row.get("text", "") or "")
            text_full = str(row.get("text_full", "") or text)
            file_path = str(row.get("file_path", "") or "")
            chunk_index = int(row.get("chunk_index", 0) or 0)
            symbol_name = ""
            symbol_kind = str(row.get("symbol_type", "") or "")
            m = re.search(r"(?:class|def|async\s+def)\s+(\w+)", text)
            if m:
                symbol_name = m.group(1)
            _meta = {}
            for key in ("summary", "module_name", "hierarchy_level", "is_public",
                        "parent_id", "callees", "health_score", "health_band",
                        "source"):
                if key in row:
                    _meta[key] = row.get(key)
            records.append(
                {
                    "chunk_id": str(row.get("id") or f"{file_path}:{chunk_index}"),
                    "file_path": file_path,
                    "chunk_index": chunk_index,
                    "text": text,
                    "text_full": text_full,
                    "symbol_name": symbol_name,
                    "symbol_kind": symbol_kind,
                    "docstring": "",
                    "layer": str(row.get("layer", "") or ""),
                    "start_line": int(row.get("start_line", 0) or 0),
                    "end_line": int(row.get("end_line", 0) or 0),
                    "indexed_at": str(row.get("indexed_at", "") or ""),
                    "chunk_hash": str(row.get("chunk_hash", "") or ""),
                    "file_hash": str(row.get("file_hash", "") or ""),
                    "file_mtime_ns": int(row.get("file_mtime_ns", 0) or 0),
                    "file_size": int(row.get("file_size", 0) or 0),
                    **_meta,
                }
            )
        # One upsert for the whole snapshot: file-level delete must see ALL
        # chunks of a file at once, otherwise a later batch deletes chunks
        # inserted by an earlier batch of the same file.
        store.upsert_records(records)
        return {"migrated": len(records), "files": store.files_count()}
    finally:
        store.close()
