"""Быстрая синхронизация src/ из dev-репо в install-папку Zed.

Использование:
  python scripts/sync_src.py [--full]

Копирует только src/, tests/, scripts/, pyproject.toml, requirements.txt.
venv, .git, .codebase_indices, AGENT_DIARY.md — НЕ трогает.

После sync нужно перезапустить Zed (или хотя бы перезапустить MCP-процесс).
"""
import argparse
import shutil
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent  # D:\Project\MSCodeBase
TARGET = Path(r"C:\Users\misha\AppData\Local\Zed\extensions\mscodebase-intelligence")

# Что копировать (относительно SOURCE)
COPY_DIRS = ["src", "tests", "scripts", "docs"]
COPY_FILES = [
    "pyproject.toml",
    "requirements.txt",
    "MANIFEST.in",
    "AGENTS.md",
    "AGENT_DIARY.md",  # на случай если в install пусто
    "CHANGELOG.md",
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "QUICKSTART.md",
    "fix_zed_settings.bat",
    "sync_to_installed.bat",
    "install.bat",
    ".zed.settings.json.example",
    "install.py",
]

# Что НЕ копировать (даже если попало в COPY_DIRS)
IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", "*.pyd",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".codebase_indices",  # индекс не копируем
    ".env",  # секреты
    "node_modules",
)


def sync_dir(rel: str) -> int:
    src = SOURCE / rel
    dst = TARGET / rel
    if not src.exists():
        print(f"  [skip] {rel} — not in source")
        return 0
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=IGNORE)
    n = sum(1 for _ in dst.rglob("*") if _.is_file())
    print(f"  [ok]   {rel}/ -> {dst}  ({n} files)")
    return n


def sync_file(rel: str) -> int:
    src = SOURCE / rel
    dst = TARGET / rel
    if not src.exists():
        print(f"  [skip] {rel} — not in source")
        return 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  [ok]   {rel} -> {dst}")
    return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Полная синхронизация (по умолчанию — только src/)")
    args = parser.parse_args()

    if not TARGET.exists():
        print(f"[ERROR] Install dir not found: {TARGET}")
        print(f"        Сначала запустите install.bat")
        sys.exit(1)

    print(f"Source: {SOURCE}")
    print(f"Target: {TARGET}")
    print(f"Mode:   {'FULL' if args.full else 'src/ only'}")
    print()

    total = 0
    for d in COPY_DIRS:
        total += sync_dir(d)
    for f in COPY_FILES:
        total += sync_file(f)

    print()
    print(f"=== Synced {total} files ===")
    print()
    print("Next steps:")
    print("  1. Закройте Zed (все окна)")
    print("  2. Откройте Zed снова — MCP/LSP подхватят новый код")
    print("  3. Или убейте python.exe и подождите пока Zed перезапустит")


if __name__ == "__main__":
    main()
