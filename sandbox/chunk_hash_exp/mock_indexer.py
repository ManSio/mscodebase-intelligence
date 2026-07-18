"""
Sandbox mock of the production indexing path for chunk-level cache.

Mirrors the REAL interface shapes from:
  - src/core/indexing/db_writer.py  (LanceDBWriter.write_records)
  - src/core/indexing/index_pipeline.py (IndexPipeline.process_file)
  - src/core/indexing/db_manager.py (schema)

But uses an in-memory dict instead of LanceDB, so we can test the
SKIP LOGIC (if chunk_hash in db: skip embed) without touching prod.

This is NOT production code. It exists only to validate the algorithm
before we write a minimal diff in indexer.py / db_writer.py / db_manager.py.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional


def chunk_hash(content: str) -> str:
    """Content-addressed hash for one chunk.

    Mirrors what we will add to db_manager schema as `chunk_hash`.
    Includes a prefix tag so it is distinguishable from file_hash.
    """
    return "ch:" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


@dataclass
class MockDB:
    """In-memory stand-in for LanceDB table.

    Records keyed by chunk_hash (the cache key for skip logic).
    Also keeps a count of how many times embed() was actually called.
    """

    records: Dict[str, dict] = field(default_factory=dict)
    embed_calls: int = 0  # how many times the embedder was invoked
    skip_calls: int = 0   # how many times we skipped due to cache hit

    def has_chunk(self, ch_hash: str) -> bool:
        return ch_hash in self.records

    def upsert(self, ch_hash: str, text: str, vector: list, metadata: dict) -> None:
        self.records[ch_hash] = {
            "chunk_hash": ch_hash,
            "text": text,
            "vector": vector,
            "metadata": metadata,
        }

    def stats(self) -> dict:
        return {
            "stored": len(self.records),
            "embed_calls": self.embed_calls,
            "skip_calls": self.skip_calls,
        }


class MockEmbedder:
    """Fake embedder that just counts calls and returns a dummy vector.

    In prod this is RemoteEmbedder.embed_batch — the expensive part we
    want to skip when the chunk hash is already known.
    """

    def __init__(self, db: MockDB, dim: int = 4):
        self._db = db
        self._dim = dim

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        self._db.embed_calls += len(texts)
        return [[0.0] * self._dim for _ in texts]


def process_file(
    db: MockDB,
    embedder: MockEmbedder,
    rel_path: str,
    chunks: List[dict],
) -> dict:
    """Sandbox replica of IndexPipeline.process_file skip-logic.

    Each item in `chunks` is {"text": str, "metadata": dict}.

    Logic under test:
      for each chunk:
          h = chunk_hash(text)
          if db.has_chunk(h): skip (no embed)
          else: embed + upsert

    Returns counts for assertions.
    """
    embedded = 0
    skipped = 0
    for chunk in chunks:
        text = chunk["text"]
        h = chunk_hash(text)
        if db.has_chunk(h):
            db.skip_calls += 1
            skipped += 1
            continue
        vec = embedder.embed_batch([text])[0]
        db.upsert(h, text, vec, chunk.get("metadata", {}))
        embedded += 1
    return {"embedded": embedded, "skipped": skipped}
# edited for cache test
# second edit for idle-timeout test
