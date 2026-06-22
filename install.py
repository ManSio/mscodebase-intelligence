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
            ".codebase_indices",
            ".codebase_models",
        ]:
            continue
        target = ZED_EXT_DIR / item.name
        if item.is_dir():
            shutil.copytree(str(item), str(target), dirs_exist_ok=True)
        else:
            shutil.copy2(str(item), str(target))

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

    # 4. Интеграция в экосистему настроек Zed IDE
    print("\n[4/5] Интеграция MCP-сервера в конфигурационный файл настроек Zed...")
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
    main_script_path = ZED_EXT_DIR / "main.py"
    settings_data["context_servers"]["mscodebase-intelligence"] = {
        "command": str(PYTHON_EXE),
        "args": [str(main_script_path)],
    }

    settings_json_path.write_text(
        json.dumps(settings_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  └─ Успешно прописано в: {settings_json_path}")

    # 5. Генерация автоматического деинсталлятора
    print("\n[5/5] Создание утилиты полной очистки (uninstall.bat)...")
    uninst_content = f"""@echo off
chcp 65001 >nul
echo ==================================================
echo  Удаление плагина MSCodebase Intelligence...
echo ==================================================
echo [1/2] Удаление настроек из Zed IDE...
"{PYTHON_EXE}" -c "
import json, pathlib, os
p = pathlib.Path(os.environ['USERPROFILE']) / '.config' / 'zed' / 'settings.json'
if not p.exists(): p = pathlib.Path(os.environ['APPDATA']) / 'Zed' / 'settings.json'
if p.exists():
    d = json.loads(p.read_text(encoding='utf-8'))
    if 'context_servers' in d and 'mscodebase-intelligence' in d['context_servers']:
        del d['context_servers']['mscodebase-intelligence']
        if not d['context_servers']:
            del d['context_servers']
        p.write_text(json.dumps(d, indent=2), encoding='utf-8')
"
echo [2/2] Стирание рабочих директорий и баз данных индексов...
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
