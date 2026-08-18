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
import gc
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Optional, Set

import lancedb
import pyarrow as pa

from adapters.local_fs.windows import to_win_long_path
from src.core.indexing.database_lock import DatabaseLock
from src.core.indexing.index_guard import IndexGuard

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
        table_write_lock: Optional[threading.Lock] = None,
    ):
        self.db_path = db_path
        self.embedder = embedder
        self.project_path = project_path
        self.embedding_dim = embedding_dim

        # Async LanceDB (ленивая инициализация)
        self._async_db: Optional[Any] = None
        self._async_table: Optional[Any] = None
        # P3-12 audit: asyncio.Lock создаётся лениво при первом ensure_async_table
        # (привязка к running loop на Python 3.10+ происходит в момент acquire,
        # создание в __init__ из sync-кода даёт wrong-loop).
        self._async_db_lock: Optional[asyncio.Lock] = None

        # ─── Thread-safety: используем переданный lock для сериализации write/reconnect
        # Это гарантирует, что reset_connection и bulk_write не выполняются одновременно
        # P1-13 audit: RLock — reset_connection() вызывает _warmup_cache()
        # из-под этого же лока (реентерабельность обязательна).
        self._write_lock = table_write_lock or threading.RLock()
        self._reindex_guard = threading.Event()  # set = reindex идёт, search fast-fail

        # ─── Single-writer PID lock (Layer 3 defense) ───
        # Гарантирует, что только ОДИН worker-процесс пишет в БД.
        # Второй процесс (launcher) будет ждать или работать read-only.
        # Логика вынесена в DatabaseLock (см. database_lock.py).
        self._pid_lock_path = self.db_path / ".write_lock"
        self._db_lock = DatabaseLock(self._pid_lock_path)
        # Диагностика при старте (Задача 3/5): человеческий текст с действием
        # вместо RuntimeError из глубины при живом владельце lock-а.
        # Семантика lock-а НЕ меняется — только сообщение об ошибке.
        self._startup_issue: Optional[str] = None
        try:
            self._db_lock.acquire()
        except RuntimeError as _lock_err:
            self._startup_issue = (
                f"База занята другим процессом MCP. Закройте второе окно Zed "
                f"или подождите завершения его индексации. "
                f"Детали: {_lock_err}"
            )
            logger.error(self._startup_issue)
            raise

        self._on_recreate = None

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
        try:
            self.db = lancedb.connect(lancedb_path)
        except Exception as _connect_err:
            # Задача 3/5: не Rust-трейс, а действие (обычно: файлы залочены
            # mmap живого процесса, либо директория повреждена).
            self._startup_issue = (
                f"Не удалось открыть базу LanceDB: {_connect_err}. "
                f"Закройте все окна Zed и удалите папку "
                f"{self.db_path.name} вручную, затем повторите."
            )
            logger.error(self._startup_issue)
            raise
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
        try:
            self.table = self._open_or_create_table(self.schema)
        except Exception as _table_err:
            self._startup_issue = (
                f"Не удалось открыть/создать таблицу '{self.table_name}': "
                f"{_table_err}. Индекс повреждён — выполните intel_reset_index "
                f"или удалите папку {self.db_path.name} при закрытом Zed."
            )
            logger.error(self._startup_issue)
            raise

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
                    logger.debug(f"Schema extraction failed: {_dim_err}")

                # Fallback: read a sample row to get actual vector length
                if not stored_dim:
                    try:
                        sample = table.limit(1).to_list()
                        if sample and "vector" in sample[0]:
                            stored_dim = len(sample[0]["vector"])
                    except Exception:
                        pass

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

    def human_report(self) -> str:
        """Человекочитаемый отчёт о состоянии БД и lock-а (Задача 3/5).

        Read-only: не захватывает lock, не трогает файлы. Может вызываться
        в любой момент (в т.ч. когда таблица закрыта/пересоздаётся).
        """
        from src.core.indexing.startup_diagnostics import build_startup_report

        try:
            report = build_startup_report(
                db_path=self.db_path,
                table_name=self.table_name,
                lock_path=self._pid_lock_path,
                current_pid=os.getpid(),
            )
            if self._startup_issue:
                report.issues.insert(0, self._startup_issue)
            return report.to_human()
        except Exception as _diag_err:
            logger.debug(f"human_report failed: {_diag_err}")
            return (
                f"Диагностика недоступна ({_diag_err}). "
                f"Проверьте intel_get_runtime_status и логи."
            )

    def _warmup_cache(self) -> None:
        """Прогрев кэша чанков и уникальных файлов (без сканирования диска).

        P2-15 audit: чтение self.table сериализуется через _write_lock,
        чтобы не попасть на закрытую таблицу при параллельном reset_connection.
        RLock позволяет вызов из-под уже захваченного лока (reset_connection).
        """
        with self._write_lock:
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

    def close_for_maintenance(self) -> None:
        """Закрывает ВСЕ handle'ы БД (sync + async) и освобождает mmap.

        Вызывается ПЕРЕД физическим удалением файлов индекса (rmtree).
        На Windows db.close() не освобождает mmap-хендлы немедленно —
        нужны gc.collect() + пауза, чтобы ОС сняла блокировки файлов.

        Thread-safe: сериализуется через _write_lock (RLock — реентерабельно).
        """
        with self._write_lock:
            try:
                if self.db is not None:
                    self.db.close()
            except Exception as _close_err:
                logger.debug(f"close_for_maintenance: db.close warning: {_close_err}")
            self.db = None
            self.table = None
            # Async-подключение: best-effort сброс (нет loop в sync-контексте)
            self._async_db = None
            self._async_table = None
            gc.collect()
            time.sleep(0.5)  # Windows: дать ОС освободить mmap-хендлы

    async def ensure_async_table(self):
        """Гарантирует наличие асинхронного подключения к LanceDB.

        P3-12 audit: asyncio.Lock создаётся лениво в контексте вызывающего
        event loop (привязка loop происходит при первом acquire) — создание
        в __init__ из sync-кода давало wrong-loop на Python 3.10.
        Multi-window: при переключении проекта создаётся новая async-таблица.
        """
        if self._async_db_lock is None:
            self._async_db_lock = asyncio.Lock()
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

        P1-4 audit: вся операция сериализуется через _write_lock,
        чтобы параллельный write не попал в закрытую БД.
        """
        with self._write_lock:
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

            # Синхронизируем ссылки на таблицу во всех компонентах
            # (stale ghost table, AGENT_DIARY 2026-08-02 00:26): switch_db /
            # fresh-path fallback НЕ вызывал callback — writer/runner/freshness
            # продолжали писать/читать удалённую таблицу по старому пути.
            if self._on_recreate is not None:
                try:
                    self._on_recreate(self.table)
                except Exception as _cb_err:
                    logger.debug(f"switch_db: on_recreate callback failed: {_cb_err}")

            # Warmup new cache
            self._warmup_cache()
            logger.info(f"Switched to DB: {new_db_path}")

    def _switch_to_fresh_path(self) -> None:
        """Переключает БД на новый путь с timestamp (fallback при залоченных файлах).

        Старая директория остаётся на диске (файлы залочены mmap) и требует
        ручной очистки при выключенном MCP — логируется для оператора.
        Использует существующий switch_db (закрытие → connect → таблица → guard).
        """
        fresh = self.db_path.parent / f"lancedb_v2_{int(time.time())}"
        logger.warning(
            f"⚠️ Using fresh DB path: {fresh} "
            f"(old: {self.db_path} locked — requires manual cleanup)"
        )
        self.switch_db(fresh)

    def recreate_table_physical(self) -> bool:
        """Физическое пересоздание БД с нуля (INC-6C62-v2).

        Проблема: drop_table + create_table в LanceDB НЕ удаляет физические
        файлы — новая таблица наследует цепочку версий старой, включая
        ссылки на мёртвые фрагменты (*.lance, которых нет на диске) →
        optimize падает с 'Not found'. Симптом «вечной» ошибки реиндекса.

        INC-6C62-v2 (рецидив 2026-08-03): удаление ТОЛЬКО директории таблицы
        (<db>/<table>.lance) НЕДОСТАТОЧНО — db-level манифест
        (<db>/__manifest/_versions/) несёт wrapped-версии (2^64−N) со ссылкой
        на мёртвый фрагмент, переживает удаление таблицы и отравляет каждую
        новую таблицу в той же директории БД. count_rows() читает свежую
        версию (работает), а vector_search идёт по цепочке версий → 'Not found'.

        Решение: закрыть все handle'ы → освободить PID-lock (.write_lock
        внутри db_dir, fd держится открытым) → gc + пауза (Windows mmap) →
        удалить ВСЮ директорию БД (ignore_errors=False) → пересоздать с нуля
        (счётчик версий = 0). Если файлы всё ещё залочены (PermissionError)
        → новый путь БД (lancedb_v2_{timestamp}).

        Returns:
            True если таблица пересоздана (в т.ч. через fresh path).
        """
        with self._write_lock:
            self.close_for_maintenance()
            # Освобождаем PID-lock до rmtree: .write_lock держит открытый fd,
            # иначе shutil.rmtree упадёт с PermissionError именно на нём.
            if self._db_lock is not None:
                try:
                    self._db_lock.release()
                except Exception as _lock_release_err:
                    logger.debug(f"recreate_table_physical: lock release warning: {_lock_release_err}")
            db_root = self.db_path
            try:
                if db_root.exists():
                    shutil.rmtree(str(db_root), ignore_errors=False)
                    logger.info(f"✅ Physically removed LanceDB DB dir: {db_root}")
                # Пересоздаём чистую директорию БД (версионная цепочка = 0)
                Path(to_win_long_path(db_root)).mkdir(parents=True, exist_ok=True)
                # Перезахватываем PID-lock на новой директории
                if self._db_lock is not None:
                    try:
                        self._db_lock.acquire()
                    except RuntimeError as _lock_racq_err:
                        logger.warning(f"recreate_table_physical: lock re-acquire failed: {_lock_racq_err}")
                self.reset_connection()
                return True
            except PermissionError as _perm_err:
                logger.warning(
                    f"⚠️ Table dir locked (mmap): {_perm_err} — switching to fresh DB path"
                )
                self._switch_to_fresh_path()
                return True
            except Exception as _recreate_err:
                logger.error(
                    f"❌ Physical table recreate failed: {_recreate_err} — switching to fresh DB path"
                )
                try:
                    self._switch_to_fresh_path()
                    return True
                except Exception as _fresh_err:
                    logger.error(f"❌ Fresh path switch failed: {_fresh_err}")
                    return False

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

    def set_on_recreate_callback(self, callback):
        """Register callback to be called when table is recreated.

        Called after reset_connection() reopens the table.
        """
        self._on_recreate = callback

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

    def __del__(self):
        """Ensure lock is released on object destruction."""
        db_lock = getattr(self, "_db_lock", None)
        if db_lock is not None:
            try:
                db_lock.release()
            except Exception:
                pass

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
