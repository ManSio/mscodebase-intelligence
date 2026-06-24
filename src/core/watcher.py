import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional, Set

logger = logging.getLogger(__name__)


class IndexerHandler:
    """Обработчик событий watchdog. Имплементирует интерфейс FileSystemEventHandler."""

    CODE_EXTENSIONS = {".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".go", ".md"}

    def __init__(self, indexer):
        self.indexer = indexer

    @classmethod
    def _is_code_file(cls, path: Path) -> bool:
        return path.suffix.lower() in cls.CODE_EXTENSIONS

    def _trigger_reindex(self):
        """Безопасный вызов сброса кэша поиска."""
        if self.indexer.searcher:
            self.indexer.searcher.reindex()

    def on_modified(self, event):
        if self.indexer._stop_event.is_set() or event.is_directory:
            return

        path = Path(event.src_path)
        if not self._is_code_file(path):
            return

        logger.info(f"⚡ Изменён: {path.name}")
        if self.indexer._indexing_in_progress:
            self.indexer.queue_event("modified", str(path))
        else:
            try:
                # Используем инкрементальную индексацию через index_project
                # для минимальной нагрузки при изменении одного файла
                self._handle_single_file_change(path)
            except Exception as e:
                logger.error(f"Ошибка обработки изменения {path}: {e}")

    def on_created(self, event):
        if self.indexer._stop_event.is_set() or event.is_directory:
            return

        path = Path(event.src_path)
        if not self._is_code_file(path):
            return

        logger.info(f"➕ Создан: {path.name}")
        if self.indexer._indexing_in_progress:
            self.indexer.queue_event("created", str(path))
        else:
            try:
                self._handle_single_file_change(path)
            except Exception as e:
                logger.error(f"Ошибка обработки создания {path}: {e}")

    def on_deleted(self, event):
        if self.indexer._stop_event.is_set() or event.is_directory:
            return

        path = Path(event.src_path)
        if not self._is_code_file(path):
            return

        logger.info(f"🗑️ Удалён: {path.name}")
        try:
            # Удаляем файл из базы данных
            self.indexer.prune_deleted_files({str(path)})
            self._trigger_reindex()
        except Exception as e:
            logger.error(f"Ошибка обработки удаления {path}: {e}")

    def on_moved(self, event):
        if self.indexer._stop_event.is_set() or event.is_directory:
            return

        src = Path(event.src_path)
        dst = Path(event.dest_path)

        is_src_code = self._is_code_file(src)
        is_dst_code = self._is_code_file(dst)

        # Если оба не код (например, переименовали .tmp в .tmp2)
        if not is_src_code and not is_dst_code:
            return

        logger.info(f"🔀 Перемещён/Переименован: {src.name} → {dst.name}")

        try:
            # Сценарий атомарного сохранения IDE (переименование из .tmp в .py)
            if not is_src_code and is_dst_code:
                self._handle_single_file_change(dst)

            # Сценарий перемещения/переименования валидного кода
            elif is_src_code and is_dst_code:
                # Удаляем старый путь, добавляем новый
                self.indexer.prune_deleted_files({str(src)})
                self._handle_single_file_change(dst)
                self._trigger_reindex()

            # Сценарий "удаления" (переименование из .py в .tmp или .bak)
            elif is_src_code and not is_dst_code:
                self.indexer.prune_deleted_files({str(src)})
                self._trigger_reindex()

        except Exception as e:
            logger.error(f"Ошибка обработки перемещения: {e}")

    def _handle_single_file_change(self, file_path: Path):
        """Обрабатывает изменение одного файла с минимальной нагрузкой.

        Вместо переиндексации всего проекта, мы:
        1. Проверяем, безопасен ли файл для обработки
        2. Вычисляем хэш файла
        3. Проверяем, изменился ли файл в базе данных
        4. Если изменился - переиндексируем только этот файл
        """
        # Проверяем, безопасен ли путь для обработки
        if not self.indexer.path_manager.is_safe_to_process(file_path):
            return

        # Проверяем, не должен ли файл быть пропущен
        if self.indexer.file_guard.should_skip_file(file_path):
            return

        # Вычисляем относительный путь к проекту
        try:
            rel_path_str = str(file_path.relative_to(self.indexer.project_path))
        except ValueError:
            # Файл не является частью проекта
            return

        # Проверяем, изменился ли файл (по хэшу)
        current_hash = self.indexer._calculate_file_hash(file_path)

        # Проверяем, есть ли файл в базе данных
        existing_hash = self._get_existing_file_hash(rel_path_str)

        if existing_hash == current_hash:
            # Файл не изменился, пропускаем
            return

        # Файл изменился или новый - переиндексируем его
        self._index_single_file(file_path, rel_path_str)

    def _get_existing_file_hash(self, rel_path_str: str) -> Optional[str]:
        """Получает хэш существующего файла из базы данных."""
        try:
            df = self.indexer.table.to_pandas()
            if df.empty:
                return None

            match = df[df["file_path"] == rel_path_str]
            if not match.empty:
                return match["file_hash"].iloc[0]
        except Exception:
            pass
        return None

    def _index_single_file(self, file_path: Path, rel_path_str: str) -> bool:
        """Индексирует один файл, если его хэш изменился."""
        try:
            # Читаем и обрабатываем файл
            safe_read_path = self.indexer.path_manager.get_safe_path(file_path)
            current_hash = self.indexer._calculate_file_hash(safe_read_path)

            # Экранируем путь для SQL-like where-выражений LanceDB
            escaped_path = self.indexer._escape_file_path_for_lance(rel_path_str)

            # Проверяем, есть ли уже этот файл с таким же хэшем в LanceDB
            existing_hash = self._get_existing_file_hash(rel_path_str)

            if existing_hash == current_hash:
                return False  # Файл не изменился, пропускаем

            # Если файл изменился или новый — удаляем его старые чанки
            if existing_hash is not None:
                try:
                    self.indexer.table.delete(f"file_path = '{escaped_path}'")
                except Exception as del_err:
                    logger.debug(f"delete() не нашёл запись: {del_err}")

            # Читаем содержимое файла
            with open(str(safe_read_path), "rb") as f:
                raw_data = f.read()
            content = raw_data.decode("utf-8", errors="replace")

            if not content.strip():
                return False

            # Чанкирование (по 1000 символов с перекрытием 200)
            chunks = [content[i : i + 1000] for i in range(0, len(content), 800)]
            if not chunks:
                return False

            # Получение эмбеддингов через провайдер
            embeddings = self.indexer.embedder.embed_batch(chunks)
            if not embeddings or any(len(e) == 0 for e in embeddings):
                logger.warning(
                    f"⚠️ Пустые эмбеддинги для файла {rel_path_str}. Пропуск записи."
                )
                return False

            # Подготовка данных для PyArrow
            data_records = []
            for i, (chunk_text, chunk_vec) in enumerate(zip(chunks, embeddings)):
                # Нормализация вектора под размерность схемы
                if len(chunk_vec) != 1024:
                    chunk_vec = chunk_vec[:1024] + [0.0] * (1024 - len(chunk_vec))

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
            self.indexer.table.add(data_records)
            logger.info(
                f"✅ Успешно проиндексирован: {rel_path_str} ({len(chunks)} чанков)"
            )
            return True

        except Exception as e:
            logger.error(f"❌ Критический сбой индексации файла {rel_path_str}: {e}")
            return False


class PollingWatcher:
    """Fallback watcher через polling с поддержкой отслеживания удалений."""

    def __init__(self, project_path: Path, indexer, poll_interval: int = 10):
        self.project_path = project_path
        self.indexer = indexer
        self.poll_interval = poll_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Храним состояние, чтобы находить удаленные файлы
        self._known_files: Set[Path] = set()

    def start(self):
        if self._running:
            return
        self._running = True

        # Заполняем начальное состояние
        self._known_files = self._get_current_files()

        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info(f"✅ Polling watcher запущен (интервал: {self.poll_interval}с)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("✅ Polling watcher остановлен")

    def _get_current_files(self) -> Set[Path]:
        """Эффективный обход директорий без захода в игнорируемые папки."""
        current_files = set()

        # Список папок, в которые категорически не нужно заходить (для ускорения I/O)
        ignore_dirs = {
            ".git",
            "node_modules",
            "venv",
            ".venv",
            "__pycache__",
            "target",
            "dist",
            "build",
        }

        for root, dirs, files in os.walk(self.project_path):
            # Модифицируем список dirs in-place, чтобы os.walk не заходил в них
            dirs[:] = [
                d for d in dirs if d not in ignore_dirs and not d.startswith(".")
            ]

            root_path = Path(root)
            for file in files:
                file_path = root_path / file

                if IndexerHandler._is_code_file(
                    file_path
                ) and self.indexer.file_guard.is_safe_to_index(file_path):
                    current_files.add(file_path)

        return current_files

    def _poll_loop(self):
        while self._running and not self.indexer._stop_event.is_set():
            try:
                self._check_changes()
            except Exception as e:
                logger.error(f"Ошибка polling: {e}")

            for _ in range(self.poll_interval * 10):
                if not self._running or self.indexer._stop_event.is_set():
                    return
                time.sleep(0.1)

    def _check_changes(self):
        """Сравнивает текущую файловую систему с известным состоянием."""
        current_files = self._get_current_files()

        if not self._running or self.indexer._stop_event.is_set():
            return

        # Находим удаленные файлы (есть в known, но нет в current)
        deleted_files = self._known_files - current_files
        for file_path in deleted_files:
            try:
                logger.info(f"🗑️ Polling заметил удаление: {file_path.name}")
                self.indexer.delete_file(file_path)
            except Exception as e:
                logger.error(f"Ошибка удаления (polling) {file_path}: {e}")

        # Индексируем новые и измененные (проверка хеша внутри index_file)
        for file_path in current_files:
            try:
                self.indexer.index_file(file_path)
            except Exception as e:
                logger.error(f"Ошибка индексации (polling) {file_path}: {e}")

        # Обновляем состояние
        self._known_files = current_files


class FileWatcher:
    """Основной класс watcher. Использует watchdog, fallback на polling."""

    def __init__(self, project_path: Path, indexer):
        self.project_path = project_path
        self.indexer = indexer
        self.observer = None
        self.polling_watcher: Optional[PollingWatcher] = None
        self._use_watchdog = True
        self.poll_interval = int(os.getenv("POLL_INTERVAL", "10"))

    def start(self):
        if self._use_watchdog:
            try:
                from watchdog.events import FileSystemEventHandler
                from watchdog.observers import Observer

                class Handler(IndexerHandler, FileSystemEventHandler):
                    pass

                self.observer = Observer()
                handler = Handler(self.indexer)
                self.observer.schedule(handler, str(self.project_path), recursive=True)
                self.observer.start()
                logger.info(f"✅ Watchdog запущен для: {self.project_path}")
                return
            except Exception as e:
                logger.warning(f"⚠️ Watchdog недоступен: {e}. Переключаюсь на polling.")
                self._use_watchdog = False

        self.polling_watcher = PollingWatcher(
            self.project_path, self.indexer, self.poll_interval
        )
        self.polling_watcher.start()

    def stop(self):
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=5)
                self.observer = None
                logger.info("✅ Watchdog остановлен")
            except Exception as e:
                logger.warning(f"Ошибка остановки watchdog: {e}")

        if self.polling_watcher:
            self.polling_watcher.stop()
            self.polling_watcher = None
