"""
MSCodeBase Intelligence - Ядро индексации (Indexer)
Интегрировано с семантическим парсером Tree-sitter и защитой от OOM.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import chromadb

from src.core.parser import CodeParser

logger = logging.getLogger("mscodebase_server.indexer")


class Indexer:
    def __init__(self, db_path: Path, embedder, file_guard):
        """Инициализация клиента ChromaDB и связей."""
        self.db_path = db_path
        self.embedder = embedder
        self.file_guard = file_guard
        self.searcher = None
        self.parser = CodeParser()

        # Инициализируем локальный постоянный клиент ChromaDB
        self.chroma_client = chromadb.PersistentClient(path=str(db_path))
        self.collection = self.chroma_client.get_or_create_collection(
            name="codebase_chunks", metadata={"hnsw:space": "cosine"}
        )
        logger.info(f"📦 ChromaDB успешно подключена по пути: {db_path}")

    def get_status(self) -> Dict[str, Any]:
        """Возвращает актуальную статистику по базе данных индексов."""
        try:
            total_chunks = self.collection.count()
            existing_data = self.collection.get(include=["metadatas"])
            unique_files = set()
            if existing_data and existing_data.get("metadatas"):
                for meta in existing_data["metadatas"]:
                    if meta and "file_path" in meta:
                        unique_files.add(meta["file_path"])
            return {
                "total_chunks": total_chunks,
                "total_files": len(unique_files),
                "db_path": str(self.db_path),
            }
        except Exception as e:
            logger.error(f"Ошибка получения статистики БД: {e}")
            return {"total_chunks": 0, "total_files": 0, "error": str(e)}

    def clear_index(self) -> bool:
        """Полностью очищает текущую коллекцию."""
        try:
            self.chroma_client.delete_collection(name="codebase_chunks")
            self.collection = self.chroma_client.get_or_create_collection(
                name="codebase_chunks", metadata={"hnsw:space": "cosine"}
            )
            if self.searcher:
                self.searcher.reindex()
            logger.info("🗑️ Индекс успешно очищен")
            return True
        except Exception as e:
            logger.error(f"Ошибка при очистке индекса: {e}")
            return False

    def delete_file_from_index(self, file_path: Path) -> None:
        """Удаляет все чанки, принадлежащие конкретному файлу."""
        try:
            file_str = str(file_path)
            self.collection.delete(where={"file_path": file_str})
            logger.debug(f"Удален старый индекс файла из базы: {file_path.name}")
        except Exception as e:
            logger.error(f"Ошибка удаления файла {file_path} из индекса: {e}")

    def index_project(self, project_path: Path) -> int:
        """
        Сканирует проект и выполняет полную или инкрементальную индексацию.
        Использует семантический парсинг Tree-sitter. Изолирует сбои отдельных файлов.
        """
        indexed_files_count = 0
        root_path = Path(project_path).resolve()

        logger.info(f"🚀 Запуск индексации проекта: {root_path}")

        for root, _, files in os.walk(root_path):
            # Жестко отсекаем системные папки на уровне обхода директорий
            if any(part in self.file_guard.SKIP_DIRS for part in Path(root).parts):
                continue

            for file_name in files:
                file_path = Path(root) / file_name

                # 1. Защита Guardrails (проверка расширения, бинарников, минификации)
                if not self.file_guard.is_supported(file_path):
                    continue

                # 2. Защита от OOM (пропускаем файлы крупнее 1.5 МБ)
                try:
                    if os.path.getsize(file_path) > 1500000:
                        logger.warning(
                            f"⏩ Файл пропущен (слишком большой): {file_path.name}"
                        )
                        continue
                except Exception:
                    continue

                # Изолируем обработку каждого конкретного файла (Bulkhead Pattern)
                try:
                    # Удаляем старый индекс файла перед перезаписью (инкрементальность)
                    self.delete_file_from_index(file_path)

                    # Читаем содержимое файла в безопасном бинарном режиме с заменой битых символов
                    with open(file_path, "rb") as f:
                        raw_content = f.read()
                    content = raw_content.decode("utf-8", errors="replace")

                    if not content.strip():
                        continue

                    # 3. Семантическое разбиение на чанки через Tree-sitter
                    parsed_chunks, _ = self.parser.parse_file(file_path)

                    chunks_text = []
                    metadatas = []
                    ids = []

                    if parsed_chunks:
                        # Успешно распарсено через Tree-sitter
                        for i, chunk in enumerate(parsed_chunks):
                            chunks_text.append(chunk["text"])
                            metadatas.append(
                                {
                                    "file_path": str(file_path),
                                    "chunk_index": i,
                                    "start_line": chunk.get("start_line", 0),
                                    "end_line": chunk.get("end_line", 0),
                                    "type": chunk.get("type", "code_block"),
                                    "symbol_name": chunk.get("symbol_name", ""),
                                }
                            )
                            ids.append(f"{hash(str(file_path))}_chunk_{i}")
                    else:
                        # Fallback: нарезаем стандартными текстовыми кусками
                        lines = content.splitlines()
                        step = 80
                        window = 100
                        for i in range(0, len(lines), step):
                            chunk_lines = lines[i : i + window]
                            if not chunk_lines:
                                break
                            text_block = "\n".join(chunk_lines)
                            chunks_text.append(text_block)
                            metadatas.append(
                                {
                                    "file_path": str(file_path),
                                    "chunk_index": len(chunks_text) - 1,
                                    "start_line": i,
                                    "end_line": i + len(chunk_lines),
                                    "type": "fallback_block",
                                    "symbol_name": "",
                                }
                            )
                            ids.append(
                                f"{hash(str(file_path))}_chunk_{len(chunks_text) - 1}"
                            )

                    if not chunks_text:
                        continue

                    # 4. Векторизация батчем через внешний RemoteEmbedder (LM Studio)
                    embeddings = self.embedder.embed_batch(chunks_text)

                    # Защита от пустых ответов эмбеддера (если сервер эмбеддингов лег)
                    if not embeddings or not embeddings[0]:
                        logger.warning(
                            f"⚠️ Пропущен апсерт {file_path.name}: Эмбеддер вернул пустые вектора."
                        )
                        continue

                    # 5. Атомарная запись пакета чанков файла в ChromaDB
                    self.collection.upsert(
                        ids=ids,
                        embeddings=embeddings,
                        documents=chunks_text,
                        metadatas=metadatas,
                    )

                    indexed_files_count += 1
                    logger.info(
                        f"✅ Проиндексирован файл: {file_path.name} ({len(chunks_text)} семантических чанков)"
                    )

                except Exception as file_error:
                    logger.error(
                        f"❌ Произошел сбой при обработке файла {file_path}: {file_error}",
                        exc_info=True,
                    )
                    continue

        # Сбрасываем поисковый кэш BM25, чтобы он перестроился под новые файлы
        if indexed_files_count > 0 and self.searcher:
            self.searcher.reindex()

        logger.info(
            f"📋 Индексация завершена. Успешно обработано файлов: {indexed_files_count}"
        )
        return indexed_files_count
