"""
One-time backfill: compute chunk_hash = sha256(text) for all existing chunks.

This is needed because the chunk_hash column was added to the schema AFTER
the index was built, so existing rows have NULL chunk_hash. Without this,
the chunk-level cache never hits on the existing index.

Run once after deploying the chunk-cache feature:
    python scripts/backfill_chunk_hash.py

Safe: reads all chunks, computes hash from `text`, rewrites table with
full schema (same as migration strategy 2). Does NOT re-embed.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.indexing.db_manager import LanceDBManager  # noqa: F401 (ensures import path)


def main() -> int:
    project_root = Path("D:/Project/MSCodeBase")
    db_base = project_root / ".codebase_indices"

    # Find the actual lance db directory (lancedb_v2 / index_*.db)
    import lancedb

    candidate_dirs = list(db_base.rglob("index_*.db"))
    if not candidate_dirs:
        print("No LanceDB index found. Nothing to backfill.")
        return 0

    db_path = candidate_dirs[0]
    print(f"Backfilling: {db_path}")

    db = lancedb.connect(str(db_path))
    if "codebase_chunks" not in db.table_names():
        print("Table codebase_chunks not found. Nothing to backfill.")
        return 0

    table = db.open_table("codebase_chunks")
    df = table.to_pandas()
    if "chunk_hash" not in df.columns:
        print("chunk_hash column missing — run migration first.")
        return 1

    filled_before = df["chunk_hash"].notna().sum()
    print(f"Before: {filled_before}/{len(df)} have chunk_hash")

    def _calc(t: str) -> str:
        return "ch:" + hashlib.sha256(str(t).encode("utf-8")).hexdigest()[:32]

    df["chunk_hash"] = df["text"].apply(_calc)

    # Rewrite table with full schema (recreate)
    db.drop_table("codebase_chunks")
    table = db.create_table("codebase_chunks", df)

    filled_after = table.to_pandas()["chunk_hash"].notna().sum()
    print(f"After: {filled_after}/{len(df)} have chunk_hash")
    print("Backfill complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
