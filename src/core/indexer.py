"""
MSCodebase Intelligence — Продакшен инкрементальный индекс на LanceDB с авто-очисткой (Pruning)
"""

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
        if self.table_name in self.db.list_tables():
            self.table = self.db.open_table(self.table_name)
        else:
            self.table = self.db.create_table(self.table_name, schema=self.schema)

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
        for root, dirs, files in os.walk(to_win_long_path(project_path)):
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

    def _index_single_file(self, full_path: Path, rel_path_str: str) -> bool:
        """Индицирует один файл, если его хэш изменился."""
        try:
            safe_read_path = self.path_manager.get_safe_path(full_path)
            current_hash = self._calculate_file_hash(safe_read_path)

            # Проверяем, есть ли уже этот файл с таким же хэшем в LanceDB
            if len(self.table) > 0:
                existing = (
                    self.table.search()
                    .where(f"file_path = '{rel_path_str}'", prefilter=True)
                    .to_pandas()
                )
                if not existing.empty and existing["file_hash"].iloc[0] == current_hash:
                    return False  # Файл не изменялся, пропускаем

                # Если файл изменился — сначала удаляем его старые чанки
                self.table.delete(f"file_path = '{rel_path_str}'")

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
                    self.table.delete(f"file_path = '{file_path}'")
                    logger.info(f"  └─ Изъят из индекса: {file_path}")
                logger.info("✅ База данных полностью синхронизирована с диском.")
        except Exception as e:
            logger.error(f"Ошибка при выполнении операции Pruning: {e}")
