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
from typing import Optional
from urllib.parse import urlparse

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [LSP] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MSCodeBase-LSP")

# Подключаем файловое логирование
try:
    from src.core.log_manager import setup_project_logging
    _ext_root = Path(__file__).resolve().parent.parent
    setup_project_logging(_ext_root)
except Exception:
    pass  # Файловое логирование опционально

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
    from src.core.parser import CodeParser

    db_path = _generate_unique_db_path(project_root)
    _embedder = RemoteEmbedder()  # Использует конфигурацию по умолчанию
    _file_guard = FileGuard(project_root)
    _code_parser = CodeParser()
    _indexer = Indexer(db_path, _embedder, _file_guard, project_path=project_root, parser=_code_parser)

    logger.info(f"LSP: Инициализирован Indexer для {project_root.name}")


def _execute_file_indexing(file_path: Path, content: Optional[str] = None):
    """Оркестрация проверки хеша и чанкера (вызывается в thread-пуле).

    Args:
        file_path: Путь к файлу
        content: Текст файла из памяти LSP. Если None — читает с диска.
    """
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

    logger.info(f"[LSP INDEXING] Анализ файла: {rel_path_str} (from_memory={content is not None})")
    success = _indexer._index_single_file(file_path, rel_path_str, content=content)

    if success and _indexer.searcher:
        _indexer.searcher.reindex()


def _process_watched_changes(changes):
    """Синхронный воркер для обработки пачки внешних событий диска."""
    need_search_reindex = False

    logger.info(f"[LSP WATCHER] Received {len(changes)} file change(s)")

    for change in changes:
        file_path = _uri_to_path(change.uri)
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.debug(f"[LSP WATCHER] Skip unsupported: {file_path.name}")
            continue

        try:
            rel_path_str = _get_rel_path_str(file_path, _indexer.project_path)
        except ValueError:
            logger.debug(f"[LSP WATCHER] Skip (not in project): {file_path.name}")
            continue

        # FileChangeType.Deleted == 3
        if change.type == 3:
            logger.info(f"[LSP DELETE] {rel_path_str}")
            try:
                escaped = _indexer._escape_file_path_for_lance(rel_path_str)
                _indexer.table.delete(f"file_path = '{escaped}'")
                logger.info(f"  └─ Deleted from index: {rel_path_str}")
            except Exception as del_err:
                logger.debug(f"delete() не нашёл запись: {del_err}")
            need_search_reindex = True

        # FileChangeType.Created == 1 или Changed == 2
        elif change.type in (1, 2):
            change_type = 'CREATE' if change.type == 1 else 'CHANGE'
            logger.info(f"[LSP {change_type}] {rel_path_str}")
            try:
                if _indexer._index_single_file(file_path, rel_path_str):
                    logger.info(f"  └─ Reindexed: {rel_path_str}")
                    need_search_reindex = True
                else:
                    logger.info(f"  └─ No changes (hash match): {rel_path_str}")
            except Exception as e:
                logger.error(f"  └─ Indexing failed: {rel_path_str}: {e}")

    if need_search_reindex and _indexer.searcher:
        logger.info("[LSP WATCHER] Rebuilding BM25 index...")
        _indexer.searcher.reindex()
        logger.info("[LSP WATCHER] BM25 rebuild complete")
    elif not need_search_reindex:
        logger.info("[LSP WATCHER] No indexing needed")


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

    # === 1. ЖИЗНЕННЫЙ ЦИКЛ ДОКУМЕНТА (didOpen, didChange, didClose) ===
    # Эти события приходят от Zed когда ИИ-ассистент меняет код в закрытых файлах!

    @server.feature("textDocument/didOpen")
    async def did_open(ls: MSCodeBaseLanguageServer, params):
        """Вызывается когда Zed открывает файл (в т.ч. в фоне для ИИ-ассистента)."""
        try:
            file_path = _uri_to_path(params.text_document.uri)
            logger.info(f"[LSP DID_OPEN] {file_path.name}")

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                return

            # При didOpen текст гарантированно в памяти pygls
            content = None
            try:
                document = ls.workspace.get_document(params.text_document.uri)
                content = document.source
            except Exception:
                pass

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _execute_file_indexing, file_path, content)
        except Exception as e:
            logger.error(f"[LSP DID_OPEN] Error: {e}")

    @server.feature("textDocument/didChange")
    async def did_change(ls: MSCodeBaseLanguageServer, params):
        """Вызывается при каждом изменении текста (включая правки ИИ-ассистента)."""
        try:
            file_path = _uri_to_path(params.text_document.uri)

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                return

            # При didChange текст в памяти pygls уже обновлён
            content = None
            try:
                document = ls.workspace.get_document(params.text_document.uri)
                content = document.source
            except Exception:
                pass

            logger.info(f"[LSP DID_CHANGE] {file_path.name} ({len(content) if content else 0} chars)")

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _execute_file_indexing, file_path, content)
        except Exception as e:
            logger.error(f"[LSP DID_CHANGE] Error: {e}")

    @server.feature("textDocument/didClose")
    async def did_close(ls: MSCodeBaseLanguageServer, params):
        """Вызывается когда Zed закрывает буфер (в т.ч. после работы ИИ-ассистента).

        В этот момент Zed уже зафлашил все изменения на диск,
        поэтому можно безопасно прочитать файл с диска.
        """
        try:
            file_path = _uri_to_path(params.text_document.uri)
            logger.info(f"[LSP DID_CLOSE] {file_path.name}")

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                return

            # При didClose буфер закрыт — файл на диске гарантированно актуален
            # Читаем с диска (content=None)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _execute_file_indexing, file_path, None)
        except Exception as e:
            logger.error(f"[LSP DID_CLOSE] Error: {e}")

    @server.feature(TEXT_DOCUMENT_DID_SAVE)
    async def did_save(ls: MSCodeBaseLanguageServer, params: DidSaveTextDocumentParams):
        """Триггерится нативным Ctrl+S в Zed. Файл уже свободен от локов Windows."""
        try:
            file_path = _uri_to_path(params.text_document.uri)

            logger.info(f"[LSP DID_SAVE] File: {file_path.name}, Suffix: {file_path.suffix}")

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                logger.info(f"[LSP DID_SAVE] Skip unsupported: {file_path.suffix}")
                return

            # Берём текст из памяти LSP (pygls хранит актуальное содержимое)
            # Это решает проблему отложенной записи на диск в Windows!
            content = None
            try:
                document = ls.workspace.get_document(params.text_document.uri)
                content = document.source
                logger.info(f"[LSP DID_SAVE] Got {len(content)} chars from memory")
            except Exception as mem_err:
                logger.warning(f"[LSP DID_SAVE] Could not get from memory: {mem_err}")

            logger.info(f"[LSP DID_SAVE] Starting indexing: {file_path.name}")

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _execute_file_indexing, file_path, content)

            logger.info(f"[LSP DID_SAVE] Indexing complete: {file_path.name}")

        except Exception as e:
            logger.error(
                f"[LSP DID_SAVE] Error: {e}", exc_info=True,
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
                logger.warning("[LSP WATCHER] Indexer not initialized, skip")
                return

            logger.info(f"[LSP WATCHER] Zed sent {len(params.changes)} change(s)")
            for change in params.changes:
                logger.info(f"  - URI: {change.uri}, Type: {change.type}")

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

    logger.info("=" * 60)
    logger.info("MSCodeBase LSP Server запущен")
    logger.info(f"Версия: 1.0.0")
    logger.info(f"Python: {sys.version.split()[0]}")
    logger.info(f"Рабочая директория: {Path.cwd()}")
    logger.info(f"Поддерживаемые расширения: {len(SUPPORTED_EXTENSIONS)} типов")
    logger.info("Ожидание подключения Zed через stdio...")
    logger.info("=" * 60)
    server.start_io()


if __name__ == "__main__":
    main()
