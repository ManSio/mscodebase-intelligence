"""
MSCodeBase Intelligence MCP Server - Главный обработчик (Handler)
Размещается в src/mcp/handler.py. Полная изоляция проектов.
"""

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path

# Импортируем FastMCP
from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("mscodebase_server")

# --- Глобальное состояние сервера ---
embedder_instance = None
indexer_instance = None
searcher_instance = None

# Оркестратор: глобальный мьютекс ОС для фоновых потоков
_indexing_lock = threading.Lock()


def create_mcp_server() -> FastMCP:
    """Фабрика для полной сборки и инициализации MCP сервера."""
    global embedder_instance, indexer_instance, searcher_instance

    mcp = FastMCP("MSCodebase Intelligence Server")

    # Так как файл лежит в src/mcp/handler.py, выходим на уровень корня самого РАСШИРЕНИЯ
    ext_root = Path(__file__).resolve().parent.parent.parent

    # Инициализация базовых модулей ядра
    from src.core.file_guard import FileGuard
    from src.core.indexer import Indexer
    from src.core.remote_embedder import RemoteEmbedder
    from src.core.searcher import Searcher

    # Твой жесткий порт LM Studio
    embedder_instance = RemoteEmbedder(port=1234)
    file_guard = FileGuard()

    # Временная точка монтирования (база инициализируется динамически под каждый проект)
    global_indices_dir = ext_root / ".codebase_indices"
    global_indices_dir.mkdir(parents=True, exist_ok=True)

    indexer_instance = Indexer(
        db_path=global_indices_dir / "default",
        embedder=embedder_instance,
        file_guard=file_guard,
    )
    searcher_instance = Searcher(indexer=indexer_instance, embedder=embedder_instance)
    indexer_instance.searcher = searcher_instance

    # Вспомогательная функция для динамического переключения базы под конкретный целевой проект
    def switch_to_project_db(target_project_path: Path):
        import hashlib

        import chromadb

        project_hash = hashlib.md5(
            str(target_project_path).lower().encode("utf-8")
        ).hexdigest()[:12]

        project_db_path = global_indices_dir / project_hash
        project_db_path.mkdir(parents=True, exist_ok=True)

        indexer_instance.db_path = project_db_path
        indexer_instance.chroma_client = chromadb.PersistentClient(
            path=str(project_db_path)
        )
        indexer_instance.collection = (
            indexer_instance.chroma_client.get_or_create_collection(
                name="codebase_chunks", metadata={"hnsw:space": "cosine"}
            )
        )
        logger.info(
            f"🚜 Оркестратор динамически переключил ChromaDB на базу проекта: [{target_project_path.name}] -> {project_db_path}"
        )

    # --- РЕГИСТРАЦИЯ ВСЕХ 6 ИНСТРУМЕНТОВ MCP ---

    # 1. Статус индекса
    @mcp.tool()
    def index_status(project_path: str = None, **kwargs) -> str:
        """Показать статус векторного индекса для указанного или текущего проекта."""
        global indexer_instance
        if not indexer_instance:
            return "Ошибка: Ядро индексации не инициализировано."
        try:
            path_str = project_path or kwargs.get("path") or str(ext_root)
            target_path = Path(path_str).resolve()

            switch_to_project_db(target_path)

            stats = indexer_instance.get_status()
            return (
                f"📊 Статус индекса для проекта [{target_path.name}]:\n"
                f"- Всего проиндексировано файлов: {stats.get('total_files', 0)}\n"
                f"- Количество векторных чанков в ChromaDB: {stats.get('total_chunks', 0)}\n"
                f"- Папка хранения этой БД: {stats.get('db_path', '?')}\n"
                f"- Статус фонового воркера ОС: {'АКТИВЕН' if _indexing_lock.locked() else 'СПИТ'}"
            )
        except Exception as e:
            return f"Ошибка получения статуса: {str(e)}"

    # 2. Переиндексация (В фоне Windows с полной изоляцией)
    @mcp.tool()
    async def reindex_all(project_path: str = None, **kwargs) -> str:
        """Запустить изолированную фоновую переиндексацию проекта."""
        global indexer_instance, searcher_instance

        path_str = project_path or kwargs.get("path") or str(ext_root)
        target_path = Path(path_str).resolve()

        if not target_path.exists():
            return (
                f"❌ Ошибка: Путь {target_path} физически не найден на диске Windows."
            )

        if not _indexing_lock.acquire(blocking=False):
            logger.warning("🚜 Оркестратор: воркер уже занят индексацией.")
            return "⚠️ Индексация проекта уже выполняется в фоне. Пожалуйста, подождите."

        def background_worker(path: Path):
            try:
                logger.info(
                    f"🚜 Оркестратор: Поток Windows ЗАПУЩЕН для воркспейса {path}"
                )

                switch_to_project_db(path)

                count = indexer_instance.index_project(path)
                if searcher_instance:
                    searcher_instance.reindex()
                logger.info(
                    f"✅ Оркестратор: Фоновая индексация завершена для {path.name}. Файлов: {count}"
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
            f"🚀 Оркестратор перехватил управление!\n"
            f"Индексация проекта '{target_path.name}' успешно уведена в изолированный фон Windows.\n"
            f"База данных полностью изолирована. Проверь логи LM Studio на порту 1234."
        )

    # 3. Семантический поиск по коду
    @mcp.tool()
    def search_code(
        query: str, project_path: str = None, limit: int = 5, **kwargs
    ) -> str:
        """Выполнить семантический поиск по изолированной кодовой базе конкретного проекта."""
        global searcher_instance
        if not searcher_instance:
            return "Ошибка: Поисковый движок не инициализирован."
        try:
            path_str = project_path or kwargs.get("path") or str(ext_root)
            target_path = Path(path_str).resolve()

            switch_to_project_db(target_path)

            results = searcher_instance.search(query, limit=limit)
            if not results:
                return f"🔍 В базе проекта '{target_path.name}' ничего не найдено."

            output = [
                f"🔍 Результаты поиска по проекту '{target_path.name}' для запроса: '{query}':\n"
            ]
            for i, res in enumerate(results, 1):
                output.append(
                    f"[{i}] Файл: {res.get('file_path')} (Сходство: {res.get('score', 0):.4f})\n"
                    f"```\n{res.get('content', '')}\n```\n"
                    f"--------------------------------------------------"
                )
            return "\n".join(output)
        except Exception as e:
            return f"❌ Ошибка поиска: {str(e)}"

    # 4. Просмотр содержимого конкретного файла
    @mcp.tool()
    def get_file_contents(file_path: str, **kwargs) -> str:
        """Прочитать содержимое конкретного файла."""
        target = Path(file_path).resolve()
        if not target.exists():
            return f"❌ Ошибка: Файл {file_path} не существует."
        try:
            with open(target, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return f"📄 Файл: {target}\n```\n{content}\n```"
        except Exception as e:
            return f"❌ Ошибка чтения файла: {str(e)}"

    # 5. Вывод структуры директории
    @mcp.tool()
    def list_directory(path: str = None, **kwargs) -> str:
        """Показать список файлов и папок в указанной директории."""
        target_path = Path(path or str(ext_root)).resolve()
        if not target_path.exists():
            return f"❌ Ошибка: Директория {target_path} не найдена."
        try:
            items = os.listdir(target_path)
            files = [i for i in items if os.path.isfile(target_path / i)]
            dirs = [i for i in items if os.path.isdir(target_path / i)]

            output = [f"📁 Директория: {target_path}\n"]
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

    # 6. Быстрый текстовый поиск файлов по имени
    @mcp.tool()
    def file_search(pattern: str, project_path: str = None, **kwargs) -> str:
        """Найти файлы по маске имени внутри конкретного проекта."""
        path_str = project_path or kwargs.get("path") or str(ext_root)
        root_path = Path(path_str).resolve()
        found_files = []
        try:
            for root, _, files in os.walk(root_path):
                if "venv" in root or ".codebase_indices" in root or ".git" in root:
                    continue
                for f in files:
                    if pattern.lower() in f.lower():
                        found_files.append(str(Path(root) / f))
            if not found_files:
                return (
                    f"🔍 Файлы по маске '{pattern}' внутри {root_path.name} не найдены."
                )
            return f"🔍 Найденные файлы ({len(found_files)}):\n" + "\n".join(
                found_files
            )
        except Exception as e:
            return f"❌ Ошибка поиска файлов: {str(e)}"

    logger.info("🚀 Полная сборка мульти-проектного MCP сервера завершена успешно.")
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
