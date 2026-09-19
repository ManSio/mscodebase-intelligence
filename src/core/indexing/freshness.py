"""FreshnessChecker — проверка актуальности индекса (Incremental Hot-Reload).

Фаза 1 (2026-09-18): переписана на stat-first сверку.
- mtime+size совпали → файл не менялся, hash НЕ читаем (экономия на 102ms
  чтения таблицы и hash-чтении содержимого; замер stat-sweep 17.83ms/1100 файлов).
- mtime/size не совпали или отсутствуют (legacy-индекс) → hash-подтверждение.
- НОВЫЕ файлы (не в индексе) теперь включаются (закрытие KI-109: авто-подхват
  новых файлов без notify_change).
- Вызов index_single_file с правильным 2-м аргументом (rel_path, а не project_path).
- Чтение колонок через table.to_lance().to_pandas (to_pandas(columns=...) не
  работает в lancedb 0.34).
- Debounce + threading.Lock + skip при полном reindex (is_reindexing callback).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

__all__ = [
    "FreshnessChecker",
]
logger = logging.getLogger("mscodebase_server.freshness")


class FreshnessChecker:
    """Сверяет файлы на диске с индексом, переиндексирует изменённые/новые."""

    def __init__(
        self,
        table,
        file_guard,
        index_single_file: Callable,
        calculate_file_hash: Callable,
        interval_sec: float = 30.0,
        is_reindexing: Optional[Callable] = None,
    ):
        self.table = table
        self.file_guard = file_guard
        self._index_single_file = index_single_file
        self._calculate_file_hash = calculate_file_hash
        self._interval_sec = max(0.0, float(interval_sec))
        self._is_reindexing = is_reindexing or (lambda: False)
        self._lock = threading.Lock()
        self._last_check = 0.0

    def verify(self, project_path: Path, force: bool = False) -> int:
        """Инкрементальная сверка: stat-first → hash-confirm → hot-reload.

        Returns:
            Число переиндексированных файлов (0 при свежем индексе/debounce).
        """
        project_path = Path(project_path).resolve()
        if not project_path.exists() or self.table is None:
            return 0

        now = time.monotonic()
        if not force and now - self._last_check < self._interval_sec:
            return 0
        if self._is_reindexing():
            return 0

        with self._lock:
            reindexed = 0
            try:
                if self._last_check > 0:
                    # повторный вызов внутри интервала — только если мало потоков хотят
                    if not force and now - self._last_check < self._interval_sec:
                        return 0
                self._last_check = now

                indexed = self._read_indexed_state()
            except Exception:
                self._last_check = now
                return 0

            if not indexed:
                # Пустой индекс (ещё не проиндексирован) — не начинаем полный
                # reindex из hot-path (это делает _delayed_auto_index).
                return 0

            has_stat = indexed.get("_has_stat", False)
            paths = indexed.get("_paths", {})  # rel -> {"hash", "mtime_ns", "size"}

            for root, dirs, files in os.walk(str(project_path.resolve())):
                if self.file_guard:
                    dirs[:] = [d for d in dirs if not self.file_guard.should_skip_dir(d)]
                for file_name in files:
                    full_path = Path(root) / file_name
                    if self.file_guard and self.file_guard.should_skip_file(full_path):
                        continue
                    try:
                        rel = str(full_path.relative_to(project_path)).replace(os.sep, "/")
                    except ValueError:
                        continue

                    old = paths.get(rel)
                    if old is None:
                        # KI-109: НОВЫЙ файл — авто-подхват без notify_change.
                        try:
                            if self._index_single_file(full_path, rel):
                                reindexed += 1
                        except Exception:
                            continue
                        continue

                    try:
                        st = full_path.stat()
                    except OSError:
                        continue

                    if has_stat:
                        stored_mtime = int(old.get("mtime_ns", 0) or 0)
                        stored_size = int(old.get("size", 0) or 0)
                        if stored_mtime == int(st.st_mtime_ns) and stored_size == int(st.st_size):
                            continue  # stat-first fast-path, без чтения hash

                    # stat не совпал (или нет stat-данных legacy) → hash-подтверждение
                    try:
                        current_hash = self._calculate_file_hash(full_path)
                    except Exception:
                        continue
                    if current_hash == old.get("hash"):
                        continue  # содержимое не изменилось (touch), индекс свежий

                    try:
                        if self._index_single_file(full_path, rel):
                            reindexed += 1
                    except Exception:
                        continue

            if reindexed > 0:
                logger.info(f"🧲 Hot-reload: переиндексировано {reindexed} файлов")
            return reindexed

    def _read_indexed_state(self) -> Dict[str, Any]:
        """Читает file_path/file_hash (+ mtime/size если есть) из индекса.

        to_pandas(columns=...) не работает в lancedb 0.34 — старый код падал.
        Рабочий паттерн: table.to_lance().to_pandas(columns=[...]) —
        замерено 102.2ms на 10366 чанков / 574 файла.
        """
        cols = ["file_path", "file_hash", "file_mtime_ns", "file_size"]
        try:
            df = self.table.to_lance().to_pandas(columns=cols)
        except Exception:
            # Legacy-схема без mtime/size — работаем по hash (опционально).
            try:
                df = self.table.to_lance().to_pandas(columns=["file_path", "file_hash"])
                has_stat = False
            except Exception:
                logger.debug("FreshnessChecker: таблица недоступна для чтения")
                return {}

        if df is None or len(df) == 0:
            return {}

        has_stat = {"file_mtime_ns", "file_size"}.issubset(df.columns)
        # Один файл может давать много чанков — берём последнюю строку на файл,
        # чтобы пути были уникальны и не было деградации на число чанков.
        paths: Dict[str, Dict[str, Any]] = {}
        for _, row in df.iterrows():
            rel = str(row["file_path"])
            entry = {"hash": str(row["file_hash"])}
            if has_stat:
                mtime = row.get("file_mtime_ns")
                size = row.get("file_size")
                entry["mtime_ns"] = int(mtime) if mtime is not None and mtime == mtime else 0
                entry["size"] = int(size) if size is not None and size == size else 0
            paths[rel] = entry

        return {"_has_stat": has_stat, "_paths": paths}
