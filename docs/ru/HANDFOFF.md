<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

# MSCodeBase Intelligence — Архитектура и опыт разработки

[🇬🇧 English](../en/HANDFOFF.md) • [🇷🇺 Русский](HANDFOFF.md) • [🇨🇳 中文](../zh/HANDFOFF.md)

> Документ для разработчиков, присоединяющихся к проекту.
> Описывает ключевые архитектурные решения, подводные камни Windows
> и результаты расследований, чтобы вы не наступали на те же грабли.

---

## 🎯 Что это за проект

**MSCodeBase Intelligence** — MCP-сервер для семантического поиска кода в Zed IDE.
Работает полностью локально: LanceDB (векторный индекс) + llama.cpp GGUF (эмбеддинги/реранкер) + ONNX (fallback).

**Ключевые цифры:**
- 50 MCP-инструментов (33 core + 14 intel + 3 diagnostic)
- 10 файлов инструментов, 15 сервисов в DI-контейнере
- Индекс: ~3000 чанков, ~170 файлов, ~1350 символов

---

## 🔑 Главное открытие: определение проекта на Windows

**Проблема:** MCP-сервер должен знать, какой проект открыт в окне Zed.
`ZED_WORKTREE_ROOT` и `current_dir` **не работают** на Windows (баг Zed).
Каждое окно запускает свой MCP-процесс, но переменные окружения не передаются.

**Решение:** читать SQLite-базу Zed напрямую:

```python
# 1. Получаем active_workspace_id из scoped_kv_store
conn.execute("""
    SELECT value FROM scoped_kv_store 
    WHERE namespace = 'multi_workspace_state'
""")
# → {"active_workspace_id": 2, ...}

# 2. Получаем путь по ID
conn.execute("""
    SELECT paths FROM workspaces WHERE workspace_id = ?
""", (active_id,))
# → "D:\path\to\project"
```

**Где:** `src/mcp/server.py`, функция `resolve_project_root()`, приоритет 0.
**Ограничение:** если у проекта несколько окон — MCP не знает, какое активно.

→ **Полное расследование:** [`ACTIVE_WORKSPACE_RESOLUTION.md`](investigations/ACTIVE_WORKSPACE_RESOLUTION.md)
  Охватывает: 6 протестированных механизмов Zed, внутренние Rust API, схемы SQLite, 4 проваленных подхода.

---

## 🏗️ Ключевые архитектурные решения

| Решение | Мотивация |
|----------|-----------|
| **DI-контейнер (ServiceCollection)** | 15 сервисов, ленивое разрешение, per-project registry |
| **late-resolve активного индексера** | Если LSP ещё не записал bridge-файл — подхватить первое живое workspace |
| **Двухфазная переиндексация** | `intel_trigger_reindex` → job_id → `intel_get_job_status` (анти-спам) |
| **asyncio.Lock для File IO** | Защита от гонок при конкурентной записи в JSON-файлы памяти |
| **ui_formatter** | Единый Markdown-стиль для всех 56 инструментов (без сырого JSON) |

---

## 🔧 Что сломано и не будет исправлено

| Компонент | Причина | Статус |
|-----------|--------|--------|
| **LSP-сервер** (`lsp_main.py`) | Zed не регистрирует кастомные имена LSP (нужен Rust/WASM) | **WONTFIX** |
| **авто-перезапуск MCP** | Нет хука в Zed для перезапуска упавшего context_server | **WONTFIX** |
| **`ZED_WORKTREE_ROOT`** | Не устанавливается на Windows (баг Zed #36019) | **Workaround через SQLite** |

→ **Полное расследование LSP:** [`LSP_WONTFIX.md`](investigations/LSP_WONTFIX.md)
  Кратко: Zed требует Rust/WASM-адаптер для кастомного LSP. `settings.json` не может
  зарегистрировать новый язык — только переопределить путь для существующего.
  8 подходов протестировано, все провалились.

---

## 🐛 Исправленные баги (чтобы предотвратить регрессии)

### 1. DebounceBatch deadlock

**Файл:** `src/core/rate_limiter.py`
**Симптом:** MCP зависает через 5 секунд после пачки `notify_change`.
**Причина:** `await` внутри `threading.Lock` (не реентерабельный) — 100% deadlock.
**Исправление:** разделение: решение `should_flush` под блокировкой, сам `await` — после отпускания блокировки.

### 2. Защита от самоиндексации

MCP-сервер иногда индексировал сам себя (исходники расширения, ~500 МБ).
**Исправление:** проверка `_is_self_index_path()` в `base.py` — блокирует ext_root
и директорию установки Zed, выбрасывает `ToolError`.

### 3. Состояние гонки в Project Memory

Конкурентные вызовы `intel_log_incident` + `intel_add_memory_node` перезаписывали
JSON-файлы. **Исправление:** `asyncio.Lock` в `IntelligenceStore`.

---

## 🗄️ Где что хранится

| Данные | Путь |
|------|------|
| Векторный индекс | `<проект>/.codebase_indices/lancedb_v2/` |
| Память проекта (ADR, issues) | `<проект>/.codebase_indices/intelligence/` |
| Логи | `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\` |
| База данных Zed | `%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite` |

---

## 📁 Ключевые файлы

| Файл | Что делает |
|------|-------------|
| `src/mcp/server.py` | `resolve_project_root()`, регистрация всех 56 инструментов |
| `src/mcp/tools/base.py` | `MCPTool` (базовый класс), `resolve_indexer_for_request()` |
| `src/core/di_container.py` | 15 сервисов, `ProjectIndexerRegistry` |
| `src/core/intelligence_layer.py` | 14 intel-инструментов, `ProjectIntelligenceLayer` |
| `src/core/indexer.py` | LanceDB, векторизация, индексация |
| `src/core/searcher.py` | BM25 + Dense + RRF гибридный поиск |
| `src/utils/ui_formatter.py` | Единый Markdown-формат для всех инструментов |
| `src/core/error_handler.py` | `_format_success_response`, `error_boundary` |
| `src/core/rate_limiter.py` | DebounceBatch, SlidingWindowRateLimiter |

---

## ⚠️ Подводные камни Windows

1. **Restricted Mode** — нажмите «Trust and Continue» при первом открытии проекта
2. **Перезапуск MCP** — только File → Quit (не `window: reload`, не kill)
3. **Git subprocess** — `GIT_ASKPASS=echo`, `CREATE_NO_WINDOW`, таймауты
4. **LanceDB на Windows** — mmap-файлы не освобождаются до `_safe_close()` + `gc.collect()`
5. **Пути** — MCP: `src\core\file.py`, terminal: `src/core/file.py`

---

## 🔗 Связанные документы

| Документ | О чём |
|----------|-------|
| `INSTALL.md` | Установка для пользователей |
| `ARCHITECTURE.md` | Полная архитектура (10 слоёв) |
| `ZED_WINDOWS_QUIRKS.md` | Особенности Windows |
| `investigations/LSP_WONTFIX.md` | Почему не работает LSP |
| `investigations/ACTIVE_WORKSPACE_RESOLUTION.md` | SQLite active_workspace |
| `../../AGENTS.md` | Правила для AI-агента в Zed |
