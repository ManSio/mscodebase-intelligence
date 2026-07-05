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


def patch_zed_settings(
    command: str | None = None,
    mode: str = "global",
    lsp_config: dict | None = None,
    languages_config: dict | None = None,
    install_path: str | None = None,
    project_path: str | None = None,
) -> bool:
    """
    Добавляет/обновляет MCP-сервер (и опционально LSP) в настройках Zed.

    Единая точка записи настроек — без double-write.

    Args:
        command: Полная команда для запуска MCP-сервера.
                 Если None — формируется автоматически по пути установки.
                 Если передан — PYTHONPATH и ext_dir определяются по команде.
                 Формат команды: "{ext_dir}/venv/Scripts/python.exe -u -m src.main"
        mode: 'global' — в глобальные настройки Zed (для всех проектов).
              'project' — в .zed/settings.json текущего проекта.
        lsp_config: Опциональная конфигурация LSP-сервера ({"command": ..., "arguments": ...}).
                    Если передана — добавляется в settings["lsp"]["mscodebase-lsp"].
        languages_config: Опциональная конфигурация language servers для языков.
                          Если передана — добавляется settings["languages"].
                          Формат: {"Python": ["mscodebase-lsp"], "TypeScript": ["mscodebase-lsp"]}
        install_path: Абсолютный путь к установленному расширению.
                      Если передан — используется для PYTHONPATH вместо автоопределения.
                      Нужен когда patch_zed_settings() вызывается из install.py,
                      где раширение копируется в %LOCALAPPDATA%/Zed/extensions/

    Returns:
        True, если настройки успешно обновлены
    """
    # Если команда не указана — формируем автоматически
    if command is None:
        python_exe = get_python_path()
        ext_dir = get_extension_install_dir()
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

    # ── Определяем ext_dir для PYTHONPATH ──
    # Приоритет:
    #   1. Явно переданный install_path (из install.py)
    #   2. Извлечение из пути executable (если он внутри .../venv/Scripts/python.exe)
    #   3. Автоопределение через get_extension_install_dir() (для разработки)
    ext_dir = None
    if install_path:
        ext_dir = Path(install_path).resolve()
        logger.debug(f"patch_zed_settings: ext_dir из install_path={ext_dir}")
    else:
        exe_path = Path(executable).resolve()
        # Проверяем структуру: {ext_dir}/venv/Scripts/python.exe
        if exe_path.parent.parent.parent.name == "venv":
            ext_dir = exe_path.parent.parent.parent.parent
            logger.debug(f"patch_zed_settings: ext_dir из пути executable={ext_dir}")
        else:
            ext_dir = get_extension_install_dir()
            logger.debug(f"patch_zed_settings: ext_dir авто={ext_dir}")

    # ══════════════════════════════════════════════════════════════
    # ВАЖНО: current_dir НЕ устанавливаем.
    # Zed НЕ подставляет $ZED_WORKTREE_ROOT в current_dir (баг Zed #36019).
    # Вместо этого MCP-сервер определяет project_root самостоятельно
    # по приоритету: PROJECT_PATH env → LSP→MCP bridge → CWD → ext_root.
    # см. src/mcp/server.py:resolve_project_root()
    # ══════════════════════════════════════════════════════════════
    entry = {
        "command": executable,
        "args": args,
    }

    # PYTHONPATH указывает на корень расширения, чтобы import src.* работал.
    # PROJECT_PATH = $ZED_WORKTREE_ROOT — Zed подставляет в env
    # (current_dir не подставляется, см. выше).
    # Многоуровневое определение project_root в resolve_project_root()
    # гарантирует работу даже при нештатной подстановке.
    env = {
        "PYTHONPATH": str(ext_dir),
        "PROJECT_PATH": "$ZED_WORKTREE_ROOT",
        # Dev-mode override: разрешает индексировать ext_root / Zed install,
        # если пользователь открыл исходники расширения как проект.
        # Без этого переменная фикс dev-сценария не сработает в Zed-сессии.
        "MSCODEBASE_ALLOW_SELF_INDEX": "1",
    }
    entry["env"] = env

    settings["context_servers"][SERVER_NAME] = entry

    # Добавляем наш сервер в auto-query список, чтобы Zed сам вызывал инструменты
    # без явной команды (как @codebase в Cursor)
    if "context_servers_to_query" not in settings:
        settings["context_servers_to_query"] = []
    if SERVER_NAME not in settings["context_servers_to_query"]:
        settings["context_servers_to_query"].append(SERVER_NAME)

    # ──────────────────────────────────────────────────
    # LSP + Languages (опционально, single-pass)
    # ──────────────────────────────────────────────────
    if lsp_config is not None:
        if "lsp" not in settings:
            settings["lsp"] = {}
        if "mscodebase-lsp" not in settings["lsp"]:
            # Добавляем env в LSP конфиг (PYTHONPATH + PROJECT_PATH)
            lsp_config["env"] = env.copy()
            settings["lsp"]["mscodebase-lsp"] = lsp_config
            logger.info(f"✅ LSP-сервер 'mscodebase-lsp' добавлен")

    if languages_config is not None:
        if "languages" not in settings:
            settings["languages"] = {}
        for lang, servers in languages_config.items():
            if lang not in settings["languages"]:
                settings["languages"][lang] = {}
            if "language_servers" not in settings["languages"][lang]:
                settings["languages"][lang]["language_servers"] = []
            for srv in servers:
                if srv not in settings["languages"][lang]["language_servers"]:
                    settings["languages"][lang]["language_servers"].append(srv)
        logger.info(f"✅ LSP-привязки к языкам добавлены")

    # ──────────────────────────────────────────────────
    # Инжект системных правил для AI-ассистента Zed
    # ──────────────────────────────────────────────────
    custom_instructions = (
        "MSCodeBase Core Rules: "
        "[MEMORY] 1. Start: intel_get_project_memory. 2. After task: intel_log_incident. "
        "[SEARCH] search_code(mode=auto|fast|quality|deep|context). Deprecated: smart/deep/context_search. "
        "[STATE] IF chunks==0 → grep, ELSE → search_code/get_symbol_info. "
        "[READ] Max 50 lines per read_file. NEVER ingest entire files. "
        "[WRITE] Read target lines before edit. Preserve indentation. "
        "[SYNC] Edit → notify_change(src\\path). Paths relative to PROJECT_ROOT. "
        "[PATHS] src\\core\\file.py for MCP, src/core/file.py for Terminal. "
        "[ERROR] No retry same tool. Pivot. "
        "[FORBID] Docker, WSL, pytz, stubs, TODOs, mocks. "
        "[SELF] Before output: verify index sync, correct paths, no stubs."
    )

    if "agent" not in settings:
        settings["agent"] = {}

    current_prompt = settings["agent"].get("system_prompt", "")
    if custom_instructions not in current_prompt:
        settings["agent"]["system_prompt"] = (
            f"{custom_instructions}\n{current_prompt}"
        ).strip()

    # Автоматически разрешаем ВСЕ инструменты MCP (чтобы не перечислять 42 штуки вручную)
    if "tool_permissions" not in settings["agent"]:
        settings["agent"]["tool_permissions"] = {}
    settings["agent"]["tool_permissions"]["default"] = "allow"
    # Если есть старый список tools — удаляем (он избыточен при default=allow)
    if "tools" in settings["agent"]["tool_permissions"]:
        logger.info("🧹 Удаляю старый список tool_permissions.tools (избыточен при default=allow)")
        del settings["agent"]["tool_permissions"]["tools"]

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
