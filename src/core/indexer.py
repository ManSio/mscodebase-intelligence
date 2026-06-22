"""
Инкрементальная индексация файлов с отслеживанием изменений через SHA256.
Атомарные операции, потокобезопасность, восстановление после сбоев.
"""

import hashlib
import logging
import os
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set

import chromadb

from src.core.parser import CodeParser
from src.core.symbol_index import SymbolIndex

logger = logging.getLogger(__name__)


class Indexer:
    """Индексирует файлы проекта в векторную БД с поддержкой инкрементальных обновлений."""

    def __init__(self, db_path: Path, embedder, file_guard, searcher=None):
        self.db_path = db_path
        self.embedder = embedder
        self.file_guard = file_guard  # Внедряем FileGuard
        self.searcher = searcher

        # Настройки из переменных окружения
        self.batch_size = int(os.getenv("BATCH_SIZE", "16"))
        self.chroma_batch_size = int(os.getenv("CHROMA_BATCH_SIZE", "100"))

        # Потокобезопасность
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._indexing_in_progress = False
        self._indexed_count = 0
        self._total_count = 0

        self.parser = CodeParser()
        self.symbol_index = SymbolIndex()

        # Очередь событий от Watchdog
        self._event_queue: List[tuple] = []
        self._event_queue_lock = threading.Lock()

        # Инициализируем хранилища
        self._init_chroma()
        self._init_sqlite()

    def _init_chroma(self):
        """Инициализирует ChromaDB с восстановлением при повреждении."""
        try:
            self.db_path.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(self.db_path))
            self.collection = self.client.get_or_create_collection(
                name="code_chunks", metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"✅ ChromaDB инициализирован: {self.db_path}")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации ChromaDB: {e}")

            if not any(part.startswith(".codebase") for part in self.db_path.parts):
                raise RuntimeError(f"Отказ удалять не-codebase папку: {self.db_path}")

            if (self.db_path / "chroma.sqlite3").exists():
                logger.warning("🔄 Пересоздаю повреждённый индекс...")
                try:
                    shutil.rmtree(self.db_path, ignore_errors=True)
                    self.db_path.mkdir(parents=True, exist_ok=True)
                    self.client = chromadb.PersistentClient(path=str(self.db_path))
                    self.collection = self.client.get_or_create_collection(
                        name="code_chunks", metadata={"hnsw:space": "cosine"}
                    )
                    logger.info("✅ Индекс пересоздан")
                except Exception as e2:
                    raise RuntimeError(f"Не удалось пересоздать индекс: {e2}")
            else:
                raise

    def _init_sqlite(self):
        """Инициализирует SQLite для метаданных с WAL-режимом."""
        self.sql_path = self.db_path / "metadata.db"
        self.conn = sqlite3.connect(
            str(self.sql_path),
            check_same_thread=False,
            timeout=30,
        )
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS file_hashes (
                file_path TEXT PRIMARY KEY,
                hash TEXT NOT NULL,
                chunk_ids TEXT,
                indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def close(self):
        """Безопасное завершение с ожиданием завершения индексации."""
        logger.info("🛑 Завершение работы Indexer...")
        self._stop_event.set()

        timeout = 10.0
        while self._indexing_in_progress and timeout > 0:
            import time

            time.sleep(0.1)
            timeout -= 0.1

        try:
            if hasattr(self, "conn") and self.conn:
                self.conn.close()
                logger.info("✅ SQLite соединение закрыто")
        except Exception as e:
            logger.warning(f"Ошибка закрытия SQLite: {e}")

    def _compute_hash(self, file_path: Path) -> str:
        """Вычисляет SHA256 хеш файла."""
        try:
            return hashlib.sha256(file_path.read_bytes()).hexdigest()
        except Exception as e:
            logger.debug(f"⚠️ Ошибка вычисления хеша {file_path}: {e}")
            return ""

    def _chunk_id(self, file_path: Path, idx: int) -> str:
        """Генерирует уникальный ID для чанка."""
        norm_path = str(file_path.absolute()).replace("\\", "/")
        return hashlib.sha256(f"{norm_path}::{idx}".encode()).hexdigest()

    def index_project(self, project_path: Path) -> int:
        """Индексирует весь проект. Возвращает количество проиндексированных файлов."""
        if self._stop_event.is_set():
            return 0

        with self._lock:
            self._indexing_in_progress = True
            try:
                current_files: Set[Path] = set()
                for f in project_path.rglob("*"):
                    if self._stop_event.is_set():
                        break
                    if f.is_file() and self.file_guard.is_safe_to_index(f):
                        current_files.add(f)

                self._cleanup_phantoms(current_files)

                count = 0
                logger.info(f"Начинаю индексацию {len(current_files)} файлов...")
                for f in current_files:
                    if self._stop_event.is_set():
                        break
                    try:
                        if self._index_file_unlocked(f):
                            count += 1
                            if count % 10 == 0:
                                logger.info(
                                    f"Проиндексировано {count}/{len(current_files)}..."
                                )
                    except Exception as e:
                        logger.error(f"Ошибка индексации {f}: {e}")
                logger.info(f"Индексация завершена: {count}/{len(current_files)}")

                if self.searcher:
                    try:
                        self.searcher.reindex()
                    except Exception:
                        pass

                self._process_queued_events()
                return count
            finally:
                self._indexing_in_progress = False

    def _cleanup_phantoms(self, current_files: Set[Path]):
        """Удаляет из индекса файлы, которых больше нет."""
        try:
            stored_paths = {
                row[0] for row in self.conn.execute("SELECT file_path FROM file_hashes")
            }
            current_paths = {str(f) for f in current_files}

            for fp in stored_paths - current_paths:
                self._delete_file_unlocked(Path(fp))

            self.conn.commit()
        except Exception as e:
            logger.error(f"Ошибка очистки фантомов: {e}")

    def _index_file_unlocked(self, file_path: Path) -> bool:
        """Индексирует один файл. Должен вызываться с захваченным self._lock."""
        if self._stop_event.is_set():
            return False

        cur_hash = self._compute_hash(file_path)
        if not cur_hash:
            return False

        row = self.conn.execute(
            "SELECT hash, chunk_ids FROM file_hashes WHERE file_path=?",
            (str(file_path),),
        ).fetchone()

        if row and row[0] == cur_hash:
            return False  # Файл не изменился

        try:
            parsed = self.parser.parse_file(file_path)
            if isinstance(parsed, tuple):
                chunks, _ = parsed
            else:
                chunks = parsed
        except Exception as e:
            logger.error(f"Ошибка парсинга {file_path}: {e}")
            return False

        if not chunks:
            self.conn.execute(
                "REPLACE INTO file_hashes (file_path, hash, chunk_ids) VALUES (?,?,?)",
                (str(file_path), cur_hash, ""),
            )
            self.conn.commit()
            return True

        # Удаляем старые чанки до начала записи новых
        if row and row[1]:
            old_ids = row[1].split(",")
            if old_ids and old_ids[0]:
                try:
                    self.collection.delete(ids=old_ids)
                except Exception as e:
                    logger.debug(
                        f"Старые чанки {file_path} уже удалены или недоступны: {e}"
                    )

        texts = [c["text"] for c in chunks]
        all_ids: List[str] = []

        # Батчинг как для эмбеддера, так и для ChromaDB
        try:
            for i in range(0, len(texts), self.batch_size):
                batch_texts = texts[i : i + self.batch_size]
                embeddings = self.embedder.embed_batch(batch_texts)

                # Защита: если эмбеддер недоступен и вернул пустые векторы —
                # пропускаем запись в ChromaDB, но сохраняем метаданные
                if not embeddings or not embeddings[0]:
                    logger.debug(
                        f"⏭️ Пропуск ChromaDB для {file_path} — нет эмбеддингов"
                    )
                    continue

                batch_ids = []
                batch_meta = []

                for j, (text, emb) in enumerate(zip(batch_texts, embeddings)):
                    chunk_idx = i + j
                    chunk = chunks[chunk_idx]
                    uid = self._chunk_id(file_path, chunk_idx)

                    batch_ids.append(uid)
                    all_ids.append(uid)
                    batch_meta.append(
                        {
                            "file": str(file_path),
                            "start_line": chunk.get("start_line", 0),
                            "end_line": chunk.get("end_line", 0),
                            "type": chunk.get("type", "unknown"),
                            "ext": file_path.suffix.lower(),
                            "context": chunk.get(
                                "context", ""
                            ),  # Сохраняем семантический контекст
                            "symbol_name": chunk.get("symbol_name", ""),
                        }
                    )

                # Upsert батчами по chroma_batch_size (чтобы не перегружать ChromaDB)
                for k in range(0, len(batch_ids), self.chroma_batch_size):
                    sub_ids = batch_ids[k : k + self.chroma_batch_size]
                    sub_texts = batch_texts[k : k + self.chroma_batch_size]
                    sub_embs = embeddings[k : k + self.chroma_batch_size]
                    sub_meta = batch_meta[k : k + self.chroma_batch_size]

                    self.collection.upsert(
                        ids=sub_ids,
                        documents=sub_texts,
                        embeddings=sub_embs,
                        metadatas=sub_meta,
                    )

        except Exception as e:
            logger.error(f"❌ Ошибка записи в ChromaDB для {file_path}: {e}")
            return False
        finally:
            self.conn.execute(
                "REPLACE INTO file_hashes (file_path, hash, chunk_ids) VALUES (?,?,?)",
                (str(file_path), cur_hash, ",".join(all_ids)),
            )
            self.conn.commit()

        if not all_ids:
            return True

        # Обновляем индекс символов
        symbol_defs = [
            {
                "name": chunk.get("symbol_name", ""),
                "line": chunk.get("start_line", 0),
                "kind": chunk.get("type", "unknown"),
            }
            for chunk in chunks
            if chunk.get("symbol_name")
        ]
        if symbol_defs and hasattr(self, "symbol_index"):
            self.symbol_index.add_definitions(str(file_path), symbol_defs)

        return True

    def index_file(self, file_path: Path) -> bool:
        """Public wrapper for indexing a single file."""
        with self._lock:
            return self._index_file_unlocked(file_path)

    def delete_file(self, file_path: Path):
        with self._lock:
            self._delete_file_unlocked(file_path)
            self.conn.commit()

    def _delete_file_unlocked(self, file_path: Path):
        try:
            row = self.conn.execute(
                "SELECT chunk_ids FROM file_hashes WHERE file_path=?", (str(file_path),)
            ).fetchone()

            if row and row[0]:
                chunk_ids = row[0].split(",")
                if chunk_ids and chunk_ids[0]:
                    try:
                        self.collection.delete(ids=chunk_ids)
                    except Exception:
                        pass

            self.conn.execute(
                "DELETE FROM file_hashes WHERE file_path=?", (str(file_path),)
            )
        except Exception as e:
            logger.error(f"Ошибка удаления {file_path}: {e}")

        self.symbol_index.remove_file(str(file_path))

    def move_file(self, src: Path, dst: Path):
        with self._lock:
            self._delete_file_unlocked(src)
            self.conn.commit()
            if dst.exists() and self.file_guard.is_safe_to_index(dst):
                self._index_file_unlocked(dst)

    def queue_event(self, event_type: str, path: str, dest_path: Optional[str] = None):
        with self._event_queue_lock:
            self._event_queue.append((event_type, path, dest_path))

    def _process_queued_events(self):
        with self._event_queue_lock:
            events = self._event_queue
            self._event_queue = []

        if not events:
            return

        with self._lock:
            for event_type, src, dst in events:
                try:
                    src_path = Path(src)
                    if event_type in ("modified", "created"):
                        if src_path.exists() and self.file_guard.is_safe_to_index(
                            src_path
                        ):
                            self._index_file_unlocked(src_path)
                    elif event_type == "deleted":
                        self._delete_file_unlocked(src_path)
                    elif event_type == "moved" and dst:
                        dst_path = Path(dst)
                        self._delete_file_unlocked(src_path)
                        if dst_path.exists() and self.file_guard.is_safe_to_index(
                            dst_path
                        ):
                            self._index_file_unlocked(dst_path)
                except Exception as e:
                    logger.error(f"Ошибка события {event_type} для {src}: {e}")
            self.conn.commit()

        if self.searcher:
            try:
                self.searcher.reindex()
            except Exception:
                pass

    def get_status(self) -> Dict:
        try:
            return {
                "total_chunks": self.collection.count(),
                "total_files": self.conn.execute(
                    "SELECT COUNT(*) FROM file_hashes"
                ).fetchone()[0],
                "db_path": str(self.db_path),
                "indexing_in_progress": self._indexing_in_progress,
                "total_symbols": self.symbol_index.stats().get("total_symbols", 0),
            }
        except Exception as e:
            return {"error": str(e)}
