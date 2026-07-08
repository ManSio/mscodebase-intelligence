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
from typing import Any, Callable, Dict, Optional, Set

import lancedb
import pyarrow as pa
import pyarrow.compute as pc

from src.core.chunk_summarizer import ChunkSummarizer
from src.core.index_guard import IndexGuard
from src.utils.paths import SafePathManager, to_win_long_path

logger = logging.getLogger("mscodebase_server.indexer")


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

        # SymbolIndex для отслеживания определений и вызовов
        # Если передан внешний индекс — используем его, иначе создаём новый
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
                    "vector", pa.list_(pa.float32(), 1024)
                ),  # Фиксируем под MiniLM / BGE размерность
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
        # Решает race condition "холодного старта" — агент Zed видит реальное количество
        # чанков с первой миллисекунды, не дожидаясь завершения lazy-инициализации LanceDB.
        self._cached_total_chunks: int = 0
        self._cached_unique_files: set = set()
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
        """Мгновенный прогрев кэша количества чанков (O(1)).

        Использует только count_rows() — БЕЗ to_pandas(), потому что
        to_pandas() читает ВСЕ данные и падает на повреждённых файлах.
        _cached_unique_files заполняется инкрементально из _index_single_file.
        """
        try:
            if self.table is None:
                return
            count = self.table.count_rows()
            self._cached_total_chunks = count
            if count > 0:
                logger.info(f"🔥 Прогрев статуса: в базе {count} чанков")
                # _cached_unique_files заполняется лениво при _index_single_file
                # Показываем 0 — при первом запросе статуса будет пересчитано
                logger.debug(
                    "🔥 unique_files будет заполнен инкрементально при индексации"
                )
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
        """Возвращает статистику базы данных (O(1), без to_pandas).

        Использует кэш количества чанков (_cached_total_chunks) и
        уникальных файлов (_cached_unique_files) для мгновенного
        ответа. Без сканирования таблицы.

        Для полной статистики с to_pandas() — используйте get_full_stats().
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

            return {
                "total_chunks": total_chunks,
                "unique_files": unique_files,
                "total_files": unique_files,
                "status": "active" if total_chunks > 0 else "empty",
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

            # Если файл изменился или новый — удаляем его старые чанки
            if existing_hash is not None:
                try:
                    # Подсчёт старых чанков для корректного декремента кэша.
                    # limit=10000 — аномально большие файлы встречаются редко;
                    # пересчёт в случае превышения не критичен (кэш обновится
                    # на следующем get_status).
                    old_chunks = 0
                    try:
                        old_chunks = self.table.count_rows(
                            filter=f"file_path = '{escaped_path}'"
                        )
                    except Exception:
                        pass

                    self.table.delete(f"file_path = '{escaped_path}'")

                    # Декремент кэша на количество удалённых старых чанков
                    if old_chunks > 0:
                        self._cached_total_chunks = max(
                            0, self._cached_total_chunks - old_chunks
                        )
                except Exception as del_err:
                    logger.debug(
                        f"delete() не нашёл запись (первичная индексация): {del_err}"
                    )

            if not content.strip():
                return False

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
                                chunk_texts.append(compact)
                                chunk_texts_full.append(full)
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
                    # Добавляем определения символов в SymbolIndex
                    if symbols:
                        self._symbol_index.add_definitions(str(full_path), symbols)
                        # Извлекаем связи вызовов
                        calls = self.parser.extract_calls(full_path)
                        if calls:
                            self._symbol_index.add_references(str(full_path), calls)
                except Exception as ast_err:
                    logger.warning(
                        f"⚠️ AST-чанкинг не удался для {rel_path_str}, fallback: {ast_err}"
                    )
                    chunk_texts = []
                    chunk_metadatas = []

            if not chunk_texts:
                # Fallback: символьное деление с перекрытием
                chunk_texts = [
                    content[i : i + 1000] for i in range(0, len(content), 800)
                ]
                chunk_texts_full = (
                    chunk_texts  # fallback: текст и полный текст одинаковы
                )
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

            # Получение эмбеддингов через провайдер (LM Studio)
            # Эмбеддинги считаются от компактных танков — быстрее и точнее
            embeddings = self.embedder.embed_batch(chunk_texts)
            if not embeddings or any(len(e) == 0 for e in embeddings):
                logger.warning(
                    f"⚠️ Пустые эмбеддинги для файла {rel_path_str}. Пропуск записи."
                )
                return False

            # Подготовка данных для PyArrow
            data_records = []
            for i, (chunk_text, chunk_vec) in enumerate(zip(chunk_texts, embeddings)):
                # Нормализация вектора под размерность схемы
                if len(chunk_vec) != 1024:
                    # Приведение размерности (дополнение нулями или обрезка) при форс-мажорах API
                    chunk_vec = chunk_vec[:1024] + [0.0] * (1024 - len(chunk_vec))

                # Полный текст для детального анализа (если есть)
                full_text = (
                    chunk_texts_full[i] if i < len(chunk_texts_full) else chunk_text
                )

                # Генерируем LLM-описание если включено
                summary = ""
                if self.summarizer and self.enable_summaries:
                    symbol_name = ""
                    if self.parser and hasattr(self.parser, "_current_symbol"):
                        symbol_name = getattr(self.parser, "_current_symbol", "")
                    summary = self.summarizer.summarize_chunk(chunk_text, symbol_name)

                # Метаданные для Metadata Enrichment (v2.4.3+)
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
                        # Metadata Enrichment (MCompassRAG + SproutRAG)
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
            # Если таблица была сброшена извне — пересоздаём и ретраим
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

            # Синхронизация кэша: инкремент на количество добавленных чанков
            # (старые чанки этого файла уже были удалены выше, поэтому чистый +N)
            self._cached_total_chunks += len(data_records)
            self._cached_unique_files.add(rel_path_str)

            logger.info(
                f"✅ Успешно проиндексирован: {rel_path_str} ({len(chunk_texts)} чанков)"
            )
            return True

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
            df = self.table.to_pandas()
            files_in_db = set(df["file_path"].unique())
            deleted_files = files_in_db - active_files_on_disk

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

                    # Подсчёт чанков для декремента кэша
                    file_chunks = int((df["file_path"] == file_path).sum())
                    total_deleted_chunks += file_chunks

                    self.table.delete(f"file_path = '{escaped}'")
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

        # Уведомление через NotificationBroker (синхронный вызов из thread)
        def _notify_progress(done: int, total: int, phase: str, current: str):
            if not self._notification_broker:
                return
            pct = int((done / total) * 100) if total > 0 else 0
            # Троттлинг: шлём только на 0%, 5%, 10%, ..., 100%
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

        _notify_progress(0, total_files, "scanning", "")

        # Шаг 1: Сканирование диска и обновление базы
        # Adaptive throttling (INC-6BCB): при высокой RAM/CPU делаем
        # короткие паузы между файлами, чтобы не блокировать Zed IDE.
        _throttle_monitor = None
        try:
            from src.core.resource_monitor import get_global_resource_monitor

            _throttle_monitor = get_global_resource_monitor()
        except Exception:
            pass
        _last_throttle_check = 0.0

        for idx, (root, file_name, full_path) in enumerate(all_files):
            rel_path_str = str(full_path.relative_to(project_path))
            current_files_on_disk.add(rel_path_str)

            if progress_callback:
                progress_callback(file_name, idx + 1, total_files, "scanning")
            _notify_progress(idx + 1, total_files, "scanning", file_name)

            try:
                if self._index_single_file(full_path, rel_path_str):
                    indexed_count += 1
            except Exception as e:
                logger.warning(f"Ошибка индексации {rel_path_str}: {e}")

            # Throttle: не чаще раза в секунду, чтобы не тратить CPU на
            # сам мониторинг. При soft pressure — 0.1s, hard — до 2s.
            if _throttle_monitor is not None and idx % 10 == 0:
                now = time.monotonic()
                if now - _last_throttle_check > 1.0:
                    delay = _throttle_monitor.suggest_throttle_delay_sec()
                    if delay > 0.01:
                        time.sleep(delay)
                    _last_throttle_check = now

        # Шаг 2: Автоматическое вычищение (Pruning) «мертвого груза"
        pruned = self.prune_deleted_files(current_files_on_disk)
        if pruned > 0:
            logger.info(f"🗑️ Удалено {pruned} устаревших файлов из базы")

        # Шаг 3: Перестройка BM25 индекса
        if indexed_count > 0 and self.searcher:
            if progress_callback:
                progress_callback("", total_files, total_files, "rebuilding_bm25")
            self.searcher.reindex()

        # Шаг 4: Финальная статистика
        final_stats = self.get_status()

        if progress_callback:
            progress_callback("", total_files, total_files, "complete")

        # Финальное Push-уведомление
        _notify_progress(total_files, total_files, "complete", "")

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
