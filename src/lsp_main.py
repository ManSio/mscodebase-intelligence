"""
MSCodeBase LSP Server — проактивный индексатор через Language Server Protocol.

Интегрируется в Zed как language server и реагирует на сохранение файлов.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

# Настраиваем логирование в stderr (stdout занят LSP протоколом)
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [LSP] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MSCodeBase-LSP")

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


def get_project_root() -> Path:
    """Определяет корень проекта (текущая директория или через PROJECT_PATH)."""
    project_path = os.environ.get("PROJECT_PATH", ".")
    return Path(project_path).resolve()


def get_db_path(project_root: Path) -> Path:
    """Генерирует путь к базе данных для проекта."""
    import hashlib

    project_hash = hashlib.md5(str(project_root).encode()).hexdigest()[:8]
    project_name = project_root.name
    db_dir = project_root.parent / ".codebase_indices" / "lancedb_v2"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / f"index_{project_name}_{project_hash}.db"


def normalize_path(uri_path: str) -> Path:
    """Нормализует URI путь из LSP в файловую систему."""
    parsed = urlparse(uri_path)
    raw_path = parsed.path

    # Windows: убираем ведущий слеш
    if sys.platform == "win32" and raw_path.startswith("/"):
        raw_path = raw_path.lstrip("/")

    return Path(raw_path).resolve()


# Глобальные переменные для lazy init
_indexer = None
_embedder = None
_file_guard = None


def init_components():
    """Ленивая инициализация компонентов."""
    global _indexer, _embedder, _file_guard

    if _indexer is not None:
        return

    from src.core.file_guard import FileGuard
    from src.core.indexer import Indexer
    from src.core.remote_embedder import RemoteEmbedder

    project_root = get_project_root()
    db_path = get_db_path(project_root)

    _embedder = RemoteEmbedder(port=1234)
    _file_guard = FileGuard(project_root)
    _indexer = Indexer(db_path, _embedder, _file_guard)

    logger.info(f"LSP: Инициализирован Indexer для {project_root.name}")


def index_file_async(file_path: Path) -> None:
    """Синхронный вызов индексации (будет запущен в executor)."""
    try:
        if _indexer is None:
            init_components()

        # Получаем относительный путь
        project_root = get_project_root()
        rel_path = str(file_path.relative_to(project_root))

        # Индексируем файл
        if _indexer is not None:
            _indexer.index_file(file_path, project_root)
            logger.info(f"LSP: ✅ Проиндексирован: {rel_path}")
        else:
            logger.warning("LSP: Indexer не инициализирован, пропуск")

    except Exception as e:
        logger.error(f"LSP: ❌ Ошибка индексации {file_path}: {e}")


# ============================================================================
# LSP Server
# ============================================================================

try:
    from lsprotocol.types import (
        TEXT_DOCUMENT_DID_SAVE,
        DidSaveTextDocumentParams,
        InitializeParams,
        TextDocumentSyncKind,
    )
    from pygls.lsp.server import LanguageServer

    class MSCodeBaseLanguageServer(LanguageServer):
        """Language Server для проактивной индексации."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._initialized = False

    server = MSCodeBaseLanguageServer("mscodebase-lsp", "1.0.0")

    @server.feature(TEXT_DOCUMENT_DID_SAVE)
    async def did_save(ls: MSCodeBaseLanguageServer, params: DidSaveTextDocumentParams):
        """Обработчик сохранения файла — триггерит индексацию."""
        try:
            file_path = normalize_path(params.text_document.uri)

            # Фильтруем по расширениям
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                return

            logger.info(f"LSP: 💾 Файл сохранён: {file_path.name}")

            # Индексируем в executor (не блокируем LSP loop)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, index_file_async, file_path)

        except Exception as e:
            logger.error(f"LSP: ❌ Ошибка обработки didSave: {e}")

    @server.feature("initialize")
    async def initialize(ls: MSCodeBaseLanguageServer, params: InitializeParams):
        """Инициализация сервера."""
        init_components()
        ls._initialized = True
        logger.info("LSP: Сервер инициализирован")

        # Возвращаем capabilities
        from lsprotocol.types import InitializeResult

        return InitializeResult(
            capabilities={
                "text_document_sync": TextDocumentSyncKind.Incremental,
            }
        )

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
