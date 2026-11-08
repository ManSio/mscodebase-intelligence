"""Phase 3 migration: LanceDB chunks -> SQLite/FTS5 text store.

Usage:
    python scripts/migrate_chunks_to_sqlite.py --project D:\\Project\\MSCodeBase

The source LanceDB path is resolved via artifact_paths.get_db_path(project).
The destination is <project>/.mscodebase/chunks.db (override: --sqlite).
No vectors are copied; search recomputes them on demand (E25).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--lancedb", default="")
    parser.add_argument("--sqlite", default="")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.exists():
        print(f"FATAL: project not found: {project}", file=sys.stderr)
        return 2

    from src.core.artifact_paths import get_db_path
    from src.core.indexing.chunk_store import get_chunks_db_path, migrate_from_lancedb

    lancedb_path = Path(args.lancedb) if args.lancedb else get_db_path(project)
    sqlite_path = Path(args.sqlite) if args.sqlite else get_chunks_db_path(project)

    if not lancedb_path.exists():
        print(f"FATAL: LanceDB not found: {lancedb_path}", file=sys.stderr)
        return 2

    result = migrate_from_lancedb(lancedb_path, sqlite_path)
    if result.get("migrated", 0) <= 0:
        print("FATAL: zero chunks migrated (empty source?)", file=sys.stderr)
        return 2

    print(
        f"OK migrated={result['migrated']} files={result['files']} "
        f"sqlite={sqlite_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
