"""
MSCodeBase Intelligence - Ядро индексации (Indexer)
Размещается в src/core/indexer.py
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb

from src.core.parser import CodeParser
from src.core.symbol_index import SymbolIndex

logger = logging.getLogger("mscodebase_server.indexer")


class Indexer:
    def __init__(self, db_path: Path, embedder, file_guard):
        """Инициализация клиента ChromaDB со сквозной привязкой парсера."""
        self.db_path = db_path
        self.embedder = embedder
        self.file_guard = file_guard
        self.searcher = None

        # Интегрируем наши компоненты
        self.parser = CodeParser()
        self.symbol_index = SymbolIndex()

        # Инициализируем локальный постоянный клиент ChromaDB
        self._init_chroma(db_path)
        logger.info(f"📦 Ядро индексации запущено. База данных: {db_path}")

    def _init_chroma(self, path: Path):
        """Безопасная инициализация ChromaDB клиента."""
        path.mkdir(parents=True, exist_ok=True)
        self.chroma_client = chromadb.PersistentClient(
            path=str(path),
            settings=chromadb.config.Settings(
                is_persistent=True, anonymized_telemetry=False
            ),
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name="codebase_chunks", metadata={"hnsw:space": "cosine"}
        )

    def update_db_path(self, new_db_path: Path):
        """Динамически и атомарно переключает ChromaDB на изолированную папку другого проекта."""
        if self.db_path.resolve() == new_db_path.resolve():
            return

        try:
            logger.info(
                f"🔄 Переключение контекста базы: {self.db_path.name} -> {new_db_path.name}"
            )
            self.db_path = new_db_path
            self._init_chroma(new_db_path)

            # Сбрасываем оперативную память индекса символов под новый проект
            self.symbol_index = SymbolIndex()

            # Обязательно уведомляем поисковой движок, чтобы он сбросил кэш BM25
            if self.searcher:
                self.searcher.reindex()
            logger.info(
                f"✅ База данных успешно изолирована под новый проект: {new_db_path}"
            )
        except Exception as e:
            logger.error(f"❌ Критическая ошибка при динамическом переключении БД: {e}")
            raise RuntimeError(f"Не удалось переключить контекст базы данных: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Возвращает актуальную и точную статистику по текущей кодовой базе."""
        try:
            total_chunks = self.collection.count()
            existing_data = self.collection.get(include=["metadatas"])
            unique_files = set()

            if existing_data and existing_data.get("metadatas"):
                for meta in existing_data["metadatas"]:
                    if meta and "file" in meta:
                        unique_files.add(meta["file"])

            return {
                "total_files": len(unique_files),
                "total_chunks": total_chunks,
                "db_path": str(self.db_path),
                "symbols_count": self.symbol_index.stats().get("total_symbols", 0),
            }
        except Exception as e:
            logger.error(f"Ошибка сбора статистики ChromaDB: {e}")
            return {
                "total_files": 0,
                "total_chunks": 0,
                "db_path": str(self.db_path),
                "error": str(e),
            }

    def index_project(self, project_path: Path) -> int:
        """Полное сканирование проекта с использованием Tree-sitter парсера."""
        indexed_files_count = 0
        project_root = Path(project_path).resolve()

        logger.info(f"🚀 Запуск глубокого сканирования директории: {project_root}")

        # Собираем файлы, проходя сквозь Guardrails
        target_files: List[Path] = []
        for root, dirs, files in os.walk(project_root):
            # Фильтруем папки «на лету»
            dirs[:] = [
                d
                for d in dirs
                if d not in self.file_guard.SKIP_DIRS and not d.startswith(".")
            ]

            for file in files:
                file_path = Path(root) / file

                # Проверка расширения и защиты от бинарников/минификации
                if file_path.suffix.lower() in self.file_guard.SUPPORTED_EXTENSIONS:
                    if not self.file_guard.is_binary_or_minified(file_path):
                        target_files.append(file_path)

        if not target_files:
            logger.warning("🔍 Полезные исходные файлы для индексации не найдены.")
            return 0

        for file_path in target_files:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                if not content.strip():
                    continue

                # Относительный путь для красивого отображения в UI и ключей в БД
                rel_path = str(file_path.relative_to(project_root))

                # 🌟 ИСПОЛЬЗУЕМ УМНЫЙ ЧАНКЕР TREE-SITTER ВМЕСТО ТУПОГО РЕЗАКА СИМВОЛОВ
                from pathlib import PurePath

                chunks_meta, symbols = self.parser.parse_file(file_path)
                if isinstance(chunks_meta, tuple):
                    chunks_meta = chunks_meta[0]

                # Регистрируем символы в глобальном индексе проекта
                for sym in symbols:
                    # Переводим в относительный путь для изоляции
                    if hasattr(sym, "file_path"):
                        sym.file_path = rel_path
                    self.symbol_index.add_definition(
                        sym.get("name", "unknown")
                        if isinstance(sym, dict)
                        else str(sym),
                        sym,
                    )

                if not chunks_meta:
                    continue

                # Очищаем старые записи этого файла из ChromaDB (чтобы не дублировать при переиндексации)
                file_hash = hashlib.md5(rel_path.encode("utf-8")).hexdigest()[:8]
                try:
                    self.collection.delete(where={"file": rel_path})
                except Exception:
                    pass  # Если файла еще не было в базе

                # Вытаскиваем тексты для пакетной векторизации
                texts_to_embed = [c["text"] for c in chunks_meta]
                embeddings = self.embedder.embed_batch(texts_to_embed)

                # Если эмбеддер лежит или вернул пустые списки — защищаем ChromaDB от падения
                if not embeddings or any(len(e) == 0 for e in embeddings):
                    logger.warning(
                        f"⚠️ Пропущен файл {rel_path}: Эмбеддер вернул пустые векторы."
                    )
                    continue

                ids = [f"chk_{file_hash}_{i}" for i in range(len(chunks_meta))]
                metadatas = []
                documents = []

                for i, c in enumerate(chunks_meta):
                    documents.append(c["text"])
                    metadatas.append(
                        {
                            "file": rel_path,
                            "start_line": c["start_line"],
                            "end_line": c["end_line"],
                            "type": c["type"],
                            "symbol_name": c.get("symbol_name", ""),
                        }
                    )

                # Атомарный апсерт пакета чанков в ChromaDB
                self.collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas,
                )
                indexed_files_count += 1
                logger.info(
                    f"✅ Успешно проиндексирован: {rel_path} [{len(chunks_meta)} чанков, {len(symbols)} символов]"
                )

            except Exception as e:
                logger.error(
                    f"❌ Сбой при обработке файла {file_path}: {e}", exc_info=True
                )

        return indexed_files_count
