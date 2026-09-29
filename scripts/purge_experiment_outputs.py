#!/usr/bin/env python3
"""One-time purge: удалить выводы экспериментов из индекса (2026-09-28).

Замер: 828 файлов / 3127 чанков (20.3%) под experiments/**/results|work.
Штатный prune_deleted_files отказывает (safety-guard >50%), т.к. файлы
НА диске — их newly-excludes FileGuard. Поэтому точечное удаление по
тому же delete-механизму, guard безопасности не трогаем.

Usage:
    python scripts/purge_experiment_outputs.py            # dry-run
    python scripts/purge_experiment_outputs.py --apply    # удалить + compaction
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from src.core.artifact_paths import get_db_path
    from src.core.di_container import create_service_collection
    from src.core.indexing.file_guard import FileGuard
    from src.core.indexing.indexer import Indexer
    from src.core.indexing.parser import CodeParser
    from src.core.indexing.symbol_index import SymbolIndex
    from src.core.system_artifacts import SystemArtifacts
    from src.providers.embedder.remote_embedder import RemoteEmbedder

    services = create_service_collection(ROOT)
    embedder = services.resolve(RemoteEmbedder)
    indexer = Indexer(db_path=get_db_path(ROOT), embedder=embedder, file_guard=FileGuard(ROOT),
                      project_path=ROOT, parser=CodeParser(), symbol_index=SymbolIndex())
    table = indexer.table
    rows = table.search().limit(100000).to_list()
    files = {r["file_path"] for r in rows if "file_path" in r}
    garbage = sorted(f for f in files if SystemArtifacts.is_experiment_output(Path(f)))
    gset = set(garbage)
    n_chunks = sum(1 for r in rows if r.get("file_path") in gset)
    print(f"files in db: {len(files)}, garbage files: {len(garbage)}, garbage chunks: {n_chunks}")
    if not args.apply:
        print("dry-run: nothing deleted (use --apply)")
        return 0

    tbl = indexer.indexer_table if hasattr(indexer, "indexer_table") else indexer
    ok, fail = 0, 0
    for i, fp in enumerate(garbage, 1):
        try:
            if tbl.delete_file(fp):
                ok += 1
            else:
                fail += 1
            pg = getattr(getattr(tbl, "_symbol_index", None), "graph", None)
            if pg:
                pg.remove_file(str(fp).replace("\\", "/"))
        except Exception as e:  # noqa: BLE001 - one bad file must not stop purge
            print(f"  FAIL {fp}: {e}")
            fail += 1
        if i % 200 == 0:
            print(f"  ...{i}/{len(garbage)}")
    try:
        table.compact_files()
        print("compaction done")
    except Exception as e:  # noqa: BLE001
        print(f"compaction skipped: {e}")
    print(f"purged files: {ok}, failed: {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
