"""
Автоматическая настройка Zed IDE.
Поддерживает Windows, macOS, Linux.

При установке в директорию расширений Zed:
  Windows: %%USERPROFILE%%/.config/zed/extensions/installed/mscodebase-intelligence
  macOS:   ~/.config/zed/extensions/installed/mscodebase-intelligence
  Linux:   ~/.config/zed/extensions/installed/mscodebase-intelligence
"""

import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Имя сервера в настройках Zed (единое для всех платформ)
SERVER_NAME = "mscodebase-intelligence"


def get_zed_config_dir() -> Path:
    """
    Находит папку настроек Zed.
    Учитывает:
    - Переменную окружения ZED_CONFIG_DIR (если задана)
    - Стандартные пути для каждой ОС
    """
    # 1. Кастомная переменная окружения (приоритет)
    custom_dir = os.environ.get("ZED_CONFIG_DIR")
    if custom_dir:
        path = Path(custom_dir)
        if path.exists():
            return path
        logger.warning(f"ZED_CONFIG_DIR указан, но папка не существует: {path}")

    # 2. Стандартные пути ОС
    if sys.platform == "win32":
        # Windows: %APPDATA%\Zed
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Zed"
        return Path.home() / "AppData" / "Roaming" / "Zed"

    elif sys.platform == "darwin":
        # macOS: ~/Library/Application Support/Zed
        return Path.home() / "Library" / "Application Support" / "Zed"

    else:
        # Linux: $XDG_CONFIG_HOME/zed или ~/.config/zed
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            return Path(xdg) / "zed"
        return Path.home() / ".config" / "zed"


def get_extension_install_dir() -> Path:
    """
    Возвращает путь к директории, куда установлено расширение.
    Определяется автоматически по расположению этого файла.
    """
    # Этот файл лежит в src/utils/zed_config.py
    # Расширение установлено на два уровня выше
    return Path(__file__).resolve().parent.parent.parent


def get_python_path() -> str:
    """
    Возвращает абсолютный путь к python.exe из venv расширения.
    """
    ext_dir = get_extension_install_dir()
    if sys.platform == "win32":
        python_exe = ext_dir / "venv" / "Scripts" / "python.exe"
    else:
        python_exe = ext_dir / "venv" / "bin" / "python3"

    if python_exe.exists():
        return str(python_exe)

    # Fallback: системный python
    return sys.executable


def patch_zed_settings(command: str | None = None, mode: str = "global") -> bool:
    """
    Добавляет/обновляет MCP-сервер в настройках Zed.

    Args:
        command: Полная команда для запуска MCP-сервера.
                 Если None — формируется автоматически по пути установки.
                 Если команда уже существует в настройках, она сохраняется.
        mode: 'global' — в глобальные настройки Zed (для всех проектов).
              'project' — в .zed/settings.json текущего проекта.

    Returns:
        True, если настройки успешно обновлены
    """
    # Если команда не указана — формируем автоматически
    if command is None:
        python_exe = get_python_path()
        ext_dir = get_extension_install_dir()
        # Используем -m src.main с PYTHONPATH, чтобы Python всегда находил src/
        # независимо от того, из какой папки Zed запускает процесс
        command = f"{python_exe} -u -m src.main"

    if mode == "project":
        zed_dir = Path.cwd() / ".zed"
        zed_dir.mkdir(exist_ok=True)
        settings_path = zed_dir / "settings.json"
        logger.info(f"Настраиваю проект: {settings_path}")
    else:
        config_dir = get_zed_config_dir()
        if not config_dir.exists():
            logger.error(f"Папка настроек Zed не найдена: {config_dir}")
            logger.info("Запустите Zed хотя бы раз, чтобы создать настройки.")

            # Пытаемся создать директорию (Zed сам её создаёт, но на всякий случай)
            try:
                config_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Создана папка настроек Zed: {config_dir}")
            except Exception as e:
                logger.error(f"Не удалось создать папку настроек: {e}")
                return False

        settings_path = config_dir / "settings.json"
        logger.info(f"Настраиваю глобально: {settings_path}")

    # Читаем существующие настройки
    settings = {}
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Удаляем однострочные комментарии // ... (Zed settings format)
            if "//" in content:
                clean_content = re.sub(r"^\s*//.*$", "", content, flags=re.MULTILINE)
            else:
                clean_content = content
            settings = json.loads(clean_content)
        except json.JSONDecodeError as e:
            logger.error(f"Файл настроек повреждён: {settings_path}")
            logger.error(f"Ошибка JSON: {e}")
            # Создаём бэкап повреждённого файла
            backup = settings_path.with_suffix(".json.broken")
            try:
                shutil.copy2(settings_path, backup)
                logger.info(f"Повреждённый файл сохранён как: {backup}")
            except Exception:
                pass
            settings = {}
        except Exception as e:
            logger.error(f"Ошибка чтения настроек: {e}")
            return False

    # Делаем бэкап перед изменением (только первый раз)
    backup_path = settings_path.with_suffix(".json.backup")
    if not backup_path.exists() and settings_path.exists():
        try:
            shutil.copy2(settings_path, backup_path)
            logger.info(f"Бэкап создан: {backup_path}")
        except Exception as e:
            logger.warning(f"Не удалось создать бэкап: {e}")

    # Добавляем или обновляем context_servers
    if "context_servers" not in settings:
        settings["context_servers"] = {}

    # Определяем формат команды
    # На Windows shlex.split ломает backslashes, парсим вручную
    # Разбиваем по пробелам, первый элемент — executable, остальное — args
    parts = command.split(maxsplit=1)
    if not parts:
        logger.error("Передана пустая команда.")
        return False

    executable = parts[0]
    args = []
    if len(parts) > 1:
        args = parts[1].split()

    # Сохраняем с нашим именем сервера
    entry = {
        "command": executable,
        "args": args,
        # Требуется Zed для корректного запуска MCP-сервера с контекстом проекта
        "current_dir": "$ZED_WORKTREE_ROOT",
    }

    # Путь проекта для AI-ассистента + PYTHONPATH для импорта src
    entry["env"] = {
        "PROJECT_PATH": "$ZED_WORKTREE_ROOT",
        "PYTHONPATH": "$ZED_WORKTREE_ROOT",
    }

    settings["context_servers"][SERVER_NAME] = entry

    # Добавляем наш сервер в auto-query список, чтобы Zed сам вызывал инструменты
    # без явной команды (как @codebase в Cursor)
    if "context_servers_to_query" not in settings:
        settings["context_servers_to_query"] = []
    if SERVER_NAME not in settings["context_servers_to_query"]:
        settings["context_servers_to_query"].append(SERVER_NAME)

    # ──────────────────────────────────────────────────
    # Инжект системных правил для AI-ассистента Zed
    # ──────────────────────────────────────────────────
    custom_instructions = (
        "MSCodeBase Core Rules: "
        "STATE-AWARENESS: IF get_index_status returns 0 chunks, FORBIDDEN to use search_code, "
        "switch to grep/regex. IF chunks > 0, use search_code for semantic, get_symbol_info for exact names. "
        "RECONNAISSANCE: NEVER guess line numbers. Use get_symbol_info or grep before read_file. "
        "CONTEXT BUDGET: Max 50 lines per read_file call. NEVER ingest entire files. "
        "SAFE WRITING: Read target lines again before edit. Preserve indentation and style. "
        "ERROR HANDLING: Do not retry same tool with same params. Pivot to alternative. "
        "WINDOWS PATHS: Normalize to POSIX lowercase via path.as_posix().lower(). "
        "POST-MODIFICATION: After writing, call index_project_dir + get_index_status. "
        "CONSTRAINTS: NO Docker, NO pytz, NO stubs, NO mocks."
    )

    if "agent" not in settings:
        settings["agent"] = {}

    current_prompt = settings["agent"].get("system_prompt", "")
    if custom_instructions not in current_prompt:
        settings["agent"]["system_prompt"] = (
            f"{custom_instructions}\n{current_prompt}"
        ).strip()

    # Записываем обратно (с сохранением всех существующих настроек)
    try:
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
        logger.info(f"✅ MCP-сервер '{SERVER_NAME}' добавлен в: {settings_path}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении настроек: {e}")
        return False


def remove_zed_settings() -> bool:
    """
    Удаляет MCP-сервер из настроек Zed (глобальных).
    Используется деинсталлятором.

    Returns:
        True, если настройки успешно очищены
    """
    config_dir = get_zed_config_dir()
    settings_path = config_dir / "settings.json"

    if not settings_path.exists():
        logger.info("Файл настроек Zed не найден, пропускаю.")
        return True

    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            content = f.read()
        clean_content = re.sub(r"^\s*//.*$", "", content, flags=re.MULTILINE)
        settings = json.loads(clean_content)
    except Exception as e:
        logger.error(f"Ошибка чтения настроек: {e}")
        return False

    if (
        "context_servers" not in settings
        or SERVER_NAME not in settings["context_servers"]
    ):
        logger.info(f"MCP-сервер '{SERVER_NAME}' не найден в настройках.")
        return True

    del settings["context_servers"][SERVER_NAME]
    if not settings["context_servers"]:
        del settings["context_servers"]

    try:
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
        logger.info(f"✅ MCP-сервер '{SERVER_NAME}' удалён из настроек Zed.")
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении настроек: {e}")
        return False
