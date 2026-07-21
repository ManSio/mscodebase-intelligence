"""
LanceDBManager — жизненный цикл LanceDB: подключение, схема, таблицы, миграции.

Выделено из Indexer.__init__ (Фаза 1 декомпозиции God-Object).
Отвечает за:
- Нормализацию путей (префикс long path на Windows)
- Синхронное и асинхронное подключение к LanceDB
- Создание/открытие таблиц с migration-ами
- Авто-детект смены размерности эмбеддинга (768↔1024)
- IndexGuard самовосстановление
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any, Optional, Set

import lancedb
import pyarrow as pa

from src.core.indexing.index_guard import IndexGuard
from src.utils.paths import to_win_long_path

__all__ = [
    "LanceDBManager",
]
logger = logging.getLogger("mscodebase_server.db_manager")


class LanceDBManager:
    """Управляет подключением к LanceDB и жизненным циклом таблиц.

    Используется Indexer как self.db_manager. Не содержит логики индексации —
    только управление БД.
    """

    def __init__(
        self,
        db_path: Path,
        embedder,
        project_path: Path,
        embedding_dim: int = 768,
    ):
        self.db_path = db_path
        self.embedder = embedder
        self.project_path = project_path
        self.embedding_dim = embedding_dim

        # Async LanceDB (ленивая инициализация)
        self._async_db: Optional[Any] = None
        self._async_table: Optional[Any] = None
        self._async_db_lock = asyncio.Lock()

        # ─── Thread-safety: межпотоковый race guard (AGENTS.md §5.13) ──
        # search_code выполняется в event-loop потоке, index_project
        # (reindex) — в executor-потоке (loop.run_in_executor). Они конкурируют
        # за self.db. threading.Lock сериализует write/reconnect; Event — fast-fail
        # для read во время reindex (паттерн chunkhound SerialDatabaseExecutor/guard).
        self._write_lock = threading.Lock()
        self._reindex_guard = threading.Event()  # set = reindex идёт, search fast-fail

        # ─── Single-writer PID lock (Layer 3 defense) ───
        # Гарантирует, что только ОДИН worker-процесс пишет в БД.
        # Второй процесс (launcher) будет ждать или работать read-only.
        self._pid_lock_path = self.db_path / ".write_lock"
        self._pid_lock_fd = None
        self._acquire_pid_lock()

        # Кэш состояния (для быстрого доступа без запросов к БД)
        self._cached_total_chunks = 0
        self._cached_unique_files: Set[str] = set()
        self._needs_full_reindex = False

        # ─── Normalize path ──────────────────────────────────
        raw_path = str(db_path.resolve())
        if raw_path.startswith("\\\\?\\"):
            lancedb_path = raw_path[4:]
        else:
            lancedb_path = raw_path

        Path(to_win_long_path(db_path)).mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(lancedb_path)
        self._lancedb_connect_path = lancedb_path
        self.table_name = "codebase_chunks"

        # ─── Schema ──────────────────────────────────────────
        _dim = embedding_dim
        self.schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), _dim)),
                pa.field("text", pa.string()),
                pa.field("text_full", pa.string()),
                pa.field("file_path", pa.string()),
                pa.field("file_hash", pa.string()),
                pa.field("chunk_index", pa.int32()),
                pa.field("source", pa.string()),
                pa.field("indexed_at", pa.string()),
                pa.field("summary", pa.string()),
                pa.field("layer", pa.string()),
                pa.field("module_name", pa.string()),
                pa.field("hierarchy_level", pa.string()),
                pa.field("is_public", pa.bool_()),
                pa.field("symbol_type", pa.string()),
                pa.field("parent_id", pa.string()),
                pa.field("callees", pa.string()),
                pa.field("health_score", pa.float64()),
                pa.field("health_band", pa.string()),
                pa.field("chunk_hash", pa.string()),
                pa.field("start_line", pa.int32()),
                pa.field("end_line", pa.int32()),
            ]
        )

        # ─── Open or create table ────────────────────────────
        self.table = self._open_or_create_table(self.schema)

        # ─── Index Guard ─────────────────────────────────────
        self._index_guard = IndexGuard(db_path, self.project_path)

        # ─── Warmup ──────────────────────────────────────────
        self._warmup_cache()

    def _open_or_create_table(self, schema: pa.Schema):
        """Открывает существующую таблицу или создаёт новую.

        Содержит миграции (text_full, metadata columns) и авто-детект
        смены размерности эмбеддинга.
        """
        try:
            table = self.db.open_table(self.table_name)
            existing_fields = [f.name for f in table.schema]

            if "text_full" not in existing_fields:
                logger.warning("Migration: adding text_full")
                self._migrate_text_full_inplace()

            self._migrate_add_metadata_columns(existing_fields)

            logger.info(f"Opened table: {self.table_name}")

            # Dimension mismatch → recreate
            _vec_field = next((f for f in table.schema if f.name == "vector"), None)
            if _vec_field is not None:
                stored_dim = 0
                try:
                    _t = _vec_field.type
                    if hasattr(_t, 'value_type'):
                        _vt = _t.value_type
                        if hasattr(_vt, 'get_field'):
                            stored_dim = _vt.get_field("item").type.list_size
                except Exception as _dim_err:
                    logger.debug(f"Не удалось определить размерность вектора: {_dim_err}")
                if stored_dim and stored_dim != self.embedding_dim:
                    logger.warning(
                        f"Dimension mismatch: index={stored_dim}, "
                        f"embedder={self.embedding_dim}. Recreating..."
                    )
                    self.db.drop_table(self.table_name)
                    table = self.db.create_table(self.table_name, schema=schema)
                    logger.info(f"Table recreated for {self.embedding_dim}dim")
                    self._needs_full_reindex = True

        except Exception as open_err:
            logger.debug(f"Table not found: {open_err}. Creating new.")
            try:
                table = self.db.create_table(self.table_name, schema=schema)
                logger.info(f"Created table: {self.table_name}")
            except Exception as create_err:
                err_str = str(create_err).lower()
                if "already exists" in err_str:
                    table = self.db.open_table(self.table_name)
                    logger.info(f"Opened table (race): {self.table_name}")
                else:
                    raise

        return table

    def _warmup_cache(self) -> None:
        """Прогрев кэша чанков и уникальных файлов (без сканирования диска)."""
        try:
            if self.table is None:
                return
            count = self.table.count_rows()
            self._cached_total_chunks = count
            if count > 0:
                logger.info(f"Cache warmup: {count} chunks")
                for attempt in range(3):
                    try:
                        ds = self.table.to_lance()
                        _fp_df = ds.to_pandas(columns=["file_path"])
                        if not _fp_df.empty:
                            self._cached_unique_files = set(_fp_df["file_path"].unique())
                        break
                    except Exception:
                        if attempt == 0:
                            continue
                        break
                logger.info(f"Cache warmup: {len(self._cached_unique_files)} files")
            else:
                logger.debug("Cache warmup: empty database (first run)")
        except Exception as e:
            err_str = str(e).lower()
            if "not found" in err_str or "does not exist" in err_str:
                logger.warning(f"Table not found during warmup: {e}")
            else:
                logger.debug(f"Cache warmup failed: {e}. Cache = 0.")
            self._cached_total_chunks = 0

    def close_sync(self):
        """Синхронное закрытие (для cleanup)."""
        if hasattr(self, 'db') and self.db is not None:
            self.db = None

    async def ensure_async_table(self):
        """Гарантирует наличие асинхронного подключения к LanceDB.

        Использует asyncio.Lock для thread-safe ленивой инициализации.
        Multi-window: при переключении проекта создаётся новая async-таблица.
        """
        async with self._async_db_lock:
            if self._async_table is not None:
                return self._async_table

            async_db = await lancedb.connect_async(self._lancedb_connect_path)
            self._async_db = async_db

            try:
                async_table = await async_db.open_table(self.table_name)
            except Exception:
                schema = self.schema
                async_table = await async_db.create_table(
                    self.table_name, schema=schema
                )

            self._async_table = async_table
            return async_table

    async def to_pandas_async(self):
        """Асинхронное чтение всей таблицы в pandas."""
        tbl = await self.ensure_async_table()
        return await tbl.to_pandas()

    async def count_rows_async(self) -> int:
        """Асинхронный подсчёт строк."""
        tbl = await self.ensure_async_table()
        return await tbl.count_rows()

    async def close_async(self) -> None:
        """Корректное закрытие async-подключения."""
        if self._async_db is not None:
            await self._async_db.close()
            self._async_db = None
            self._async_table = None

    def switch_db(self, new_db_path: Path) -> None:
        """Переключает базу данных на новый проект.

        Вызывается из Indexer.switch_project(). Закрывает старое
        подключение и открывает новое.
        """
        # Sync close
        if hasattr(self, 'db') and self.db is not None:
                    try:
                        self.db.close()
                    except Exception as _close_err:
                        logger.debug(f"DB close warning: {_close_err}")

        # Normalize new path
        raw_path = str(new_db_path.resolve())
        if raw_path.startswith("\\\\?\\"):
            lancedb_path = raw_path[4:]
        else:
            lancedb_path = raw_path

        Path(to_win_long_path(new_db_path)).mkdir(parents=True, exist_ok=True)
        self.db_path = new_db_path
        self.db = lancedb.connect(lancedb_path)
        self._lancedb_connect_path = lancedb_path

        # Reset async
        self._async_db = None
        self._async_table = None

        # Open/create table
        self.table = self._open_or_create_table(self.schema)

        # Reset IndexGuard
        self._index_guard = IndexGuard(self.db_path, self.project_path)
        guard_report = self._index_guard.check_and_repair(self.db)
        if guard_report["status"] != "ok":
            logger.warning(
                f"IndexGuard after switch: {guard_report['status']} — "
                f"{', '.join(guard_report['actions_taken'])}"
            )
            try:
                self.table = self.db.open_table(self.table_name)
            except Exception as _open_err:
                logger.warning(f"Table re-open after switch failed: {_open_err}")

        # Warmup new cache
        self._warmup_cache()
        logger.info(f"Switched to DB: {new_db_path}")

    def reset_connection(self) -> None:
        """Сбрасывает handle БД и переподключается.

        Вызывать после внешних миграций (drop_table, add_columns)
        или когда таблица повреждена. Не требует перезапуска MCP.

        Thread-safe: сериализуется через _write_lock (межпотоковый race guard).
        """
        with self._write_lock:
            logger.info("🔄 DB Connection reset: переподключение к LanceDB...")

            # 1. Закрываем старое подключение
            try:
                if self.db is not None:
                    self.db.close()
            except Exception as _reset_close_err:
                logger.debug(f"reset_connection: DB close warning: {_reset_close_err}")

            # 2. Переподключаемся
            self.db = lancedb.connect(self._lancedb_connect_path)

            # 3. Сбрасываем async
            self._async_db = None
            self._async_table = None

            # 4. Открываем/пересоздаём таблицу
            try:
                self.table = self._open_or_create_table(self.schema)
            except Exception as e:
                logger.error(f"❌ reset_connection: таблица не восстановлена: {e}")
                raise

            # 5. Синхронизируем writer если есть callback
            if hasattr(self, '_on_recreate') and self._on_recreate:
                try:
                    self._on_recreate(self.table)
                except Exception as _cb_err:
                    logger.debug(f"reset_connection: on_recreate callback failed: {_cb_err}")

            # 6. Пересоздаём IndexGuard
            try:
                self._index_guard = IndexGuard(self.db_path, self.project_path)
            except Exception as _ig_err:
                logger.debug(f"reset_connection: IndexGuard rebuild failed: {_ig_err}")

            # 7. Прогрев кэша
            self._warmup_cache()

        count = self.table.count_rows() if self.table else 0
        logger.info(f"✅ DB Connection reset: таблица {self.table_name} ({count} rows)")

    # ══════════════════════════════════════════════════════════
    # Reindex guard (fast-fail для search во время reindex)
    # ══════════════════════════════════════════════════════════
    def set_reindexing(self) -> None:
        """Ставит guard: search должен fast-fail, пока идёт reindex.

        Вызывается из trigger_async_reindex перед index_project.
        """
        self._reindex_guard.set()

    def clear_reindexing(self) -> None:
        """Снимает guard после завершения reindex."""
        self._reindex_guard.clear()

    # ══════════════════════════════════════════════════════════
    # Single-writer PID lock (Layer 3 defense)
    # ═════════════════════════════════════════════════════════
    def _acquire_pid_lock(self) -> None:
        """Acquire exclusive PID lock on the database directory.

        Uses a lock file with PID + timestamp. Если lock занят живым PID —
        сразу выходим (raise), не ждём 30 секунд. Дубли MCP должны умирать
        быстро, чтобы не плодить 6 процессов на 30 секунд.
        """
        import os
        import time
        import json
        from pathlib import Path

        lock_path = self._pid_lock_path

        # Убеждаемся, что parent dir существует (LanceDB может не создать его до первого connect)
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Try to create lock file exclusively
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            self._pid_lock_fd = fd
            lock_data = json.dumps({
                "pid": os.getpid(),
                "started": time.time(),
                "role": "worker"
            }).encode()
            os.write(fd, lock_data)
            os.fsync(fd)
            logger.info(f"🔒 PID lock acquired: {lock_path} (pid={os.getpid()})")
            return
        except FileExistsError:
            # Lock exists - check if holder is alive
            try:
                with open(lock_path, 'r') as f:
                    data = json.load(f)
                holder_pid = data.get('pid')
                if holder_pid and self._is_pid_alive(holder_pid):
                    # Дубликат — умираем сразу, без 30-секундных танцев
                    logger.warning(f"PID lock held by alive pid={holder_pid}, exiting (duplicate MCP)")
                    raise RuntimeError(
                        f"PID lock already held by alive process {holder_pid}. "
                        "Дубликат MCP — завершаюсь."
                    )
                else:
                    # Stale lock (holder dead) — steal it
                    logger.warning(f"Stealing stale PID lock from dead pid={holder_pid}")
                    try:
                        lock_path.unlink(missing_ok=True)
                    except PermissionError:
                        # Windows: файл занят живым процессом — некража
                        raise RuntimeError(
                            f"Cannot steal PID lock from pid={holder_pid}: file in use"
                        )
            except (json.JSONDecodeError, OSError):
                # Corrupted lock file - remove and retry once
                lock_path.unlink(missing_ok=True)
                try:
                    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                    self._pid_lock_fd = fd
                    lock_data = json.dumps({
                        "pid": os.getpid(),
                        "started": time.time(),
                        "role": "worker"
                    }).encode()
                    os.write(fd, lock_data)
                    os.fsync(fd)
                    logger.info(f"🔒 PID lock acquired (after retry): {lock_path} (pid={os.getpid()})")
                    return
                except FileExistsError:
                    raise RuntimeError("PID lock race: another process acquired lock during retry")
        except Exception as e:
            logger.error(f"PID lock error: {e}")
            raise

    def _is_pid_alive(self, pid: int) -> bool:
        """Check if a PID is alive (cross-platform).

        На Unix: os.kill(pid, 0) — signal 0, ProcessLookupError = dead.
        На Windows: os.kill для чужих процессов кидает WinError 11 (OSError)
        даже если процесс жив. Используем ctypes.OpenProcess.
        """
        import os
        import sys

        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                # PROCESS_QUERY_LIMITED_INFORMATION (0x1000) — минимальные права
                handle = kernel32.OpenProcess(0x1000, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                # ERROR_INVALID_PARAMETER (87) — процесс не существует
                return False
            except Exception:
                # fallback: если ctypes недоступен, считаем живым (safe side)
                return True

        # Unix: os.kill(pid, 0)
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            # PermissionError и др. — процесс существует, но недоступен
            return True

    def _release_pid_lock(self) -> None:
        """Release the PID lock."""
        if self._pid_lock_fd is not None:
            try:
                os.close(self._pid_lock_fd)
            except Exception:
                pass
            self._pid_lock_fd = None
        try:
            self._pid_lock_path.unlink(missing_ok=True)
            logger.info(f"🔓 PID lock released: {self._pid_lock_path}")
        except Exception:
            pass

    def __del__(self):
        """Ensure lock is released on object destruction."""
        self._release_pid_lock()

    def is_reindexing(self) -> bool:
        """True, если reindex в процессе — search должен fast-fail."""
        return self._reindex_guard.is_set()

    def begin_write(self):
        """Context manager: эксклюзивный доступ к write/reconnect.

        Использовать в index_project / drop_table, чтобы search не читал
        поломанный индекс (паттерн chunkhound SerialDatabaseExecutor).
        """
        return self._write_lock

    # ══════════════════════════════════════════════════════════
    # Migration helpers (from IndexerTableMixin)
    # ══════════════════════════════════════════════════════════

    def _migrate_text_full_inplace(self):
        """Добавляет колонку text_full через alti_method."""
        from src.core.indexing.indexer_table import _migrate_text_full_inplace as _do
        _do(self.db, self.table_name, self.table)

    def _migrate_add_metadata_columns(self, existing_fields):
        """Добавляет колонки метаданных (v2.4.3+)."""
        from src.core.indexing.indexer_table import _migrate_add_metadata_columns as _do
        _do(self.db, self.table_name, existing_fields)
