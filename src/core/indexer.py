"""
MSCodebase Intelligence — Продакшен инкрементальный индекс на LanceDB с авто-очисткой (Pruning)
"""

import hashlib
import logging
import os
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
    project_root = project_path.parent
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
    ):
        self.db_path = db_path
        self.embedder = embedder
        self.file_guard = file_guard
        self.path_manager = SafePathManager(db_path.parent)
        self.searcher = None
        self.project_path = project_path or db_path.parent.parent.parent
        self.parser = parser  # CodeParser для AST-aware чанкинга

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

        # Подключение к LanceDB (чистый путь, без \\?\)
        # Для предотвращения блокировок при параллельной индексации
        # используем WAL режим (если поддерживается)
        self.db = lancedb.connect(lancedb_path)

        # Схема таблицы: id, vector, text, text_full, file_path, file_hash, chunk_index, source, summary
        # text — компактный чанк (сигнатура + превью) для эмбеддинга и экономии токенов
        # text_full — полный текст функции/метода (для детального анализа по запросу)
        # source — источник индексации: 'lsp_vfs' (память IDE) или 'filesystem' (диск)
        # summary — LLM-описание чанка (для улучшения семантического поиска)
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
            ]
        )

        self.table_name = "codebase_chunks"
        # LanceDB может кэшировать список таблиц, из-за чего open_table и create_table
        # могут кидать race condition. Пробуем открыть, при ошибке — создаём,
        # при "already exists" — пробуем открыть снова.
        try:
            self.table = self.db.open_table(self.table_name)
            # Проверяем, что схема содержит text_full (миграция)
            existing_fields = [f.name for f in self.table.schema]
            if "text_full" not in existing_fields:
                logger.warning("⚠️ Миграция: добавляем text_full в существующую таблицу")

                try:
                    old_df = self.table.to_pandas()
                    records = []

                    if len(old_df) > 0:
                        # Гарантируем наличие колонки для копирования данных
                        if "text_full" not in old_df.columns:
                            old_df["text_full"] = old_df["text"]

                        # 1. СНАЧАЛА ПОЛНОСТЬЮ ФОРМИРУЕМ И ВАЛИДИРУЕМ ДАННЫЕ В ПАМЯТИ
                        for _, row in old_df.iterrows():
                            # Безопасное извлечение chunk_index (защита от NaN/Float в Pandas)
                            try:
                                import pandas as pd

                                c_idx = (
                                    int(row["chunk_index"])
                                    if pd.notna(row["chunk_index"])
                                    else 0
                                )
                            except Exception:
                                c_idx = 0

                            records.append(
                                {
                                    "id": str(row["id"]),
                                    "vector": row["vector"],
                                    "text": str(row["text"]),
                                    "text_full": str(row["text_full"]),
                                    "file_path": str(row["file_path"]),
                                    "file_hash": str(row["file_hash"]),
                                    "chunk_index": c_idx,
                                    "source": str(row.get("source", "filesystem")),
                                    "indexed_at": str(row.get("indexed_at", "")),
                                    "summary": str(row.get("summary", "")),
                                }
                            )

                    # 2. АТОМАРНАЯ СМЕНА ТАБЛИЦЫ (только если сбор данных выше не упал)
                    self.db.drop_table(self.table_name)
                    self.table = self.db.create_table(
                        self.table_name, schema=self.schema
                    )

                    if len(records) > 0:
                        self.table.add(records)
                        logger.info(
                            f"📦 Миграция успешно завершена: {len(records)} записей восстановлено"
                        )
                    else:
                        logger.info(
                            "📦 Миграция завершена: исходная таблица была пустой"
                        )

                except Exception as mig_err:
                    # 3. АБСОЛЮТНАЯ ЗАЩИТА: никакого деструктивного drop_table при ошибках!
                    logger.critical(
                        f"❌ Критическая ошибка миграции данных: {mig_err}. Данные СОХРАНЕНЫ в старой таблице."
                    )
                    # Восстанавливаем стабильное подключение к исходной таблице
                    try:
                        self.table = self.db.open_table(self.table_name)
                    except Exception:
                        # Фолбек на создание чистой таблицы только если старая физически стёрта
                        self.table = self.db.create_table(
                            self.table_name, schema=self.schema
                        )
            else:
                logger.info(f"📦 Открыта существующая таблица: {self.table_name}")
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

    def _warmup_status(self) -> None:
        """Мгновенный прогрев кэша количества чанков при старте.

        Открывает существующую таблицу LanceDB и считает количество записей
        без запуска сканирования диска и без обращения к эмбеддеру.
        Результат сохраняется в self._cached_total_chunks.

        При первом запуске (база ещё не существует) кэш остаётся 0.
        Любая ошибка прогрева логируется как debug и не ломает инициализацию.
        """
        try:
            if self.table is None:
                return
            count = self.table.count_rows()
            self._cached_total_chunks = count
            if count > 0:
                logger.info(
                    f"🔥 Прогрев статуса: в базе {count} чанков (cold start предотвращён)"
                )
            else:
                logger.debug("🔥 Прогрев статуса: база пустая (первый запуск)")
        except Exception as e:
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
        if raw_path.startswith("\\?\\"):
            lancedb_path = raw_path[4:]
        else:
            lancedb_path = raw_path

        Path(to_win_long_path(new_db_path)).mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(lancedb_path)

        # Открываем или создаём таблицу
        try:
            self.table = self.db.open_table(self.table_name)
            logger.info(f"📦 Открыта таблица: {self.table_name}")
        except Exception:
            self.table = self.db.create_table(self.table_name, schema=self.schema)
            logger.info(f"📦 Создана таблица: {self.table_name}")

    def _calculate_file_hash(self, safe_path: Path) -> str:
        """Вычисляет хэш файла для отслеживания изменений (SHA256)."""
        hasher = hashlib.sha256()
        with open(str(safe_path), "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def get_status(self) -> Dict[str, Any]:
        """Возвращает статистику базы данных.

        Использует кэш количества чанков (_cached_total_chunks) для мгновенного
        ответа без сканирования таблицы. При пустой базе или ошибке кэша
        выполняет полный подсчёт через to_pandas() как fallback.
        """
        try:
            total_chunks = self._cached_total_chunks

            if total_chunks == 0:
                # Fallback: полный подсчёт (для случаев, когда кэш не прогрет)
                try:
                    total_chunks = self.table.count_rows()
                    self._cached_total_chunks = total_chunks
                except Exception:
                    pass

                if total_chunks == 0:
                    return {
                        "total_chunks": 0,
                        "unique_files": 0,
                        "total_files": 0,
                        "status": "empty",
                    }

            try:
                df = self.table.to_pandas()
                unique_files = df["file_path"].nunique()
            except ImportError:
                # Fallback: pandas не загрузился — используем PyArrow напрямую
                arrow_table = self.table.to_arrow()
                unique_files = pc.count_distinct(
                    arrow_table.column("file_path")
                ).as_py()
            except Exception:
                # Любая другая ошибка конвертации — возвращаем хотя бы общее число чанков
                return {
                    "total_chunks": total_chunks,
                    "unique_files": 0,
                    "total_files": 0,
                    "status": "active",
                }

            return {
                "total_chunks": total_chunks,
                "unique_files": int(unique_files),
                "total_files": int(unique_files),
                "status": "active",
            }
        except Exception as e:
            logger.error(f"Ошибка получения статистики индекса: {e}")
            return {"error": str(e)}

    def _escape_file_path_for_lance(self, file_path: str) -> str:
        """Экранирует file_path для безопасного использования в where/delete запросах LanceDB.
        LanceDB не поддерживает параметризованные запросы, поэтому экранируем вручную.
        """
        # Экранируем одинарные кавычки (удвоением) и обратные слеши
        escaped = file_path.replace("'", "''")
        return escaped

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

            # Проверяем, есть ли уже этот файл с таким же хэшем в LanceDB
            existing_hash = None
            try:
                df_all = self.table.to_pandas()
                if not df_all.empty:
                    match = df_all[df_all["file_path"] == rel_path_str]
                    if not match.empty:
                        existing_hash = match["file_hash"].iloc[0]
            except Exception:
                pass

            if existing_hash == current_hash:
                return False  # Файл не изменился, пропускаем

            # Если файл изменился или новый — удаляем его старые чанки
            if existing_hash is not None:
                try:
                    # Подсчёт старых чанков для корректного декремента кэша
                    old_chunks = 0
                    try:
                        df_check = self.table.to_pandas()
                        if not df_check.empty:
                            old_chunks = int(
                                (df_check["file_path"] == rel_path_str).sum()
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
            chunk_texts = []  # компактные тексты для эмбеддинга
            chunk_texts_full = []  # полные тексты для хранения
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

            if not chunk_texts:
                # Fallback: символьное деление с перекрытием
                chunk_texts = [
                    content[i : i + 1000] for i in range(0, len(content), 800)
                ]
                chunk_texts_full = (
                    chunk_texts  # fallback: текст и полный текст одинаковы
                )

            if not chunk_texts:
                return False

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
                    }
                )

            # Атомарная запись пачки чанков в таблицу
            self.table.add(data_records)

            # Синхронизация кэша: инкремент на количество добавленных чанков
            # (старые чанки этого файла уже были удалены выше, поэтому чистый +N)
            self._cached_total_chunks += len(data_records)

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

        # Шаг 1: Сканирование диска и обновление базы
        for idx, (root, file_name, full_path) in enumerate(all_files):
            rel_path_str = str(full_path.relative_to(project_path))
            current_files_on_disk.add(rel_path_str)

            if progress_callback:
                progress_callback(file_name, idx + 1, total_files, "scanning")

            try:
                if self._index_single_file(full_path, rel_path_str):
                    indexed_count += 1
            except Exception as e:
                logger.warning(f"Ошибка индексации {rel_path_str}: {e}")

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
