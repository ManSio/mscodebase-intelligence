# Архитектура

> Перевод: 2026-11-08, источник — docs/en/ARCHITECTURE.md. Английская версия — канон.

> Переписано 2026-11-08. Описывает дефолтный runtime Phase 3 (text-first:
> SQLite FTS5/BM25 + PropertyGraph). Vector/LanceDB, эмбеддинги, реранкер и
> LSP rename — опциональные слои, и они помечены как таковые.
> Числа живут в [FACTS.md](../FACTS.md); эта страница объясняет устройство, а не счётчики.
> Настройка клиента: [CLIENTS.md](CLIENTS.md). Конфигурация: [CONFIGURATION.md](CONFIGURATION.md).
> Гейты коммитов: [HOOKS_AND_GATES.md](HOOKS_AND_GATES.md).

## 1. Слои

```text
┌───────────────────────────────────────────────────────────────────┐
│ Клиент: хост MCP — OpenCode (основной) или Zed (stdio, JSON-RPC)  │
├───────────────────────────────────────────────────────────────────┤
│ Слой инструментов  src/mcp/tools/*                                │
│   investigate · search_code · grep_code · get_symbol_info         │
│   impact_analysis · graph_query · хаб codebase · lifecycle        │
│   каждый инструмент обёрнут в @error_boundary (timeout + envelope)│
├───────────────────────────────────────────────────────────────────┤
│ Intelligence       src/core/intelligence/*                        │
│   память проекта · инциденты · health · jobs · телеметрия         │
├───────────────────────────────────────────────────────────────────┤
│ Сервисы ядра       src/core/search, src/core/indexing, graph      │
│   Searcher · SQLiteChunkStore · Indexer · PropertyGraph           │
├───────────────────────────────────────────────────────────────────┤
│ Провайдеры         src/providers/*   (опционально)                │
│   эмбеддеры llama.cpp/ONNX/LM Studio/Ollama · реранкер BGE-M3     │
└───────────────────────────────────────────────────────────────────┘
```

Правила, которые обеспечивает линтер архитектуры (`scripts/architecture_linter.py`)
и гейт границ слоёв:

- `core` никогда не импортирует `mcp`; инструменты зависят от core, а не наоборот.
- Готовность определяет `RuntimeCoordinator`; инструменты не перепроверяют его решение.
- Каждый инструмент — один файл (или один класс) с одной ответственностью; хаб
  `codebase` диспетчеризует по `action`, вместо того чтобы плодить новые
  инструменты верхнего уровня.

## 2. Сборка и жизненный цикл

`src/main.py` → `create_mcp_server()` (`src/mcp/server_factory.py`):

1. Собрать DI-контейнер (`src/core/di_container.py`) с путями данных из
   `src/core/artifact_paths.py`.
2. Зарегистрировать инструменты ядра, затем intel, inline-диагностику и dev-инструменты
   (`register_all_tools`).
3. Применить **профиль инструментов** (`_apply_tool_profile`): полный реестр
   собирается целиком (все 69 инструментов), затем всё, что вне `CORE_PROFILE`,
   удаляется из клиентской поверхности. Регистрация не зависит от профиля — это
   утверждение было ложным до 2026-11-08, когда жёстко заданный дефолтный allowlist
   всё ещё урезал регистрацию до 56 имён, а `_apply_tool_profile` выполнялся раньше,
   чем регистрировались dev-инструменты. Теперь инвариант закреплён в
   `tests/test_tool_profile.py` (`test_core_profile_registers_full_registry_then_hides`).
4. Запустить stdio-транспорт; провайдеры и реестр противоречий стартуют в фоне,
   чтобы рукопожатие никогда не блокировалось.

Жизненный цикл одного запроса: `require_ready_project()` → тело инструмента →
`error_boundary` оборачивает результат (таймаут, телеметрия, структурированная
ошибка). Инструменты поиска перед запросом также запускают троттлингованную проверку
свежести (hot-reload).

## 3. Хранилище

| Что | Где | Формат |
|---|---|---|
| Текстовые чанки + индекс FTS5 | `<project>/.mscodebase/chunks.db` | SQLite |
| Граф (символы, рёбра, мета) | `<data_root>/projects/<hash>/graph.db` | SQLite (PropertyGraph) |
| Память проекта, инциденты, jobs | `<data_root>/projects/<hash>/intelligence/` | JSON |
| Память коммитов | `<data_root>/projects/<hash>/commit_memory/` | JSON |
| Логи, телеметрия | `<data_root>/logs/`, `<data_root>/projects/<hash>/telemetry/` | файлы |
| Таблица векторов (опционально) | `<data_root>/projects/<hash>/lancedb_v2/` | LanceDB |

`<data_root>` — это `MSCODEBASE_DATA_DIR`, иначе `%LOCALAPPDATA%/mscodebase`
(Windows) или `~/.cache/mscodebase`. Внутри проекта лежат только `chunks.db` и
`.mscodebase/`, и оба в gitignore.

## 4. Индексация

Две точки входа, один конвейер:

- **Полный текстовый индекс** — `scripts/reindex_text_only.py`: обход (с исключениями
  FileGuard), разбор через Tree-sitter, запись чанков в SQLite, а символов и рёбер —
  в граф. Без эмбеддингов.
- **Инкрементальная** — `FreshnessChecker` сравнивает `(mtime, size, hash)` файлов
  на диске с хранилищем SQLite, переиндексирует изменённые/новые файлы и вычищает
  удалённые. Работает с троттлингом (по умолчанию 30 с) после поисков и при старте
  через задачу автоиндексации, когда хранилище пусто.

`experiments/**` исключён из индексации через `SystemArtifacts`
(`src/core/indexing/file_guard.py`): замороженные панели не должны протекать в
выдачу поиска.

## 5. Стек поиска

`Searcher` (`src/core/search/engine.py`) отвечает за retrieval:

- **Путь Phase 3** — кандидаты SQLite FTS5 (лимит × 4, с потолком), опциональный
  реранк верхней части пула по запросу; доступа к LanceDB нет.
- **Короткое замыкание по идентификатору** — запросы, похожие на идентификатор,
  идут сразу в графовую стадию за точным расположением.
- **Маршрутизация документов** — один дополнительный FTS-запрос по `docs/**`; если
  лучший счёт документов превышает лучший счёт кода на `MSCODEBASE_DOCS_MARGIN` (4.0),
  побеждают документы.
- **Legacy dense-путь** — только когда `MSCODEBASE_DENSE_OFF=false` и доступен
  провайдер.

Детали и бюджеты стадий — в [SEARCH_PIPELINE.md](SEARCH_PIPELINE.md).

## 6. Слой инструментов

**Зарегистрировано 69** инструментов (36 core + 16 intel + 13 inline + 4 dev);
дефолтный профиль `core` открывает **17**. `execute_script` — опциональный 70-й
инструмент за `MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`.

Видимый набор — одна запись на намерение: `investigate`, `search_code`,
`grep_code`, `get_symbol_info`, `impact_analysis`, `graph_query`, `codebase`,
`read_live_file`, `notify_change`, `get_health_report`,
`intel_get_project_memory`, `predict_change`, `tool_help`, плюс четыре dev-инструмента.
`MSCODEBASE_MCP_PROFILE=full` открывает всё; `MSCODEBASE_MCP_TOOLS` остаётся явным
allowlist.

`investigate` — двухпроходный веер: проход 1 параллельно запускает поиск, символы и
grep; проход 2 запускает impact, вызывающие, тесты и память проекта по тому, что
нашёл проход 1. Результаты сливаются по `(file, line)` и несут набор каналов, которые
нашли каждый элемент; канал, ушедший в таймаут, попадает в `degraded[]`.

`codebase(action=…)` — хаб: `index` (status/progress/health/timeline),
`git` (log/history/branch) и действия записи (rename/move/safe_delete/
replace/insert) с preview и impact-guard.

## 7. Безопасность и поведение при отказах

- У каждого инструмента есть таймаут; зависший провайдер ухудшает ответ, но не
  замораживает сервер.
- Инструменты поиска и записи отказываются работать на пустом индексе, вместо того
  чтобы вернуть «ничего не найдено» (пустое и сломанное должны выглядеть по-разному).
- Записи выполняются с предпросмотром; деструктивные действия требуют токен
  подтверждения impact.
- Подпроцессы запускаются через `Popen(stdin=DEVNULL, stdout=PIPE,
  stderr=DEVNULL) + communicate`; `capture_output=True` приводит к взаимной
  блокировке, когда stdout сервера — это JSON-RPC-пайп (AGENTS.md §5.16).
- Реестр противоречий (при старте, кеш 6 ч) проверяет утверждения `✅` в
  `AGENT_DIARY.md` против кода; о его собственных сбоях сообщается, они никогда
  не игнорируются молча.

## 8. Опциональные слои

- **Эмбеддинги/реранкер:** llama.cpp GGUF, ONNX, LM Studio или Ollama;
  используются реранком по запросу и legacy dense-путём.
- **LSP:** ссылки/определения/диагностика на базе basedpyright, с жёстким
  бюджетом запуска и кешем отказов на 30 с.
- **Векторное хранилище:** LanceDB, только когда включён dense-retrieval.

Ни один из них не нужен для дефолтного text-first пути.

## 9. Ссылки на код (аудит 2026-11-12)

| Утверждение на странице | Код |
|---|---|
| точку входа строит сервер, сначала DI | `src/main.py::main`, `src/mcp/server_factory.py::create_mcp_server` (строка 156), `src/core/di_container.py` |
| раскладка артефактов | `src/core/artifact_paths.py::get_data_root`, `::project_hash`, `::get_graph_db_path`, `::get_logs_dir` |
| чанки в `<project>/.mscodebase/chunks.db` | `src/config/settings.py::SearchConfig.sqlite_chunks` |
| `experiments/**` исключён из индексации | `src/core/indexing/file_guard.py` |
| владелец поиска | `src/core/search/engine.py::Searcher` |
| парсинг и граф | `src/core/indexing/parser.py`, `src/core/graph.py` |
| профиль `core` = 17 из 69 | `src/mcp/server_tools.py::CORE_PROFILE`; замер `tools/list`: 17 / 69, 2026-11-12 |
| опциональный LSP-слой | инструменты `lsp_*`, кеш отказов 30 с (`src/config/settings.py::LSPConfig`) |

