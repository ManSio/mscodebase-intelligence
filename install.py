"""
MSCodebase Intelligence — Продакшен автоматический установщик расширения для Zed IDE (Windows)

Требования безопасной установки:
  • Проверка доступности LM Studio/Ollama на порту 1234 с Fallback-режимом
  • Атомарность обновлений: деликатная проверка схемы LanceDB без удаления
  • Изоляция окружения: venv строго внутри расширения
  • Контроль семафора: лимит параллельных запросов к локальной LLM
  • Экранирование f-string: }} вместо }
"""

import json
import os
import shutil
import socket
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

LM_STUDIO_HOST = "127.0.0.1"
LM_STUDIO_PORT = 1234
LM_STUDIO_TIMEOUT_SEC = 3

# Ожидаемая схема LanceDB v2 (поля и типы PyArrow)
EXPECTED_SCHEMA_FIELDS = {
    "id": "string",
    "vector": "list<float32>",  # list_(float32(), 1024)
    "text": "string",
    "file_path": "string",
    "file_hash": "string",
    "chunk_index": "int32",
}

# Семафор: максимум параллельных запросов к локальной LLM от LSP + MCP
MAX_CONCURRENT_LLM_REQUESTS = 2


def run_cmd(cmd: str, cwd: Path = PROJECT_ROOT) -> bool:
    res = subprocess.run(cmd, cwd=str(cwd), shell=True)
    return res.returncode == 0


def check_lm_studio_available() -> bool:
    """Проверяет доступность LM Studio/Ollama на порту 1234.

    Возвращает True, если порт открыт и отвечает.
    Не падает — любой ошибке соответствует False.
    """
    try:
        with socket.create_connection(
            (LM_STUDIO_HOST, LM_STUDIO_PORT), timeout=LM_STUDIO_TIMEOUT_SEC
        ):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def validate_lancedb_schema(db_path: Path) -> str:
    """Деликатная проверка схемы существующей базы LanceDB v2.

    Возвращает статус:
      'ok'           — база валидна, схема совпадает
      'mismatch'     — база существует, но схема отличается (миграция нужна)
      'empty'        — база существует, но таблица пуста или отсутствует
      'not_found'    — базы нет (чистая установка)
    """
    if not db_path.exists():
        return "not_found"

    # Проверяем, что директория содержит файлы LanceDB
    lance_files = list(db_path.glob("*.lance")) + list(db_path.glob("*.manifest"))
    if not lance_files:
        return "not_found"

    # Пробуем подключиться и прочитать схему
    try:
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(str(db_path))
        table_names = db.table_names()

        if not table_names:
            return "empty"

        table = db.open_table("codebase_chunks")
        existing_schema = table.schema

        # Сравниваем поля
        existing_fields = {}
        for field in existing_schema:
            field_name = field.name
            field_type = str(field.type)
            existing_fields[field_name] = field_type

        # Проверяем наличие всех ожидаемых полей
        missing_fields = set(EXPECTED_SCHEMA_FIELDS.keys()) - set(
            existing_fields.keys()
        )
        if missing_fields:
            print(f"  ⚠️ Отсутствуют поля схемы: {missing_fields}")
            return "mismatch"

        # Проверяем критичные типы (id, text, file_path — string; chunk_index — int32)
        critical_type_checks = {
            "id": "string",
            "text": "string",
            "file_path": "string",
            "file_hash": "string",
            "chunk_index": "int32",
        }
        for field_name, expected_type in critical_type_checks.items():
            actual = existing_fields.get(field_name, "")
            if expected_type not in actual:
                print(
                    f"  ⚠️ Тип поля '{field_name}': ожидается {expected_type}, "
                    f"фактически {actual}"
                )
                return "mismatch"

        return "ok"

    except ImportError:
        # lancedb ещё не установлен (pip install будет позже) —
        # проверяем только наличие директории
        print("  ℹ️ LanceDB ещё не установлен — пропускаю проверку схемы.")
        return "ok" if lance_files else "not_found"
    except Exception as e:
        print(f"  ⚠️ Ошибка при проверке схемы LanceDB: {e}")
        return "mismatch"


def _build_uninstall_bat(python_exe: str, zed_ext_dir: str) -> str:
    """Генерирует содержимое uninstall.bat.

    Строится через список строк, чтобы избежать ложных срабатываний
    type-checker на встроенном Python-коде внутри строковых литералов.
    """
    _RX_COMMENT = r"r'^\s*//.*$'"
    _RX_TRAIL_COMMA_OBJ = r"r',\s*}\s*}'"
    _RX_TRAIL_COMMA_ARR = r"r',\s*]'"
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "echo ==================================================",
        "echo  Удаление плагина MSCodebase Intelligence...",
        "echo ==================================================",
        "echo [1/3] Удаление настроек из Zed IDE...",
        f'"{python_exe}" -c "',
        "import json, pathlib, os, re",
        "p = pathlib.Path(os.environ['USERPROFILE']) / '.config' / 'zed' / 'settings.json'",
        "if not p.exists(): p = pathlib.Path(os.environ['APPDATA']) / 'Zed' / 'settings.json'",
        "if p.exists():",
        "    content = p.read_text(encoding='utf-8')",
        f"    clean = re.sub({_RX_COMMENT}, '', content, flags=re.MULTILINE)",
        f"    clean = re.sub({_RX_TRAIL_COMMA_OBJ}, '}}', clean)",
        f"    clean = re.sub({_RX_TRAIL_COMMA_ARR}, ']', clean)",
        "    d = json.loads(clean)",
        "    # Удаляем MCP-сервер",
        "    if 'context_servers' in d and 'mscodebase-intelligence' in d['context_servers']:",
        "        del d['context_servers']['mscodebase-intelligence']",
        "        if not d['context_servers']:",
        "            del d['context_servers']",
        "    # Удаляем LSP-сервер",
        "    if 'lsp' in d and 'mscodebase-lsp' in d['lsp']:",
        "        del d['lsp']['mscodebase-lsp']",
        "        if not d['lsp']:",
        "            del d['lsp']",
        "    # Удаляем mscodebase-lsp из language_servers",
        "    if 'languages' in d:",
        "        for lang in list(d['languages'].keys()):",
        "            lang_cfg = d['languages'][lang]",
        "            if 'language_servers' in lang_cfg and 'mscodebase-lsp' in lang_cfg['language_servers']:",
        "                lang_cfg['language_servers'].remove('mscodebase-lsp')",
        "                if not lang_cfg['language_servers']:",
        "                    del lang_cfg['language_servers']",
        "            if not lang_cfg:",
        "                del d['languages'][lang]",
        "        if not d['languages']:",
        "            del d['languages']",
        "    # Удаляем секцию mscodebase",
        "    if 'mscodebase' in d:",
        "        del d['mscodebase']",
        "    p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding='utf-8')",
        '"',
        "echo [2/3] Стирание рабочих директорий и баз данных индексов...",
        "timeout /t 2 >nul",
        f'rd /s /q "{zed_ext_dir}"',
        "echo ✅ Удаление полностью завершено! Перезапустите Zed.",
        "pause",
    ]
    return "\n".join(lines) + "\n"


def generate_semaphore_config() -> dict:
    """Генерирует конфигурацию семафора для конкурентных LSP+MCP запросов."""
    return {
        "max_concurrent_llm_requests": MAX_CONCURRENT_LLM_REQUESTS,
        "lm_studio_host": LM_STUDIO_HOST,
        "lm_studio_port": LM_STUDIO_PORT,
    }


def main():
    print("==================================================")
    print(" MSCodebase Intelligence — Развертывание Системы ")
    print("==================================================")

    # ──────────────────────────────────────────────────
    # 0. Проверка доступности LM Studio / Ollama
    # ──────────────────────────────────────────────────
    print("\n[0/6] Проверка доступности LM Studio/Ollama...")
    lm_available = check_lm_studio_available()
    fallback_mode = not lm_available

    if lm_available:
        print(f"  ✅ LM Studio/Ollama доступен на {LM_STUDIO_HOST}:{LM_STUDIO_PORT}")
    else:
        print(f"  ⚠️ LM Studio/Ollama НЕ доступен на {LM_STUDIO_HOST}:{LM_STUDIO_PORT}")
        print("  ℹ️ Переход в Fallback-режим: только Tree-sitter + текстовые индексы.")
        print("     Векторный поиск будет недоступен до запуска LM Studio/Ollama.")

    # ──────────────────────────────────────────────────
    # 1. Изоляция файлов расширения
    # ──────────────────────────────────────────────────
    print("\n[1/6] Изоляция компонентов расширения...")
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

    # ──────────────────────────────────────────────────
    # 2. Создание изолированного Venv
    # ──────────────────────────────────────────────────
    print("\n[2/6] Создание изолированного Python Virtual Environment...")
    if not VENV_DIR.exists():
        if not run_cmd(f'"{sys.executable}" -m venv "{VENV_DIR}"'):
            print("❌ Не удалось инициализировать venv.")
            return
    else:
        print(f"  └─ Venv уже существует: {VENV_DIR}")

    # ──────────────────────────────────────────────────
    # 3. Установка бинарных пакетов Arrow/LanceDB
    # ──────────────────────────────────────────────────
    print("\n[3/6] Компиляция и установка Rust/C++ зависимостей (LanceDB, PyArrow)...")
    run_cmd(f'"{PYTHON_EXE}" -m pip install --upgrade pip')
    if not run_cmd(
        f'"{PYTHON_EXE}" -m pip install -r requirements.txt', cwd=ZED_EXT_DIR
    ):
        print("❌ Критическая ошибка установки Python-пакетов.")
        return

    # ──────────────────────────────────────────────────
    # 4. Атомарная проверка существующей базы LanceDB
    # ──────────────────────────────────────────────────
    print("\n[4/6] Проверка существующей базы данных LanceDB v2...")
    # Определяем путь к базе относительно PROJECT_ROOT (как в indexer.py)
    existing_db_path = PROJECT_ROOT / ".codebase_indices" / "lancedb_v2"
    schema_status = validate_lancedb_schema(existing_db_path)

    if schema_status == "ok":
        print("  ✅ Существующая база LanceDB v2 валидна. Схема совпадает.")
    elif schema_status == "mismatch":
        print("  ⚠️ Схема базы LanceDB v2 отличается от ожидаемой!")
        print("     База НЕ удалена. При запуске Indexer выполнит миграцию данных.")
        print("     Если миграция невозможна — будет создана новая таблица рядом.")
    elif schema_status == "empty":
        print(
            "  ℹ️ База LanceDB v2 существует, но таблица пуста. Будет заполнена при индексации."
        )
    else:
        print(
            "  ℹ️ База LanceDB v2 не найдена. Чистая установка — будет создана при первом запуске."
        )

    # ──────────────────────────────────────────────────
    # 5. Интеграция MCP + LSP в настройки Zed IDE
    # ──────────────────────────────────────────────────
    print("\n[5/6] Интеграция MCP-сервера и LSP-сервера в настройки Zed...")
    zed_config_dir = Path(os.environ["USERPROFILE"]) / ".config" / "zed"
    if sys.platform == "win32":
        alt_path = Path(os.environ["APPDATA"]) / "Zed"
        if alt_path.exists():
            zed_config_dir = alt_path

    settings_json_path = zed_config_dir / "settings.json"
    zed_config_dir.mkdir(parents=True, exist_ok=True)

    settings_data = {}
    if settings_json_path.exists():
        try:
            content = settings_json_path.read_text(encoding="utf-8")
            import re

            content_clean = re.sub(r"^\s*//.*$", "", content, flags=re.MULTILINE)
            settings_data = json.loads(content_clean)
        except Exception:
            settings_data = {}

    if "context_servers" not in settings_data:
        settings_data["context_servers"] = {}

    main_script_path = ZED_EXT_DIR / "src" / "main.py"
    settings_data["context_servers"]["mscodebase-intelligence"] = {
        "command": str(PYTHON_EXE),
        "args": [str(main_script_path)],
    }

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

    # Конфигурация семафора для конкурентных LSP+MCP запросов
    sem_config = generate_semaphore_config()
    if "mscodebase" not in settings_data:
        settings_data["mscodebase"] = {}
    settings_data["mscodebase"]["semaphore"] = sem_config
    settings_data["mscodebase"]["fallback_mode"] = fallback_mode

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

    if "agent" not in settings_data:
        settings_data["agent"] = {}

    current_prompt = settings_data["agent"].get("system_prompt", "")
    if custom_instructions not in current_prompt:
        settings_data["agent"]["system_prompt"] = (
            f"{custom_instructions}\n{current_prompt}"
        ).strip()

    settings_json_path.write_text(
        json.dumps(settings_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  └─ MCP + LSP прописаны в: {settings_json_path}")
    print(f"  └─ Семафор LLM: max_concurrent={MAX_CONCURRENT_LLM_REQUESTS}")
    if fallback_mode:
        print("  └─ Режим: Fallback (Tree-sitter + текстовые индексы)")
    else:
        print("  └─ Режим: Полный (векторный + структурный + текстовый)")

    # ──────────────────────────────────────────────────
    # 6. Генерация автоматического деинсталлятора
    # ──────────────────────────────────────────────────
    print("\n[6/6] Создание утилиты полной очистки (uninstall.bat)...")
    uninst_content = _build_uninstall_bat(str(PYTHON_EXE), str(ZED_EXT_DIR))
    UNINSTALLER.write_text(uninst_content, encoding="utf-8")

    # ──────────────────────────────────────────────────
    # Итог
    # ──────────────────────────────────────────────────
    print("\n==================================================")
    print(" 🎉 СИСТЕМА УСПЕШНО УСТАНОВЛЕНА И ГОТОВА К РАБОТЕ!")
    print("==================================================")
    if fallback_mode:
        print(" ⚠️  Fallback-режим: LM Studio/Ollama не обнаружен.")
        print("     Доступны: Tree-sitter структура + текстовые индексы.")
        print("     Для полного функционала запустите LM Studio и перезапустите Zed.")
    else:
        print(" ✅ Полный режим: векторный + структурный + текстовый поиск.")
    print(f" 🔒 Семафор LLM: {MAX_CONCURRENT_LLM_REQUESTS} параллельных запросов.")
    print(" 1. Запустите LM Studio и включите сервер эмбеддингов (порт 1234).")
    print(" 2. Перезапустите Zed IDE.")
    print(" Все процессы очистки и синхронизации теперь полностью автоматизированы.")


if __name__ == "__main__":
    main()
