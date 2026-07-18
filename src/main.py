"""
Главная точка входа в приложение.
"""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("MSCodebase")

# Определяем PROJECT_ROOT:
# Если Python запущен из расширения -> корень расширения
# Иначе -> родитель родителя __file__
_exec = Path(sys.executable).resolve()
_EXT_MARKER = "extensions" + os.sep + "mscodebase-intelligence" + os.sep + "venv"
_EXT_MARKER_FILE = "__mscodebase_ext__.marker"
if _EXT_MARKER in str(_exec):
    # Запущены из расширения: PROJECT_ROOT = корень расширения
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    # Если __file__ из проекта (Zed ставит CWD=проект), то PROJECT_ROOT неверный.
    # Проверяем через маркерный файл в корне расширения:
    _marker_path = Path(__file__).resolve().parent.parent / _EXT_MARKER_FILE
    _exec_marker = _exec.parent.parent.parent.resolve() / _EXT_MARKER_FILE
    if _marker_path.exists():
        pass  # PROJECT_ROOT уже правильный
    elif _exec_marker.exists():
        # PROJECT_ROOT через sys.executable
        PROJECT_ROOT = _exec.parent.parent.parent.resolve()
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

_normalized_sys_path = [str(Path(p).resolve()) for p in sys.path]

# ⚠️ КРИТИЧЕСКИ ВАЖНО: Убираем CWD из sys.path, если он — корень проекта
# (чтобы src/ из проекта не перекрыл src/ из расширения)
cwd = Path.cwd().resolve()
if cwd != PROJECT_ROOT:
    sys.path = [p for p in sys.path if Path(p).resolve() != cwd]

# Добавляем PROJECT_ROOT в sys.path (если ещё нет)
project_root_resolved = str(PROJECT_ROOT.resolve())
if project_root_resolved not in [str(Path(p).resolve()) for p in sys.path]:
    sys.path.insert(0, str(PROJECT_ROOT))

# ⚠️ Критично: при запуске через `python -m src.main` пакет `src` уже загружен
# из CWD (проекта). Даже если мы поменяли sys.path, Python не перезагружает
# уже загруженный пакет. Принудительно переключаем src на расширение.
try:
    _src_pkg = sys.modules.get("src")
    if _src_pkg and hasattr(_src_pkg, "__path__"):
        _new_src_path = str(PROJECT_ROOT / "src")
        if _src_pkg.__path__[0] != _new_src_path:
            _old_path = _src_pkg.__path__[0]
            _src_pkg.__path__ = [_new_src_path]
            # Удаляем src.mcp.* — они будут перезагружены с новым __path__
            # (src.core.* уже загружен в setup_logging — не трогаем)
            for _mod_name in list(sys.modules.keys()):
                if _mod_name.startswith("src.mcp"):
                    del sys.modules[_mod_name]
except Exception as _e:
    logger.warning("exception", exc_info=True)
    pass
# После удаления src/ из sys.path модули src.* всё ещё доступны
# через PROJECT_ROOT, но import mcp теперь правильно идёт в site-packages.


def log_crash(error: BaseException) -> None:
    """Записывает критический сбой в файл, чтобы Zed мог перезапустить сервер."""
    import traceback

    log_path = PROJECT_ROOT / "crash_debug.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 80}\n")
        f.write(f"Critical crash at {Path.cwd()}\n")
        traceback.print_exc(file=f)


def _load_env():
    """Загружает .env файл из корня проекта."""
    try:
        from dotenv import load_dotenv
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        pass  # python-dotenv не установлен — используем системные env


def setup_logging():
    """Настраивает логирование и перенаправляет stdout в stderr.
    Возвращает (original_stdout, logger).
    """
    _load_env()

    # 1. Сохраняем оригинальный stdout (он нужен для общения с MCP)
    original_stdout = sys.stdout

    # 2. Перенаправляем все print/logs в stderr
    sys.stdout = sys.stderr

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    # 3. Подключаем файловое логирование (проект определится позже в create_mcp_server)
    try:
        from src.core.log_manager import setup_project_logging
        ext_root = Path(__file__).resolve().parent.parent
        # Фиксированное имя лог-файла для единообразия (см. MAIN_LOG_FILE в log_manager.py)
        setup_project_logging(ext_root, project_label="mscodebase-intelligence")
    except Exception:
        pass  # Файловое логирование опционально

    return original_stdout


def main():
    """Главная функция запуска MCP-сервера."""
    original_stdout = setup_logging()
    logger = logging.getLogger("MSCodebase")
    logger.info("MSCodebase Intelligence MCP Server запускается...")
    logger.info(f"PROJECT_ROOT: {PROJECT_ROOT}")

    try:
        # Обработка аргументов командной строки
        if "--help" in sys.argv or "-h" in sys.argv:
            print("MSCodebase Intelligence MCP Server", file=sys.stderr)
            print("\nИспользование:", file=sys.stderr)
            print(
                "  python -m src.main              # Запуск MCP сервера",
                file=sys.stderr,
            )
            print(
                "  python -m src.main --install    # Установка в проект (.zed/settings.json)",
                file=sys.stderr,
            )
            print(
                "  python -m src.main --install-global  # Установка глобально (для всех проектов)",
                file=sys.stderr,
            )
            print(
                "  python -m src.main --remove     # Удаление из глобальных настроек",
                file=sys.stderr,
            )
            return

        # Логика инсталлятора
        if "--install" in sys.argv or "--install-global" in sys.argv:
            mode = "global" if "--install-global" in sys.argv else "project"

            from src.utils.zed_config import patch_zed_settings

            # Используем автоопределение путей (абсолютные пути к venv python и main.py)
            success = patch_zed_settings(mode=mode)

            if success:
                logger.info(f"✅ Установка ({mode}) завершена. Перезапустите Zed IDE.")
            else:
                logger.error("❌ Установка не удалась.")
            return

        # Логика деинсталлятора
        if "--remove" in sys.argv:
            from src.utils.zed_config import remove_zed_settings

            success = remove_zed_settings()
            if success:
                logger.info("✅ MCP-сервер удалён из настроек Zed.")
            else:
                logger.error("❌ Ошибка при удалении.")
            return

        # Запуск MCP сервера
        from src.mcp.server import run_server

        logger.info("Запуск MCP сервера...")
        # run_server сам создаёт event loop и запускает stdio
        run_server(original_stdout)

    except KeyboardInterrupt:
        logger.info("Сервер остановлен пользователем.")
    except Exception as e:
        log_crash(e)
        logger.error(f"❌ Критическая ошибка сервера: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
