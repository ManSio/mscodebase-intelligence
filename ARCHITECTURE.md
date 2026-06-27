# 📑 ТЕХНИЧЕСКИЙ ПАСПОРТ И АРХИТЕКТУРА

## 1. Спецификация тестового стенда

| Параметр | Значение |
|----------|----------|
| CPU | AMD Ryzen 5 5600H (12 логических ядер, 3.3 GHz) |
| RAM | 16 GB DDR4 (3200 MHz) |
| GPU | AMD Radeon(TM) Graphics |
| Диск | SSD 341 GB (NTFS), диск `D:` |
| OS | Windows 11 Home Insider Preview |

## 2. Векторное окружение

| Компонент | Значение |
|-----------|----------|
| Модель эмбеддингов | `text-embedding-bge-m3` (1024 dim) |
| Протокол | LM Studio OpenAI-совместимый API (`/v1/embeddings`) |
| Fallback | ONNX Runtime (локальная модель) |
| СУБД хранилища | LanceDB v2 (Apache Arrow) |

## 3. Топология данных

Векторные индексы изолированы по проектам:

```
<PARENT_DIR>/.codebase_indices/lancedb_v2/index_<project>_<hash>.db
```

### Структура путей (Windows)

```python
# src/core/indexer.py → _generate_unique_db_path()
normalized_path = str(project_path.resolve()).lower().replace('\\', '/')
project_hash = hashlib.md5(normalized_path.encode()).hexdigest()[:8]
db_dir = project_path.parent / ".codebase_indices" / "lancedb_v2"
db_name = f"index_{project_name}_{project_hash}.db"
```

## 4. Архитектура системы

### 4.1. Потоки данных

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Zed IDE    │────▶│  MCP Server  │────▶│  RemoteEmbedder │
│  (AI Agent) │     │  (server.py) │     │  (LM Studio)    │
└─────────────┘     └──────────────┘     └─────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   Indexer    │
                    │ (LanceDB v2) │
                    └──────────────┘
                           ▲
                           │
┌─────────────┐     ┌──────────────┐
│  Zed IDE    │────▶│  LSP Server  │
│  (on save)  │     │ (lsp_main.py)│
└─────────────┘     └──────────────┘
```

### 4.2. Модули

| Модуль | Файл | Назначение |
|--------|------|------------|
| MCP Server | `src/mcp/server.py` | Тools + Prompts для AI-агента |
| LSP Server | `src/lsp_main.py` | Индексация при сохранении файлов |
| Indexer | `src/core/indexer.py` | Сканирование + запись в LanceDB |
| Searcher | `src/core/searcher.py` | Гибридный поиск (vector + BM25) |
| SymbolIndex | `src/core/symbol_index.py` | Tree-sitter парсинг + Call Graph |
| ContextEngine | `src/core/context_engine.py` | Сжатый контекст для AI |
| RemoteEmbedder | `src/core/remote_embedder.py` | LM Studio / Ollama / ONNX |
| Parser | `src/core/parser.py` | Tree-sitter AST парсер |
| Chunker | `src/core/chunker.py` | Семантический чанкинг кода |
| FileGuard | `src/core/file_guard.py` | Фильтрация файлов + gitignore |
| Integrity | `src/core/integrity.py` | Merkle Tree для детекции изменений |
| ContentCache | `src/core/content_cache.py` | Кэш хешей файлов |

## 5. MCP Tools

| Tool | Тип | Описание |
|------|-----|----------|
| `get_index_status` | sync | Статус индекса (chunks, files, symbols) |
| `index_project_dir` | async | Запуск полной индексации проекта |
| `search_code` | sync | Семантический поиск (vector + BM25) |
| `get_context` | sync | Сжатый контекст по запросу |
| `get_symbol_info` | sync | Call Graph: definition + callers + callees |
| `get_repo_map` | sync | Карта проекта (файлы + символы) |
| `scan_changes` | async | Архитектурный дифф изменений |
| `watcher_status` | sync | Статус компонентов (embedder, LSP) |

## 6. MCP Prompts

| Prompt | Назначение |
|--------|------------|
| `mscodebase-rules` | Системные правила для AI-агента (state-awareness, context budget, safe writing) |

## 7. Установка

Скрипт `install.py` выполняет:

1. Копирование расширения в `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`
2. Создание изолированного venv + установка зависимостей
3. Проверка схемы LanceDB (миграция при необходимости)
4. Настройка MCP + LSP в `settings.json` Zed
5. Настройка `system_prompt` в блоке `agent`
6. Генерация `uninstall.bat`

### Конфигурация в settings.json

```json
{
  "context_servers": {
    "mscodebase-intelligence": {
      "command": "<venv_python>",
      "args": ["<ext_dir>/src/main.py"]
    }
  },
  "lsp": {
    "mscodebase-lsp": {
      "command": "<venv_python>",
      "arguments": ["-u", "<ext_dir>/src/lsp_main.py"]
    }
  },
  "languages": {
    "Python": { "language_servers": ["mscodebase-lsp"] },
    "TypeScript": { "language_servers": ["mscodebase-lsp"] },
    "Rust": { "language_servers": ["mscodebase-lsp"] },
    "Go": { "language_servers": ["mscodebase-lsp"] },
    "JavaScript": { "language_servers": ["mscodebase-lsp"] }
  },
  "agent": {
    "system_prompt": "MSCodeBase Core Rules: ..."
  },
  "mscodebase": {
    "semaphore": { "max_concurrent": 2 },
    "fallback_mode": false
  }
}
```

## 8. Ограничения

- Максимальный размер файла: 1 MB
- Поддерживаемые языки: Python, Rust, TypeScript, JavaScript, Go
- Требуется LM Studio (или Ollama/ONNX fallback) для векторного поиска
- Windows native (без Docker/WSL)

---

*Последнее обновление: 2026-06-27*
