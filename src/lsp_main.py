"""
MSCodeBase LSP Server - проактивный индексатор через Language Server Protocol.

Интегрируется в Zed как language server и получает события файлов напрямую
от Rust-ядра редактора. Никакого polling, watchdog или ручного трекинга.

Два источника событий:
1. didSave - пользователь нажал Ctrl+S (файл гарантированно свободен от локов)
2. didChangeWatchedFiles - встроенный в Zed Rust-watcher заметил изменения на диске
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [LSP] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MSCodeBase-LSP")

# Поддерживаемые расширения (код + конфиги + документация)
SUPPORTED_EXTENSIONS = {
    ".py",
    ".rs",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".php",
    ".rb",
    ".swift",
    ".kt",
    ".scala",
    ".r",
    ".m",
    ".mm",
    ".html",
    ".css",
    ".scss",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
}


def _uri_to_path(uri: str) -> Path:
    """Безопасная конвертация URI от редактора в системный Path (с учетом Windows)."""
    parsed = urlparse(uri)
    raw_path = parsed.path
    if sys.platform == "win32" and raw_path.startswith("/"):
        raw_path = raw_path.lstrip("/")
    return Path(raw_path).resolve()


def _get_rel_path_str(file_path: Path, project_path: Path) -> str:
    """Возвращает нормализованный относительный POSIX-путь для LanceDB."""
    return file_path.relative_to(project_path).as_posix()


# Глобальные переменные для lazy init
_indexer = None
_embedder = None
_file_guard = None
_project_path = None


def init_components(project_root: Path):
    """Ленивая инициализация компонентов ядра."""
    global _indexer, _embedder, _file_guard, _project_path

    if _indexer is not None:
        return

    _project_path = project_root

    from src.core.file_guard import FileGuard
    from src.core.indexer import Indexer, _generate_unique_db_path
    from src.core.remote_embedder import RemoteEmbedder

    db_path = _generate_unique_db_path(project_root)
    _embedder = RemoteEmbedder(port=1234)
    _file_guard = FileGuard(project_root)
    _indexer = Indexer(db_path, _embedder, _file_guard)

    logger.info(f"LSP: Инициализирован Indexer для {project_root.name}")


def _execute_file_indexing(file_path: Path):
    """Оркестрация проверки хеша и чанкера (вызывается в thread-пуле)."""
    if _indexer is None:
        init_components(_project_path or Path.cwd())

    # Проверки безопасности
    if not _indexer.path_manager.is_safe_to_process(file_path):
        return
    if _indexer.file_guard.should_skip_file(file_path):
        return

    try:
        rel_path_str = _get_rel_path_str(file_path, _indexer.project_path)
    except ValueError:
        return

    logger.info(f"[LSP INDEXING] Анализ файла: {rel_path_str}")
    success = _indexer._index_single_file(file_path, rel_path_str)

    if success and _indexer.searcher:
        _indexer.searcher.reindex()


def _process_watched_changes(changes):
    """Синхронный воркер для обработки пачки внешних событий диска."""
    need_search_reindex = False

    for change in changes:
        file_path = _uri_to_path(change.uri)
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            rel_path_str = _get_rel_path_str(file_path, _indexer.project_path)
        except ValueError:
            continue

        # FileChangeType.Deleted == 3
        if change.type == 3:
            logger.info(f"[LSP DELETE] {file_path.name}")
            _indexer.prune_deleted_files({rel_path_str})
            need_search_reindex = True

        # FileChangeType.Created == 1 или Changed == 2
        elif change.type in (1, 2):
            logger.info(
                f"[LSP {'CREATE' if change.type == 1 else 'CHANGE'}] {file_path.name}"
            )
            if _indexer._index_single_file(file_path, rel_path_str):
                need_search_reindex = True

    if need_search_reindex and _indexer.searcher:
        _indexer.searcher.reindex()


# ============================================================================
# LSP Server
# ============================================================================

try:
    from lsprotocol.types import (
        TEXT_DOCUMENT_DID_SAVE,
        DidSaveTextDocumentParams,
        InitializeParams,
        InitializeResult,
        TextDocumentSyncKind,
    )
    from pygls.lsp.server import LanguageServer

    class MSCodeBaseLanguageServer(LanguageServer):
        """Language Server для проактивной индексации."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._initialized = False

    server = MSCodeBaseLanguageServer("mscodebase-lsp", "1.0.0")

    # === 1. ОБРАБОТКА ИЗМЕНЕНИЙ ПРИ СОХРАНЕНИИ (ГОРЯЧИЙ СЦЕНАРИЙ) ===
    @server.feature(TEXT_DOCUMENT_DID_SAVE)
    async def did_save(ls: MSCodeBaseLanguageServer, params: DidSaveTextDocumentParams):
        """Триггерится нативным Ctrl+S в Zed. Файл уже свободен от локов Windows."""
        try:
            file_path = _uri_to_path(params.text_document.uri)

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                return

            logger.info(f"[LSP EVENT] Файл сохранен пользователем: {file_path.name}")

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _execute_file_indexing, file_path)

        except Exception as e:
            logger.error(
                f"[LSP RECOVERY] Ошибка при сохранении файла: {e}", exc_info=True
            )

    # === 2. ОБРАБОТКА ВНЕШНИХ ИЗМЕНЕНИЙ (git checkout, удаление вне редактора) ===
    @server.feature("workspace/didChangeWatchedFiles")
    async def did_change_watched_files(ls: MSCodeBaseLanguageServer, params):
        """
        Вызывается, когда встроенный в Zed (Rust) файловый watcher
        заметил физические изменения на диске.
        """
        try:
            if _indexer is None:
                return

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _process_watched_changes, params.changes)
        except Exception as e:
            logger.error(
                f"[LSP RECOVERY] Ошибка обработки изменений воркспейса: {e}",
                exc_info=True,
            )

    # === 3. ИНИЦИАЛИЗАЦИЯ ===
    @server.feature("initialize")
    async def on_initialize(ls: MSCodeBaseLanguageServer, params: InitializeParams):
        """При старте забираем у Zed реальный корень открытого проекта."""
        project_root = Path(urlparse(params.root_uri).path)
        if sys.platform == "win32" and str(project_root).startswith("\\"):
            project_root = Path(str(project_root).lstrip("\\"))

        logger.info(f"[LSP INIT] Запуск на корне воркспейса: {project_root}")

        init_components(project_root)
        ls._initialized = True

        return InitializeResult(
            capabilities={
                "text_document_sync": TextDocumentSyncKind.Incremental,
            }
        )

    @server.feature("initialized")
    async def on_initialized(ls: MSCodeBaseLanguageServer, params):
        """После успешной инициализации подписываемся на системный watcher редактора."""
        try:
            from lsprotocol.types import (
                DidChangeWatchedFilesRegistrationOptions,
                FileSystemWatcher,
            )

            options = DidChangeWatchedFilesRegistrationOptions(
                watchers=[FileSystemWatcher(glob_pattern="**/*")]
            )
            await ls.register_capability_async(
                "workspace/didChangeWatchedFiles", options
            )
            logger.info("[LSP INIT] Подписка на системные события файлов Zed оформлена")
        except Exception as e:
            logger.warning(f"[LSP INIT] Не удалось подписаться на watcher: {e}")

except ImportError:
    logger.warning("pygls/lsprotocol не установлены. LSP-сервер недоступен.")
    server = None


def main():
    """Запуск LSP сервера."""
    if server is None:
        logger.error("LSP: Не удалось запустить сервер (отсутствуют зависимости)")
        sys.exit(1)

    logger.info("LSP: Запуск сервера через stdio...")
    server.start_io()


if __name__ == "__main__":
    main()
