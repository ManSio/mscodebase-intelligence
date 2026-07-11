# Threads.db Research — Zed Conversation Memory Mining

> Исследование: как извлечь историю диалогов Zed из threads.db
> и интегрировать в LanceDB для долговременной памяти.

---

## 1. 📂 Расположение и размер

**Файл:** `%LOCALAPPDATA%\Zed\threads\threads.db`
**Размер:** 39 MB (SQLite)

| Параметр | Значение |
|----------|----------|
| **Всего тредов** | 300 |
| **Самый большой** | 1,034,436 bytes (сжатый) |
| **Формат сжатия** | Zstandard (zstd) |
| **Формат данных** | JSON |
| **Версия** | 0.3.0 |

---

## 2. 🗄 Схема SQLite

```sql
CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    data_type TEXT NOT NULL,       -- 'zstd'
    data BLOB NOT NULL,            -- zstd compressed JSON
    parent_id TEXT,
    folder_paths TEXT,
    folder_paths_order TEXT,
    created_at TEXT
);
```

### Data flow:
```
threads.db (SQLite)
    ↓ SELECT data WHERE data_type='zstd'
    ↓ zstandard.decompress(data)
    ↓ json.loads()
    ↓ messages[] → chunks → LanceDB
```

---

## 3. 📄 Формат JSON (расшифрован)

```json
{
  "title": "Session title",
  "messages": [
    {
      "User": {
        "id": "uuid",
        "content": [{"Text": "user message"}]
      }
    },
    {
      "Assistant": {
        "id": "uuid",
        "content": [{"Text": "assistant response"}],
        "tool_calls": [...]
      }
    }
  ],
  "model": {
    "provider": "openrouter|opencode|...",
    "model": "deepseek/deepseek-v4-flash|..."
  },
  "profile": "write|ask|...",
  "cumulative_token_usage": {"input": N, "output": M},
  "initial_project_snapshot": {
    "worktree_snapshots": [
      {
        "worktree_path": "D:\\Project\\MSCodeBase",
        "git_state": {
          "remote_url": "...",
          "head_sha": "...",
          "current_branch": "main",
          "diff": ""
        }
      }
    ]
  },
  "thinking_enabled": true,
  "version": "0.3.0"
}
```

### Пример из реальных данных (наш текущий диалог):

| Параметр | Значение |
|----------|----------|
| **Summary** | Initial greeting and assistance introduction |
| **Messages** | 702 |
| **Decompressed** | **11.2 MB** |
| **Provider** | opencode |
| **Model** | go/deepseek-v4-flash |
| **Project** | D:\Project\MSCodeBase |

---

## 4. 🐍 Код декодирования (Python)

```python
import sqlite3
import zstandard
import json

conn = sqlite3.connect(r'%LOCALAPPDATA%\Zed\threads\threads.db')
c = conn.cursor()
dctx = zstandard.ZstdDecompressor()

c.execute('SELECT id, summary, data FROM threads ORDER BY updated_at DESC')
for row in c.fetchall():
    thread_id, summary, compressed = row
    decompressed = dctx.decompress(compressed, max_output_size=52428800)
    obj = json.loads(decompressed)
    messages = obj.get('messages', [])
    model = obj.get('model', {})
    # → нарезаем messages[] на чанки → LanceDB
```

**Зависимость:** `pip install zstandard`

---

## 5. 🔄 Интеграция с LanceDB (план)

```
threads.db                    MSCodeBase
    │                              │
    ▼                              ▼
[ZstdDecompressor]          [Indexer.chunk_and_embed()]
    │                              │
    ▼                              ▼
[JSON Parser]               [LanceDB Table]
    │                              │
    ▼                              ▼
[Chunk messages] ──────────► [Semantic Search]
    │                              │
    ▼                              ▼
[Metadata: thread_id,       [Find past discussions
 provider, model,            by semantic query]
 project, timestamp]
```

### Схема чанка в LanceDB:

```python
{
    "file_path": "threads://{thread_id}",
    "content": "message text",
    "module_name": "threads",
    "layer": "threads",
    "role": "user|assistant",
    "provider": "openrouter|opencode",
    "model": "deepseek/deepseek-v4-flash",
    "thread_summary": "...",
    "project_path": "D:\\Project\\MSCodeBase",
    "timestamp": "2026-07-11T..."
}
```

---

## 6. ⚠️ Риски и ограничения

| Риск | Описание | Митигация |
|------|----------|-----------|
| **SQLite concurrent access** | Zed пишет в threads.db во время работы | Read-only транзакции, retry при locked |
| **Zed bug #59442** | agent_ui SQLite write loop → OOM | Мы только читаем, не пишем → не затронуты |
| **Размер** | 11MB на тред, 300 тредов | Инкрементальная синхронизация (check updated_at) |
| **Zstd dependency** | Нужен pip install zstandard | Добавить в pyproject.toml |
| **Privacy** | Все диалоги попадают в индекс | Фильтр по project_path |

---

## 7. 🔬 edit_prediction 403 — Вердикт

**Ошибка в логах Zed:**
```
ERROR [edit_prediction/src/edit_prediction.rs:2566] Request failed with status: 403
Body: {"code":"edit_prediction_blocked","message":"Edit predictions are blocked. If you think this is a mistake, please reach out to billing-support@zed.dev."}
```

**Статус:** ❌ НЕ ИСПРАВЛЯЕТСЯ С НАШЕЙ СТОРОНЫ
- Server-side API ошибка сервиса edit prediction от Zed
- Требуется обращение в billing-support@zed.dev
- Известный баг: Zed #59013 (closed as "not planned")
- MSCodeBase НЕ ИСПОЛЬЗУЕТ edit prediction — ошибка не влияет на работу

**Другие ошибки в логах Zed (безопасные):**

| Ошибка | Причина | Влияние |
|--------|---------|---------|
| `lsp_store: no snapshots found` | Внутренняя LSP синхронизация | Нет |
| `window not found` | Windows specific gpui | Нет |
| `failed to resize alacritty pty` | Терминал | Нет |

---

## 8. 🔗 Связанные проекты (memory-layer)

| Проект | Звёзды | Язык | Подход |
|--------|--------|------|--------|
| **OB1** | 4.1k | TS | Open Brain — единая БД для всех AI |
| **AtomicMemory** | 440 | TS | Portable semantic memory, MCP SDK |
| **knowns** | 214 | Go | Memory layer для AI-native разработки |
| **Memesh** | 14 | TS | **SQLite + FTS5 + vectors — легче всех** |
| **Engram** | 7 | JS | SQLite, zero cloud, MCP-native |
| **Remi** | 4 | Rust | SQLite + FTS5 + ONNX для coding agents |
| **GroundMemory** | 3 | Python | MCP-native, BM25+vector hybrid |

**Вывод:** Можем использовать тот же подход что и Memesh/Remi — SQLite как локальное хранилище + FTS5 + вектора. Но у нас уже есть LanceDB — добавляем новую таблицу `threads` с той же схемой чанков.

---

*Исследование проведено: 2026-07-11*
*Статус: ✅ Формат расшифрован, код декодирования работает*
