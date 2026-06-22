"""
MSCodeBase Intelligence - Ядро индексации (Indexer)
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import chromadb

logger = logging.getLogger("mscodebase_server.indexer")


class Indexer:
    def __init__(self, db_path: Path, embedder, file_guard):
        """Инициализация клиента ChromaDB и связей."""
        self.db_path = db_path
        self.embedder = embedder
        self.file_guard = file_guard
        self.searcher = None

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
                "total_files": len(unique_files),
                "total_chunks": total_chunks,
                "db_path": str(self.db_path),
            }
        except Exception as e:
            logger.error(f"Ошибка при подсчете статуса ChromaDB: {e}")
            return {"total_files": 0, "total_chunks": 0, "db_path": str(self.db_path)}

    def index_project(self, project_path: Path) -> int:
        """Сканирует директорию, бьет код на чанки и заливает вектора в ChromaDB."""
        logger.info(f"🔍 Начинается сканирование проекта: {project_path}")
        indexed_files_count = 0

        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if not d.startswith((".", "venv"))]

            for file in files:
                file_path = Path(root) / file
                if getattr(self.file_guard, "should_index", lambda x: True)(file_path):
                    # Если у file_guard нет метода should_index, используем file_guard как есть
                    if hasattr(self.file_guard, "should_index"):
                        if not self.file_guard.should_index(file_path):
                            continue
                    elif hasattr(self.file_guard, "is_safe_to_index"):
                        if not self.file_guard.is_safe_to_index(file_path):
                            continue

                    try:
                        with open(
                            file_path, "r", encoding="utf-8", errors="ignore"
                        ) as f:
                            content = f.read()

                        # Простая логика чанкирования (по 1000 символов с перекрытием)
                        chunks = [
                            content[i : i + 1000] for i in range(0, len(content), 800)
                        ]
                        if not chunks:
                            continue

                        # Получаем вектора через наш RemoteEmbedder
                        embeddings = self.embedder.embed_batch(chunks)

                        ids = [
                            f"{file_path.name}_chunk_{i}" for i in range(len(chunks))
                        ]
                        metadatas = [
                            {"file_path": str(file_path), "chunk_index": i}
                            for i in range(len(chunks))
                        ]

                        # Сохраняем в ChromaDB
                        self.collection.upsert(
                            ids=ids,
                            embeddings=embeddings,
                            documents=chunks,
                            metadatas=metadatas,
                        )
                        indexed_files_count += 1
                        logger.info(
                            f"✅ Проиндексирован файл: {file_path.name} ({len(chunks)} чанков)"
                        )
                    except Exception as e:
                        logger.error(f"❌ Ошибка индексации файла {file_path}: {e}")

        return indexed_files_count
