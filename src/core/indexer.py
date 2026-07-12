"""
MSCodebase Intelligence — Продакшен инкрементальный индекс на LanceDB с авто-очисткой (Pruning)
"""

import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import lancedb
import pyarrow as pa

from src.core.chunk_summarizer import ChunkSummarizer
from src.core.index_guard import IndexGuard
from src.utils.paths import SafePathManager, to_win_long_path

logger = logging.getLogger("mscodebase_server.indexer")

# Размер батча для кросс-файлового эмбеддинга.
# E5-base/BGE-M3 обрабатывают 64 текста почти за то же время, что и 1.
_BATCH_SIZE = 64


def _generate_unique_db_path(project_path: Path) -> Path:
    """Генерирует уникальный путь к базе данных на основе пути проекта.

    Это позволяет каждому проекту иметь свою изолированную базу данных,
    предотвращая конфликты при параллельной индексации.
    """
    # Используем хэш пути проекта для создания уникального имени файла
    # Нормализуем путь: lower() + replace('\', '/') для защиты от разного регистра в Windows
    normalized_path = str(project_path.resolve()).lower().replace("\\", "/")
    project_hash = hashlib.md5(normalized_path.encode()).hexdigest()[:8]
    project_name = os.path.basename(project_path).lower()

    # Создаем директорию .codebase_indices в корне проекта, если её нет
    # ВАЖНО: используем сам project_path, а не его parent — иначе БД создаётся
    # в родительской директории (D:\Project\.codebase_indices вместо D:\Project\MSCodeBase\.codebase_indices)
    project_root = project_path
    db_dir = project_root / ".codebase_indices" / "lancedb_v2"
    db_dir.mkdir(parents=True, exist_ok=True)

    # Имя базы данных: index_{project_name}_{hash}.db
    db_name = f"index_{project_name}_{project_hash}.db"
    return db_dir / db_name


class Indexer:
    def __init__(
        self,
        db_path: Path,
        embedder,
        file_guard,
        project_path: Optional[Path] = None,
        parser=None,
        enable_summaries: bool = True,
        symbol_index=None,
        notification_broker=None,
        searcher=None,
    ):
        self.db_path = db_path
        self.embedder = embedder
        self.file_guard = file_guard
        self.path_manager = SafePathManager(db_path.parent)
        # searcher инжектируется явно через DI (см. INC-53EC / REFC-05).
        # Если None — будет установлен позже через set_searcher().
        self.searcher = searcher
        self.project_path = project_path or db_path.parent.parent.parent
        self.parser = parser  # CodeParser для AST-aware чанкинга
        self._notification_broker = notification_broker  # опциональный брокер событий
        self._last_reported_progress = -1  # для троттлинга уведомлений

        import threading
        # Блокировки для thread-safe параллельной индексации
        self._index_lock = threading.Lock()          # защита shared state
        self._table_write_lock = threading.Lock()    # сериализация записи в LanceDB
        self._symbol_index_lock = threading.Lock()   # SymbolIndex thread safety

        # Watchdog: heartbeat обновляется при каждом прогрессе
        self._watchdog_heartbeat = 0.0
        self._watchdog_label = "init"
        self._watchdog_lock = threading.Lock()

        # Счётчики кэша (защищены _index_lock)
        self._cached_total_chunks = 0
        self._cached_unique_files: Set[str] = set()

        # Определяем размерность из embedder (768 для E5-base, 1024 для BGE-M3 и т.д.)
        _dim = getattr(self.embedder, 'embedding_dim', None) or 768
        logger.info(f"📐 Размерность эмбеддинга: {_dim}")

        # Схема таблицы: id, vector, text, text_full, file_path, file_hash, chunk_index, source, summary
        if symbol_index is not None:
            self._symbol_index = symbol_index
        else:
            from src.core.symbol_index import SymbolIndex

            self._symbol_index = SymbolIndex()

        # Chunk Summarizer для LLM-описаний
        self.enable_summaries = enable_summaries
        self.summarizer = None
        if enable_summaries:
            cache_dir = db_path.parent / "summaries_cache"
            self.summarizer = ChunkSummarizer(embedder=embedder, cache_dir=cache_dir)

        # Настройка директории базы данных
        # На Windows tmp_path может содержать \\?\ префикс.
        # LanceDB (Rust) не понимает этот префикс — снимаем его.
        raw_path = str(db_path.resolve())
        if raw_path.startswith("\\\\?\\"):
            lancedb_path = raw_path[4:]
        else:
            lancedb_path = raw_path

        # Создаём директорию через \\?\ если нужно (обходит MAX_PATH)
        Path(to_win_long_path(db_path)).mkdir(parents=True, exist_ok=True)

        # Подключение к LanceDB (чистый путь, без \\?\\).
        # Async-соединение для неблокирующих операций (поиск).
        self.db = lancedb.connect(lancedb_path)
        self._lancedb_connect_path = lancedb_path

        # Async LanceDB (ленивая инициализация при первом поиске).
        self._async_db: Optional[Any] = None
        self._async_table: Optional[Any] = None
        self._async_db_lock = asyncio.Lock()

        # Схема таблицы: id, vector, text, text_full, file_path, file_hash, chunk_index, source, summary
        # text — компактный чанк (сигнатура + превью) для эмбеддинга и экономии токенов
        # text_full — полный текст функции/метода (для детального анализа по запросу)
        # source — источник индексации: 'lsp_vfs' (память IDE) или 'filesystem' (диск)
        # summary — LLM-описание чанка (для улучшения семантического поиска)
        #
        # Metadata Enrichment (MCompassRAG-style + SproutRAG-style):
        # layer — архитектурный слой (core/mcp/tests/...)
        # module_name — логическое имя модуля (core.parser)
        # hierarchy_level — уровень иерархии (function/method/class/...)
        # is_public — публичный/приватный символ
        # symbol_type — AST-тип (function_definition/method_definition/...)
        # parent_id — детерминированный хеш родителя для multi-granularity
        self.schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field(
                    "vector", pa.list_(pa.float32(), _dim)
                ),  # Динамическая размерность от embedder
                pa.field("text", pa.string()),
                pa.field("text_full", pa.string()),
                pa.field("file_path", pa.string()),
                pa.field("file_hash", pa.string()),
                pa.field("chunk_index", pa.int32()),
                pa.field("source", pa.string()),
                pa.field("indexed_at", pa.string()),
                pa.field("summary", pa.string()),
                # Metadata Enrichment (v2.4.3+)
                pa.field("layer", pa.string()),
                pa.field("module_name", pa.string()),
                pa.field("hierarchy_level", pa.string()),
                pa.field("is_public", pa.bool_()),
                pa.field("symbol_type", pa.string()),
                pa.field("parent_id", pa.string()),
                # Call-graph edges (v3.0): JSON-массив callee-имён из AST
                pa.field("callees", pa.string()),
                # Code Health (v3.0): score 1-10, вычисляется при индексации
                pa.field("health_score", pa.float64()),
                pa.field("health_band", pa.string()),
            ]
        )

        self.table_name = "codebase_chunks"
        # LanceDB может кэшировать список таблиц, из-за чего open_table и create_table
        # могут кидать race condition. Пробуем открыть, при ошибке — создаём,
        # при "already exists" — пробуем открыть снова.
        try:
            self.table = self.db.open_table(self.table_name)
            # Проверяем, что схема содержит text_full (миграция).
            # Используем add_columns — НЕ drop+create (см. INC-53EC / REFC-07):
            # ранее при kill -9 между drop_table и create_table вся база терялась.
            existing_fields = [f.name for f in self.table.schema]
            if "text_full" not in existing_fields:
                logger.warning(
                    "⚠️ Миграция: добавляем text_full через _migrate_text_full_inplace"
                )
                self._migrate_text_full_inplace()

            # Миграция: Metadata Enrichment (v2.4.3+)
            self._migrate_add_metadata_columns(existing_fields)

            logger.info(f"📦 Открыта таблица: {self.table_name}")

            # ── Auto-detect: dimension mismatch → пересоздание ──
            # При смене модели эмбеддинга (1024→768, 768→1024) старые
            # векторы несовместимы. Проверяем размерность при старте.
            _schema = self.table.schema
            _vec_field = next((f for f in _schema if f.name == "vector"), None)
            if _vec_field is not None:
                _stored_dim = 0
                try:
                    _t = _vec_field.type
                    if hasattr(_t, 'value_type'):
                        _vt = _t.value_type
                        if hasattr(_vt, 'get_field'):
                            _stored_dim = _vt.get_field("item").type.list_size
                except Exception:
                    pass
                _current_dim = getattr(self.embedder, 'embedding_dim', None) or 768
                if _stored_dim and _stored_dim != _current_dim:
                    logger.warning(f"⚠️ Dim mismatch: index={_stored_dim}, embedder={_current_dim}. Recreating table...")
                    self.db.drop_table(self.table_name)
                    self.table = self.db.create_table(self.table_name, schema=self.schema)
                    logger.info(f"✅ Table recreated for {_current_dim}dim")
                    self._needs_full_reindex = True

        except Exception as open_err:
            logger.debug(f"Не удалось открыть таблицу: {open_err}. Пробуем создать.")
            try:
                self.table = self.db.create_table(self.table_name, schema=self.schema)
                logger.info(f"📦 Создана новая таблица: {self.table_name}")
            except Exception as create_err:
                # Если таблица уже существует (race condition) — пробуем открыть ещё раз
                err_str = str(create_err).lower()
                if "already exists" in err_str:
                    self.table = self.db.open_table(self.table_name)
                    logger.info(f"📦 Открыта таблица после гонки: {self.table_name}")
                else:
                    raise

        # Прогрев статуса: мгновенный подсчёт существующих чанков без сканирования диска.
        # Решает race condition "холодного старта".
        # Счётчики уже инициализированы в блоке threading выше.
        self._warmup_status()

        # ══════════════════════════════════════════════════════════
        # Index Guard: самовосстановление при сбоях
        # ══════════════════════════════════════════════════════════
        self._index_guard = IndexGuard(db_path, self.project_path)
        guard_report = self._index_guard.check_and_repair(self.db)
        if guard_report["status"] != "ok":
            logger.warning(
                f"⚠️ Index Guard: {guard_report['status']} — "
                f"{', '.join(guard_report['actions_taken'])}"
            )
            # Перезагружаем таблицу после возможных изменений
            try:
                self.table = self.db.open_table(self.table_name)
            except Exception:
                pass

        logger.info(f"📦 Движок LanceDB запущен. Индексы изолированы в {db_path}")

        # Загружаем сохранённый SymbolIndex с диска (если есть)
        try:
            if self._index_guard.load_symbol_index(self._symbol_index):
                logger.info(
                    f"SymbolIndex loaded: {self._symbol_index.get_symbol_count()} symbols"
                )
        except Exception:
            pass

    def watchdog_heartbeat(self, label: str = ""):
        """Обновляет heartbeat — вызывается при каждом прогрессе.

        Если индексер завис, watchdog не обновляется >60s.
        HealthReport проверяет это поле.
        """
        with self._watchdog_lock:
            self._watchdog_heartbeat = time.time()
            if label:
                self._watchdog_label = label

    def watchdog_status(self) -> dict:
        """Возвращает статус watchdog для HealthReport."""
        with self._watchdog_lock:
            age = time.time() - self._watchdog_heartbeat
            return {
                "alive": age < 60.0,
                "idle_sec": round(age, 1),
                "label": self._watchdog_label,
            }

    def set_searcher(self, searcher) -> None:
        """Ленивая инжекция Searcher (см. INC-53EC / REFC-05).

        Документированная альтернатива прямому присваиванию
        `indexer.searcher = ...` — не нарушает инкапсуляцию.
        Идемпотентен: повторный вызов заменяет ссылку.
        """
        self.searcher = searcher

    # ══════════════════════════════════════════════════════════
    # Async LanceDB API (неблокирующие чтения для поиска)
    # ══════════════════════════════════════════════════════════

    async def _ensure_async_table(self):
        """Ленивая thread-safe инициализация async-соединения LanceDB.

        Использует отдельный AsyncConnection для неблокирующих
        read-операций (поиск). Синхронный self.db остаётся для
        write-операций (индексация).

        Если таблица была сброшена извне — пересоздаёт её
        через синхронный self.db, затем открывает async-соединение.
        """
        if self._async_table is not None:
            return self._async_table
        async with self._async_db_lock:
            if self._async_table is not None:
                return self._async_table
            try:
                self._async_db = await lancedb.connect_async(self._lancedb_connect_path)
                self._async_table = await self._async_db.open_table(self.table_name)
                logger.debug(f"Async LanceDB подключён: {self._lancedb_connect_path}")
            except Exception as e:
                err_str = str(e).lower()
                if "not found" in err_str or "does not exist" in err_str:
                    logger.warning(
                        f"⚠️ Async таблица не найдена, пересоздаём через sync: {e}"
                    )
                    # Сначала закрываем неудачное async-соединение
                    if self._async_db is not None:
                        try:
                            await self._async_db.close()
                        except Exception:
                            pass
                        self._async_db = None
                    # Пересоздаём таблицу через синхронный API
                    if self._ensure_table_ready():
                        # Пробуем снова открыть async-соединение
                        try:
                            self._async_db = await lancedb.connect_async(
                                self._lancedb_connect_path
                            )
                            self._async_table = await self._async_db.open_table(
                                self.table_name
                            )
                            logger.debug(
                                f"Async LanceDB переподключён: {self._lancedb_connect_path}"
                            )
                        except Exception as retry_err:
                            logger.warning(f"Async LanceDB retry failed: {retry_err}")
                            self._async_db = None
                            self._async_table = None
                    else:
                        logger.error("Не удалось восстановить таблицу для async-поиска")
                else:
                    logger.warning(f"Async LanceDB init failed: {e}")
                    self._async_db = None
                    self._async_table = None
            return self._async_table

    async def search_async(
        self,
        query_vector: list,
        limit: int = 5,
        filter_expr: str = "",
    ) -> list:
        """Асинхронный векторный поиск через AsyncTable.

        В LanceDB >= 0.33 AsyncTable.search() возвращает coroutine →
        await даёт AsyncVectorQuery builder; builder.where() синхронен,
        builder.limit() синхронен, to_pandas() асинхронен.

        Args:
            query_vector: Вектор запроса.
            limit: Максимальное число результатов.
            filter_expr: SQL-выражение (например, "layer = 'core'").

        Returns:
            Список dict-ов с полями text, text_full, metadata.
        """
        table = await self._ensure_async_table()
        if table is None:
            return []

        try:
            builder = await table.search(query_vector, vector_column_name="vector")
            if filter_expr:
                builder = builder.where(filter_expr)
            df = await builder.limit(limit).to_pandas()

            results = []
            for _, row in df.iterrows():
                results.append(
                    {
                        "text": row["text"],
                        "text_full": row.get("text_full", row["text"]),
                        "metadata": {
                            "file": row["file_path"],
                            "chunk_index": row["chunk_index"],
                            "indexed_at": row.get("indexed_at", ""),
                            "layer": row.get("layer", ""),
                            "hierarchy_level": row.get("hierarchy_level", ""),
                            "parent_id": row.get("parent_id", ""),
                        },
                    }
                )
            return results
        except Exception as e:
            logger.error(f"Ошибка async векторного поиска LanceDB: {e}")
            return []

    async def to_pandas_async(self):
        """Асинхронная загрузка всей таблицы в DataFrame."""
        table = await self._ensure_async_table()
        if table is None:
            return None
        try:
            return await table.to_pandas()
        except Exception as e:
            logger.error(f"Ошибка async to_pandas: {e}")
            return None

    async def count_rows_async(self) -> int:
        """Асинхронный подсчёт строк таблицы."""
        table = await self._ensure_async_table()
        if table is None:
            return 0
        try:
            return await table.count_rows()
        except Exception:
            return 0

    async def close_async(self) -> None:
        """Закрывает async-соединение LanceDB."""
        if self._async_db is not None:
            try:
                await self._async_db.close()
            except Exception as e:
                logger.debug(f"Ошибка закрытия async LanceDB: {e}")
            finally:
                self._async_db = None
                self._async_table = None

    def _warmup_status(self) -> None:
        """Прогрев кэша чанков и уникальных файлов.

        count_rows() — O(1). Уникальные файлы читаются через
        search + select (без vector), что работает в LanceDB 0.33
        стабильно, в отличие от to_pandas(columns=[...]).
        """
        try:
            if self.table is None:
                return
            count = self.table.count_rows()
            self._cached_total_chunks = count
            if count > 0:
                logger.info(f"🔥 Прогрев статуса: в базе {count} чанков")
                # Тройной fallback для file_path
                _fp_set = None
                try:
                    ds = self.table.to_lance()
                    _fp_df = ds.to_pandas(columns=["file_path"])
                    if not _fp_df.empty:
                        _fp_set = set(_fp_df["file_path"].unique())
                except Exception:
                    try:
                        _fp_df = self.table.search().select(["file_path"]).limit(count).to_pandas()
                        if not _fp_df.empty:
                            _fp_set = set(_fp_df["file_path"].unique())
                    except Exception:
                        try:
                            _fp_df = self.table.to_pandas(columns=["file_path"])
                            if not _fp_df.empty:
                                _fp_set = set(_fp_df["file_path"].unique())
                        except Exception:
                            pass
                if _fp_set is not None:
                    self._cached_unique_files = _fp_set
                    logger.info(f"🔥 Прогрев статуса: {len(_fp_set)} файлов")
            else:
                logger.debug("🔥 Прогрев статуса: база пустая (первый запуск)")
        except Exception as e:
            err_str = str(e).lower()
            if "not found" in err_str or "does not exist" in err_str:
                logger.warning(
                    f"🔥 Таблица не найдена при прогреве: {e}. Будет создана при первой индексации."
                )
            else:
                logger.debug(f"🔥 Прогрев статуса не удался: {e}. Кэш = 0.")
            self._cached_total_chunks = 0

    def switch_project(self, project_path: Path) -> None:
        """Динамически переключает базу данных на проект.

        Позволяет использовать один инстанс Indexer для разных проектов.

        Args:
            project_path: Путь к корневой директории проекта.
                Должен существовать и быть директорией.

        Raises:
            FileNotFoundError: Если project_path не существует.
            NotADirectoryError: Если project_path не является директорией.
        """
        project_path = Path(project_path).resolve()

        if not project_path.exists():
            raise FileNotFoundError(f"Путь проекта не существует: {project_path}")
        if not project_path.is_dir():
            raise NotADirectoryError(f"Путь не является директорией: {project_path}")

        new_db_path = _generate_unique_db_path(project_path)
        if new_db_path == self.db_path:
            return  # Уже на нужной базе

        logger.info(f"🔄 Переключение БД: {self.db_path.name} → {new_db_path.name}")
        self.db_path = new_db_path
        self.project_path = project_path
        self.path_manager = SafePathManager(new_db_path.parent)

        # Переподключаемся к новой базе
        raw_path = str(new_db_path.resolve())
        # \\?\ (4 backslashes в Python-строке = 2 литеральных backslash)
        if raw_path.startswith("\\\\?\\"):
            lancedb_path = raw_path[4:]
        else:
            lancedb_path = raw_path

        Path(to_win_long_path(new_db_path)).mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(lancedb_path)
        self._lancedb_connect_path = lancedb_path

        # Сбрасываем async-соединение (пересоздастся лениво при следующем поиске)
        self._async_db = None
        self._async_table = None

        # Открываем или создаём таблицу
        try:
            self.table = self.db.open_table(self.table_name)
            logger.info(f"📦 Открыта таблица: {self.table_name}")
            # Проверяем схему — при необходимости мигрируем
            existing_fields = [f.name for f in self.table.schema]
            self._migrate_add_metadata_columns(existing_fields)
        except Exception:
            self.table = self.db.create_table(self.table_name, schema=self.schema)
            logger.info(f"📦 Создана таблица: {self.table_name}")

        # Прогрев кэша
        self._cached_total_chunks = 0
        self._cached_unique_files = set()
        self._warmup_status()

    def _calculate_file_hash(self, safe_path: Path) -> str:
        """Вычисляет хэш файла для отслеживания изменений (SHA256)."""
        hasher = hashlib.sha256()
        with open(str(safe_path), "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def get_status(self) -> Dict[str, Any]:
        """Возвращает статистику базы данных.

        Использует кэш количества чанков (_cached_total_chunks) и
        уникальных файлов (_cached_unique_files) для мгновенного
        ответа. Если кэш пуст — делает быстрый scan LanceDB.
        """
        try:
            total_chunks = self._cached_total_chunks
            if total_chunks == 0 and self.table is not None:
                try:
                    total_chunks = self.table.count_rows()
                    self._cached_total_chunks = total_chunks
                except Exception:
                    pass

            unique_files = getattr(self, "_cached_unique_files", 0)
            if isinstance(unique_files, set):
                unique_files = len(unique_files)

            # Если кэш пуст, но чанки есть — делаем быстрый запрос
            # Пробуем 3 fallback-метода: to_lance → search → to_pandas
            if unique_files == 0 and total_chunks > 0 and self.table is not None:
                _fp_series = None
                try:
                    ds = self.table.to_lance()
                    _fp_series = ds.to_pandas(columns=["file_path"])["file_path"]
                except Exception as e1:
                    logger.debug(f"get_status: to_lance failed ({e1}), trying search...")
                    try:
                        _fp_series = (
                            self.table.search()
                            .select(["file_path"])
                            .limit(total_chunks)
                            .to_pandas()
                        )["file_path"]
                    except Exception as e2:
                        logger.debug(f"get_status: search failed ({e2}), trying to_pandas...")
                        try:
                            _fp_series = self.table.to_pandas(columns=["file_path"])["file_path"]
                        except Exception:
                            logger.warning(f"get_status: все fallback-и не удались: {e1}")
                if _fp_series is not None and len(_fp_series) > 0:
                    unique_files = _fp_series.nunique()
                    self._cached_unique_files = set(_fp_series.unique())

            # Считаем stale/устаревшие файлы (быстрое сканирование диска)
            stale_files = 0
            on_disk_files = 0
            missing_files = 0
            if unique_files > 0 and self.project_path:
                try:
                    # Получаем file_hash из индекса для сверки
                    idx_df = self.table.search().select(["file_path", "file_hash"]).limit(total_chunks).to_pandas()
                    indexed_files = {}
                    if not idx_df.empty:
                        # Берём последний hash для каждого файла
                        for fp, fh in zip(idx_df["file_path"], idx_df["file_hash"]):
                            indexed_files[fp] = fh

                    # Сканируем файлы на диске (учитываем file_guard)
                    walk_root = str(self.project_path.resolve())
                    for root, dirs, files in os.walk(walk_root):
                        if self.file_guard:
                            dirs[:] = [d for d in dirs if not self.file_guard.should_skip_dir(d)]
                        for file_name in files:
                            full_path = Path(root) / file_name
                            if self.file_guard and self.file_guard.should_skip_file(full_path):
                                continue
                            on_disk_files += 1
                            try:
                                rel = str(full_path.relative_to(self.project_path)).replace(os.sep, "/")
                            except ValueError:
                                continue
                            if rel not in indexed_files:
                                missing_files += 1
                            else:
                                # Сверяем hash (быстро — только SHA256 первых 8KB)
                                try:
                                    hasher = hashlib.sha256()
                                    with open(str(full_path), "rb") as f:
                                        hasher.update(f.read(8192))
                                    current_hash = hasher.hexdigest()
                                    if current_hash != indexed_files[rel]:
                                        stale_files += 1
                                except Exception:
                                    pass
                except Exception as stale_err:
                    logger.debug(f"get_status: stale scan skipped: {stale_err}")

            watchdog = self.watchdog_status()
            return {
                "total_chunks": total_chunks,
                "unique_files": unique_files,
                "total_files": on_disk_files or unique_files,
                "stale_files": stale_files,
                "missing_files": missing_files,
                "status": "active" if total_chunks > 0 else "empty",
                "watchdog": watchdog,
            }
        except Exception as e:
            logger.error(f"get_status error: {e}")
            return {"error": str(e)}

    def _escape_file_path_for_lance(self, file_path: str) -> str:
        """Экранирует file_path для безопасного использования в where/delete запросах LanceDB.
        LanceDB не поддерживает параметризованные запросы, поэтому экранируем вручную.
        """
        # Экранируем одинарные кавычки (удвоением) и обратные слеши
        escaped = file_path.replace("'", "''")
        return escaped

    def _migrate_text_full_inplace(self) -> None:
        """Мигрирует text_full без drop_table (см. INC-53EC / REFC-07).

        Стратегия:
        1. Добавляем колонку через add_columns (если API доступно).
        2. На следующих вызовах _index_single_file text_full будет
           перезаписан при чанковании. Для старых записей оставляем
           копию text (медленно, но безопасно).
        """
        try:
            # LanceDB >= 0.5 поддерживает add_columns.
            if hasattr(self.table, "add_columns"):
                # Дефолтное значение — пустая строка. Заполним lazy
                # при следующем переиндексе.
                try:
                    self.table.add_columns({"text_full": ""})
                except TypeError:
                    # Старая сигнатура add_columns без value
                    self.table.add_columns({"text_full": "string"})
                logger.info("📦 add_columns(text_full) выполнен")
            else:
                logger.warning(
                    "add_columns недоступен — text_full будет заполняться "
                    "по мере переиндексации (без потери данных)."
                )
        except Exception as e:
            logger.warning(f"_migrate_text_full_inplace: {e}")

    def _migrate_add_metadata_columns(self, existing_fields: list) -> None:
        """Мигрирует Metadata Enrichment колонки (v2.4.3+).

        Пытается добавить поля layer, module_name, hierarchy_level, is_public,
        symbol_type, parent_id, callees, health_score, health_band
        в существующую таблицу.
        Использует три стратегии:
        1. add_columns — быстрая миграция без чтения данных.
           Работает в LanceDB < 0.30. На 0.33+ падает с SQL parser error
           из-за неэкранирования строковых значений по умолчанию.
        2. read-drop-recreate — если add_columns не сработал,
           пересоздаёт таблицу с полной схемой.
        3. _safe_recreate_table — если to_pandas() тоже упал (таблица
           повреждена), создаёт пустую таблицу с полной схемой.
        """
        # Проверяем, каких колонок не хватает
        string_columns = [
            "layer",
            "module_name",
            "hierarchy_level",
            "symbol_type",
            "parent_id",
            "callees",
            "health_band",
        ]
        bool_columns = ["is_public"]
        float_columns = ["health_score"]
        missing = [
            c
            for c in string_columns + bool_columns + float_columns
            if c not in existing_fields
        ]
        if not missing:
            return  # Все колонки уже есть

        logger.info(
            f"📦 Миграция metadata: не хватает {len(missing)} колонок: {missing}"
        )

        # Стратегия 1: add_columns (для LanceDB < 0.33)
        if hasattr(self.table, "add_columns"):
            all_ok = True
            for col in string_columns:
                if col not in existing_fields:
                    try:
                        self.table.add_columns({col: "string"})
                        logger.info(f"📦 Миграция: добавлена колонка {col}")
                    except Exception as e:
                        logger.debug(f"add_columns({col}) не сработал: {e}")
                        all_ok = False
                        break
            if all_ok and "is_public" not in existing_fields:
                try:
                    self.table.add_columns({"is_public": "bool"})
                    logger.info("📦 Миграция: добавлена колонка is_public")
                except Exception as e:
                    logger.debug(f"add_columns(is_public) не сработал: {e}")
                    all_ok = False
            if all_ok and "health_score" not in existing_fields:
                try:
                    # ВАЖНО: health_score — float64, передаём строку типа, а не значение
                    # В LanceDB 0.33+ add_columns принимает {name: type_str}
                    self.table.add_columns({"health_score": "float64"})
                    logger.info("📦 Миграция: добавлена колонка health_score")
                except Exception as e:
                    logger.debug(f"add_columns(health_score) не сработал: {e}")
                    all_ok = False
            if all_ok:
                logger.info("📦 Миграция metadata через add_columns завершена")
                return

        # Стратегия 2: read-drop-recreate (надёжно для всех версий LanceDB)
        logger.info("📦 Миграция metadata: читаем существующие данные...")
        try:
            try:
                old_df = self.table.to_pandas()
            except Exception as pandas_err:
                # Таблица может быть повреждена (сброшена внешним скриптом)
                logger.warning(
                    f"📦 to_pandas() не доступен ({pandas_err}), создаём пустую таблицу"
                )
                self._safe_recreate_table()
                return

            logger.info(f"📦 Миграция: прочитано {len(old_df)} чанков")

            # Восстанавливаем отсутствующие поля с пустыми значениями
            for col in string_columns:
                if col not in old_df.columns:
                    old_df[col] = ""
            if "is_public" not in old_df.columns:
                old_df["is_public"] = False
            if "health_score" not in old_df.columns:
                old_df["health_score"] = 0.0

            # Пересоздаём таблицу с полной схемой
            self.db.drop_table(self.table_name)
            self.table = self.db.create_table(self.table_name, schema=self.schema)

            # Конвертируем DataFrame в список словарей
            records = []
            for _, row in old_df.iterrows():
                record = {
                    "id": str(row["id"]),
                    "vector": row["vector"],
                    "text": str(row["text"]),
                    "text_full": str(row.get("text_full", row["text"])),
                    "file_path": str(row["file_path"]),
                    "file_hash": str(row.get("file_hash", "")),
                    "chunk_index": int(row.get("chunk_index", 0)),
                    "source": str(row.get("source", "filesystem")),
                    "indexed_at": str(row.get("indexed_at", "")),
                    "summary": str(row.get("summary", "")),
                    "layer": str(row.get("layer", "")),
                    "module_name": str(row.get("module_name", "")),
                    "hierarchy_level": str(row.get("hierarchy_level", "")),
                    "is_public": bool(row.get("is_public", False)),
                    "symbol_type": str(row.get("symbol_type", "")),
                    "parent_id": str(row.get("parent_id", "")),
                    "callees": str(row.get("callees", "")),
                    "health_score": float(row.get("health_score", 0.0)),
                    "health_band": str(row.get("health_band", "")),
                }
                records.append(record)

            self.table.add(records)
            logger.info(
                f"📦 Миграция metadata завершена: {len(records)} чанков пересозданы с полной схемой"
            )
        except Exception as e:
            logger.error(
                f"❌ Миграция metadata провалилась: {e}. "
                f"Метаданные появятся после полной переиндексации."
            )

    def _safe_recreate_table(self) -> bool:
        """Безопасно пересоздаёт таблицу с полной схемой.

        Используется когда таблица повреждена, сброшена извне или
        migration не удался. Сбрасывает кэши и обновляет self.table.

        Returns:
            True если таблица создана, False при ошибке.
        """
        try:
            # Пытаемся удалить таблицу если существует
            try:
                self.db.drop_table(self.table_name)
            except Exception:
                pass

            # Создаём новую таблицу с полной схемой
            self.table = self.db.create_table(self.table_name, schema=self.schema)

            # Сбрасываем кэши (таблица пуста)
            self._cached_total_chunks = 0
            self._cached_unique_files = set()

            # Сбрасываем async-кэш (будет пересоздан лениво)
            self._async_table = None

            # Сбрасываем BM25-индекс Searcher-а (будет перестроен лениво)
            if hasattr(self, "searcher") and self.searcher is not None:
                try:
                    self.searcher.reindex()
                except Exception:
                    pass

            logger.info(f"📦 Таблица {self.table_name} пересоздана с полной схемой")
            return True
        except Exception as e:
            logger.error(f"❌ Не удалось пересоздать таблицу: {e}")
            return False

    def _ensure_table_ready(self) -> bool:
        """Проверяет, что таблица существует и доступна для записи.

        Если таблица была сброшена извне или повреждена — пересоздаёт её.
        Безопасно вызывает count_rows() для проверки.

        Returns:
            True если таблица готова, False если не удалось восстановить.
        """
        if self.table is None:
            return self._safe_recreate_table()

        try:
            # Быстрая проверка: count_rows не читает данные, только metadata
            self.table.count_rows()
            return True
        except Exception as e:
            err_str = str(e).lower()
            if (
                "not found" in err_str
                or "does not exist" in err_str
                or "no such table" in err_str
            ):
                logger.warning(f"⚠️ Таблица не найдена ({e}), пересоздаём...")
                return self._safe_recreate_table()
            if "corrupt" in err_str or "io error" in err_str:
                logger.warning(f"⚠️ Таблица повреждена ({e}), пересоздаём...")
                return self._safe_recreate_table()
            # Другая ошибка — логируем, но не трогаем таблицу
            logger.debug(f"_ensure_table_ready: {e}")
            return True

    def _write_file_records(
        self,
        parsed: Dict,
        embeddings: List[List[float]],
    ) -> bool:
        """Запись результатов эмбеддинга в LanceDB.

        Принимает результат `_parse_file_only` и список векторов,
        собирает PyArrow-записи и атомарно пишет в таблицу.

        Args:
            parsed: результат _parse_file_only
            embeddings: список векторов (по одному на чанк)

        Returns:
            True если запись успешна, иначе False
        """
        rel_path_str = parsed["rel_path"]
        current_hash = parsed["current_hash"]
        escaped_path = parsed["escaped_path"]
        existing_hash = parsed["existing_hash"]
        chunk_texts = parsed["chunk_texts"]
        chunk_texts_full = parsed["chunk_texts_full"]
        chunk_metadatas = parsed["chunk_metadatas"]
        health = parsed["health"]
        source = parsed["source"]

        if not embeddings or len(embeddings) != len(chunk_texts):
            logger.warning(
                f"⚠️ Несовпадение числа эмбеддингов и чанков для {rel_path_str}: "
                f"{len(embeddings)} vs {len(chunk_texts)}"
            )
            return False

        _target_dim = self.embedder.embedding_dim or 768
        data_records = []
        for i, (chunk_text, chunk_vec) in enumerate(zip(chunk_texts, embeddings)):
            # Нормализация вектора под размерность схемы
            if len(chunk_vec) != _target_dim:
                chunk_vec = chunk_vec[:_target_dim] + [0.0] * (_target_dim - len(chunk_vec))

            full_text = (
                chunk_texts_full[i] if i < len(chunk_texts_full) else chunk_text
            )

            # LLM-описание если включено
            summary = ""
            if self.summarizer and self.enable_summaries:
                symbol_name = ""
                if self.parser and hasattr(self.parser, "_current_symbol"):
                    symbol_name = getattr(self.parser, "_current_symbol", "")
                summary = self.summarizer.summarize_chunk(chunk_text, symbol_name)

            meta = chunk_metadatas[i] if i < len(chunk_metadatas) else {}

            data_records.append(
                {
                    "id": f"{hashlib.md5(rel_path_str.encode()).hexdigest()}_{i}",
                    "vector": chunk_vec,
                    "text": chunk_text,
                    "text_full": full_text,
                    "file_path": rel_path_str,
                    "file_hash": current_hash,
                    "chunk_index": i,
                    "source": source,
                    "indexed_at": datetime.now().isoformat(),
                    "summary": summary,
                    "layer": meta.get("layer", ""),
                    "module_name": meta.get("module_name", ""),
                    "hierarchy_level": meta.get("hierarchy_level", "other"),
                    "is_public": meta.get("is_public", False),
                    "symbol_type": meta.get("symbol_type", ""),
                    "parent_id": meta.get("parent_id", ""),
                    "callees": meta.get("callees", ""),
                    "health_score": health.get("score", 0.0),
                    "health_band": health.get("band", ""),
                }
            )

        # Атомарная запись пачки чанков в таблицу
        with self._table_write_lock:
            old_chunks = 0
            if existing_hash is not None:
                try:
                    old_chunks = self.table.count_rows(
                        filter=f"file_path = '{escaped_path}'"
                    )
                except Exception:
                    pass
                try:
                    self.table.delete(f"file_path = '{escaped_path}'")
                except Exception as del_err:
                    logger.debug(f"delete() не нашёл запись: {del_err}")

            try:
                self.table.add(data_records)
            except Exception as add_err:
                err_str = str(add_err).lower()
                if (
                    "not found" in err_str
                    or "does not exist" in err_str
                    or "no such table" in err_str
                ):
                    logger.warning(
                        f"⚠️ Таблица не найдена при записи, пересоздаём и ретраим: {add_err}"
                    )
                    if self._safe_recreate_table():
                        self.table.add(data_records)
                    else:
                        raise
                else:
                    raise

        # Синхронизация кэша
        with self._index_lock:
            if old_chunks > 0:
                self._cached_total_chunks = max(
                    0, self._cached_total_chunks - old_chunks + len(data_records)
                )
            else:
                self._cached_total_chunks += len(data_records)
            self._cached_unique_files.add(rel_path_str)

        # Сохраняем SymbolIndex на диск
        try:
            self._index_guard.save_symbol_index(self._symbol_index)
        except Exception:
            pass

        logger.info(
            f"✅ Записано в БД: {rel_path_str} ({len(chunk_texts)} чанков)"
        )
        return True

    def _parse_file_only(
        self,
        full_path: Path,
        rel_path_str: str,
        source: str = "filesystem",
        known_hashes: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict]:
        """Только парсинг файла (без эмбеддинга и записи в БД).

        Returns:
            Dict с данными чанков или None если файл не изменился.
            Структура: {
                "rel_path": str, "current_hash": str, "escaped_path": str,
                "existing_hash": str | None, "chunk_texts": List[str],
                "chunk_texts_full": List[str], "chunk_metadatas": List[Dict],
                "health": Dict, "source": str
            }
        """
        try:
            safe_read_path = self.path_manager.get_safe_path(full_path)
            with open(str(safe_read_path), "rb") as f:
                raw_data = f.read()
            content = raw_data.decode("utf-8", errors="replace")

            current_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
            escaped_path = self._escape_file_path_for_lance(rel_path_str)

            # Проверка хэша (один bulk-запрос в index_project или per-file в _index_single_file)
            existing_hash = None
            if known_hashes is not None:
                existing_hash = known_hashes.get(rel_path_str)
            else:
                try:
                    if self.table is not None:
                        existing_df = (
                            self.table.search()
                            .where(f"file_path = '{escaped_path}'", prefilter=True)
                            .limit(1)
                            .to_pandas()
                        )
                        if not existing_df.empty:
                            existing_hash = str(existing_df["file_hash"].iloc[0])
                except Exception:
                    pass

            if existing_hash == current_hash:
                return None  # не изменился

            if not content.strip():
                return None

            # Очистка PropertyGraph
            if hasattr(self._symbol_index, "graph"):
                pg = self._symbol_index.graph
                if pg:
                    pg.remove_file(rel_path_str.replace("\\", "/"))

            # AST-чанкинг + Breadcrumbs (как в _index_single_file)
            chunk_texts: List[str] = []
            chunk_texts_full: List[str] = []
            chunk_metadatas: List[Dict] = []
            health = {"score": 0.0, "band": ""}

            if self.parser is not None:
                try:
                    ast_chunks, symbols = self.parser.parse_file(full_path)
                    if ast_chunks:
                        for c in ast_chunks:
                            compact = c.get("text_compact", "") or c.get("text", "")
                            full = c.get("text", "")
                            if compact.strip():
                                _module = c.get("module_name", "")
                                _level = c.get("hierarchy_level", "other")
                                _type = c.get("symbol_type", c.get("type", ""))
                                _scope_parts = [p for p in [_level, _type, _module] if p]
                                _scope = " | ".join(_scope_parts) if _scope_parts else _module
                                _header = f"// File: {rel_path_str} | Scope: {_scope}\n"
                                chunk_texts.append(_header + compact)
                                chunk_texts_full.append(_header + full)
                                chunk_metadatas.append({
                                    "layer": c.get("layer", ""),
                                    "module_name": c.get("module_name", ""),
                                    "hierarchy_level": c.get("hierarchy_level", "other"),
                                    "is_public": c.get("is_public", False),
                                    "symbol_type": c.get("symbol_type", c.get("type", "")),
                                    "parent_id": c.get("parent_id", ""),
                                    "callees": c.get("callees", ""),
                                })
                    if symbols:
                        with self._symbol_index_lock:
                            self._symbol_index.add_definitions(str(full_path), symbols)
                        calls = self.parser.extract_calls(full_path)
                        if calls:
                            with self._symbol_index_lock:
                                self._symbol_index.add_references(str(full_path), calls)
                        assignments = self.parser.extract_assignments(full_path)
                        if assignments:
                            with self._symbol_index_lock:
                                self._symbol_index.add_assignments(str(full_path), assignments)
                except Exception as ast_err:
                    logger.warning(f"⚠️ AST-чанкинг не удался для {rel_path_str}: {ast_err}")
                    chunk_texts = []
                    chunk_metadatas = []

            if not chunk_texts:
                _fb_header = f"// File: {rel_path_str} | Scope: fallback\n"
                chunk_texts = [
                    _fb_header + content[i : i + 1000] for i in range(0, len(content), 800)
                ]
                chunk_texts_full = chunk_texts
                chunk_metadatas = [{
                    "layer": "", "module_name": "", "hierarchy_level": "other",
                    "is_public": False, "symbol_type": "", "parent_id": "", "callees": "",
                } for _ in chunk_texts]

            if not chunk_texts:
                return None

            # Code Health
            try:
                from src.core.code_health import score_file
                health = score_file(rel_path_str, self.project_path)
            except Exception:
                pass

            return {
                "rel_path": rel_path_str,
                "current_hash": current_hash,
                "escaped_path": escaped_path,
                "existing_hash": existing_hash,
                "chunk_texts": chunk_texts,
                "chunk_texts_full": chunk_texts_full,
                "chunk_metadatas": chunk_metadatas,
                "health": health,
                "source": source,
            }
        except Exception as e:
            logger.warning(f"⚠️ Ошибка парсинга {rel_path_str}: {e}")
            return None

    def _index_single_file(
        self,
        full_path: Path,
        rel_path_str: str,
        content: Optional[str] = None,
        source: str = "filesystem",
    ) -> bool:
        """Индицирует один файл, если его хэш изменился.

        Args:
            full_path: Абсолютный путь к файлу
            rel_path_str: Относительный путь для хранения в базе
            content: Готовый текст файла (из памяти LSP). Если None — читает с диска.
            source: источник индексации — 'lsp_vfs' (память IDE) или 'filesystem' (диск)
        """
        try:
            safe_read_path = self.path_manager.get_safe_path(full_path)

            # Если контент не передан — читаем с диска
            if content is None:
                with open(str(safe_read_path), "rb") as f:
                    raw_data = f.read()
                content = raw_data.decode("utf-8", errors="replace")

            # Вычисляем хэш из контента (не с диска)
            current_hash = hashlib.md5(content.encode("utf-8")).hexdigest()

            # Экранируем путь для SQL-like where-выражений LanceDB
            escaped_path = self._escape_file_path_for_lance(rel_path_str)

            # Проверяем, есть ли уже этот файл с таким же хэшем в LanceDB.
            # Используем table.search().where(...) вместо to_pandas() по всей
            # таблице — см. INC-53EC / REFC-09. Раньше: O(N) на каждый чанк.
            existing_hash = None
            try:
                # LanceDB SQL: фильтрация по file_path нативно.
                existing_df = (
                    self.table.search()
                    .where(f"file_path = '{escaped_path}'", prefilter=True)
                    .limit(1)
                    .to_pandas()
                )
                if not existing_df.empty:
                    existing_hash = str(existing_df["file_hash"].iloc[0])
            except Exception:
                # Fallback: пусть будет без хеша → переиндексируем.
                pass

            if existing_hash == current_hash:
                return False  # Файл не изменился, пропускаем

            # СТАРЫЙ delete ПЕРЕМЕЩЁН ниже — после compute, перед add.
            # Раньше delete был здесь, до parser + embedder, что приводило
            # к потере файла из индекса при таймауте между delete и add.
            # Теперь: compute safe → delete (fast) → add (fast).
            # INC-TIMEOUT-FIX v3.1

            if not content.strip():
                return False

            # Очистка старых данных файла из PropertyGraph перед переиндексацией
            if hasattr(self._symbol_index, "graph"):
                pg = self._symbol_index.graph
                if pg:
                    rel_posix = rel_path_str.replace("\\", "/")
                    pg.remove_file(rel_posix)

            # AST-aware чанкинг через CodeParser (если доступен)
            # Fallback: примитивное деление по 1000 символов с перекрытием 200
            #
            # Стратегия экономии токенов:
            # - text_compact (сигнатура + 3 строки тела) → для эмбеддинга и поиска
            # - text_full (полный код функции) → для детального анализа по запросу
            #
            # Metadata Enrichment (v2.4.3+):
            # - layer, module_name, hierarchy_level, is_public, symbol_type, parent_id
            chunk_texts = []  # компактные тексты для эмбеддинга
            chunk_texts_full = []  # полные тексты для хранения
            chunk_metadatas = []  # метаданные для Metadata Enrichment
            health = {"score": 0.0, "band": ""}  # Code Health v3.0
            if self.parser is not None:
                try:
                    ast_chunks, symbols = self.parser.parse_file(full_path)
                    if ast_chunks:
                        for c in ast_chunks:
                            compact = c.get("text_compact", "") or c.get("text", "")
                            full = c.get("text", "")
                            if compact.strip():
                                # Контекстуальный заголовок (breadcrumb) для E5-base
                                # Каждый чанк получает «якорь»: файл + модуль + тип символа
                                # Это компенсирует ограничение окна 512 токенов E5-base.
                                _module = c.get("module_name", "")
                                _level = c.get("hierarchy_level", "other")
                                _type = c.get("symbol_type", c.get("type", ""))
                                _scope_parts = [p for p in [_level, _type, _module] if p]
                                _scope = " | ".join(_scope_parts) if _scope_parts else _module
                                _header = f"// File: {rel_path_str} | Scope: {_scope}\n"
                                compact_with_ctx = _header + compact
                                full_with_ctx = _header + full
                                chunk_texts.append(compact_with_ctx)
                                chunk_texts_full.append(full_with_ctx)
                                # Извлекаем метаданные из результата парсера
                                chunk_metadatas.append(
                                    {
                                        "layer": c.get("layer", ""),
                                        "module_name": c.get("module_name", ""),
                                        "hierarchy_level": c.get(
                                            "hierarchy_level", "other"
                                        ),
                                        "is_public": c.get("is_public", False),
                                        "symbol_type": c.get(
                                            "symbol_type", c.get("type", "")
                                        ),
                                        "parent_id": c.get("parent_id", ""),
                                        "callees": c.get("callees", ""),
                                    }
                                )
                        logger.debug(
                            f"🌳 AST-чанкинг: {full_path.name} → {len(chunk_texts)} семантических чанков"
                        )
                    # Добавляем определения символов в SymbolIndex (thread-safe)
                    if symbols:
                        with self._symbol_index_lock:
                            self._symbol_index.add_definitions(str(full_path), symbols)
                        # Извлекаем связи вызовов
                        calls = self.parser.extract_calls(full_path)
                        if calls:
                            with self._symbol_index_lock:
                                self._symbol_index.add_references(str(full_path), calls)
                        # ASSIGNED_FROM: отслеживание присваиваний переменных
                        assignments = self.parser.extract_assignments(full_path)
                        if assignments:
                            with self._symbol_index_lock:
                                self._symbol_index.add_assignments(str(full_path), assignments)
                except Exception as ast_err:
                    logger.warning(
                        f"⚠️ AST-чанкинг не удался для {rel_path_str}, fallback: {ast_err}"
                    )
                    chunk_texts = []
                    chunk_metadatas = []

            if not chunk_texts:
                # Fallback: символьное деление с перекрытием + контекстуальный заголовок
                _fb_header = f"// File: {rel_path_str} | Scope: fallback\n"
                chunk_texts = [
                    _fb_header + content[i : i + 1000] for i in range(0, len(content), 800)
                ]
                chunk_texts_full = chunk_texts
                chunk_metadatas = [
                    {
                        "layer": "",
                        "module_name": "",
                        "hierarchy_level": "other",
                        "is_public": False,
                        "symbol_type": "",
                        "parent_id": "",
                        "callees": "",
                    }
                    for _ in chunk_texts
                ]

            if not chunk_texts:
                return False

            # v3.0: Code Health — вычисляем один раз на файл
            try:
                from src.core.code_health import score_file

                health = score_file(rel_path_str, self.project_path)
            except Exception:
                pass

            # Получение эмбеддингов через провайдер
            embeddings = self.embedder.embed_batch(chunk_texts)
            import gc
            gc.collect()  # освободить ONNX тензоры
            if not embeddings or any(len(e) == 0 for e in embeddings):
                logger.warning(
                    f"⚠️ Пустые эмбеддинги для файла {rel_path_str}. Пропуск записи."
                )
                return False

            # Собираем parsed-словарь и делегируем запись в _write_file_records
            parsed = {
                "rel_path": rel_path_str,
                "current_hash": current_hash,
                "escaped_path": escaped_path,
                "existing_hash": existing_hash,
                "chunk_texts": chunk_texts,
                "chunk_texts_full": chunk_texts_full,
                "chunk_metadatas": chunk_metadatas,
                "health": health,
                "source": source,
            }
            result = self._write_file_records(parsed, embeddings)
            import gc
            gc.collect()
            return result

        except Exception as e:
            logger.error(f"❌ Критический сбой индексации файла {rel_path_str}: {e}")
            return False

    def prune_deleted_files(self, active_files_on_disk: Set[str]) -> int:
        """Удаляет из базы данных файлы, которых больше нет на физическом диске.

        Args:
            active_files_on_disk: Полный набор файлов на диске (не только удалённые!).

        Returns:
            Количество удалённых файлов.

        Warning:
            НЕ вызывайте эту функцию с одним элементом — это удалит все
            остальные файлы из базы! Используйте delete_file() для одиночного удаления.
        """
        if self._cached_total_chunks == 0:
            return 0
        if not active_files_on_disk:
            logger.warning(
                "⚠️ prune_deleted_files вызван с пустым набором файлов. Пропуск."
            )
            return 0

        try:
            # Arrow-native: в 5-10x быстрее и в 3x меньше RAM чем to_pandas
            import pyarrow.compute as pc

            tbl = self.table.to_arrow()
            files_in_db = pc.unique(tbl["file_path"]).to_pylist()
            deleted_files = set(files_in_db) - active_files_on_disk

            if deleted_files:
                # Safety ratio: не удалять >50% индекса за раз — это значит
                # что active_files_on_disk неполный (прерванная индексация).
                total_files_in_db = len(files_in_db)
                delete_ratio = len(deleted_files) / max(total_files_in_db, 1)
                if delete_ratio > 0.5:
                    logger.warning(
                        f"⚠️ Safety guard: prune_deleted_files хочет удалить "
                        f"{len(deleted_files)}/{total_files_in_db} файлов "
                        f"({delete_ratio:.0%}). Пропуск — active_files_on_disk неполный."
                    )
                    return 0

                logger.info(
                    "🧹 Обнаружены удаленные файлы. Начинается чистка базы от мёртвого груза..."
                )
                total_deleted_chunks = 0
                for file_path in deleted_files:
                    escaped = self._escape_file_path_for_lance(file_path)

                    # Подсчёт чанков из Arrow-таблицы (без to_pandas)
                    fp_mask = pc.equal(tbl["file_path"], file_path)
                    file_chunks = int(pc.sum(fp_mask).as_py() or 0)
                    total_deleted_chunks += file_chunks

                    self.table.delete(f"file_path = '{escaped}'")

                    # Очистка PropertyGraph
                    if hasattr(self._symbol_index, "graph"):
                        pg = self._symbol_index.graph
                        if pg:
                            rel_posix = file_path.replace("\\", "/")
                            deleted_nodes = pg.remove_file(rel_posix)
                            if deleted_nodes:
                                logger.info(
                                    f"  └─ Изъято из PropertyGraph: {deleted_nodes} узлов"
                                )

                    logger.info(f"  └─ Изъят из индекса: {file_path}")

                # Синхронизация кэша: декремент на количество удалённых чанков
                if total_deleted_chunks > 0:
                    self._cached_total_chunks = max(
                        0, self._cached_total_chunks - total_deleted_chunks
                    )
                for fp in deleted_files:
                    self._cached_unique_files.discard(fp)

                # Compaction: оптимизация хранения после удаления данных
                # LanceDB накапливает stale версии, compaction освобождает место
                if total_deleted_chunks > 50:
                    try:
                        import gc

                        gc.collect()  # Принудительная сборка перед compaction
                        logger.info(
                            f"🗜️ Compaction: {total_deleted_chunks} чанков удалено, "
                            f"запускаю оптимизацию..."
                        )
                        self.table.compact_files()
                        logger.info("✅ Compaction завершён")
                    except Exception as compact_err:
                        logger.debug(f"Compaction не удался: {compact_err}")

                logger.info("✅ База данных полностью синхронизирована с диском.")
                return len(deleted_files)
            return 0
        except Exception as e:
            logger.error(f"Ошибка при выполнении операции Pruning: {e}")
            return 0

    def delete_file(self, rel_path_str: str) -> bool:
        """Удаляет один файл из базы по относительному пути. Безопасно для одиночного удаления."""
        try:
            escaped = self._escape_file_path_for_lance(rel_path_str)

            # Подсчёт количества удаляемых чанков для корректного декремента кэша
            deleted_count = 0
            try:
                df_all = self.table.to_pandas()
                if not df_all.empty:
                    deleted_count = int((df_all["file_path"] == rel_path_str).sum())
            except Exception:
                pass

            self.table.delete(f"file_path = '{escaped}'")

            # Синхронизация кэша: декремент на количество удалённых чанков
            if deleted_count > 0:
                self._cached_total_chunks = max(
                    0, self._cached_total_chunks - deleted_count
                )
            self._cached_unique_files.discard(rel_path_str)

            logger.info(f"🗑️ Удалён файл: {rel_path_str}")
            return True
        except Exception as e:
            logger.debug(f"delete_file() не нашёл запись {rel_path_str}: {e}")
            return False

    def move_chunks_metadata(self, old_path: str, new_path: str) -> int:
        """P0 Meta-patching: update file_path in LanceDB WITHOUT re-embedding.

        Extracts old chunks, changes file_path metadata, re-inserts same vectors.
        Returns count of affected chunks for BM25 sync.

        Args:
            old_path: Old relative file path
            new_path: New relative file path

        Returns:
            Number of chunks moved
        """
        # Sanitize paths for LanceDB SQL filter
        safe_old = old_path.replace("\\", "/").replace("'", "''")
        safe_new = new_path.replace("\\", "/").replace("'", "''")

        if safe_old == safe_new:
            return 0

        try:
            # 1. Read old chunks with vectors and metadata
            old_df = self.table.search().where(f"file_path = '{safe_old}'").limit(10000).to_pandas()

            if old_df.empty:
                logger.debug(f"move_chunks_metadata: no chunks found for {old_path}")
                return 0

            count = len(old_df)

            # 2. Delete old entries from vector index
            self.table.delete(f"file_path = '{safe_old}'")

            # 3. Mutate metadata
            old_df['file_path'] = safe_new
            old_df['module_name'] = self._infer_module_name(new_path)
            old_df['layer'] = self._infer_layer(new_path)
            old_df['indexed_at'] = datetime.now().isoformat()

            # 4. Re-insert same vectors with new metadata
            self.table.add(old_df.to_dict('records'))

            # 5. Invalidate cache
            self._cached_total_chunks = None
            self._cached_unique_files.discard(old_path)

            logger.info(f"\u267b\ufe0f Meta-patched {count} chunks: {old_path} \u2192 {new_path}")
            return count

        except Exception as e:
            logger.error(f"move_chunks_metadata failed: {old_path} \u2192 {new_path}: {e}")
            return 0

    def apply_file_move(self, old_path: str, new_path: str) -> dict:
        """Coordinate file rename across all index layers.

        Instead of notify_change (which triggers full reindex),
        this does fast meta-patching in all layers.

        Args:
            old_path: Old relative file path
            new_path: New relative file path

        Returns:
            Dict with status, chunks_moved, symbol_updates
        """
        results = {"status": "ok", "chunks_moved": 0, "symbol_updates": 0, "bm25": "invalidated"}

        # 1. LanceDB meta-patching
        chunks = self.move_chunks_metadata(old_path, new_path)
        results["chunks_moved"] = chunks

        # 2. SymbolIndex remap
        try:
            symbol_updates = self._symbol_index.remap_file(old_path, new_path)
            results["symbol_updates"] = symbol_updates
        except Exception as e:
            logger.warning(f"SymbolIndex remap failed: {e}")
            results["symbol_updates"] = -1

        # 3. BM25 invalidation (next search will rebuild from LanceDB)
        if self.searcher is not None and hasattr(self.searcher, '_reset_bm25'):
            try:
                self.searcher._reset_bm25()
                results["bm25"] = "invalidated"
            except Exception as e:
                logger.debug(f"BM25 reset failed: {e}")

        # 4. Notify file guard
        try:
            if hasattr(self.file_guard, 'notify_file_renamed'):
                self.file_guard.notify_file_renamed(old_path, new_path)
        except Exception:
            pass

        return results

    def _infer_module_name(self, file_path: str) -> str:
        """Infer Python module name from relative file path.

        E.g., 'src/core/indexer.py' \u2192 'core.indexer'
        """
        p = Path(file_path.replace("\\", "/"))
        stem = p.stem
        parts = p.parts
        # Find package root (src/, app/, lib/, or first meaningful dir)
        skip_dirs = {"src", "app", "lib"}
        module_parts = []
        in_package = False
        for part in parts[:-1]:  # exclude filename
            if not in_package:
                if part in skip_dirs:
                    in_package = True
                continue
            module_parts.append(part)
        module_parts.append(stem)
        return ".".join(module_parts)

    def _infer_layer(self, file_path: str) -> str:
        """Infer architectural layer from file path.

        E.g., 'src/core/foo.py' \u2192 'core', 'src/mcp/tools/bar.py' \u2192 'mcp_tools'
        """
        parts = file_path.replace("\\", "/").split("/")
        if "core" in parts:
            return "core"
        if "mcp" in parts:
            if "tools" in parts:
                return "mcp_tools"
            return "mcp"
        if "tests" in parts:
            return "tests"
        if "utils" in parts:
            return "utils"
        if "docs" in parts:
            return "docs"
        return "root"

    def verify_index_freshness(self, project_path: Path) -> int:
        """Быстрая проверка: переиндексирует только файлы с изменившимся hash.

        В отличие от index_project:
        - Не удаляет orphan файлы (только предупреждает)
        - Не перестраивает BM25
        - Не создаёт IVF_PQ индекс
        - Работает за 2-5 секунд вместо 5 минут

        Returns: количество переиндексированных файлов.
        """
        project_path = Path(project_path).resolve()
        if not project_path.exists():
            return 0

        if self.table is None:
            return 0

        try:
            # Получаем все file_hash из индекса
            df = self.table.to_pandas(columns=["file_path", "file_hash"])
        except Exception:
            return 0

        if df.empty:
            return 0

        indexed_hashes = dict(zip(df["file_path"], df["file_hash"]))

        reindexed = 0
        walk_root = str(project_path.resolve())
        for root, dirs, files in os.walk(walk_root):
            dirs[:] = [d for d in dirs if not self.file_guard.should_skip_dir(d)]
            for file_name in files:
                full_path = Path(root) / file_name
                if self.file_guard.should_skip_file(full_path):
                    continue
                try:
                    rel = str(full_path.relative_to(project_path)).replace(
                        os.sep, "/"
                    )
                except ValueError:
                    continue

                # Если файла нет в индексе — пропускаем (не наша забота)
                if rel not in indexed_hashes:
                    continue

                # Сверяем hash
                try:
                    current_hash = self._calculate_file_hash(full_path)
                except Exception:
                    continue

                if current_hash == indexed_hashes[rel]:
                    continue  # не изменился

                # Файл изменился — переиндексируем
                if self._index_single_file(full_path, project_path):
                    reindexed += 1

        if reindexed > 0:
            logger.info(f"📝 Переиндексировано {reindexed} изменённых файлов")
        else:
            logger.info("✅ Индекс свежий, изменений нет")

        return reindexed

    def index_project(
        self, project_path: Path, progress_callback: Optional[Callable] = None
    ) -> int:
        """Полное сканирование проекта.

        1. Инкрементально добавляет новые/измененные файлы.
        2. Автоматически удаляет из базы файлы, стертые с диска (Pruning).

        Args:
            project_path: Путь к корневой директории проекта.
                Должен существовать и быть директорией.
            progress_callback: Опциональный callback для отслеживания прогресса.
                Вызывается с аргументами: (current_file, files_done, files_total, phase)
                phase: 'scanning', 'embedding', 'complete'

        Returns:
            Количество индексированных (новых/изменённых) файлов.

        Raises:
            FileNotFoundError: Если project_path не существует.
            NotADirectoryError: Если project_path не является директорией.
        """
        project_path = Path(project_path).resolve()

        if not project_path.exists():
            raise FileNotFoundError(f"Путь проекта не существует: {project_path}")
        if not project_path.is_dir():
            raise NotADirectoryError(f"Путь не является директорией: {project_path}")

        logger.info(f"🚀 Старт фоновой синхронизации проекта: {project_path}")
        indexed_count = 0
        current_files_on_disk: Set[str] = set()

        if not self.path_manager.is_safe_to_process(project_path):
            logger.warning(f"Путь не прошёл проверку безопасности: {project_path}")
            if progress_callback:
                progress_callback("", 0, 0, "error_security")
            return 0

        # Подсчёт общего числа файлов для прогресса
        all_files: list = []
        walk_root = str(project_path.resolve())
        for root, dirs, files in os.walk(walk_root):
            dirs[:] = [d for d in dirs if not self.file_guard.should_skip_dir(d)]
            for file_name in files:
                full_path = Path(root) / file_name
                if self.file_guard.should_skip_file(full_path):
                    continue
                all_files.append((root, file_name, full_path))

        total_files = len(all_files)
        logger.info(f"📁 Найдено {total_files} файлов для индексации")

        if progress_callback:
            progress_callback("", 0, total_files, "scanning")

        # Уведомление через NotificationBroker — сквозной прогресс 0-100%
        # через все фазы: Phase 1 (parse) 0-70%, Phase 2 (embed) 70-90%, Phase 3 (write) 90-100%
        def _notify_progress(
            done: int, total: int, phase: str, current: str,
            offset_pct: float = 0.0, span_pct: float = 100.0,
        ):
            if not self._notification_broker:
                return
            raw = (done / total) if total > 0 else 0.0
            continuous = offset_pct + raw * span_pct
            pct = int(continuous)
            if (
                pct == 0
                or pct == 100
                or (pct % 5 == 0 and pct != self._last_reported_progress)
            ):
                self._last_reported_progress = pct
                self._notification_broker.publish_sync(
                    "mscodebase/indexing_status",
                    {
                        "status": "indexing" if pct < 100 else "idle",
                        "progress": pct,
                        "total_chunks": total,
                        "current_file": current or "",
                    },
                )

        _notify_progress(0, total_files, "scanning", "", 0, 5)

        # ═══════════════════════════════════════════════════════════
        # Batch Embedder: Фаза 1 (Parse) → Фаза 2 (Sort+Embed) → Фаза 3 (Write)
        # ═══════════════════════════════════════════════════════════
        #
        # Фаза 1 (параллельный парсинг):
        #   workers парсят файлы → список parsed (с хэшами)
        #
        # Фаза 2 (сортировка + батчинг):
        #   все чанки собираются в плоский список
        #   сортируются по длине (чтобы минимизировать padding)
        #   эмбеддятся батчами по _BATCH_SIZE
        #
        # Фаза 3 (запись):
        #   результаты разбираются обратно по файлам → _write_file_records
        # ═══════════════════════════════════════════════════════════

        # ── Фаза 1: Параллельный парсинг ───────────────────────────
        from concurrent.futures import ThreadPoolExecutor

        _max_workers = min(4, (os.cpu_count() or 4) // 2)
        _all_parsed: list = []  # список {"parsed": Dict, "name": str}
        _parse_errors = []

        def _parse_worker_file(args):
            _idx, _root, _fname, _full_path = args
            _rel_path = str(_full_path.relative_to(project_path))
            current_files_on_disk.add(_rel_path)

            try:
                parsed = self._parse_file_only(
                    _full_path, _rel_path, source="filesystem"
                )
                if parsed is not None:
                    return {"parsed": parsed, "name": _fname, "rel": _rel_path}
            except Exception as e:
                return {"error": str(e), "rel": _rel_path}
            return None

        _parsed_list: list = []
        with ThreadPoolExecutor(max_workers=_max_workers) as _exec:
            _futs = []
            for idx, (root, fname, fpath) in enumerate(all_files):
                _futs.append(_exec.submit(_parse_worker_file, (idx, root, fname, fpath)))
            
            for i, fut in enumerate(_futs):
                try:
                    res = fut.result()
                    if res:
                        if "error" in res:
                            _parse_errors.append((res["rel"], res["error"]))
                        else:
                            _parsed_list.append(res)
                            self.watchdog_heartbeat(f"parse:{res['name']}")
                except Exception as e:
                    logger.warning(f"\u26a0\ufe0f Worker error: {e}")
                
                # Прогресс парсинга
                if i % max(1, total_files // 20) == 0 or i == total_files - 1:
                    if progress_callback:
                        try:
                            progress_callback("", i + 1, total_files, "parsing")
                        except Exception:
                            pass
                    _notify_progress(i + 1, total_files, "parsing", "", 5, 50)

        parsed_count = len(_parsed_list)
        logger.info(f"\u2705 Парсинг завершён: {parsed_count} файлов изменено из {total_files}")

        if parsed_count == 0:
            logger.info("\u2705 Нет изменённых файлов — индекс актуален")
            indexed_count = 0
            # Всё равно делаем pruning и финализируем
            pruned = self.prune_deleted_files(current_files_on_disk)
            if self.searcher:
                self.searcher.reindex()
            if progress_callback:
                progress_callback("", total_files, total_files, "complete")
            _notify_progress(total_files, total_files, "complete", "", 0, 100)
            return 0

        # ── Фаза 2: Сортировка + батчинг эмбеддинга ────────────────
        # Собираем все чанки в плоский список с индексами файлов
        _flat_chunks: list = []  # [(file_idx, text), ...]
        for fp_idx, fp_data in enumerate(_parsed_list):
            parsed = fp_data["parsed"]
            for chunk_text in parsed["chunk_texts"]:
                _flat_chunks.append((fp_idx, chunk_text))

        total_chunks = len(_flat_chunks)
        logger.info(f"\U0001f4ca Всего чанков: {total_chunks}, batch_size={_BATCH_SIZE}")

        # Сортируем по длине текста (минимизируем padding)
        _flat_chunks.sort(key=lambda x: len(x[1]))

        # Проверка: embedder готов?
        if not getattr(self.embedder, 'is_ready', lambda: True)():
            logger.error("❌ Embedder не готов к работе. Индексация прервана.")
            return 0

        # Батчим по _BATCH_SIZE
        _all_embeddings: list = [None] * total_chunks
        _embed_t0 = time.time()

        for batch_start in range(0, total_chunks, _BATCH_SIZE):
            batch_end = min(batch_start + _BATCH_SIZE, total_chunks)
            batch_data = _flat_chunks[batch_start:batch_end]
            batch_texts = [text for (_, text) in batch_data]
            batch_indices = [idx for (idx, _) in batch_data]

            # Эмбеддинг батча
            t0 = time.time()
            try:
                embeddings = self.embedder.embed_batch(batch_texts)
            except Exception as embed_err:
                logger.error(f"❌ Embedder error: {embed_err}. Пропускаем батч.")
                embeddings = [[0.0] * (self.embedder.embedding_dim or 768) for _ in batch_texts]
                # Продолжаем с нулевыми векторами — лучше пустой поиск, чем краш
            embed_time = time.time() - t0

            if not embeddings or len(embeddings) != len(batch_texts):
                logger.warning(f"⚠️ embed вернул {len(embeddings) if embeddings else 0} вместо {len(batch_texts)}")
                embeddings = [[0.0] * (self.embedder.embedding_dim or 768) for _ in batch_texts]

            # Раскладываем результаты обратно по flat-индексу
            for i, flat_idx in enumerate(range(batch_start, batch_end)):
                _all_embeddings[flat_idx] = embeddings[i]

            # Мониторинг каждые 5 батчей
            if batch_start % (_BATCH_SIZE * 5) == 0 or batch_end >= total_chunks:
                elapsed = time.time() - _embed_t0
                done = min(batch_end, total_chunks)
                speed = done / elapsed if elapsed > 0 else 0
                try:
                    from src.core.resource_monitor import get_monitor
                    mon = get_monitor()
                    snap = mon.sample(force=True)
                    ram_info = f"RAM={snap.rss_mb:.0f}MB CPU={snap.cpu_percent:.0f}%"
                except Exception:
                    ram_info = ""
                logger.info(
                    f"\U0001f4ca [embed] {done}/{total_chunks} chunks "
                    f"{ram_info} "
                    f"batch={len(batch_texts)}ch/{embed_time:.1f}s={len(batch_texts)/max(embed_time,0.001):.0f}ch/s "
                    f"avg={speed:.0f}ch/s elapsed={elapsed:.0f}s"
                )
                _notify_progress(done, total_chunks, "embedding", "", 50, 40)
                self.watchdog_heartbeat(f"embed:{done}/{total_chunks}")

            import gc
            gc.collect()

        _embed_total = time.time() - _embed_t0
        logger.info(f"\u2705 Эмбеддинг завершён: {total_chunks} чанков за {_embed_total:.1f}s ({total_chunks/max(_embed_total,0.001):.0f} ch/s)")
        _notify_progress(total_chunks, total_chunks, "writing", "", 90, 10)

        # ── Фаза 3: Запись результатов по файлам ────────────────────
        # Восстанавливаем маппинг: для каждого файла собираем его embeddings
        _file_embeddings: dict = {}  # {fp_idx: {parsed: ..., vecs: [...]}}
        for flat_idx, (fp_idx, _) in enumerate(_flat_chunks):
            if fp_idx not in _file_embeddings:
                _file_embeddings[fp_idx] = {
                    "parsed": _parsed_list[fp_idx]["parsed"],
                    "vecs": [],
                }
            _file_embeddings[fp_idx]["vecs"].append(_all_embeddings[flat_idx])

        indexed_count = 0
        for fp_idx, fdata in _file_embeddings.items():
            try:
                if self._write_file_records(fdata["parsed"], fdata["vecs"]):
                    indexed_count += 1
                    self.watchdog_heartbeat(f"write:{Path(fdata['parsed']['rel_path']).name}")
            except Exception as e:
                logger.warning(f"\u26a0\ufe0f Ошибка записи {fdata['parsed']['rel_path']}: {e}")

        logger.info(f"\u2705 Запись завершена: {indexed_count} файлов записано")

        # Финальное уведомление
        if progress_callback:
            progress_callback("", total_files, total_files, "indexing")

        # Пауза: даём Windows сбросить буферы записи (race condition LanceDB)
        time.sleep(1)

        # Шаг 2: Автоматическое вычищение (Pruning) «мертвого груза"
        pruned = 0
        try:
            pruned = self.prune_deleted_files(current_files_on_disk)
            if pruned > 0:
                logger.info(f"🗑️ Удалено {pruned} устаревших файлов из базы")
        except Exception as prune_err:
            logger.warning(f"⚠️ Pruning не удался (некритично): {prune_err}")

        # Шаг 3: Перестройка BM25 индекса
        if indexed_count > 0 and self.searcher:
            if progress_callback:
                progress_callback("", total_files, total_files, "rebuilding_bm25")
            self.searcher.reindex()

        # Шаг 4: Создание индекса для ускорения косинусного поиска
        if self.table and self.table.count_rows() > 1000:
            try:
                # 1. Flush данных на диск (compaction)
                try:
                    self.table.optimize(compaction=True)
                except Exception as opt_err:
                    logger.debug(f"optimize: {opt_err}")

                # 2. Пауза для Windows I/O
                time.sleep(2)

                # 3. Проверка реального количества строк
                _row_count = self.table.count_rows()
                logger.info(f"📊 Создаю индекс ({_row_count} чанков)...")
                if _row_count == 0:
                    logger.warning("⚠️ Таблица пуста после optimize, индекс пропущен")
                    return

                # Удаляем старый индекс
                try:
                    for idx in self.table.list_indices():
                        idx_name = getattr(idx, "name", None)
                        if idx_name:
                            self.table.drop_index(idx_name)
                except Exception:
                    pass

                # 4. IVF_FLAT — стабилен на Windows, без KMeans/PQ
                self.table.create_index(
                    metric="cosine",
                    vector_column_name="vector",
                    index_type="IVF_FLAT",
                    replace=True,
                )
                logger.info("✅ IVF_FLAT индекс создан")
            except Exception as e:
                logger.error(f"⚠️ IVF_PQ индекс не создан: {e}")

        # Шаг 5: Финальная статистика
        final_stats = self.get_status()

        if progress_callback:
            progress_callback("", total_files, total_files, "complete")

        # Финальное Push-уведомление
        _notify_progress(total_files, total_files, "complete", "", 0, 100)

        # Сохраняем кэш суммари
        if self.summarizer:
            self.summarizer.save_cache()

        # Сохраняем SymbolIndex на диск (persistence между перезапусками)
        if hasattr(self, "_symbol_index") and self._symbol_index:
            self._index_guard.save_symbol_index(self._symbol_index)

        logger.info(
            f"✅ Индексация завершена: {indexed_count} новых/изменённых, "
            f"{pruned} удалено, всего {final_stats.get('total_chunks', 0)} чанков"
        )

        return indexed_count

    def index_file(
        self, full_path: Path, project_path: Path, content: Optional[str] = None
    ) -> bool:
        """Публичный метод для индексации одного файла (вызывается из LSP-сервера).

        Args:
            full_path: Абсолютный путь к файлу
            project_path: Корневая директория проекта
            content: Готовый текст файла из памяти LSP (didSave). Если None — читает с диска.

        Returns:
            True если файл был проиндексирован, False если пропущен
        """
        try:
            if not self.path_manager.is_safe_to_process(full_path):
                return False
            if self.file_guard.should_skip_file(full_path):
                return False

            rel_path_str = str(full_path.relative_to(project_path))
            return self._index_single_file(full_path, rel_path_str, content=content)
        except Exception as e:
            logger.error(f"[index_file] Ошибка индексации {full_path}: {e}")
            return False
