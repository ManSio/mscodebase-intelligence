# MSCodeBase — правила для AI-агентов

> Локальный MCP-сервер для навигации по коду: Tree-sitter → SQLite FTS5/BM25 + PropertyGraph.
> Числа и версии здесь не дублируются — только `docs/FACTS.md` с командой перевывода.
> Глобальные правила (уровни задач, TDD, ревью, Git, секреты, DoD) — `~/.config/opencode/AGENTS.md`;
> этот файл их не повторяет, а добавляет проектное. Размер держит `scripts/check_agents_md.py`.

## 1. Кто клиент

Любой MCP-хост: OpenCode, Zed, Claude Code, Cursor, generic `mcpServers`
(`docs/en/CLIENTS.md`). `install.py` создаёт обычное Python-окружение в
`MSCODEBASE_INSTALL_ROOT` (по умолчанию — исторический
`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`; к Zed относится только имя).
Zed — опциональный адаптер (`--no-zed`); конфиг для остальных печатает
`python install.py --print-config --client <generic|opencode|zed|claude-code|cursor>`.

## 2. Первые шаги в сессии

1. MCP живой? `tool_help()` → профиль и видимые инструменты; `get_health_report()` → индекс, провайдеры.
2. Память проекта: `intel_get_project_memory()`.
3. Индекс: `codebase(action="index", path="status")`. `total_chunks = 0` — индекс не построен,
   а **не** «ничего не найдено». Только граф — `python scripts/rebuild_graph.py`;
   `experiments/**` намеренно не индексируется.
4. Дерево: `git worktree list`, `git status`. Чужие незакоммиченные файлы — не коммитить.

### Как вызываются инструменты

- Из хоста — обычный вызов по имени.
- Из скриптов/CI — CLI-мост: `python -m src.cli <tool> '<json>' [--project <root>]`.
- Transport error → fallback `grep`/`read`, но не выдавать это за результат MCP.
- Ошибка не повторяется теми же аргументами: сначала здоровье MCP, затем смена входа.
- Профили: `MSCODEBASE_MCP_PROFILE=core` (по умолчанию) / `full`; что скрыто — `tool_help()`.

## 3. MCP-FIRST

Пока MCP отвечает, исследование кода идёт через него.

| Задача | Не использовать | Использовать |
|---|---|---|
| Вопрос по смыслу, один вход | `search_code` руками | `investigate(query)` |
| Точное имя файла/символа | `grep` | `search_code(mode="fast")` |
| Regex с AST-контекстом | `grep` | `grep_code(scope="code")` |
| Определение, вызовы | `grep` | `get_symbol_info` |
| Что сломается при правке | чтение файлов | `impact_analysis` |
| Связи, поток переменной | `grep` | `graph_query` |
| Статус индекса, git, правки | shell `git`/`cat` | `codebase(action=...)` |
| Прочитать файл | весь файл | `read_live_file` (диапазон) |
| Файл изменился | полный reindex | `notify_change` |

Режимы `search_code`: `auto` (по умолчанию — выбирает сам), `fast` (точное имя), `quality`,
`deep` (архитектура), `context` (по фрагменту). Fallback `grep` разрешён, если MCP недоступен,
`total_chunks = 0`, идёт правка файлов или операция среды; >10 файлов — batch-grep с блоком
`[🔍 BATCH CHECK]`.

`codebase(action=…)` — хаб: `index` (status/progress/health/project_dir), `git`
(log/history/branch), правки `rename`/`move`/`safe_delete`/`replace`/`insert_before`/`insert_after`
(с preview и impact-guard: деструктивные — только после `ack_impact`).

### Intel Intelligence Layer (16 tools)

`intel_get_project_memory`, `intel_add_memory_node`, `intel_supersede_memory_node`,
`intel_retract_memory_node`, `intel_restore_memory_node`, `intel_log_incident`,
`intel_analyze_incident`, `intel_auto_collect_adrs`, `intel_code_topology`,
`intel_get_hotspots`, `intel_get_runtime_status`, `intel_get_job_status`, `intel_get_telemetry`,
`intel_predict_root_cause`, `intel_reset_index`, `intel_trigger_reindex`.
Узлы `SUPERSEDED`/`REFUTED` — не факт: противоречащий коду узел перекрывается или отзывается,
а не «остаётся как есть».

## 4. Цикл доставки: исходники → установка → хост

- **Исходники:** этот репозиторий. **Установленное:** `MSCODEBASE_INSTALL_ROOT`
  (venv + код + опциональные модели); данные, логи и кэши — `MSCODEBASE_DATA_DIR`
  (`docs/en/DATA_MAP.md`).
- Хост запускает MCP как `<install-root>/venv/Scripts/mscodebase-mcp.exe -u -m src.main`
  с `PYTHONPATH` на каталог установки и `PROJECT_PATH` = рабочая папка.
- После правки кода: `python install.py --sync-only` → перезапуск хоста → `tool_help()`.
- `install.py --doctor [--json]` — что стоит и сколько весит; `--clean [--dry-run]`,
  удаление только с `--yes`.
- Правок нет в каталоге установки — в рантайме их нет: «работает» проверяется после sync + restart.

## 5. Структура корня

Разрешено: `src/`, `tests/`, `scripts/`, `tools/`, `docs/`, `experiments/`, `adapters/`,
`extensions/`, `deploy/`, `locales/`, `examples/`, `logo/`, `telemetry/`, `.githooks/`,
`.github/`, `.opencode/`, `.locks/`; реестры — `AGENT_DIARY.md`, `KNOWN_ISSUES.md`,
`EXPERIMENTS_LOG.md`, `WISDOM.md`, `ISSUE.md`; пакет и установка — `pyproject.toml`,
`requirements.txt`, `requirements-lock.txt`, `MANIFEST.in`, `install.py`, `uninstall.bat`,
`start_server.bat`, `start_remote.bat`, `extension.toml`, `__mscodebase_ext__.marker`;
метаданные — `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`, `ruff.toml`.

`docs/generated/MODULE_INDEX.md` — генерируемый, не трекается. Одноразовые скрипты и логи
в корне запрещены.

## 6. Контракт правки

- Прочитать файл → `impact_analysis` (риск средний и выше) → точечная правка, стиль соседнего кода.
- После `edit`/`write` — `notify_change(file_path)`, затем `codebase(action="index", path="status")`.
- Переименование файла — `codebase(action="move")` (под капотом `apply_file_move`), не полный reindex.
- Память проекта: найденный техдолг/инцидент — `intel_add_memory_node`/`intel_log_incident`;
  узел, противоречащий коду, — `intel_supersede_memory_node`/`intel_retract_memory_node`.
- Windows: `subprocess` в фоновом потоке — `Popen(stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL)`
  + `communicate(timeout)` + `CREATE_NO_WINDOW`; `capture_output`/`check_output` вешают пайп.
- PowerShell: `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`, иначе кириллица в логах ломается.

## 7. Запреты проекта

- Устаревшие имена (deprecated, не использовать): `smart_search`, `deep_search`, `context_search`,
  `get_index_status`, `rename_symbol`.
- Блокирующий `codebase(action="index", path="project_dir")` — только `scripts/reindex_text_only.py`
  или `intel_trigger_reindex`.
- Слои: `core` не импортирует `mcp`; инструмент не обходит `RuntimeCoordinator`/`ProjectContext`
  своей проверкой готовности. Новый компонент обязан ответить: какой существующий слой он расширяет.
- Файл >800 строк в `core/`/`providers/` — триггер декомпозиции (или запись в `KNOWN_ISSUES.md`).
- Windows: MCP-пути в `\`-форме, терминал (PowerShell/GitBash) — в `/`.
- Заглушки, `TODO/FIXME`, `NotImplementedError`, `print` в stdout (ломает JSON-RPC).
- `git add -A`, `git add .`, `git commit -a` — только явные пути.
- Чужие данные: личные email, чужие тексты целиком, дампы страниц (`scripts/check_third_party_data.py`).
- Секреты: `.env`, ключи, токены — только имена и структура, значения не читать.
- Один писатель на реестр; параллельная работа — свой worktree.

## 8. Проверка перед сдачей (проектное; общее — глобальный протокол)

1. Индекс обновлён (`notify_change` → статус).
2. `python -m pytest tests/ -q` зелёный; slow-тесты отдельно (`-m "not benchmark"`).
3. `ruff check src/ tests/` — чисто (как в CI; `scripts/` вне этого прогона, для него
   `scripts/ruff_gate.py` — проверяет только изменённые файлы).
4. Хуки активны (`core.hooksPath = .githooks`). Docs-only коммит пропускает gate-zero (полный
   pytest) — поэтому гейты документации живут в самом хуке, а не только в тестах.
   `MSCB_PRECOMMIT_FAST=1` — только когда полный прогон всё равно уходит в CI.
5. Для индекса/провайдеров — `python scripts/smoke_e2e.py --project .`.
6. CI: `gh run list --branch <ветка>`, `gh run view <id> --log-failed`; чек-лист PR —
   `.github/pull_request_template.md`.
7. Корень чистый, реестры синхронны.

## 9. Где правда

- Числа (инструменты, чанки, тайминги) — `docs/FACTS.md` вместе с командой перевывода.
- Канон документации — `README.md`, `docs/en/ARCHITECTURE.md`, `docs/en/SEARCH_PIPELINE.md`,
  `docs/en/INSTALL.md`, `docs/en/CLIENTS.md`, `docs/en/DATA_MAP.md`, `docs/en/CONFIGURATION.md`
  (переводы — `docs/ru/`, `docs/zh/`).
- Канонические страницы — три языка (EN/RU/ZH), полный перевод, числа совпадают с EN.
  `KNOWN_ISSUES.md` — лимит держит `scripts/check_known_issues.py`; закрытое уезжает в
  `docs/archive/KNOWN_ISSUES_YYYY_MM.md`; `docs/blog/`, `docs/research/`, `docs/archive/` не переписываются.
  ID записей: `EXP-N`, `ADR-NNN`, `YYYY-MM-DD-slug`.
- «Документация = код» держат `scripts/check_docs_vs_installer.py`, `scripts/check_docs_vs_config.py`,
  `scripts/check_docs_refs.py`; этот файл — `scripts/check_agents_md.py` (пути существуют, флаги и
  переменные есть в коде, версия совпадает с `pyproject.toml`, размер в лимите).
