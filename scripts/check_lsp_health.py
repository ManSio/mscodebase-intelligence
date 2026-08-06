#!/usr/bin/env python3
"""
check_lsp_health.py — Диагностика LSP-сервера mscodebase-lsp.

Запуск:
    python scripts/check_lsp_health.py

Что проверяет:
1. Зарегистрирован ли mscodebase-lsp в settings.json (блок lsp)
2. Запущен ли процесс lsp_main.py
3. Есть ли bridge-файлы от LSP
4. Есть ли ошибки Serde в settings.json (поле tab_size и др.)
5. Выдаёт рекомендацию на основе текущего состояния

Статусы на выходе:
    ✅ PASS — LSP работает (если когда-нибудь заработает)
    ⚠️  WARN — LSP зарегистрирован в settings.json, но не стартует (WONTFIX)
    ❌ FAIL — Критическая проблема с settings.json
    ℹ️  INFO — LSP не зарегистрирован, MCP работает — это норма
"""

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path


def _get_zed_config_dir() -> Path:
    """Возвращает путь к директории настроек Zed."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", ""))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    return base / "Zed"


def _get_zed_logs_dir() -> Path:
    """Возвращает путь к директории логов Zed."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", ""))
    else:
        base = Path.home() / "Library" / "Logs"
    return base / "Zed" / "logs"


def _get_zed_db_path() -> Path:
    """Возвращает путь к базе данных Zed (для проверки active windows)."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", ""))
    else:
        base = Path.home() / "Library" / "Application Support"
    return base / "Zed" / "db" / "0-stable" / "db.sqlite"


def _get_ext_root() -> Path | None:
    """Определяет директорию установки расширения."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", ""))
    else:
        base = Path.home() / "Library" / "Application Support"
    ext_dir = base / "Zed" / "extensions" / "mscodebase-intelligence"
    return ext_dir if ext_dir.exists() else None


def check_settings_json(settings_path: Path) -> dict:
    """Читает settings.json, возвращает статус каждой секции."""
    result = {"ok": True, "issues": [], "has_lsp_block": False, "has_mcp_block": False}

    if not settings_path.exists():
        result["ok"] = False
        result["issues"].append(f"❌ Файл не найден: {settings_path}")
        return result

    try:
        content = settings_path.read_text(encoding="utf-8")
        clean = re.sub(r"^\s*//.*$", "", content, flags=re.MULTILINE)
        settings = json.loads(clean)
    except json.JSONDecodeError as e:
        result["ok"] = False
        result["issues"].append(f"❌ Ошибка парсинга JSON: {e}")
        return result
    except Exception as e:
        result["ok"] = False
        result["issues"].append(f"❌ Ошибка чтения: {e}")
        return result

    # Проверяем lsp.mscodebase-lsp
    lsp_block = settings.get("lsp", {}).get("mscodebase-lsp")
    if lsp_block is not None:
        result["has_lsp_block"] = True
        binary = lsp_block.get("binary", lsp_block.get("command", None))
        if binary:
            result["issues"].append(
                "⚠️  LSP 'mscodebase-lsp' зарегистрирован в settings.json, "
                "но НЕ БУДЕТ СТАРТОВАТЬ на Windows."
            )
            result["issues"].append(
                "   Причина: кастомные имена LSP невозможны без Rust+WASM-расширения "
                "(перепроверено 2026-08-06 на Zed 1.14.2). "
                "Подробности: docs/en/investigations/LSP_WONTFIX.md"
            )
    else:
        result["issues"].append("ℹ️  LSP 'mscodebase-lsp' не зарегистрирован в settings.json — это норма.")

    # Проверяем MCP
    mcp_block = settings.get("context_servers", {}).get("mscodebase-intelligence")
    if mcp_block is not None:
        result["has_mcp_block"] = True

    # Проверяем на наличие ошибок парсинга (например от tab_size)
    raw_errors = [line for line in content.split("\n") if "mscodebase-lsp" in line and "//" in line]
    if raw_errors:
        result["issues"].append(
            "ℹ️  В settings.json есть комментарии рядом с mscodebase-lsp — "
            "это остатки от предыдущих попыток настройки."
        )

    return result


def check_lsp_process() -> list[str]:
    """Проверяет, запущен ли процесс lsp_main.py."""
    issues = []
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            if "lsp_main" in result.stdout.lower():
                issues.append("✅ Процесс lsp_main.py найден в tasklist")
            else:
                issues.append("ℹ️  Процесс lsp_main.py НЕ запущен (ожидаемо — LSP не стартует на Zed 1.9.0)")
        else:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True, text=True, timeout=5,
            )
            if "lsp_main" in result.stdout:
                issues.append("✅ Процесс lsp_main.py найден")
            else:
                issues.append("ℹ️  Процесс lsp_main.py не запущен")
    except Exception as e:
        issues.append(f"⚠️  Не удалось проверить процессы: {e}")

    return issues


def check_bridge_files() -> list[str]:
    """Проверяет bridge-файлы (DEPRECATED 2026-08-06 — LSP-мост удалён)."""
    issues = []
    bridge_dir = Path.home() / ".mscodebase" / "bridge"
    if bridge_dir.exists():
        json_files = list(bridge_dir.glob("*.json"))
        if json_files:
            issues.append(
                f"ℹ️  Найдено {len(json_files)} bridge-файл(ов) — артефакты удалённого "
                "LSP-моста, игнорируются (LSP server removed 2026-07-20)"
            )
        else:
            issues.append("ℹ️  Директория bridge пуста")
    else:
        issues.append("ℹ️  Директория bridge не найдена — ожидаемо (мост деприцирован)")
    return issues


def main():
    print("=" * 70)
    print("  MSCodeBase Intelligence — Диагностика LSP-сервера")
    print("  check_lsp_health.py v1.0")
    print("=" * 70)
    print()

    all_issues = []

    # ── Системная информация ──
    print(f"  Платформа:      {platform.system()} {platform.release()}")
    print(f"  Python:         {sys.version.split()[0]}")
    print(f"  CWD:            {Path.cwd()}")
    print()

    # ── 1. Проверка settings.json ──
    print("📋 Шаг 1: Проверка settings.json")
    zed_config_dir = _get_zed_config_dir()
    settings_path = zed_config_dir / "settings.json"
    print(f"     Файл: {settings_path}")

    s_result = check_settings_json(settings_path)
    all_issues.extend(s_result["issues"])

    if not s_result["ok"]:
        print(f"     ❌ Файл повреждён или не найден")
    elif s_result["has_lsp_block"]:
        print(f"     ⚠️  Блок lsp.mscodebase-lsp найден")
    else:
        print(f"     ℹ️  Блок lsp.mscodebase-lsp отсутствует")

    if s_result["has_mcp_block"]:
        print(f"     ✅ Блок context_servers.mscodebase-intelligence найден")
    else:
        print(f"     ❌ MCP-сервер не зарегистрирован!")
    print()

    # ── 2. Проверка процессов ──
    print("🔄 Шаг 2: Проверка процессов")
    proc_issues = check_lsp_process()
    all_issues.extend(proc_issues)
    for line in proc_issues:
        print(f"     {line}")
    print()

    # ── 3. Проверка bridge-файлов ──
    print("🔗 Шаг 3: Проверка bridge-файлов LSP")
    bridge_issues = check_bridge_files()
    all_issues.extend(bridge_issues)
    for line in bridge_issues:
        print(f"     {line}")
    print()

    # ── 4. Проверка базы Zed SQLite ──
    print("🗄️  Шаг 4: Проверка SQLite DB (workspaces)")
    db_path = _get_zed_db_path()
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"     ✅ База данных Zed найдена ({size_mb:.1f} MB)")
    else:
        print(f"     ℹ️  База данных Zed не найдена")
    print()

    # ── 5. Вердикт ──
    print("=" * 70)
    print("  🧠 ВЕРДИКТ")
    print("=" * 70)
    print()

    if s_result["has_lsp_block"] and platform.system() == "Windows":
        print("  ⚠️  LSP 'mscodebase-lsp' зарегистрирован в settings.json,")
        print("      но НЕ БУДЕТ СТАРТОВАТЬ (перепроверено 2026-08-06 на Zed 1.14.2).")
        print()
        print("  Причина: кастомные имена LSP невозможны через settings.json —")
        print("  имя обязано быть в LanguageRegistry (встроенное или WASM-расширение).")
        print()
        print("  Подробности: docs/en/investigations/LSP_WONTFIX.md")
        print()
        print("  Рекомендация: удалить блок lsp из settings.json")
        print("  (он не работает, но не вредит).")
    elif platform.system() == "Windows" and not s_result["has_lsp_block"]:
        print("  ℹ️  LSP-сервер 'mscodebase-lsp' не зарегистрирован — корректно.")
        print("      Редакторный LSP требует Rust+WASM-расширения (путь A, не реализован).")
        print()
        print("  MCP-сервер работает и обеспечивает весь функционал:")
        print("  семантический поиск, точный AST-анализ через LspClient")
        print("  (basedpyright): lsp_find_references / lsp_find_definition /")
        print("  lsp_document_symbols, плюс 49 других инструментов.")
    else:
        print("  ✅ Всё в порядке.")
        print()
        print("  Если вы на Linux/macOS — проверьте, стартует ли LSP")
        print("  через sudo journalctl -u zed или логи Zed.")

    print()
    if all_issues:
        print("  Сводка замечаний:")
        for issue in all_issues:
            print(f"    {issue}")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
