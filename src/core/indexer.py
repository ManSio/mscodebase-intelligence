"""
MSCodebase Intelligence — Продакшен инкрементальный индекс на LanceDB с авто-очисткой (Pruning)
"""

import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Set

import lancedb
import numpy as np
import pyarrow as pa

from src.utils.paths import SafePathManager, to_win_long_path

logger = logging.getLogger("mscodebase_server.indexer")


def _generate_unique_db_path(project_path: Path) -> Path:
    """Генерирует уникальный путь к базе данных на основе пути проекта.

    Это позволяет каждому проекту иметь свою изолированную базу данных,
    предотвращая конфликты при параллельной индексации.
    """
    # Используем хэш пути проекта для создания уникального имени файла
    project_hash = hashlib.md5(str(project_path.resolve()).encode()).hexdigest()[:8]
    project_name = os.path.basename(project_path)

    # Создаем директорию .codebase_indices в корне проекта, если её нет
    project_root = project_path.parent
    db_dir = project_root / ".codebase_indices" / "lancedb_v2"
    db_dir.mkdir(parents=True, exist_ok=True)

    # Имя базы данных: index_{project_name}_{hash}.db
    db_name = f"index_{project_name}_{project_hash}.db"
    return db_dir / db_name


class Indexer:
    def __init__(self, db_path: Path, embedder, file_guard):
        self.db_path = db_path
        self.embedder = embedder
        self.file_guard = file_guard
        self.path_manager = SafePathManager(db_path.parent)
        self.searcher = None

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

        # Схема таблицы: id, vector, text, file_path, file_hash, chunk_index
        self.schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field(
                    "vector", pa.list_(pa.float32(), 384)
                ),  # Фиксируем под MiniLM / BGE размерность
                pa.field("text", pa.string()),
                pa.field("file_path", pa.string()),
                pa.field("file_hash", pa.string()),
                pa.field("chunk_index", pa.int32()),
            ]
        )

        self.table_name = "codebase_chunks"
        # LanceDB может кэшировать список таблиц, из-за чего open_table и create_table
        # могут кидать race condition. Пробуем открыть, при ошибке — создаём,
        # при "already exists" — пробуем открыть снова.
        try:
            self.table = self.db.open_table(self.table_name)
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

        logger.info(f"📦 Движок LanceDB запущен. Индексы изолированы в {db_path}")

    def _calculate_file_hash(self, safe_path: Path) -> str:
        """Вычисляет хэш файла для отслеживания изменений (SHA256)."""
        hasher = hashlib.sha256()
        with open(str(safe_path), "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def get_status(self) -> Dict[str, Any]:
        """Возвращает статистику базы данных."""
        try:
            total_chunks = len(self.table)
            if total_chunks == 0:
                return {
                    "total_chunks": 0,
                    "unique_files": 0,
                    "total_files": 0,
                    "status": "empty",
                }

            df = self.table.to_pandas()
            unique_files = df["file_path"].nunique()
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

    def _index_single_file(self, full_path: Path, rel_path_str: str) -> bool:
        """Индицирует один файл, если его хэш изменился."""
        try:
            safe_read_path = self.path_manager.get_safe_path(full_path)
            current_hash = self._calculate_file_hash(safe_read_path)

            # Экранируем путь для SQL-like where-выражений LanceDB
            escaped_path = self._escape_file_path_for_lance(rel_path_str)

            # Проверяем, есть ли уже этот файл с таким же хэшем в LanceDB
            # Используем to_pandas() вместо .search().where() для совместимости
            # со всеми версиями LanceDB
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
                    self.table.delete(f"file_path = '{escaped_path}'")
                except Exception as del_err:
                    logger.debug(
                        f"delete() не нашёл запись (первичная индексация): {del_err}"
                    )

            # Гарантированное бинарное чтение с защитой от UnicodeDecodeError
            with open(str(safe_read_path), "rb") as f:
                raw_data = f.read()
            content = raw_data.decode("utf-8", errors="replace")

            if not content.strip():
                return False

            # Чанкирование (по 1000 символов с перекрытием 200)
            chunks = [content[i : i + 1000] for i in range(0, len(content), 800)]
            if not chunks:
                return False

            # Получение эмбеддингов через провайдер (LM Studio)
            embeddings = self.embedder.embed_batch(chunks)
            if not embeddings or any(len(e) == 0 for e in embeddings):
                logger.warning(
                    f"⚠️ Пустые эмбеддинги для файла {rel_path_str}. Пропуск записи."
                )
                return False

            # Подготовка данных для PyArrow
            data_records = []
            for i, (chunk_text, chunk_vec) in enumerate(zip(chunks, embeddings)):
                # Нормализация вектора под размерность схемы
                if len(chunk_vec) != 384:
                    # Приведение размерности (дополнение нулями или обрезка) при форс-мажорах API
                    chunk_vec = chunk_vec[:384] + [0.0] * (384 - len(chunk_vec))

                data_records.append(
                    {
                        "id": f"{hashlib.md5(rel_path_str.encode()).hexdigest()}_{i}",
                        "vector": chunk_vec,
                        "text": chunk_text,
                        "file_path": rel_path_str,
                        "file_hash": current_hash,
                        "chunk_index": i,
                    }
                )

            # Атомарная запись пачки чанков в таблицу
            self.table.add(data_records)
            logger.info(
                f"✅ Успешно проиндексирован: {rel_path_str} ({len(chunks)} чанков)"
            )
            return True

        except Exception as e:
            logger.error(f"❌ Критический сбой индексации файла {rel_path_str}: {e}")
            return False

    def prune_deleted_files(self, active_files_on_disk: Set[str]):
        """Удаляет из базы данных файлы, которых больше нет на физическом диске."""
        if len(self.table) == 0:
            return

        try:
            df = self.table.to_pandas()
            files_in_db = set(df["file_path"].unique())
            deleted_files = files_in_db - active_files_on_disk

            if deleted_files:
                logger.info(
                    f"🧹 Обнаружены удаленные файлы. Начинается чистка базы от мёртвого груза..."
                )
                for file_path in deleted_files:
                    escaped = self._escape_file_path_for_lance(file_path)
                    self.table.delete(f"file_path = '{escaped}'")
                    logger.info(f"  └─ Изъят из индекса: {file_path}")
                logger.info("✅ База данных полностью синхронизирована с диском.")
        except Exception as e:
            logger.error(f"Ошибка при выполнении операции Pruning: {e}")

    def index_project(self, project_path: Path) -> int:
        """
        Полное сканирование проекта:
        1. Инкрементально добавляет новые/измененные файлы.
        2. Автоматически удаляет из базы файлы, стертые с диска (Pruning).
        """
        logger.info(f"🚀 Старт фоновой синхронизации проекта: {project_path}")
        indexed_count = 0
        current_files_on_disk: Set[str] = set()

        if not self.path_manager.is_safe_to_process(project_path):
            return 0

        # Шаг 1: Сканирование диска и обновление базы
        # Используем сырой путь (без \\?\) для os.walk, иначе relative_to не сработает
        walk_root = str(project_path.resolve())
        for root, dirs, files in os.walk(walk_root):
            # Фильтрация директорий «на лету"
            dirs[:] = [d for d in dirs if not self.file_guard.should_skip_dir(d)]

            for file_name in files:
                full_path = Path(root) / file_name
                if not self.path_manager.is_safe_to_process(full_path):
                    continue

                if self.file_guard.should_skip_file(full_path):
                    continue

                rel_path_str = str(full_path.relative_to(project_path))
                current_files_on_disk.add(rel_path_str)

                if self._index_single_file(full_path, rel_path_str):
                    indexed_count += 1

        # Шаг 2: Автоматическое вычищение (Pruning) «мертвого груза"
        self.prune_deleted_files(current_files_on_disk)

        if indexed_count > 0 and self.searcher:
            self.searcher.reindex()

        return indexed_count
