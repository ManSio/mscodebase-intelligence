"""
Скрипт для сборки дистрибутива MSCodebase Intelligence через PyInstaller.
"""

import shutil
import subprocess
import sys
from pathlib import Path


def build():
    """Собирает standalone исполняемый файл."""
    print("=" * 60)
    print("Сборка MSCodebase Intelligence (Standalone)")
    print("=" * 60)

    # 1. Проверка PyInstaller
    try:
        import PyInstaller  # type: ignore[import-not-found,unused-import]
    except ImportError:
        print("Устанавливаю PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. Очистка старых данных
    dist_dir = Path("dist")
    build_dir = Path("build")
    spec_file = Path("MSCodebase-mcp.spec")

    for folder in [dist_dir, build_dir]:
        if folder.exists():
            shutil.rmtree(folder)
    if spec_file.exists():
        spec_file.unlink()

    # 3. Настройка параметров
    exe_name = "MSCodebase-mcp"
    if sys.platform == "win32":
        exe_name += ".exe"

    # Используем --collect-all для сложных библиотек (ChromaDB, Transformers, Tree-sitter)
    # Это гарантирует, что все вспомогательные данные (json, bin, dll) попадут в билд
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        exe_name.replace(".exe", ""),
        "--clean",
        "--noconfirm",
        # Сборка зависимостей данных
        "--collect-all",
        "chromadb",
        "--collect-all",
        "transformers",
        "--collect-all",
        "tree_sitter",
        "--collect-all",
        "huggingface_hub",
        # Явное включение скрытых импортов
        "--hidden-import",
        "onnxruntime",
        "--hidden-import",
        "rank_bm25",
        "--hidden-import",
        "dotenv",
        "src/main.py",
    ]

    print("\nЗапуск процесса сборки...")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Ошибка во время сборки: {e}")
        sys.exit(1)

    # 4. Финишная проверка
    output_path = Path("dist") / exe_name
    if output_path.exists():
        size_mb = output_path.stat().st_size / 1024 / 1024
        print("\n" + "=" * 60)
        print("✅ Сборка завершена успешно!")
        print(f"📦 Исполняемый файл: {output_path.absolute()}")
        print(f"📏 Размер файла: {size_mb:.1f} МБ")
        print("=" * 60)
    else:
        print("\n❌ Ошибка: Исполняемый файл не найден после сборки.")
        sys.exit(1)


if __name__ == "__main__":
    build()
