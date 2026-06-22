"""
MSCodeBase Intelligence MCP Server - Главный обработчик (Handler)
Версия со всеми 6 инструментами и фоновой оркестровкой.
"""

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path

# Импортируем FastMCP из библиотеки mcp
from mcp.server.fastmcp import FastMCP

# Настройка логирования
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
    ext_dir = Path(__file__).resolve().parent

    # Автоматическое определение рабочей директории проекта
    current_project = ext_dir.resolve()

    # Генерируем уникальный хэш пути проекта для изоляции ChromaDB
    import hashlib

    project_hash = hashlib.md5(
        str(current_project).lower().encode("utf-8")
    ).hexdigest()[:12]
    db_path = ext_dir / ".codebase_indices" / project_hash
    db_path.mkdir(parents=True, exist_ok=True)

    logger.info(f"🚜 Оркестратор: выделена папка БД -> {db_path}")

    # Инициализация ядра системы
    from src.core.file_guard import FileGuard
    from src.core.indexer import Indexer
    from src.core.remote_embedder import RemoteEmbedder
    from src.core.searcher import Searcher

    # Твой жесткий порт LM Studio
    embedder_instance = RemoteEmbedder(port=1234)
    file_guard = FileGuard()

    indexer_instance = Indexer(
        db_path=db_path, embedder=embedder_instance, file_guard=file_guard
    )
    searcher_instance = Searcher(indexer=indexer_instance, embedder=embedder_instance)
    indexer_instance.searcher = searcher_instance

    # --- РЕГИСТРАЦИЯ ВСЕХ 6 ИНСТРУМЕНТОВ MCP ДЛЯ ZED ---

    # ИНСТРУМЕНТ 1: Статус индекса
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

    # ИНСТРУМЕНТ 2: Запуск переиндексации (Оркестратор в фоне Windows)
    @mcp.tool()
    async def reindex_all(project_path: str = None, **kwargs) -> str:
        """Запустить полную переиндексацию проекта в фоновом режиме ОС Windows."""
        global indexer_instance, searcher_instance

        # Если путь не передан, берем текущую директорию расширения
        path_str = (
            project_path or kwargs.get("path") or str(Path(__file__).resolve().parent)
        )
        target_path = Path(path_str).resolve()

        if not target_path.exists():
            return f"❌ Ошибка: Путь {target_path} не найден на диске."

        if not _indexing_lock.acquire(blocking=False):
            logger.warning("🚜 Оркестратор: воркер уже занят.")
            return (
                "⚠️ Индексация проекта уже выполняется в фоне ОС. Пожалуйста, подождите."
            )

        def background_worker(path: Path):
            try:
                logger.info(f"🚜 Оркестратор: Фоновый поток ОС ЗАПУЩЕН для {path}")
                count = indexer_instance.index_project(path)
                if searcher_instance:
                    searcher_instance.reindex()
                logger.info(
                    f"✅ Оркестратор: Фоновая индексация завершена. Файлов: {count}"
                )
            except Exception as e:
                logger.error(f"❌ Ошибка внутри фонового воркера: {e}", exc_info=True)
            finally:
                _indexing_lock.release()

        thread = threading.Thread(
            target=background_worker,
            args=(target_path,),
            name="MSCodebase-Indexer-Worker",
            daemon=True,
        )
        thread.start()

        return (
            f"🚀 Индексация директории '{target_path}' успешно переведена в изолированный фон Windows.\n"
            f"Zed полностью свободен. Следи за логами в окне LM Studio на порту 1234."
        )

    # ИНСТРУМЕНТ 3: Семантический поиск по коду (ChromaDB + ИИ)
    @mcp.tool()
    def search_code(query: str, limit: int = 5, **kwargs) -> str:
        """Выполнить семантический поиск по кодовой базе проекта с использованием эмбеддингов."""
        global searcher_instance
        if not searcher_instance:
            return "Ошибка: Поисковый движок не инициализирован."
        try:
            results = searcher_instance.search(query, limit=limit)
            if not results:
                return "🔍 Поисковый движок ничего не нашел по этому запросу."

            output = [f"🔍 Результаты поиска по запросу: '{query}':\n"]
            for i, res in enumerate(results, 1):
                output.append(
                    f"[{i}] Файл: {res.get('file_path')} (Сходство: {res.get('score', 0):.4f})\n"
                    f"```\n{res.get('content', '')}\n```\n"
                    f"--------------------------------------------------"
                )
            return "\n".join(output)
        except Exception as e:
            return f"❌ Ошибка при выполнении семантического поиска: {str(e)}"

    # ИНСТРУМЕНТ 4: Просмотр содержимого конкретного файла
    @mcp.tool()
    def get_file_contents(file_path: str, **kwargs) -> str:
        """Прочитать и вернуть полное содержимое конкретного файла из проекта."""
        target = Path(file_path).resolve()
        if not target.exists():
            return f"❌ Ошибка: Файл {file_path} не существует."
        try:
            with open(target, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return f"📄 Содержимое файла: {target}\n```\n{content}\n```"
        except Exception as e:
            return f"❌ Ошибка чтения файла: {str(e)}"

    # ИНСТРУМЕНТ 5: Вывод структуры директории
    @mcp.tool()
    def list_directory(path: str = None, **kwargs) -> str:
        """Показать список файлов и папок в указанной директории проекта."""
        target_path = Path(path or str(Path(__file__).resolve().parent)).resolve()
        if not target_path.exists():
            return f"❌ Ошибка: Директория {target_path} не найдена."
        try:
            items = os.listdir(target_path)
            files = [i for i in items if os.path.isfile(target_path / i)]
            dirs = [i for i in items if os.path.isdir(target_path / i)]

            output = [f"📁 Структура директории: {target_path}\n"]
            output.append("Поддиректории:")
            for d in dirs:
                if not d.startswith((".", "venv")):
                    output.append(f"  [DIR]  {d}")
            output.append("\nФайлы:")
            for f in files:
                output.append(f"  [FILE] {f}")
            return "\n".join(output)
        except Exception as e:
            return f"❌ Ошибка вывода директории: {str(e)}"

    # ИНСТРУМЕНТ 6: Быстрый текстовый поиск файлов по имени
    @mcp.tool()
    def file_search(pattern: str, **kwargs) -> str:
        """Найти файлы в проекте, имена которых соответствуют маске (паттерну)."""
        root_path = Path(__file__).resolve().parent
        found_files = []
        try:
            for root, _, files in os.walk(root_path):
                if "venv" in root or ".codebase_indices" in root or ".git" in root:
                    continue
                for f in files:
                    if pattern.lower() in f.lower():
                        found_files.append(str(Path(root) / f))
            if not found_files:
                return f"🔍 Файлы по маске '{pattern}' не найдены."
            return f"🔍 Найденные файлы ({len(found_files)}):\n" + "\n".join(
                found_files
            )
        except Exception as e:
            return f"❌ Ошибка поиска файлов: {str(e)}"

    logger.info("🚀 Полная сборка MCP сервера со всеми 6 инструментами завершена.")
    return mcp


def run_server(original_stdout=None):
    """Точка входа для запуска stdio сервера."""
    mcp = create_mcp_server()
    if mcp:
        try:
            if original_stdout:
                sys.stdout = original_stdout
            asyncio.run(mcp.run_stdio_async())
        except KeyboardInterrupt:
            logger.info("Сервер остановлен пользователем.")
        except Exception as e:
            logger.error(f"Критическая ошибка сервера: {e}", exc_info=True)


if __name__ == "__main__":
    run_server()
