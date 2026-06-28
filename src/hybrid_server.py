"""
MSCodeBase Intelligence — Hybrid LSP + MCP Server (Единый процесс)

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

# Настройка логирования
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [MSCodeBase] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MSCodeBase-Hybrid")

# Добавляем проект в PYTHONPATH
_ext_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ext_root))

from src.core.indexer import Indexer, _generate_unique_db_path
from src.core.remote_embedder import RemoteEmbedder
from src.core.file_guard import FileGuard
from src.core.parser import CodeParser
from src.core.searcher import Searcher
from src.core.log_manager import setup_project_logging

# Настройка файлового логирования
setup_project_logging(_ext_root)

# Поддерживаемые расширения
SUPPORTED_EXTENSIONS = {
    ".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".go",
    ".java", ".cpp", ".c", ".h", ".hpp", ".php", ".rb",
    ".md", ".json", ".yaml", ".yml", ".toml",
}


class SharedIndexer:
    """Общий индексатор для LSP и MCP серверов."""

    def __init__(self):
        self.indexer: Optional[Indexer] = None
        self.project_path: Optional[Path] = None
        self._initialized = False

    def initialize(self, project_path: Path):
        """Инициализация индексатора."""
        if self._initialized:
            return

        self.project_path = project_path

        db_path = _generate_unique_db_path(project_path)
        embedder = RemoteEmbedder(port=1234)
        file_guard = FileGuard(project_path)
        parser = CodeParser()

        self.indexer = Indexer(
            db_path, embedder, file_guard,
            project_path=project_path, parser=parser
        )
        self.searcher = Searcher(self.indexer, embedder)
        self.indexer.searcher = self.searcher

        self._initialized = True
        logger.info(f"✅ SharedIndexer initialized for {project_path}")

    def index_file(self, file_path: Path, content: Optional[str] = None) -> bool:
        """Индексировать один файл."""
        if not self._initialized or self.indexer is None:
            return False

        try:
            rel_path = str(file_path.relative_to(self.project_path))
            return self.indexer._index_single_file(file_path, rel_path, content=content)
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
    if path.startswith('/') and len(path) > 2 and path[2] == ':':
        path = path[1:]
    return Path(path).resolve()


# ============================================================================
# LSP SERVER (stdio)
# ============================================================================

from lsprotocol.types import (
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_DID_CHANGE,
    TEXT_DOCUMENT_DID_CLOSE,
    TEXT_DOCUMENT_DID_SAVE,
    DidOpenTextDocumentParams,
    DidChangeTextDocumentParams,
    DidCloseTextDocumentParams,
    DidSaveTextDocumentParams,
    InitializeParams,
)
from pygls.lsp.server import LanguageServer

server = LanguageServer("mscodebase-lsp", "2.0.0")


@server.feature("initialize")
async def on_initialize(ls: LanguageServer, params: InitializeParams):
    """Инициализация LSP-сервера."""
    try:
        workspace = params.workspace_folders[0] if params.workspace_folders else None
        if workspace:
            project_path = uri_to_path(workspace.uri)
        else:
            project_path = Path.cwd()

        shared_indexer.initialize(project_path)
        logger.info(f"🚀 LSP initialized for {project_path}")
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
    shared_indexer.index_file(file_path, content)


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

    logger.info(f"✏️ DID_CHANGE: {file_path.name} ({len(content) if content else 0} chars)")
    shared_indexer.index_file(file_path, content)


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

    shared_indexer.index_file(file_path, content)


# ============================================================================
# MCP SERVER (HTTP/SSE)
# ============================================================================

def start_mcp_server():
    """Запуск MCP-сервера через SSE в отдельном потоке."""
    try:
        from mcp.server.fastmcp import FastMCP
        import uvicorn

        mcp = FastMCP("mscodebase-mcp")

        @mcp.tool()
        def search_code(query: str) -> str:
            """Поиск кода по базе."""
            return shared_indexer.search(query)

        @mcp.tool()
        def get_index_status() -> str:
            """Статус индекса."""
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

        logger.info("🌐 Starting MCP server on http://127.0.0.1:8765/sse")
        uvicorn.run(sse_app, host="127.0.0.1", port=8765, log_level="info")
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

    # Даём MCP время запуститься
    import time
    time.sleep(1)

    # Запускаем LSP в основном потоке (stdio)
    logger.info("🚀 Starting LSP server (stdio)...")
    server.start_io()
