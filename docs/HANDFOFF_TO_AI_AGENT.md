<img src="../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](HANDFOFF_TO_AI_AGENT.en.md) • [🇷🇺 Русский](HANDFOFF_TO_AI_AGENT.md) • [🇨🇳 中文](HANDFOFF_TO_AI_AGENT.zh.md)

# MSCodeBase Intelligence — Архитектура и опыт разработки

> Документ для разработчиков, которые подключаются к проекту.
> Описаны ключевые архитектурные решения, подводные камни Windows
> и результаты расследований, чтобы не наступать на те же грабли.

---

## 🎯 Что это за проект

**MSCodeBase Intelligence** — MCP-сервер для семантического поиска кода в Zed IDE.
Работает полностью локально: LanceDB (векторный индекс) + LM Studio (эмбеддинги).

**Ключевые числа:**
- 43 инструмента MCP (33 core + 10 intel)
- 10 файлов инструментов, 15 сервисов в DI-контейнере
- Индекс: ~1600 чанков, ~115 файлов, ~180 символов

---

## 🔑 Главное открытие: определение проекта на Windows

**Проблема:** MCP-серверу нужно знать, какой проект открыт в окне Zed.
`ZED_WORKTREE_ROOT` и `current_dir` **не работают** на Windows (баг Zed).
Каждое окно запускает свой MCP-процесс, но env-переменные не передаются.

**Решение:** читать SQLite-базу Zed напрямую:

```python
# 1. Берём active_workspace_id из scoped_kv_store
conn.execute("""
    SELECT value FROM scoped_kv_store 
    WHERE namespace = 'multi_workspace_state'
""")
# → {"active_workspace_id": 2, ...}

# 2. По ID получаем путь
conn.execute("""
    SELECT paths FROM workspaces WHERE workspace_id = ?
""", (active_id,))
# → "D:\путь\к\проекту"
```

**Где:** `src/mcp/server.py`, функция `resolve_project_root()`, приоритет 0.
**Ограничение:** если у проекта несколько окон — MCP не знает, какое активно.

→ **Полное расследование:** [`docs/investigations/2026-07-05-active-workspace-resolution.md`](investigations/2026-07-05-active-workspace-resolution.md)
  Там: проверка 6 механизмов Zed, внутренние Rust API, SQLite-схемы, 4 неудачных подхода.

---

## 🏗️ Ключевые архитектурные решения

| Решение | Мотивация |
|---------|-----------|
| **DI-контейнер (ServiceCollection)** | 15 сервисов, lazy-резолвинг, per-project registry |
| **late-resolve active indexer** | Если LSP не успел записать bridge — подхватываем первый живой workspace |
| **Двухфазный reindex** | `intel_trigger_reindex` → job_id → `intel_get_job_status` (анти-spam) |
| **asyncio.Lock для File IO** | Защита от race при конкурентных записях в JSON-файлы памяти |
| **ui_formatter** | Единый Markdown-стиль для всех 43 инструментов (без сырого JSON) |

---

## 🔧 Что сломано и не будет починено

| Компонент | Причина | Статус |
|-----------|---------|--------|
| **LSP-сервер** (`lsp_main.py`) | Zed не регистрирует кастомные имена LSP (нужен Rust/WASM) | **WONTFIX** |
| **auto-restart MCP** | Нет хука в Zed для перезапуска упавшего context_server | **WONTFIX** |
| **`ZED_WORKTREE_ROOT`** | Не устанавливается на Windows (баг Zed #36019) | **Обход через SQLite** |

→ **Полное расследование LSP:** [`docs/investigations/2026-07-05-lsp-zed-1.9.0.md`](investigations/2026-07-05-lsp-zed-1.9.0.md)
  Суть: Zed требует Rust/WASM-адаптер для кастомного LSP. `settings.json` не может
  зарегистрировать новый язык — только переопределить путь для существующего.
  8 подходов проверено, все провалились.

---

## 🐛 Исправленные баги (чтобы не регрессить)

### 1. DebounceBatch deadlock

**Файл:** `src/core/rate_limiter.py`
**Симптом:** MCP зависает через 5с после пачки `notify_change`.
**Причина:** `await` внутри `threading.Lock` (не reentrant) — 100% дедлок.
**Фикс:** разделение: решение `should_flush` под lock, сам `await` — после lock.

### 2. Self-indexing guard

MCP-сервер иногда индексировал сам себя (исходники расширения, ~500MB).
**Фикс:** проверка `_is_self_index_path()` в `base.py` — блокирует ext_root
и директорию установки Zed, бросает `ToolError`.

### 3. Race condition в Project Memory

Конкурентные вызовы `intel_log_incident` + `intel_add_memory_node` затирали
JSON-файлы. **Фикс:** `asyncio.Lock` в `IntelligenceStore`.

---

## 🗄️ Где что лежит

| Данные | Путь |
|--------|------|
| Векторный индекс | `<проект>/.codebase_indices/lancedb_v2/` |
| Память проекта (ADR, issues) | `<проект>/.codebase_indices/intelligence/` |
| Логи | `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\` |
| База Zed | `%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite` |

---

## 📁 Ключевые файлы

| Файл | Что делает |
|------|-----------|
| `src/mcp/server.py` | `resolve_project_root()`, регистрация всех 43 инструментов |
| `src/mcp/tools/base.py` | `MCPTool` (базовый класс), `resolve_indexer_for_request()` |
| `src/core/di_container.py` | 15 сервисов, `ProjectIndexerRegistry` |
| `src/core/intelligence_layer.py` | 10 intel-инструментов, `ProjectIntelligenceLayer` |
| `src/core/indexer.py` | LanceDB, векторизация, индексация |
| `src/core/searcher.py` | BM25 + Dense + RRF гибридный поиск |
| `src/utils/ui_formatter.py` | Единый Markdown-формат для всех инструментов |
| `src/core/error_handler.py` | `_format_success_response`, `error_boundary` |
| `src/core/rate_limiter.py` | DebounceBatch, SlidingWindowRateLimiter |

---

## ⚠️ Подводные камни Windows

1. **Restricted Mode** — при первом открытии проекта нажать "Trust and Continue"
2. **MCP restart** — только File → Quit (не `window: reload`, не kill)
3. **Git subprocess** — `GIT_ASKPASS=echo`, `CREATE_NO_WINDOW`, таймауты
4. **LanceDB on Windows** — mmap-файлы не освобождаются до `_safe_close()` + `gc.collect()`
5. **Paths** — MCP: `src\core\file.py`, терминал: `src/core/file.py`

---

## 🔗 Связанные документы

| Документ | О чём |
|----------|-------|
| `docs/INSTALL.md` | Установка для пользователей |
| `docs/architecture.md` | Полная архитектура (10 слоёв) |
| `ZED_WINDOWS_QUIRKS.md` | Windows-специфика |
| `docs/investigations/2026-07-05-lsp-zed-1.9.0.md` | Почему LSP не работает |
| `docs/investigations/2026-07-05-active-workspace-resolution.md` | SQLite active_workspace |
| `AGENTS.md` | Правила для AI-агента в Zed |
