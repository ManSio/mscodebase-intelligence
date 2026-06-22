"""
Установщик расширения MSCodebase Intelligence для Zed IDE.
Делает всё:
  1. Создаёт venv (если нет)
  2. Ставит зависимости
  3. Скачивает ONNX-модель
  4. Прописывает MCP-сервер в глобальные настройки Zed
  5. Создаёт uninstall.bat
  6. Копирует файлы в папку расширений Zed (чтобы расширение жило независимо)
"""

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
UNINSTALLER = ZED_EXT_DIR / "uninstall.bat"


def step(n, total, label):
    print(f"\n[{n}/{total}] {label}")


def run(cmd, cwd=None):
    """Запускает команду и возвращает True при успехе."""
    result = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, shell=True)
    return result.returncode == 0


def main():
    total_steps = 7

    # ─── 1. Копирование в директорию расширений ───
    step(1, total_steps, "Копирование файлов в директорию расширений Zed...")

    ZED_EXT_DIR.mkdir(parents=True, exist_ok=True)

    excludes = {
        ".git",
        "__pycache__",
        "venv",
        ".venv",
        ".codebase_models",
        ".codebase_indices",
        "node_modules",
        "nul",  # зарезервированное имя Windows-устройства
    }

    for item in PROJECT_ROOT.iterdir():
        name = item.name
        if (
            name in excludes
            or name.startswith(".")
            and name not in (".env", ".gitignore")
        ):
            continue
        dst = ZED_EXT_DIR / name
        if item.is_dir():
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(
                item, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
        else:
            try:
                shutil.copy2(item, dst)
            except OSError as e:
                print(f"   ⚠️ Пропущен {name}: {e}")
                continue

    # Удаляем `nul` если он затесался (зарезервированное имя Windows)
    nul_file = ZED_EXT_DIR / "nul"
    if nul_file.exists():
        try:
            nul_file.unlink()
        except OSError:
            subprocess.run(
                ["C:\\Program Files\\Git\\bin\\bash.exe", "-c", f"rm -f '{nul_file}'"],
                capture_output=True,
            )

    print("   ✅ Файлы скопированы")

    # ─── 2. Виртуальное окружение ───
    step(2, total_steps, "Настройка виртуального окружения...")

    python_exe = VENV_DIR / "Scripts" / "python.exe"
    if not VENV_DIR.exists():
        if not run(f'python -m venv "{VENV_DIR}"'):
            print("   ❌ Не удалось создать venv")
            return False
        print("   ✅ Виртуальное окружение создано")
    else:
        print("   ✅ Виртуальное окружение уже существует")

    # ─── 3. Очистка .pyc кэша перед установкой ───
    step(3, total_steps, "Очистка Python кэша...")
    for pycache_dir in ZED_EXT_DIR.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache_dir, ignore_errors=True)
        except Exception:
            pass
    for pyc_file in ZED_EXT_DIR.rglob("*.pyc"):
        try:
            pyc_file.unlink()
        except Exception:
            pass
    print("   ✅ Кэш очищен")

    # ─── 4. Установка зависимостей ───
    step(4, total_steps, "Установка зависимостей (это может занять время)...")

    pip = f'"{python_exe}" -m pip'
    run(f"{pip} install --upgrade pip -q", cwd=ZED_EXT_DIR)
    if not run(f"{pip} install -r requirements.txt", cwd=ZED_EXT_DIR):
        print("   ❌ Ошибка установки зависимостей")
        return False
    print("   ✅ Зависимости установлены")

    # ─── 4.1 Копирование chromadb_rust_bindings.pyd ───
    step(4.1, total_steps, "Копирование chromadb_rust_bindings.pyd в venv...")
    import chromadb_rust_bindings as _crb

    crb_dir = Path(_crb.__file__).resolve().parent
    crb_pyd = crb_dir / "chromadb_rust_bindings.pyd"
    if crb_pyd.exists():
        venv_crb_dir = VENV_DIR / "Lib" / "site-packages" / "chromadb_rust_bindings"
        venv_crb_dir.mkdir(parents=True, exist_ok=True)
        dst_pyd = venv_crb_dir / "chromadb_rust_bindings.pyd"
        shutil.copy2(str(crb_pyd), str(dst_pyd))
        print(f"   ✅ .pyd скопирован в {dst_pyd}")
    else:
        print("   ⚠️ chromadb_rust_bindings.pyd не найден в системе")

    # ─── 5. Проверка модели ───
    step(5, total_steps, "Проверка AI-модели...")

    # Проверяем, есть ли уже ONNX-модель
    onnx_path = ZED_EXT_DIR / ".codebase_models" / "onnx" / "model.onnx"
    lm_studio_available = False
    if not onnx_path.exists():
        # Проверяем, запущен ли LM Studio
        try:
            import httpx

            r = httpx.get("http://localhost:1234/v1/models", timeout=2.0)
            if r.status_code == 200:
                models = r.json().get("data", [])
                if models:
                    lm_studio_available = True
                    model_id = models[0]["id"]
                    print(
                        f"   🌐 Обнаружен LM Studio: модель {model_id}. Пропускаем скачивание ONNX."
                    )
        except Exception:
            pass

    if not lm_studio_available and not onnx_path.exists():
        print("   📥 Скачивание AI-модели (это может занять время)...")
        if not run(f'"{python_exe}" -m download_model', cwd=ZED_EXT_DIR):
            print("   ⚠️ Не удалось скачать модель автоматически")
            print(
                "     Запустите позже: cd /d",
                ZED_EXT_DIR,
                "&& venv\\Scripts\\python -m download_model",
            )
        else:
            print("   ✅ Модель скачана")
    elif onnx_path.exists():
        print("   ✅ ONNX-модель уже скачана. Пропускаем.")

    # ─── 6. Настройка Zed + uninstaller ───
    step(6, total_steps, "Настройка Zed IDE и создание деинсталлятора...")

    # Прописываем MCP-сервер
    if not run(f'"{python_exe}" -u -m src.main --install-global', cwd=ZED_EXT_DIR):
        print("   ⚠️ Не удалось настроить Zed автоматически")
    else:
        print("   ✅ MCP-сервер добавлен в настройки Zed")

    # Создаём деинсталлятор
    create_uninstaller()

    print("\n" + "=" * 50)
    print(" ✅ Установка завершена успешно!")
    print()
    print(" Расширение установлено в:")
    print(f"   {ZED_EXT_DIR}")
    print()
    print(" Следующие шаги:")
    print("   1. Перезапустите Zed IDE.")
    print("   2. Откройте любой проект.")
    print('   3. Откройте Agent Panel (Ctrl+Shift+P -> "Agent Panel: Toggle").')
    print('   4. Спросите: "Найди файлы, отвечающие за роутинг"')
    print()
    print(f" Для удаления запустите: {UNINSTALLER}")
    print("=" * 50)

    return True


def create_uninstaller():
    """Создаёт uninstall.bat в папке расширения."""
    uninstall_content = f'''@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

title MSCodebase Intelligence — Удаление расширения

echo ==================================================
echo  MSCodebase Intelligence — Удаление
echo ==================================================
echo.

:: 1. Удаляем MCP-сервер из настроек Zed
echo [1/3] Удаление MCP-сервера из настроек Zed...
"{ZED_EXT_DIR}\\venv\\Scripts\\python" -u -c "
import json, os, sys
from pathlib import Path

appdata = os.environ.get('APPDATA', '')
if appdata:
    settings_path = Path(appdata) / 'Zed' / 'settings.json'
else:
    settings_path = Path.home() / 'AppData' / 'Roaming' / 'Zed' / 'settings.json'

if settings_path.exists():
    try:
        content = settings_path.read_text(encoding='utf-8')
        import re
        clean = re.sub(r'//.*', '', content)
        settings = json.loads(clean)
        if 'context_servers' in settings and 'mscodebase-intelligence' in settings['context_servers']:
            del settings['context_servers']['mscodebase-intelligence']
            if not settings['context_servers']:
                del settings['context_servers']
            settings_path.write_text(json.dumps(settings, indent=4, ensure_ascii=False), encoding='utf-8')
            print('MCP-сервер удалён из настроек Zed')
        else:
            print('MCP-сервер не найден в настройках')
    except Exception as e:
        print(f'Ошибка: {{e}}')
else:
    print('Файл настроек Zed не найден')
"

:: 2. Удаляем файлы
echo [2/3] Удаление файлов расширения...
rd /s /q "{ZED_EXT_DIR}" 2>nul

:: 3. Очистка
echo [3/3] Очистка завершена.

echo.
echo ==================================================
echo  ✅ Расширение MSCodebase Intelligence удалено.
echo  Перезапустите Zed IDE для полной очистки.
echo ==================================================
echo.
pause
'''
    UNINSTALLER.write_text(uninstall_content, encoding="utf-8")
    print(f"   ✅ Деинсталлятор создан: {UNINSTALLER}")


if __name__ == "__main__":
    success = main()
    if not success:
        print("\n❌ Установка прервана из-за ошибки.")
        sys.exit(1)
