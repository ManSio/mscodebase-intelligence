"""FreshnessChecker — проверка актуальности индекса."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

logger = logging.getLogger("mscodebase_server.freshness")


class FreshnessChecker:
    """Сверяет хэши файлов на диске с индексом, переиндексирует изменившиеся."""

    def __init__(self, table, file_guard, index_single_file: Callable, calculate_file_hash: Callable):
        self.table = table
        self.file_guard = file_guard
        self._index_single_file = index_single_file
        self._calculate_file_hash = calculate_file_hash

    def verify(self, project_path: Path) -> int:
        project_path = Path(project_path).resolve()
        if not project_path.exists() or self.table is None:
            return 0

        try:
            df = self.table.to_pandas(columns=["file_path", "file_hash"])
        except Exception:
            return 0
        if df.empty:
            return 0

        indexed_hashes = dict(zip(df["file_path"], df["file_hash"]))
        reindexed = 0

        for root, dirs, files in os.walk(str(project_path.resolve())):
            dirs[:] = [d for d in dirs if self.file_guard and self.file_guard.should_skip_dir(d)]
            for file_name in files:
                full_path = Path(root) / file_name
                if self.file_guard and self.file_guard.should_skip_file(full_path):
                    continue
                try:
                    rel = str(full_path.relative_to(project_path)).replace(os.sep, "/")
                except ValueError:
                    continue
                if rel not in indexed_hashes:
                    continue
                try:
                    current_hash = self._calculate_file_hash(full_path)
                except Exception:
                    continue
                if current_hash == indexed_hashes[rel]:
                    continue
                if self._index_single_file(full_path, project_path):
                    reindexed += 1

        if reindexed > 0:
            logger.info(f"Re-indexed {reindexed} changed files")
        else:
            logger.info("Index is fresh, no changes")
        return reindexed
