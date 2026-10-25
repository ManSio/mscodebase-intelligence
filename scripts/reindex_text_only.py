"""Phase 3 text-only full reindex: rebuild SQLite chunks + AST graph, no vectors.

Use this after wiping the vector/chunk/graph stores. It walks the project,
parses every file through IndexParser (same AST/symbol pipeline as the indexer),
writes text chunks to SQLite/FTS5 and updates PropertyGraph.

No embeddings are computed: vectors are recreated on demand at query time.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import threading
import time
from pathlib import Path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.exists():
        print(f"FATAL: project not found: {project}", file=sys.stderr)
        return 2

    # Imports are local so `--help` works without a configured project.
    from src.core.artifact_paths import get_graph_db_path
    from src.core.graph import PropertyGraph
    from src.core.indexing.chunk_store import SQLiteChunkStore, get_chunks_db_path
    from src.core.indexing.db_writer import LanceDBWriter
    from src.core.indexing.file_guard import FileGuard
    from src.core.indexing.index_parser import IndexParser
    from src.core.indexing.index_pipeline import IndexPipeline
    from src.core.indexing.parser import CodeParser
    from src.core.search.graph_adapter import SymbolIndexAdapter
    from src.sources.local_fs.windows import SafePathManager

    print(f"[text-reindex] project={project}")
    t0 = time.perf_counter()

    cfg_dir = project / ".mscodebase"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    guard = FileGuard(project)
    code_parser = CodeParser()
    path_manager = SafePathManager(cfg_dir)
    index_parser = IndexParser(
        parser=code_parser,
        path_manager=path_manager,
        project_path=project,
    )

    graph_db = get_graph_db_path(project)
    graph_db.parent.mkdir(parents=True, exist_ok=True)
    pg = PropertyGraph(graph_db)
    symbol_index = SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)

    store = SQLiteChunkStore(get_chunks_db_path(project))
    writer = LanceDBWriter(
        table=None,
        table_write_lock=threading.RLock(),
        index_lock=threading.Lock(),
        embedder=None,
        chunk_store=store,
    )
    pipeline = IndexPipeline(
        embedder=None,
        parser=code_parser,
        index_parser=index_parser,
        symbol_index=symbol_index,
        symbol_index_lock=threading.Lock(),
        project_path=project,
        table=None,
    )

    files_seen = 0
    files_indexed = 0
    chunks_written = 0
    errors = 0
    seen_paths: set[str] = set()
    pruned = 0
    try:
        for root, dirs, files in os.walk(str(project)):
            dirs[:] = [d for d in dirs if not guard.should_skip_dir(d)]
            for name in files:
                if args.max_files and files_seen >= args.max_files:
                    break
                fp = Path(root) / name
                if guard.should_skip_file(fp):
                    continue
                files_seen += 1
                rel = fp.relative_to(project).as_posix()
                seen_paths.add(rel)
                try:
                    content = fp.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if not content.strip():
                    continue
                rel = fp.relative_to(project).as_posix()
                current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                try:
                    parsed = pipeline.process_file(
                        rel_path_str=rel,
                        full_path=fp,
                        content=content,
                        current_hash=current_hash,
                    )
                except Exception as e:
                    errors += 1
                    if not args.quiet:
                        print(f"[text-reindex] parse error {rel}: {e}")
                    continue
                if not parsed:
                    continue
                records = writer.write_text_records(parsed) if parsed.get("skip_vectors") else []
                if records:
                    files_indexed += 1
                    chunks_written += len(records)
                if not args.quiet and files_indexed and files_indexed % 100 == 0:
                    print(
                        f"[text-reindex] files={files_indexed} chunks={chunks_written} "
                        f"seen={files_seen}"
                    )
            else:
                continue
            break

        # Persist graph metadata (head) if available.
        try:
            from src.core.intelligence.verify_on_read import resolve_head_dirty

            fresh = resolve_head_dirty(project)
            if fresh is not None:
                head, _dirty = fresh
                pg.set_meta("build_head", head)
        except Exception:
            pass

        # Prune stale rows (removed files + now-excluded experiments/**).
        # Skip for partial runs (--max-files), otherwise we would delete files
        # that were simply not visited.
        if not args.max_files:
            existing = {
                str(r.get("file_path") or "").replace("\\", "/")
                for r in store.all_records()
            }
            stale = sorted(existing - seen_paths)
            if stale:
                store.delete_files(stale)
                pruned = len(stale)

        elapsed = time.perf_counter() - t0
        print(
            f"[text-reindex] done files={files_indexed} chunks={chunks_written} "
            f"seen={files_seen} errors={errors} pruned={pruned} sqlite_rows={store.count()} "
            f"graph_nodes={pg.count_nodes()} graph_edges={pg.count_edges()} "
            f"elapsed={elapsed:.1f}s"
        )
        if chunks_written <= 0:
            print("FATAL: zero chunks written (empty project?)", file=sys.stderr)
            return 2
        return 0
    finally:
        store.close()
        try:
            pg.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
