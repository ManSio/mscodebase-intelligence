"""
Главная точка входа в приложение.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ⚠️ КРИТИЧЕСКИ ВАЖНО: Убираем src/ из sys.path, чтобы не перекрывать
# пакет mcp из site-packages.
script_dir = str(Path(__file__).resolve().parent)
if script_dir in sys.path:
    sys.path.remove(script_dir)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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


def setup_logging():
    """Настраивает логирование и перенаправляет stdout в stderr.
    Возвращает (original_stdout, logger).
    """
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
        setup_project_logging(ext_root)
    except Exception:
        pass  # Файловое логирование опционально

    return original_stdout


def main():
    """Главная функция запуска."""
    original_stdout = setup_logging()
    logger = logging.getLogger("MSCodebase")

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
