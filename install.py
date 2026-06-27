"""
MSCodebase Intelligence — Продакшен автоматический установщик расширения для Zed IDE (Windows)
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ZED_EXT_DIR = (
    Path(os.environ["LOCALAPPDATA"]) / "Zed" / "extensions" / "mscodebase-intelligence"
)
VENV_DIR = ZED_EXT_DIR / "venv"
PYTHON_EXE = VENV_DIR / "Scripts" / "python.exe"
UNINSTALLER = ZED_EXT_DIR / "uninstall.bat"


def run_cmd(cmd: str, cwd: Path = PROJECT_ROOT) -> bool:
    res = subprocess.run(cmd, cwd=str(cwd), shell=True)
    return res.returncode == 0


def main():
    print("==================================================")
    print(" MSCodebase Intelligence — Развертывание Системы ")
    print("==================================================")

    # 1. Изоляция файлов расширения
    print("\n[1/5] Изоляция компонентов расширения...")
    ZED_EXT_DIR.mkdir(parents=True, exist_ok=True)

    for item in PROJECT_ROOT.iterdir():
        if item.name in [
            ".git",
            "__pycache__",
            "venv",
            ".venv",
            ".codebase_indices",
            ".codebase_models",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
            ".zed",
            ".idea",
            ".vscode",
        ]:
            continue
        target = ZED_EXT_DIR / item.name
        try:
            if item.is_dir():
                shutil.copytree(str(item), str(target), dirs_exist_ok=True)
                print(f"  └─ Скопирована папка: {item.name}")
            else:
                shutil.copy2(str(item), str(target))
                print(f"  └─ Скопирован файл: {item.name}")
        except Exception as e:
            print(f"  ⚠️ Пропущен элемент {item.name} из-за ошибки: {e}")

    # 2. Создание изолированного Venv
    print("\n[2/5] Создание изолированного Python Virtual Environment...")
    if not VENV_DIR.exists():
        if not run_cmd(f'"{sys.executable}" -m venv "{VENV_DIR}"'):
            print("❌ Не удалось инициализировать venv.")
            return

    # 3. Установка бинарных пакетов Arrow/LanceDB
    print("\n[3/5] Компиляция и установка Rust/C++ зависимостей (LanceDB, PyArrow)...")
    run_cmd(f'"{PYTHON_EXE}" -m pip install --upgrade pip')
    if not run_cmd(
        f'"{PYTHON_EXE}" -m pip install -r requirements.txt', cwd=ZED_EXT_DIR
    ):
        print("❌ Критическая ошибка установки Python-пакетов.")
        return

    # 4. Интеграция MCP + LSP в настройки Zed IDE
    print("\n[4/6] Интеграция MCP-сервера и LSP-сервера в настройки Zed...")
    zed_config_dir = Path(os.environ["USERPROFILE"]) / ".config" / "zed"
    if sys.platform == "win32":
        # Проверка стандартного альтернативного пути Windows для настроек Zed
        alt_path = Path(os.environ["APPDATA"]) / "Zed"
        if alt_path.exists():
            zed_config_dir = alt_path

    settings_json_path = zed_config_dir / "settings.json"
    zed_config_dir.mkdir(parents=True, exist_ok=True)

    settings_data = {}
    if settings_json_path.exists():
        try:
            content = settings_json_path.read_text(encoding="utf-8")
            # Очистка возможных комментариев в JSON комьюнити-формата Zed
            import re

            content_clean = re.sub(r"^\s*//.*$", "", content, flags=re.MULTILINE)
            settings_data = json.loads(content_clean)
        except Exception:
            settings_data = {}

    if "context_servers" not in settings_data:
        settings_data["context_servers"] = {}

    # Задаем абсолютные жесткие пути запуска, чтобы Zed никогда не терял плагин
    main_script_path = ZED_EXT_DIR / "src" / "main.py"
    settings_data["context_servers"]["mscodebase-intelligence"] = {
        "command": str(PYTHON_EXE),
        "args": [str(main_script_path)],
    }

    # Настраиваем LSP-сервер для проактивной индексации
    lsp_script_path = ZED_EXT_DIR / "src" / "lsp_main.py"
    if "lsp" not in settings_data:
        settings_data["lsp"] = {}
    settings_data["lsp"]["mscodebase-lsp"] = {
        "command": str(PYTHON_EXE),
        "arguments": ["-u", str(lsp_script_path)],
    }

    # Добавляем mscodebase-lsp в language_servers для основных языков
    if "languages" not in settings_data:
        settings_data["languages"] = {}
    for lang in ["Python", "TypeScript", "Rust", "Go", "JavaScript"]:
        if lang not in settings_data["languages"]:
            settings_data["languages"][lang] = {}
        lang_config = settings_data["languages"][lang]
        if "language_servers" not in lang_config:
            lang_config["language_servers"] = []
        if "mscodebase-lsp" not in lang_config["language_servers"]:
            lang_config["language_servers"].append("mscodebase-lsp")

    settings_json_path.write_text(
        json.dumps(settings_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  └─ MCP + LSP прописаны в: {settings_json_path}")

    # 5. Генерация автоматического деинсталлятора
    print("\n[5/6] Создание утилиты полной очистки (uninstall.bat)...")
    uninst_content = f"""@echo off
chcp 65001 >nul
echo ==================================================
echo  Удаление плагина MSCodebase Intelligence...
echo ==================================================
echo [1/3] Удаление настроек из Zed IDE...
"{PYTHON_EXE}" -c "
import json, pathlib, os, re
p = pathlib.Path(os.environ['USERPROFILE']) / '.config' / 'zed' / 'settings.json'
if not p.exists(): p = pathlib.Path(os.environ['APPDATA']) / 'Zed' / 'settings.json'
if p.exists():
    content = p.read_text(encoding='utf-8')
    clean = re.sub(r'^\s*//.*$', '', content, flags=re.MULTILINE)
    clean = re.sub(r',\s*}}', '}}', clean)
    clean = re.sub(r',\s*]', ']', clean)
    d = json.loads(clean)
    # Удаляем MCP-сервер
    if 'context_servers' in d and 'mscodebase-intelligence' in d['context_servers']:
        del d['context_servers']['mscodebase-intelligence']
        if not d['context_servers']:
            del d['context_servers']
    # Удаляем LSP-сервер
    if 'lsp' in d and 'mscodebase-lsp' in d['lsp']:
        del d['lsp']['mscodebase-lsp']
        if not d['lsp']:
            del d['lsp']
    # Удаляем mscodebase-lsp из language_servers
    if 'languages' in d:
        for lang in list(d['languages'].keys()):
            lang_cfg = d['languages'][lang]
            if 'language_servers' in lang_cfg and 'mscodebase-lsp' in lang_cfg['language_servers']:
                lang_cfg['language_servers'].remove('mscodebase-lsp')
                if not lang_cfg['language_servers']:
                    del lang_cfg['language_servers']
            if not lang_cfg:
                del d['languages'][lang]
        if not d['languages']:
            del d['languages']
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding='utf-8')
"
echo [2/3] Стирание рабочих директорий и баз данных индексов...
timeout /t 2 >nul
rd /s /q "{ZED_EXT_DIR}"
echo ✅ Удаление полностью завершено! Перезапустите Zed.
pause
"""
    UNINSTALLER.write_text(uninst_content, encoding="utf-8")

    print("\n==================================================")
    print(" 🎉 СИСТЕМА УСПЕШНО УСТАНОВЛЕНА И ГОТОВА К РАБОТЕ!")
    print("==================================================")
    print(" 1. Запустите LM Studio и включите сервер эмбеддингов.")
    print(" 2. Перезапустите Zed IDE.")
    print(" Все процессы очистки и синхронизации теперь полностью автоматизированы.")


if __name__ == "__main__":
    main()
