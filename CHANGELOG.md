# CHANGELOG

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
- `indexer.py` — добавлена защита от пустых эмбеддингов: если Embedder вернул `[]`, upsert в ChromaDB пропускается, а не падает с `list index out of range`.
- `.gitignore` — унифицирован: `.codebase_indices/`, `.model_server.*`, `crash_debug.log`, `Agent Panel`, `nul`.
- `pyproject.toml` — обновлены URL репозитория на `ManSio/mscodebase-intelligence`.
- `README.md` — синхронизирован с архитектурой (RemoteEmbedder → LM Studio), добавлен шаг подготовки LM Studio перед установкой.

### Проблемы и исследования

#### Проблема: ChromaDB не стартует в venv расширения
- **Причина**: `chromadb_rust_bindings.pyd` не копировался из системного Python в venv при установке.
- **Исследование**: на системном Python `.pyd` присутствовал, в venv — только `__init__.py`.
- **Решение**: добавлен шаг 4.1 в `install.py` — копирование `.pyd` в venv расширения.

#### Проблема: `indexer.py` падает с `"Отказ удалять не-codebase папку"`
- **Причина**: проверка `self.db_path.name.startswith(".codebase")` смотрела только на имя последней папки (хэш проекта), а не на `.codebase_indices`.
- **Исследование**: `db_path` = `ext_dir / .codebase_indices / <project_hash>`, `.name` возвращает хэш.
- **Решение**: заменено на `any(part.startswith(".codebase") for part in self.db_path.parts)`.

#### Проблема: `list index out of range in upsert` при пустых эмбеддингах
- **Причина**: Embedder возвращал пустые списки `[]`, а ChromaDB `upsert()` ожидал векторы.
- **Исследование**: Embedder недоступен (нет ONNX, нет LM Studio) → `embed_batch()` возвращает `[[]]` → ChromaDB падает в C++ слое с IndexError.
- **Решение**: защита в `_index_file_unlocked()` — если эмбеддинги пустые, пропускаем запись в ChromaDB.

#### Проблема: `WinError 87` при `shutil.copy2` в `install.py`
- **Причина**: в корне проекта оказался файл `nul` (зарезервированное имя устройства Windows).
- **Исследование**: `_winapi.CopyFile2` не может скопировать файл с именем системного устройства.
- **Решение**: `nul` добавлен в список исключений `excludes` + `try-except` вокруг `shutil.copy2`.

#### Проблема: сервер индексации не стартует из-за неправильного пути проекта
- **Причина**: `os.getcwd()` возвращает папку Zed (Program Files), а не проект пользователя.
- **Исследование**: при запуске из Zed CWD — папка редактора, а не проекта.
- **Решение**: хардкод `D:\Project\gemma_agent` как fallback, если CWD содержит "Zed" или "Program Files".

---

## [1.0.0] — 2026-06-21

- Первый релиз. ONNX-векторизация (BAAI/bge-m3), ChromaDB, инкрементальная индексация, MCP-инструменты.