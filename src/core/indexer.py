"""
MSCodeBase Intelligence — Модуль индексации на базе LanceDB и Tree-sitter графа.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import lancedb
import pyarrow as pa

from src.core.parser import CodeParser
from src.utils.paths import to_win_long_path

logger = logging.getLogger("mscodebase_server.indexer")


class Indexer:
    def __init__(self, db_path: Path, embedder, file_guard):
        """Инициализация LanceDB движка на Rust."""
        self.db_path = db_path
        self.embedder = embedder
        self.file_guard = file_guard
        self.searcher = None
        self.parser = CodeParser()

        # Создаем папку индексов
        self.db_path.mkdir(parents=True, exist_ok=True)

        # Подключаем LanceDB (работает embedded внутри процесса Python)
        self.db = lancedb.connect(str(self.db_path))

        # Описание схемы таблицы Apache Arrow для хранения векторов и графа связей
        self.schema = pa.schema(
            [
                pa.field(
                    "vector", pa.list_(pa.float32(), list_size=1024)
                ),  # Под BGE-M3 (1024) или вашу модель
                pa.field("id", pa.string()),
                pa.field("document", pa.string()),
                pa.field("file_path", pa.string()),
                pa.field("chunk_index", pa.int32()),
                pa.field("start_line", pa.int32()),
                pa.field("end_line", pa.int32()),
                pa.field("type", pa.string()),  # 'class', 'function', 'method'
                pa.field("symbol_name", pa.string()),  # Имя сущности для графа связей
                pa.field(
                    "parent_symbol", pa.string()
                ),  # Родительский контекст (какому классу принадлежит метод)
            ]
        )

        self.table_name = "codebase_chunks"
        if self.table_name in self.db.table_names():
            self.table = self.db.open_table(self.table_name)
        else:
            self.table = self.db.create_table(self.table_name, schema=self.schema)

        logger.info(
            f"⚡ Успешно подключена база данных LanceDB (Rust Engine) по пути: {db_path}"
        )

    def get_status(self) -> Dict[str, Any]:
        """Возвращает статистику базы LanceDB."""
        try:
            total_chunks = len(self.table)
            df = self.table.to_pandas()
            unique_files = df["file_path"].nunique() if total_chunks > 0 else 0
            return {
                "total_chunks": total_chunks,
                "total_files": unique_files,
                "db_path": str(self.db_path),
                "engine": "LanceDB (Apache Arrow)",
            }
        except Exception as e:
            logger.error(f"Ошибка чтения статистики LanceDB: {e}")
            return {"total_chunks": 0, "total_files": 0, "error": str(e)}

    def clear_index(self) -> bool:
        """Очищает таблицу."""
        try:
            self.db.drop_table(self.table_name, ignore_missing=True)
            self.table = self.db.create_table(self.table_name, schema=self.schema)
            if self.searcher:
                self.searcher.reindex()
            logger.info("🗑️ Таблица индексов LanceDB успешно очищена.")
            return True
        except Exception as e:
            logger.error(f"Ошибка очистки LanceDB: {e}")
            return False

    def delete_file_from_index(self, file_path: Path) -> None:
        """Атомарно удаляет чанки файла из LanceDB."""
        try:
            file_str = str(file_path).replace("'", "''")
            # LanceDB поддерживает быстрое удаление через SQL-like предикаты
            self.table.delete(f"file_path = '{file_str}'")
            logger.debug(f"Удален индекс файла: {file_path.name}")
        except Exception as e:
            logger.error(f"Ошибка удаления файла {file_path} из LanceDB: {e}")

    def index_project(self, project_path: Path) -> int:
        """
        Сканирует проект, извлекает семантический граф через Tree-sitter
        и записывает векторы в LanceDB пакетным методом.
        """
        indexed_files_count = 0
        root_path = Path(project_path).resolve()

        logger.info(f"🚀 Запуск сканирования и построения графа проекта: {root_path}")

        data_to_insert = []

        for root, _, files in os.walk(root_path):
            if any(part in self.file_guard.SKIP_DIRS for part in Path(root).parts):
                continue

            for file_name in files:
                file_path = Path(root) / file_name

                if not self.file_guard.is_supported(file_path):
                    continue

                # Защита от OOM
                try:
                    if os.path.getsize(file_path) > 1500000:
                        continue
                except Exception:
                    continue

                try:
                    self.delete_file_from_index(file_path)

                    # Защита слоя ввода-вывода: бинарное чтение с безопасной заменой битых байт
                    win_long_p = to_win_long_path(str(file_path))
                    with open(win_long_p, "rb") as f:
                        raw_data = f.read()
                    content = raw_data.decode("utf-8", errors="replace")

                    if not content.strip():
                        continue

                    # Семантический разбор файла через Tree-sitter
                    parsed_chunks, _ = self.parser.parse_file(file_path)

                    chunks_text = []
                    metadata_list = []

                    if parsed_chunks:
                        # Обработка структуры графа вызовов и определений
                        for i, chunk in enumerate(parsed_chunks):
                            chunks_text.append(chunk["text"])

                            # Определяем "родителя" для методов (например, класс)
                            parent = ""
                            if chunk.get("type") in [
                                "method_definition",
                                "method_declaration",
                            ]:
                                for potential_parent in parsed_chunks:
                                    if potential_parent.get("type") in [
                                        "class_definition",
                                        "struct_item",
                                    ]:
                                        if (
                                            potential_parent.get("start_line")
                                            <= chunk.get("start_line", 0)
                                            <= potential_parent.get("end_line")
                                        ):
                                            parent = potential_parent.get(
                                                "symbol_name", ""
                                            )
                                            break

                            metadata_list.append(
                                {
                                    "id": f"{hash(str(file_path))}_chunk_{i}",
                                    "document": chunk["text"],
                                    "file_path": str(file_path),
                                    "chunk_index": i,
                                    "start_line": int(chunk.get("start_line", 0)),
                                    "end_line": int(chunk.get("end_line", 0)),
                                    "type": str(chunk.get("type", "code_block")),
                                    "symbol_name": str(chunk.get("symbol_name", "")),
                                    "parent_symbol": parent,
                                }
                            )
                    else:
                        # Текстовый Fallback чанкер, если язык не поддерживается Tree-sitter
                        lines = content.splitlines()
                        step, window = 80, 100
                        for i in range(0, len(lines), step):
                            chunk_lines = lines[i : i + window]
                            if not chunk_lines:
                                break
                            text_block = "\n".join(chunk_lines)
                            chunks_text.append(text_block)
                            metadata_list.append(
                                {
                                    "id": f"{hash(str(file_path))}_chunk_{len(chunks_text) - 1}",
                                    "document": text_block,
                                    "file_path": str(file_path),
                                    "chunk_index": len(chunks_text) - 1,
                                    "start_line": i,
                                    "end_line": i + len(chunk_lines),
                                    "type": "fallback_block",
                                    "symbol_name": "",
                                    "parent_symbol": "",
                                }
                            )

                    if not chunks_text:
                        continue

                    # Вычисление эмбеддингов
                    embeddings = self.embedder.embed_batch(chunks_text)
                    if not embeddings or not embeddings[0]:
                        continue

                    # Собираем данные в формате схемы для LanceDB
                    for idx, emb in enumerate(embeddings):
                        meta = metadata_list[idx]
                        data_to_insert.append(
                            {
                                "vector": emb,
                                "id": meta["id"],
                                "document": meta["document"],
                                "file_path": meta["file_path"],
                                "chunk_index": meta["chunk_index"],
                                "start_line": meta["start_line"],
                                "end_line": meta["end_line"],
                                "type": meta["type"],
                                "symbol_name": meta["symbol_name"],
                                "parent_symbol": meta["parent_symbol"],
                            }
                        )

                    indexed_files_count += 1

                except Exception as file_error:
                    logger.error(f"Сбой обработки файла {file_path}: {file_error}")
                    continue

        # Пакетная атомарная запись всей сессии в LanceDB
        if data_to_insert:
            self.table.add(data_to_insert)

        if indexed_files_count > 0 and self.searcher:
            self.searcher.reindex()

        logger.info(
            f"📊 Индексация в LanceDB завершена. Проиндексировано файлов: {indexed_files_count}"
        )
        return indexed_files_count
