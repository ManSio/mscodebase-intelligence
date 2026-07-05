# ═══════════════════════════════════════════════════════════════
# HANDFOFF — MSCodeBase Intelligence (2026-07-05)
# ═══════════════════════════════════════════════════════════════
# Этот файл — передача контекста между AI-агентами.
# Читать ПЕРЕД началом работы. Обновлять ПОСЛЕ завершения.
# ═══════════════════════════════════════════════════════════════

## 1. КОНТЕКСТ ПРОЕКТА

- **Пользователь:** misha, Windows 11, Zed 1.9.0, Python 3.14.3
- **Репозиторий:** `D:\Project\MSCodeBase` → `github.com/ManSio/mscodebase-intelligence`
- **Установленное расширение:** `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\`
- **Синхронизация:** `python install.py` копирует исходники из репозитория в расширение

### Терминология

- **MCP-сервер** — Python-процесс (`python -u -m src.main`), запущенный Zed как context_server
- **LSP-сервер** — `lsp_main.py` (pygls) — **НЕ РАБОТАЕТ на Windows** (WONTFIX)
- **ext_root** — директория установленного расширения
- **project_root** — директория пользовательского проекта

---

## 2. ТЕКУЩЕЕ СОСТОЯНИЕ (2026-07-05, 17:34)

### 2.1 Что работает

| Компонент | Статус | Примечание |
|-----------|--------|-----------|
| MCP-сервер (43 инструмента) | ✅ | 33 core + 10 intel |
| Проект резолвится правильно | ✅ | Через `active_workspace_id` в SQLite |
| Поиск кода (search_code) | ✅ | Все режимы: fast/quality/deep/context/auto |
| LM Studio (эмбеддинги) | ✅ | phi-4-mini-instruct, ~544-1228 tok/s |
| Индекс (LanceDB) | ✅ | 1586 чанков, 113 файлов |
| SymbolIndex (Tree-sitter) | ⚠️ | 134 символа (загружаются из pkl, но может быть 0 до первого сохранения) |
| LSP (in-editor фичи) | ❌ WONTFIX | Не работает на Windows Zed 1.9.0 |
| Multi-window (одно окно, неск. проектов) | ✅ | `active_workspace_id` переключается |
| Multi-window (разные окна) | ⚠️ | MCP не знает, из какого окна запрос |
| Auto-restart MCP | ❌ | Только File → Quit → снова открыть проект |

### 2.2 Инструменты с UI-форматтером

Внедрён `src/utils/ui_formatter.py` — единый стиль вывода Markdown:

| Инструмент | Формат | Статус |
|-----------|--------|--------|
| `get_index_status` | `key_value` + multi-project warning | ✅ |
| `search_code` | `format_search_code` (таблица) | ✅ |
| `get_repo_rank` | `format_repo_rank` (таблица) | ✅ |
| Остальные 40 инструментов | dict → `_format_success_response` | ❌ Не интегрированы |

### 2.3 БД и файловые пути

| Данные | Путь | Формат |
|--------|------|--------|
| Векторный индекс | `<project>/.codebase_indices/lancedb_v2/` | LanceDB |
| Символьный индекс | `<project>/.codebase_indices/lancedb_v2/.../symbol_index.pkl` | pickle |
| Память проекта (ADR, issues) | `<project>/.codebase_indices/intelligence/` | JSON |
| Коммит-память | `<project>/.codebase_indices/commit_memory/` | JSON |
| Логи | `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\` | Лог-файлы |
| База Zed (для чтения) | `%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite` | SQLite |

### 2.4 Архитектура проекта

```
D:\Project\MSCodeBase
├── src/
│   ├── main.py                    # Точка входа MCP (setup_logging → run_server)
│   ├── lsp_main.py                # LSP (не работает на Windows)
│   ├── mcp/
│   │   ├── server.py              # resolve_project_root + DI + регистрация
│   │   └── tools/                 # 10 файлов, 33 инструмента
│   │       ├── search_tools.py    # 3: search_code, get_symbol_info, impact_analysis
│   │       ├── system_tools.py    # 9: get_index_status, get_logs, health, eta...
│   │       ├── analysis_tools.py  # 5: structural_search, get_repo_rank...
│   │       ├── indexing_tools.py  # 3: notify_change, index_project_dir...
│   │       ├── git_tools.py       # 3: get_commit_history, get_file_history...
│   │       ├── graph_tools.py     # 4: cross_repo_search, graph_query...
│   │       ├── investigation_tools.py  # 3: get_bug_correlation...
│   │       └── lifecycle_tools.py # 3: submit_background_task...
│   ├── core/
│   │   ├── di_container.py        # 15 service types
│   │   ├── indexer.py             # LanceDB (векторная БД)
│   │   ├── searcher.py            # BM25 + Dense + RRF
│   │   ├── intelligence_layer.py  # 10 intel_* инструментов
│   │   ├── rate_limiter.py        # DebounceBatch + CircuitBreaker
│   │   ├── log_manager.py         # Централизованное логирование
│   │   └── ...
│   └── utils/
│       ├── ui_formatter.py        # ❗ НОВЫЙ — единый UI-форматтер
│       └── zed_config.py          # patch_zed_settings
├── docs/
│   ├── INSTALL.md                 # ❗ Полностью переписан
│   ├── architecture.md            # ⚠️ Исправлены числа
│   ├── investigations/
│   │   ├── 2026-07-05-lsp-zed-1.9.0.md         # LSP WONTFIX
│   │   └── 2026-07-05-active-workspace-resolution.md  # ❗ НОВЫЙ
│   └── HANDFOFF_TO_AI_AGENT.md    # ❗ НОВЫЙ — этот файл
├── scripts/
│   ├── check_lsp_health.py        # ❗ НОВЫЙ — диагностика
│   └── collect_telemetry.py
├── ZED_WINDOWS_QUIRKS.md          # ❗ Переписан
├── AGENTS.md                      # ⚠️ Добавлено multi-window правило
├── README.md                      # ⚠️ Карта документации + фиксы
└── CHANGELOG.md                   # ⚠️ Обновлён
```

---

## 3. ВАЖНЫЕ РЕШЕНИЯ И ПОДВОДНЫЕ КАМНИ

### 3.1 Как определяется проект (КРИТИЧНО)

`resolve_project_root()` в `src/mcp/server.py`, приоритет:

```
0. SQLite active_workspace_id (НОВЫЙ, главный!) ← работает на Windows
1. Явный project_root из аргументов
2. LSP Bridge — не работает на Windows
3. SQLite workspaces (старый fallback)
4. PROJECT_PATH из окружения
5. CWD — всегда отклоняется (self-indexing guard)
6. ext_root — fallback (режим самодиагностики)
```

**Ключевое:** `src/mcp/server.py`, строка ~310 — чтение `scoped_kv_store`:
```sql
SELECT value FROM scoped_kv_store 
WHERE namespace = 'multi_workspace_state'
```
Парсим JSON, берём `active_workspace_id`, ищем в `workspaces` таблице путь.

### 3.2 Почему LSP не работает (WONTFIX)

Исходники Zed: `lsp_store.rs:start_language_server()`:
```rust
let adapter = self.languages.lsp_adapters(name)
    .find(|a| a.name() == server_name)
    .expect("To find LSP adapter");
```

Кастомные имена (`mscodebase-lsp`) **невозможно зарегистрировать** через `settings.json`. Адаптер должен быть или встроенным (Rust), или из WASM-расширения. На Windows оба варианта недоступны без Rust/WASM-обёртки.

### 3.3 Дедлок DebounceBatch (исправлен)

`src/core/rate_limiter.py:169-201` — `_debounce_wait()` вызывал `await self._flush()` внутри `with self._lock:`. `threading.Lock` не reentrant — при повторном захвате на том же треде event loop блокируется навсегда.

Симптом: MCP зависает через ~5 секунд после пачки `notify_change`.

Фикс: решение о flush принимается под lock (`should_flush`, `should_exit` флаги), сам `await` — вне lock.

### 3.4 `_ext_root` — определение через PYTHONPATH

`src/mcp/server.py`, строка ~168:
```python
_pythonpath = os.environ.get("PYTHONPATH", "")
if _pythonpath:
    _ext_root = Path(_pythonpath.split(";")[0]).resolve()
else:
    _ext_root = Path(__file__).resolve().parent.parent.parent
```

**Зачем:** Если запустить `python -m src.main` из исходников (а не из установленного расширения), `__file__` укажет на `D:\Project\MSCodeBase`, а не на `%LOCALAPPDATA%\Zed\extensions\...`. Из-за этого `_reject_self_index_target()` отклонял правильный проект как self-indexing.

### 3.5 Где хранить конфиг семафора

Был в `settings.json` → `mscodebase.semaphore`. **Удалён** — Zed ругался на неизвестный корневой ключ. Теперь семафор (2 параллельных LLM-запроса) жёстко зашит в `install.py` как константа.

---

## 4. ЧТО ОСТАЛОСЬ НЕДОДЕЛАННЫМ

### 🔴 Важное

| Задача | Где | Суть |
|--------|-----|------|
| **UI formatter в остальные 40 инструментов** | `src/mcp/tools/*.py` | Интегрирован только в 3. Остальные возвращают `dict` → автоформат через `_format_success_response` |
| **`intel_get_telemetry` — улучшить вывод** | `intelligence_layer.py` | Уже есть, но можно через `format_telemetry` |

### 🟡 Среднее

| Задача | Где | Суть |
|--------|-----|------|
| **check_lsp_health интеграция** | `intel_diagnose()` | Сделать как инструмент, а не отдельный скрипт |
| **Multi-window warning в другие инструменты** | `search_code`, `get_repo_rank` | Сейчас только в `get_index_status` |
| **Auto-restart MCP** | Нет решения | На Windows не работает — ждём фикса от Zed |

### 🟢 Мелочи

| Задача | Где | Суть |
|--------|-----|------|
| `time` импортирован, но не используется | `system_tools.py:11` | Pre-existing warning |
| `pandas` импортирован, но не используется | `analysis_tools.py` | Pre-existing warning |
| `fastmcp` not found | `server.py:484` | Файл импортирует `FastMCP` из `openai` — возможно устаревший импорт |

---

## 5. ПРОТОКОЛ РАБОТЫ ДЛЯ AI-АГЕНТА

### 5.1 Первый шаг в сессии

```python
# 1. Прочитать AGENT_DIARY.md (первые 5 записей)
# 2. Прочитать этот файл (HANDFOFF_TO_AI_AGENT.md)
# 3. intel_get_runtime_status() — проверить проект
# 4. intel_get_project_memory() — ADR, known_issues
```

### 5.2 Если MCP не отвечает

- **Не retry** тот же инструмент. Pivot:
- Проверить процесс: `tasklist //FI "IMAGENAME eq python.exe"`
- Если процесс есть, но не отвечает — возможно дедлок (старый код)
- Если процесса нет — сказать пользователю: «перезапусти Zed (File → Quit)»

### 5.3 Если проект резолвится неверно

- Убедиться, что в `scoped_kv_store` есть `multi_workspace_state`
- Проверить `active_workspace_id`
- Если показывает не тот проект — пользователь переключился. Спросить.

### 5.4 После изменений

```python
# 1. diagnostics() для изменённых файлов
# 2. notify_change(file_path) для обновления индекса
# 3. intel_log_incident(component, symptom, root_cause, fix)
# 4. AGENT_DIARY.md — запись о сделанном
```

---

## 6. КЛЮЧЕВЫЕ ФАЙЛЫ ДЛЯ БЫСТРОГО СТАРТА

| Файл | Зачем читать |
|------|-------------|
| `src/mcp/server.py` | resolve_project_root, ext_root, регистрация инструментов |
| `src/core/rate_limiter.py` | DebounceBatch (был дедлок), CircuitBreaker |
| `src/core/log_manager.py` | Централизация логов (v2.4.6) |
| `src/utils/ui_formatter.py` | ❗ НОВЫЙ — единый формат вывода |
| `ZED_WINDOWS_QUIRKS.md` | ❗ Все Windows-особенности в одном месте |
| `docs/investigations/2026-07-05-active-workspace-resolution.md` | ❗ Полный аудит всех механизмов Zed |

---

## 7. ПОЛЕЗНЫЕ КОМАНДЫ

```bash
# Синхронизация изменений в расширение
python install.py

# Проверка индекса (из чата Zed)
get_index_status()

# Проверка здоровья
intel_get_runtime_status()

# Запуск индексации
intel_trigger_reindex()

# Телеметрия
intel_get_telemetry()

# Диагностика LSP (если установка)
python scripts/check_lsp_health.py
```
