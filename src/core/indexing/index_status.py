"""
IndexStatusReporter — сбор статуса индексатора для health report и API.

Выделено из Indexer.get_status (Фаза 3 декомпозиции God-Object).
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, Set

__all__ = [
    "IndexStatusReporter",
]
logger = logging.getLogger("mscodebase_server.index_status")


class IndexStatusReporter:
    """Собирает статистику индекса: чанки, файлы, stale-проверка."""

    def __init__(self, table, project_path: Path, file_guard, watchdog_callback):
        self.table = table
        self.project_path = project_path
        self.file_guard = file_guard
        self._watchdog_callback = watchdog_callback
        self._cached_total_chunks = 0
        self._cached_unique_files: Set[str] = set()

    def reset_cache(self) -> None:
        """Сбрасывает кэш (вызывается при пересоздании таблицы)."""
        self._cached_total_chunks = 0
        self._cached_unique_files.clear()

    def get_status(self) -> Dict[str, Any]:
        """Возвращает статистику базы данных.
        
        Всегда сверяет кэш с реальным count_rows() — stale cache
        не должен показывать данные, которых нет в таблице.
        """
        try:
            # Всегда FALLBACK к реальному count_rows, кэш — только оптимизация
            total_chunks = 0
            if self.table is not None:
                try:
                    total_chunks = self.table.count_rows()
                except Exception:
                    total_chunks = self._cached_total_chunks
            self._cached_total_chunks = total_chunks

            unique_files = self._cached_unique_files
            unique_count = len(unique_files) if isinstance(unique_files, set) else 0

            # Всегда обновляем unique_files из таблицы, если есть чанки
            if total_chunks > 0 and self.table is not None:
                _fp_series = None
                for method_name, method in [
                    ("to_lance", lambda: self.table.to_lance().to_pandas(columns=["file_path"])["file_path"]),
                    ("search", lambda: self.table.search().select(["file_path"]).limit(total_chunks).to_pandas()["file_path"]),
                    ("to_pandas", lambda: self.table.to_pandas(columns=["file_path"])["file_path"]),
                ]:
                    try:
                        _fp_series = method()
                        break
                    except Exception:
                        continue
                if _fp_series is not None and len(_fp_series) > 0:
                    unique_count = _fp_series.nunique()
                    self._cached_unique_files = set(_fp_series.unique())

            # Stale scan
            stale_files, on_disk_files, missing_files = self._scan_stale(total_chunks, unique_count)

            watchdog = self._watchdog_callback() if self._watchdog_callback else {}

            return {
                "total_chunks": total_chunks,
                "unique_files": unique_count,
                "total_files": on_disk_files or unique_count,
                "stale_files": stale_files,
                "missing_files": missing_files,
                "status": "active" if total_chunks > 0 else "empty",
                "watchdog": watchdog,
            }
        except Exception as e:
            logger.error(f"get_status error: {e}")
            return {"error": str(e)}

    def _scan_stale(self, total_chunks: int, unique_count: int):
        """Сканирует файлы на диске и сверяет с индексом."""
        stale = 0
        on_disk = 0
        missing = 0
        if unique_count > 0 and self.project_path:
            try:
                idx_df = self.table.search().select(["file_path", "file_hash"]).limit(total_chunks).to_pandas()
                indexed_files = {}
                if not idx_df.empty:
                    for fp, fh in zip(idx_df["file_path"], idx_df["file_hash"]):
                        indexed_files[fp] = fh

                walk_root = str(self.project_path.resolve())
                for root, dirs, files in os.walk(walk_root):
                    if self.file_guard:
                        dirs[:] = [d for d in dirs if not self.file_guard.should_skip_dir(d)]
                    for file_name in files:
                        full_path = Path(root) / file_name
                        if self.file_guard and self.file_guard.should_skip_file(full_path):
                            continue
                        on_disk += 1
                        try:
                            rel = str(full_path.relative_to(self.project_path)).replace(os.sep, "/")
                        except ValueError:
                            continue
                        if rel not in indexed_files:
                            missing += 1
                        else:
                            try:
                                hasher = hashlib.sha256()
                                with open(str(full_path), "rb") as f:
                                    hasher.update(f.read(8192))
                                if hasher.hexdigest() != indexed_files[rel]:
                                    stale += 1
                            except Exception:
                                pass
            except Exception as stale_err:
                logger.debug(f"stale scan skipped: {stale_err}")
        return stale, on_disk, missing
