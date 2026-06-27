# CHANGELOG

## [Unreleased] — 2026-06-27

### Исправлено
- `src/mcp/server.py` — `@mcp.prompt()` перемещён внутрь `create_mcp_server()` (исправлен `NameError: name 'mcp' is not defined`)
- `install.py` — `system_prompt` записывается в `"agent"` вместо устаревшего `"assistant"` (Zed актуальных версий игнорирует старый блок)

### Документация
- `README.md` — полная перезапись: актуальная структура, архитектура, инструкции
- `ARCHITECTURE.md` — синхронизирована с текущим кодом
- `AI_PROMPT.md` — добавлены инструменты `scan_changes`, `watcher_status`
- `PROJECT_DOCS.md` — синхронизирована с реальной структурой проекта

---

## [1.1.0] — 2026-06-22

### Добавлено
- Режим работы через **RemoteEmbedder** — векторизация кода через LM Studio (OpenAI-совместимый API) без загрузки ONNX. Основной провайдер эмбеддингов (автоопределение LM Studio при старте).
- **Оркестратор потоков** в `handler.py` — глобальный `threading.Lock()`, защита от повторного запуска индексации.
- Установщик (`install.py`): копирование `chromadb_rust_bindings.pyd` в venv расширения (шаг 4.1).
- `CHANGELOG.md` — дневник изменений, проблем и решений.

### Изменено
- `handler.py` — полный рефакторинг: убран `background_init` с `SERVER_READY`, вся инициализация синхронная при создании MCP-сервера.
- `remote_embedder.py` — убран флаг `is_available`; каждый запрос принудительно стучится к LM Studio.
- `indexer.py` — исправлена проверка `.codebase`: теперь смотрит любую часть пути, а не только имя последней папки.
- `indexer.py` — добавлена защита от пустых эмбеддингов: если Embedder вернул `[]`, upsert в LanceDB пропускается.
- `.gitignore` — унифицирован: `.codebase_indices/`, `.model_server.*`, `crash_debug.log`, `Agent Panel`, `nul`.
- `pyproject.toml` — обновлены URL репозитория на `ManSio/mscodebase-intelligence`.
- `README.md` — синхронизирован с архитектурой (RemoteEmbedder → LM Studio).

### Проблемы и исследования

#### Проблема: ChromaDB не стартует в venv расширения
- **Причина**: `chromadb_rust_bindings.pyd` не копировался из системного Python в venv при установке.
- **Решение**: добавлен шаг 4.1 в `install.py` — копирование `.pyd` в venv расширения.

#### Проблема: `indexer.py` падает с `"Отказ удалять не-codebase папку"`
- **Причина**: проверка `self.db_path.name.startswith(".codebase")` смотрела только на имя последней папки.
- **Решение**: заменено на `any(part.startswith(".codebase") for part in self.db_path.parts)`.

#### Проблема: `list index out of range in upsert` при пустых эмбеддингах
- **Причина**: Embedder возвращал пустые списки `[]`, а БД ожидала векторы.
- **Решение**: защита в `_index_file_unlocked()` — если эмбеддинги пустые, пропускаем запись.

#### Проблема: `WinError 87` при `shutil.copy2` в `install.py`
- **Причина**: в корне проекта оказался файл `nul` (зарезервированное имя устройства Windows).
- **Решение**: `nul` добавлен в список исключений + `try-except` вокруг `shutil.copy2`.

#### Проблема: сервер индексации не стартует из-за неправильного пути проекта
- **Причина**: `os.getcwd()` возвращает папку Zed (Program Files), а не проект пользователя.
- **Решение**: хардкод `D:\Project\gemma_agent` как fallback, если CWD содержит "Zed" или "Program Files".

---

## [1.0.0] — 2026-06-21

- Первый релиз. ONNX-векторизация (BAAI/bge-m3), LanceDB, инкрементальная индексация, MCP-инструменты.
