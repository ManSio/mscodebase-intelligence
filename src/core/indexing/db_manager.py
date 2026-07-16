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
from pathlib import Path
from typing import Any, Optional, Set

import lancedb
import pyarrow as pa

from src.core.indexing.index_guard import IndexGuard
from src.utils.paths import to_win_long_path

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
            except Exception:
                pass

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
            except Exception:
                pass

        # Warmup new cache
        self._warmup_cache()
        logger.info(f"Switched to DB: {new_db_path}")

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
