"""
MSCodeBase Intelligence MCP Server - Главный обработчик (Handler)
"""

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path

# Импортируем FastMCP из библиотеки mcp
from mcp.server.fastmcp import FastMCP

# Настройка логирования для отладки
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("mscodebase_server")

# --- Глобальное состояние сервера ---
embedder_instance = None
indexer_instance = None
searcher_instance = None

# Оркестратор: глобальный мьютекс ОС для контроля фоновых потоков
_indexing_lock = threading.Lock()


def create_mcp_server() -> FastMCP:
    """Фабрика для полной сборки и инициализации MCP сервера."""
    global embedder_instance, indexer_instance, searcher_instance

    mcp = FastMCP("MSCodebase Intelligence Server")
    ext_dir = Path(__file__).resolve().parent.parent

    # 1. Определение рабочей директории проекта и изоляция индексов
    current_cwd = Path(os.getcwd()).resolve()
    if "Zed" in str(current_cwd) or "Program Files" in str(current_cwd):
        current_project = Path(r"D:\Project\gemma_agent")
    else:
        current_project = current_cwd

    # Генерируем уникальный хэш пути проекта для изоляции ChromaDB
    import hashlib

    project_hash = hashlib.md5(
        str(current_project).lower().encode("utf-8")
    ).hexdigest()[:12]

    # Путь к базе данных конкретного проекта
    db_path = ext_dir / ".codebase_indices" / project_hash
    db_path.mkdir(parents=True, exist_ok=True)

    logger.info(
        f"🚜 Оркестратор: выделена изолированная папка БД для [{current_project}] -> {db_path}"
    )

    # 2. Инициализация ядра (Явно импортируем твои модули)
    from src.core.file_guard import FileGuard
    from src.core.indexer import Indexer
    from src.core.remote_embedder import RemoteEmbedder
    from src.core.searcher import Searcher

    # Твой жесткий порт LM Studio
    embedder_instance = RemoteEmbedder(port=1234)
    file_guard = FileGuard(project_path=current_project)

    indexer_instance = Indexer(
        db_path=db_path, embedder=embedder_instance, file_guard=file_guard
    )
    searcher_instance = Searcher(indexer=indexer_instance, embedder=embedder_instance)
    indexer_instance.searcher = searcher_instance

    # --- РЕГИСТРАЦИЯ ИНСТРУМЕНТОВ MCP ДЛЯ ZED ---

    @mcp.tool()
    def index_status(**kwargs) -> str:
        """Показать текущий статус векторного индекса проекта."""
        global indexer_instance
        if not indexer_instance:
            return "Ошибка: Ядро индексации не инициализировано."
        try:
            stats = indexer_instance.get_status()
            return (
                f"📊 Статус индекса кодовой базы:\n"
                f"- Всего проиндексировано файлов: {stats.get('total_files', 0)}\n"
                f"- Количество векторных чанков в ChromaDB: {stats.get('total_chunks', 0)}\n"
                f"- Директория хранения БД: {stats.get('db_path', '?')}\n"
                f"- Статус фонового воркера ОС: {'АКТИВЕН' if _indexing_lock.locked() else 'СПИТ'}"
            )
        except Exception as e:
            return f"Ошибка получения статуса: {str(e)}"

    @mcp.tool()
    async def reindex_all(project_path: str = None, **kwargs) -> str:
        """
        Запустить полную переиндексацию проекта в фоновом режиме.
        Zed мгновенно получит ответ, а воркер продолжит работу в фоне ОС Windows.
        """
        global indexer_instance, searcher_instance

        # Подхватываем твой рабочий путь по умолчанию
        path_str = project_path or kwargs.get("path") or r"D:\Project\gemma_agent"
        target_path = Path(path_str).resolve()

        if not target_path.exists():
            return (
                f"❌ Ошибка: Путь {target_path} физически не найден на диске Windows."
            )

        # Проверка замка оркестратора (non-blocking acquire)
        if not _indexing_lock.acquire(blocking=False):
            logger.warning(
                "🚜 Оркестратор: Запрос отклонен, фоновый воркер уже выполняет индексацию."
            )
            return (
                "⚠️ Индексация проекта уже выполняется в фоне ОС. Пожалуйста, подождите."
            )

        # Воркер, который будет выполняться в изолированном физическом потоке Windows
        def background_worker(path: Path):
            try:
                logger.info(
                    f"🚜 Оркестратор: Фоновый поток ОС [MSCodebase-Worker] ЗАПУЩЕН для {path}"
                )

                # Синхронный запуск тяжелого сканирования файлов и отправки векторов
                count = indexer_instance.index_project(path)

                # Обновление поискового кэша BM25
                if searcher_instance:
                    searcher_instance.reindex()

                logger.info(
                    f"✅ Оркестратор: Фоновая индексация успешно завершена. Файлов обработано: {count}"
                )
            except Exception as e:
                logger.error(
                    f"❌ Ошибка внутри фонового воркера оркестратора: {e}",
                    exc_info=True,
                )
            finally:
                # Железное освобождение замка при любом раскладе
                _indexing_lock.release()
                logger.info(
                    "🚜 Оркестратор: Фоновый поток завершил работу и освободил замок."
                )

        # Создаем и стартуем независимый OS Thread
        thread = threading.Thread(
            target=background_worker,
            args=(target_path,),
            name="MSCodebase-Indexer-Worker",
            daemon=True,
        )
        thread.start()

        # Мгновенный ответ в Zed RPC, чтобы исключить заморозку Event Loop-а со стороны редактора
        return (
            f"🚀 Оркестратор перехватил управление!\n"
            f"Индексация директории '{target_path}' успешно переведена в изолированный фон Windows.\n"
            f"Zed полностью свободен для работы. Смотри логи в окне LM Studio на порту 1234."
        )

    logger.info("🚀 Полная сборка MCP сервера завершена успешно.")
    return mcp


def run_server(original_stdout=None):
    """Точка входа для запуска stdio сервера."""
    mcp = create_mcp_server()
    if mcp:
        try:
            if original_stdout:
                sys.stdout = original_stdout
            # Запуск асинхронного stdio-интерфейса FastMCP
            asyncio.run(mcp.run_stdio_async())
        except KeyboardInterrupt:
            logger.info("Сервер остановлен пользователем.")
        except Exception as e:
            logger.error(f"Критическая ошибка сервера: {e}", exc_info=True)


if __name__ == "__main__":
    run_server()
