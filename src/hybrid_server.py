"""(DEPRECATED) Устаревший способ запуска LSP+MCP в одном процессе.

Вся функциональность перенесена:
- lsp_main.py — LSP обработчики
- mcp/server.py — MCP сервер
- core/di_container.py — общее состояние (DI контейнер)
- mcp/tools/system_tools.py — read_live_file (замена hybrid режиму)

Причина удаления: DI Container решает проблему общего состояния
между LSP и MCP без единого процесса. Оба сервера используют
один и тот же create_service_collection(), подключены к одной
LanceDB базе.
"""

"""
MSCodebase Intelligence — Hybrid LSP + MCP Server (Единый процесс)

Архитектура:
- LSP-сервер (stdio): получает события от Zed (didOpen, didChange, didSave)
- MCP-сервер (HTTP/SSE): предоставляет инструменты для AI-ассистента
- Общая память: индексатор LanceDB доступен обоим серверам

Это решает проблемы:
1. WinError 5 (нет конфликтов — один процесс)
2. Отложенная запись на диск (читаем из памяти LSP)
3. Закрытые файлы (MCP может читать через LSP VFS)
"""

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional, Set
from urllib.parse import urlparse

# ⚠️ КРИТИЧНО: убираем src/ из sys.path ДО любого импорта!
# При запуске "python -u src/hybrid_server.py" Python автоматически добавляет
# src/ в sys.path[0], и наш src/mcp/ затеняет библиотеку mcp (pip-пакет).
# Убираем все пути, содержащие src/mcp, чтобы mcp резолвился из site-packages.
_script_dir = str(Path(__file__).resolve().parent)
sys.path = [p for p in sys.path if p != _script_dir]

# Настройка логирования
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [MSCodeBase] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MSCodeBase-Hybrid")

# Импортируем mcp-библиотеку (теперь из site-packages, не из src/mcp/)
import uvicorn  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

# Добавляем проект в PYTHONPATH (теперь безопасно — mcp уже в sys.modules)
_ext_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ext_root))

from src.core.file_guard import FileGuard
from src.core.indexer import Indexer, _generate_unique_db_path
from src.core.log_manager import get_log_summary, setup_project_logging
from src.core.multi_project_searcher import MultiProjectSearcher, ProjectRegistry
from src.core.parser import CodeParser
from src.core.remote_embedder import RemoteEmbedder
from src.core.searcher import Searcher
from src.core.structural_search import StructuralSearcher
from src.core.symbol_index import SymbolIndex

# Настройка файлового логирования
setup_project_logging(_ext_root)

# Поддерживаемые расширения
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
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
}


class SharedIndexer:
    """Общий индексатор для LSP и MCP серверов.

    Использует asyncio.Lock для безопасного доступа из разных корутин.
    """

    def __init__(self):
        self.indexer: Optional[Indexer] = None
        self.project_path: Optional[Path] = None
        self._initialized = False
        self._lock = asyncio.Lock()  # Синхронизация доступа к индексу

    def initialize(self, project_path: Path):
        """Инициализация индексатора."""
        if self._initialized:
            return

        self.project_path = project_path

        db_path = _generate_unique_db_path(project_path)
        # RemoteEmbedder теперь использует конфигурацию по умолчанию
        self.embedder = RemoteEmbedder()
        file_guard = FileGuard(project_path)
        self.parser = CodeParser()

        self.indexer = Indexer(
            db_path,
            self.embedder,
            file_guard,
            project_path=project_path,
            parser=self.parser,
        )
        self.searcher = Searcher(self.indexer, self.embedder)
        self.indexer.searcher = self.searcher

        # Структурный индекс символов (Tree-sitter)
        self.symbol_index = SymbolIndex()

        # Cross-repo поиск
        self.project_registry = ProjectRegistry()
        self.project_registry.register(project_path)
        self.multi_project_searcher = MultiProjectSearcher(
            self.embedder, self.project_registry
        )

        self._initialized = True
        logger.info(f"✅ SharedIndexer initialized for {project_path}")

    async def index_file(self, file_path: Path, content: Optional[str] = None) -> bool:
        """Индексировать один файл (thread-safe через asyncio.Lock)."""
        if not self._initialized or self.indexer is None or self.project_path is None:
            return False

        async with self._lock:  # Защита от гонок
            try:
                rel_path = str(file_path.relative_to(self.project_path))
                # Запускаем синхронный индексатор в thread pool
                return await asyncio.to_thread(
                    self.indexer._index_single_file, file_path, rel_path, content
                )
            except Exception as e:
                logger.error(f"Index error: {e}")
                return False

    def search(self, query: str, limit: int = 6) -> str:
        """Поиск по базе."""
        if not self._initialized or self.searcher is None:
            return "❌ Индекс не инициализирован"
        return self.searcher.search(query, limit=limit)

    def get_status(self) -> dict:
        """Статус базы."""
        if not self._initialized or self.indexer is None:
            return {"status": "not_initialized"}
        return self.indexer.get_status()


# Глобальный экземпляр
shared_indexer = SharedIndexer()


def uri_to_path(uri: str) -> Path:
    """Конвертация LSP URI в системный путь."""
    parsed = urlparse(uri)
    path = parsed.path
    # Windows: /C:/path -> C:/path
    if path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return Path(path).resolve()


# ============================================================================
# LSP SERVER (stdio)
# ============================================================================

from lsprotocol.types import (
    TEXT_DOCUMENT_DID_CHANGE,
    TEXT_DOCUMENT_DID_CLOSE,
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_SAVE,
    DidChangeTextDocumentParams,
    DidCloseTextDocumentParams,
    DidOpenTextDocumentParams,
    DidSaveTextDocumentParams,
    InitializeParams,
)
from pygls.lsp.server import LanguageServer

server = LanguageServer("mscodebase-lsp", "2.0.0")


@server.feature("initialized")
async def on_initialized(ls: LanguageServer, params):
    """Инициализация после подключения Zed (params пустой — это нормально)."""
    try:
        # Используем root_path из pygls (надёжнее чем params.workspace_folders)
        root_path = ls.workspace.root_path
        if not root_path:
            root_path = str(Path.cwd())

        project_path = Path(root_path).resolve()
        shared_indexer.initialize(project_path)
        logger.info(f"🚀 LSP initialized for {project_path}")

        # Регистрируем file watcher для отслеживания внешних изменений
        # (git checkout, правки ИИ в закрытых файлах)
        try:
            from lsprotocol.types import (
                DidChangeWatchedFilesRegistrationOptions,
                FileSystemWatcher,
            )

            await ls.register_capability_async(
                "workspace/didChangeWatchedFiles",
                DidChangeWatchedFilesRegistrationOptions(
                    watchers=[
                        FileSystemWatcher(glob_pattern="**/*.py"),
                        FileSystemWatcher(glob_pattern="**/*.ts"),
                        FileSystemWatcher(glob_pattern="**/*.rs"),
                        FileSystemWatcher(glob_pattern="**/*.js"),
                        FileSystemWatcher(glob_pattern="**/*.go"),
                        FileSystemWatcher(glob_pattern="**/*.md"),
                    ]
                ),
            )
            logger.info("👁️ File watcher registered for external changes")
        except Exception as watch_err:
            logger.warning(f"Could not register watcher: {watch_err}")

        # Холодный старт — индексация всех файлов
        logger.info("🔄 Cold start indexing...")
        await asyncio.to_thread(shared_indexer.indexer.index_project, project_path)
        logger.info("✅ Cold start complete")

    except Exception as e:
        logger.error(f"LSP init error: {e}")


@server.feature(TEXT_DOCUMENT_DID_OPEN)
async def did_open(ls: LanguageServer, params: DidOpenTextDocumentParams):
    """Файл открыт (в т.ч. в фоне для ИИ-ассистента)."""
    file_path = uri_to_path(params.text_document.uri)

    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return

    # Берём текст из памяти LSP
    content = None
    try:
        doc = ls.workspace.get_document(params.text_document.uri)
        content = doc.source
    except Exception:
        pass

    logger.info(f"📂 DID_OPEN: {file_path.name}")
    await shared_indexer.index_file(file_path, content)


@server.feature(TEXT_DOCUMENT_DID_CHANGE)
async def did_change(ls: LanguageServer, params: DidChangeTextDocumentParams):
    """Файл изменён (включая правки ИИ-ассистента)."""
    file_path = uri_to_path(params.text_document.uri)

    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return

    # Берём актуальный текст из памяти
    content = None
    try:
        doc = ls.workspace.get_document(params.text_document.uri)
        content = doc.source
    except Exception:
        pass

    logger.info(
        f"✏️ DID_CHANGE: {file_path.name} ({len(content) if content else 0} chars)"
    )
    await shared_indexer.index_file(file_path, content)


@server.feature(TEXT_DOCUMENT_DID_CLOSE)
async def did_close(ls: LanguageServer, params: DidCloseTextDocumentParams):
    """Файл закрыт. Индекс остаётся в базе."""
    file_path = uri_to_path(params.text_document.uri)
    logger.info(f"📁 DID_CLOSE: {file_path.name}")


@server.feature(TEXT_DOCUMENT_DID_SAVE)
async def did_save(ls: LanguageServer, params: DidSaveTextDocumentParams):
    """Ctrl+S нажат. Берём текст из памяти (не с диска!)."""
    file_path = uri_to_path(params.text_document.uri)

    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return

    # Ключевое: читаем из памяти LSP, а не с диска!
    content = None
    try:
        doc = ls.workspace.get_document(params.text_document.uri)
        content = doc.source
        logger.info(f"💾 DID_SAVE: {file_path.name} ({len(content)} chars from memory)")
    except Exception as e:
        logger.warning(f"DID_SAVE: could not get from memory: {e}")

    await shared_indexer.index_file(file_path, content)


@server.feature("workspace/didChangeWatchedFiles")
async def did_change_watched_files(ls: LanguageServer, params):
    """Внешние изменения файлов (git checkout, правки ИИ в закрытых файлах)."""
    try:
        for change in params.changes:
            file_path = uri_to_path(change.uri)

            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            # FileChangeType: 1=Created, 2=Changed, 3=Deleted
            change_type = change.type

            if change_type == 3:  # Deleted
                logger.info(f"🗑️ WATCHER DELETE: {file_path.name}")
                if shared_indexer.indexer and shared_indexer.project_path is not None:
                    try:
                        rel_path = str(
                            file_path.relative_to(shared_indexer.project_path)
                        )
                        escaped = shared_indexer.indexer._escape_file_path_for_lance(
                            rel_path
                        )
                        shared_indexer.indexer.table.delete(f"file_path = '{escaped}'")
                    except Exception as e:
                        logger.debug(f"Delete error: {e}")
            else:  # Created or Changed
                logger.info(f"👁️ WATCHER CHANGE: {file_path.name} (type={change_type})")
                # Читаем с диска (файл уже на диске)
                await shared_indexer.index_file(file_path, content=None)

    except Exception as e:
        logger.error(f"WATCHER error: {e}")


# ============================================================================
# MCP SERVER (HTTP/SSE)
# ============================================================================


def start_mcp_server():
    """Запуск MCP-сервера через SSE в отдельном потоке."""
    try:
        mcp = FastMCP("mscodebase-mcp")

        @mcp.tool()
        def search_code(query: str) -> str:
            """Поиск кода по базе."""
            if not shared_indexer._initialized:
                return "⏳ Индексатор ещё инициализируется..."
            return shared_indexer.search(query)

        @mcp.tool()
        def get_index_status() -> str:
            """Статус индекса."""
            if not shared_indexer._initialized:
                return "⏳ Индексатор ещё инициализируется..."
            status = shared_indexer.get_status()
            return f"Chunks: {status.get('total_chunks', 0)}, Files: {status.get('unique_files', 0)}"

        @mcp.tool()
        def read_live_file(absolute_path: str) -> str:
            """Чтение файла из памяти LSP (включая несохранённые изменения)."""
            # Пробуем получить из памяти LSP
            try:
                path = Path(absolute_path).resolve()
                uri = f"file://{path.as_posix()}"
                doc = server.workspace.get_document(uri)
                if doc and doc.source:
                    return doc.source
            except Exception:
                pass

            # Fallback: читаем с диска
            try:
                return Path(absolute_path).read_text(encoding="utf-8")
            except Exception as e:
                return f"Error: {e}"

        # Получаем ASGI приложение для SSE
        sse_app = mcp.sse_app()

        # Используем конфигурацию для MCP сервера
        from src.core.config import get_config

        config = get_config()
        mcp_host = config.server.mcp_host
        mcp_port = config.server.mcp_port

        logger.info(f"🌐 Starting MCP server on http://{mcp_host}:{mcp_port}/sse")
        uvicorn.run(sse_app, host=mcp_host, port=mcp_port, log_level="info")
        logger.info("MCP server stopped")

    except ImportError as e:
        logger.warning(f"MCP/Starlette not installed: {e}, running LSP only")
    except Exception as e:
        logger.error(f"MCP server error: {e}")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # Запускаем MCP в отдельном потоке (не-daemon чтобы не умирал)
    mcp_thread = threading.Thread(target=start_mcp_server, daemon=False)
    mcp_thread.start()

    # Даём MCP время запуститься (конфигурируемая задержка)
    from src.core.config import get_config

    config = get_config()

    import time

    startup_delay = config.performance.mcp_startup_delay
    time.sleep(startup_delay)

    # Запускаем LSP в основном потоке (stdio)
    logger.info("🚀 Starting LSP server (stdio)...")
    server.start_io()
