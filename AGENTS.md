# MSCodeBase — правила для AI-агентов

> Файл для агентов, которые работают **в этом репозитории**.
> Проверено по коду 2026-11-08 (`main` @ `1bf94af`, версия `3.5.0`).
> Канон чисел (индекс, качество, тайминги) — `docs/FACTS.md`; здесь — правила и
> проверенные факты, а не пересказ документации.

**Что это за проект.** Локальный MCP-сервер: индексирует репозиторий (Tree-sitter →
SQLite FTS5/BM25 + PropertyGraph), отвечает на вопросы о коде, даёт impact/граф/память
проекта и безопасные правки. По умолчанию работает **без эмбеддингов и без LanceDB**
(`MSCODEBASE_DENSE_OFF=true`).

**Кто клиент.** Сейчас основной хост — **OpenCode**; расширение Zed остаётся рабочим
вариантом. `install.py` в обоих случаях доставляет код в каталог расширения
(`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`), откуда MCP запускается.
Отсюда правило: после правки кода сервера — `python install.py --sync-only` и
**перезапуск хоста** (сессия OpenCode / окно Zed), иначе работает старый процесс.

---

## §0. Первые шаги в сессии

1. **Проверить MCP.** В профиле `core` доступны `get_health_report` и `tool_help`
   (`debug_runtime_passport` скрыт до `MSCODEBASE_MCP_PROFILE=full`):
   ```
   tool_help()          → активный профиль, видимые и скрытые инструменты
   get_health_report()  → индекс, провайдеры, ресурсы
   ```
   Ответ пришёл → MCP живой, работаем через него. Transport error → MCP не
   подключён: перейти на `grep`/`read`, но не выдавать это за результат MCP.
2. **Память проекта:** `intel_get_project_memory()` — ADR, инциденты, техдолг.
   Узлы со статусом `SUPERSEDED`/`REFUTED` не использовать как факт.
3. **Состояние индекса:** `codebase(action="index", path="status")`. `total_chunks = 0`
   → семантический поиск запрещён, пока индекс не пересобран.
4. **Границы территории:** `git worktree list` и `git status`. Если в дереве есть
   чужие незакоммиченные файлы — не коммитить их (см. §6, «Параллельные сессии»).

### §0.1. Как вызываются инструменты

- **Из OpenCode/Zed-агента** — обычный вызов инструмента по имени (`search_code`,
  `investigate`, …). Никакого ручного JSON-RPC не требуется.
- **Из скриптов, CI и хуков** — CLI-мост без MCP-протокола:
  ```
  python -m src.cli <tool> '<json-args>' [--project <root>]
  echo '<json>' | python -m src.cli <tool> -
  ```
  Пример: `python -m src.cli stale_detector '{}'`.
- Один вызов — один инструмент. Не собирать несколько инструментов в один вызов.
- Ошибка инструмента не повторяется теми же аргументами: сначала проверить
  здоровье MCP, затем сменить вход (другой инструмент/аргумент).

### §0.2. MCP-FIRST

Пока MCP отвечает — исследование кода идёт через него, не через `grep`/чтение файлов.

| Задача | ❌ Не использовать | ✅ Использовать |
|---|---|---|
| Вопрос по смыслу, один вход | `search_code` вручную + grep | `investigate(query)` — search + symbols + grep + impact/callers/tests/память |
| Точное имя файла/символа | grep | `search_code(mode="fast")` |
| Regex с AST-контекстом | grep | `grep_code(scope="code")` |
| Определение/вызовы/вызываемые | grep | `get_symbol_info` |
| Что сломается при правке | чтение файлов | `impact_analysis` |
| Связи, поток переменной, cypher | grep | `graph_query` |
| Статус индекса, git, write-actions | shell `git`/`cat` | `codebase(action=...)` |
| Прочитать файл | `cat` целиком | `read_live_file` (только нужный диапазон) |
| Файл изменился | полный reindex | `notify_change` |
| Архитектура / горячие точки | чтение | `investigate`, `graph_query`, `predict_change` |

**Fallback разрешён**, только если: MCP transport error/timeout; `total_chunks == 0`
(до пересборки); правка файлов (`edit`/`write`); операции среды (`pytest`, `install.py`,
git commit/push); два подряд отказа MCP на одном инструменте.

**Batch-исключение:** >10 файлов/символов — допустим `rg`/grep с явным блоком
`[🔍 BATCH CHECK] Задача / Объём / Обоснование / Результат`. ≤10 — только MCP.

**Запрещено при живом MCP:** `grep` вместо `search_code`; чтение файла целиком вместо
`read_live_file`/`get_symbol_info`; `git log` вместо `codebase(action="git", …)`;
угадывание номеров строк.

### §0.5. Цикл доставки: исходники → расширение → хост

- **Исходники:** этот репозиторий. **Установленное:** каталог расширения
  `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence` (venv + код + модели).
- OpenCode запускает MCP как `…\extensions\mscodebase-intelligence\venv\Scripts\mscodebase-mcp.exe
  -u -m src.main` с `PYTHONPATH` на каталог расширения (`PROJECT_PATH` = рабочая папка).
- Порядок после правки кода:

  ```
  1. правка в src/… (после edit → notify_change)
  2. python install.py --sync-only     # код, без pip/llama/GGUF
  3. перезапустить хост: сессию OpenCode (или окно Zed)
  4. проверить: tool_help() / get_health_report()
  ```

- `python install.py` (без флагов) — интерактивная полная установка (pip, llama.cpp,
  модели). Запускать только по явной задаче.
- Правки, которых нет в расширении, в рантайме не существуют — «работает» проверять
  только после sync + restart.

### §0.6. Структура корня

Разрешённый набор (проверено `git ls-files` на 2026-11-08):

- **Код:** `src/`, `tests/`, `scripts/`, `tools/`, `docs/`, `experiments/`
- **Интеграции:** `adapters/` (клиентские MCP-конфиги), `extensions/`, `deploy/` (Docker),
  `locales/`, `examples/`, `logo/`, `telemetry/`
- **Хуки и CI:** `.githooks/`, `.github/`, `.opencode/` (plugin + commands), `.locks/`
- **Правила и реестры:** `AGENTS.md`, `AGENT_DIARY.md`, `KNOWN_ISSUES.md`,
  `EXPERIMENTS_LOG.md`, `WISDOM.md`, `ISSUE.md`
- **Пакет и установка:** `pyproject.toml`, `requirements.txt`, `requirements-lock.txt`,
  `MANIFEST.in`, `install.py|bat|sh`, `uninstall.bat`, `start_server.bat`,
  `start_remote.bat`, `extension.toml`, `__mscodebase_ext__.marker`
- **Метаданные репозитория:** `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `SECURITY.md`, `CODE_OF_CONDUCT.md`, `AI_INSTALLATION_PROMPT.md`, `LICENSE`,
  `ruff.toml`, `.gitignore`, `.dockerignore`, `.coveragerc.ci`, `.env.example`,
  `DEV_DIARY.md` (редирект)

**Запрещено:** одноразовые скрипты/логи/выводы тестов в корне; второй дневник или
второй `KNOWN_ISSUES.md`; файлы вне списка без причины. `docs/generated/MODULE_INDEX.md`
— генерируемый артефакт, он **не** трекается.

---

## §1. Выбор инструмента

### §1.1. Замещения

| Вместо | Использовать |
|---|---|
| `codebase(action="index", path="project_dir")` (блокирующе) | `scripts/reindex_text_only.py` или `intel_trigger_reindex` (полный профиль) |
| Ручной обход нескольких инструментов | `investigate` (один вход, параллельные каналы) |
| `smart_search` / `deep_search` / `context_search` | не существуют (deprecated/удалены) — `search_code(mode=…)` |
| `get_index_status` / `rename_symbol` (старые имена) | `codebase(action="index", …)`, `codebase(action="rename", …)` |

### §1.2. Режимы поиска

`search_code(query, mode=…)` — единственный поисковый инструмент:

| mode | Когда | Ориентир |
|---|---|---|
| `fast` | точное имя файла/переменной | ~1.4 s на этом репо |
| `quality` | логика, архитектура, связи (по умолчанию) | ~5 s |
| `deep` | сложное архитектурное расследование | 5 s+ |
| `context` | поиск по фрагменту кода | ~0.5 s |
| `auto` | автовыбор | — |

### §1.3. Профиль инструментов

Регистрируются **все 69** (36 core + 16 intel + 13 inline + 4 dev; `execute_script` —
опциональный 70-й при `MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`). Наружу отдаётся
профиль:

| Профиль | Видимо | Как включить |
|---|---:|---|
| `core` (по умолчанию) | **17** | — |
| `full` | **69** | `MSCODEBASE_MCP_PROFILE=full` + перезапуск хоста |

`MSCODEBASE_MCP_TOOLS=a,b,c` — явный allowlist, перекрывает профиль. Что скрыто и
как включить — всегда `tool_help()`; не полагаться на список из памяти.

---

## §2. Инструменты

`core` (17): `investigate`, `search_code`, `grep_code`, `get_symbol_info`,
`impact_analysis`, `graph_query`, `codebase`, `read_live_file`, `notify_change`,
`get_health_report`, `intel_get_project_memory`, `predict_change`, `tool_help`,
`generate_docs`, `bump_version`, `auto_update_docs`, `install_git_hooks`.

`full` (69) добавляет: `debug_runtime_passport`, `intel_add_memory_node`,
`intel_analyze_incident`, `intel_auto_collect_adrs`, `intel_code_topology`,
`intel_execution_timeline`, `intel_explain_project_state`, `intel_get_hotspots`,
`intel_get_job_status`, `intel_get_project_context`, `intel_get_runtime_status`,
`intel_get_telemetry`, `intel_log_incident`, `intel_predict_root_cause`,
`intel_reset_index`, `intel_restore_memory_node`, `intel_retract_memory_node`,
`intel_supersede_memory_node`, `intel_trigger_reindex`, `lsp_*` (6), `plan_search`,
`structural_search`, `submit_background_task`/`get_task_status`/`verify_action`/
`get_action_receipt`, `ack_impact`, `get_logs`, `get_runtime_counters`,
`dual_arm_health_check`, `stale_detector`, `bootstrap_pipeline`, `cross_repo_search`,
`cross_project_deps`, `detect_communities`, `find_duplicates`, `find_similar_bugs`,
`get_bug_correlation`, `get_context`, `get_repo_map`, `get_repo_rank`,
`generate_chunk_summaries`, `set_project`, `refresh_db_connection`, `execute_script`.

`codebase(action=…)` — хаб, а не отдельные тулы:
`index` (status/progress/health/timeline/project_dir), `git` (log/history/branch),
`rename`/`move`/`safe_delete`/`replace`/`insert_before`/`insert_after` (с preview и
impact-guard).

`investigate(query, limit=8)` — основной вход: проход 1 (search+symbols+grep
параллельно), проход 2 (impact/callers/tests/project memory по найденному), слияние
по `(file, line)`, `degraded[]` для медленных каналов. Заменяет ручной перебор
инструментов для вопроса «где и почему».

---

## §3. Состояние и готовность

- `codebase(action="index", path="status")` → `total_chunks`, `unique_files`.
  Ноль чанков — **не** «ничего не найдено», а «индекс не построен».
- Полная пересборка текста и графа без эмбеддингов:
  `python scripts/reindex_text_only.py --project .` (снапшот: 498 файлов, 7 375 чанков,
  262–266 s — `docs/FACTS.md`).
- Пустой только граф: `python scripts/rebuild_graph.py`.
- `experiments/**` намеренно исключён из индексации (`FileGuard`): артефакты прогонов
  не должны попадать в выдачу.
- После правки файла — `notify_change`, не полный reindex.
- Готовность инструментов решает `RuntimeCoordinator`; инструмент не дублирует эту
  проверку своим кодом.

---

## §4. Память проекта

1. В начале — `intel_get_project_memory()`.
2. После инцидента/решения — `intel_log_incident` (полный профиль) с компонентом,
   симптомом, root cause, фиксом.
3. Замеченный анти-паттерн — `intel_add_memory_node(section="tech_debt", …)`.
4. Дрейф: узел памяти, противоречащий коду, — `intel_supersede_memory_node` /
   `intel_retract_memory_node`, не «оставить как есть».
5. Память недоступна → факты непроверены, помечать явно.

---

## §5. Контракт выполнения

### Reconnaissance
- Не угадывать номера строк: `get_symbol_info` / `search_code`, затем `read_live_file`.
- Читать только нужный диапазон; целые файлы — исключение (конфиг, маленький модуль).
- Перед правкой символа — `impact_analysis` (blast radius) и классификация риска.

### Write
- Сначала прочитать изменяемый файл в этой сессии; затем точечный `edit`.
- Сохранять стиль и отступы окружающего кода; минимальный diff.
- Деструктивные операции (`codebase(action="safe_delete")`, rename) — только с
  impact-guard и подтверждением (`ack_impact`).

### Post-modification
- `edit`/`write` → `notify_change(file_path)` (батч: список путей).
- Переименование файла — `apply_file_move`, а не полный reindex.
- Затем `codebase(action="index", path="status")` — индекс должен видеть правку.

### Error handling
- Не повторять тот же вызов с теми же аргументами. Две неудачи одной гипотезы →
  сменить гипотезу или остановиться и спросить.
- Молчание инструмента ≠ успех: смотреть `ok`, код возврата и содержимое.

### Windows
- MCP-пути: `src\\core\\config.py`. Терминал (PowerShell/GitBash): `src/core/config.py`.
- Кодировка вывода: `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` перед
  командами, иначе кириллица в логах ломается.
- `subprocess` в фоновом потоке MCP: только `Popen(stdin=DEVNULL, stdout=PIPE,
  stderr=DEVNULL) + communicate(timeout)` + `CREATE_NO_WINDOW`. `capture_output=True` /
  `check_output` в потоке с перенаправленным stdout вешают пайп (Windows).
  `Popen.communicate` ловит `TimeoutExpired`, затем `kill()` + повторный `communicate`.
- Не запускать дочерние процессы в демон-потоках без таймаута.

---

## §6. Запреты

### Устаревшее
- `smart_search`, `deep_search`, `context_search` — устаревшие (deprecated) имена, таких инструментов нет.
- Блокирующий `codebase(action="index", path="project_dir")` — использовать скрипт
  пересборки или `intel_trigger_reindex` (full).
- `get_index_status`, `rename_symbol` — старые имена; см. §1.1.

### Архитектура
- Слои: `core` не импортирует `mcp`; инструменты зависят от core, не наоборот
  (`scripts/check_layer_boundaries.py`, `scripts/architecture_linter.py`).
- Инструмент не обходит `RuntimeCoordinator`/`ProjectContext` своей проверкой
  готовности.
- Новый компонент обязан ответить: какой существующий слой он расширяет.
- Один класс — одна ответственность. Файл >800 строк в `core/`/`providers/` —
  триггер декомпозиции (или запись в `KNOWN_ISSUES.md`).
- Без заглушек и TODO в проде; без отладочных `print` в stdout (ломает JSON-RPC).

### Окружение
- Локально не требуются Docker/WSL; образ собирается в CI (`docker-build`), конфиги —
  `deploy/docker/`.
- Зависимости — только точные пины (`==`); источник истины `pyproject.toml`, зеркало
  `requirements.txt`, заморозка `requirements-lock.txt`. Дрейф ловит
  `scripts/check_lock_drift.sh`.

### Гигиена репозитория (§0.6)
- Никаких одноразовых скриптов, логов и выводов тестов в корне.
- Один дневник (`AGENT_DIARY.md`) и один `KNOWN_ISSUES.md`. Второй файл — мёрдж, не
  параллельная копия.
- Коммит — только явные файлы: `git add <paths>`. `git add -A`, `git add .`,
  `git commit -a` запрещены: заберут чужую незакоммиченную работу.

### Чужие данные (репозиторий публичный, MIT)
- Не коммитить выгрузку чужих страниц/профилей: личные email, чужие тексты целиком.
- Допустимо: свой вывод, `sha256`, URL источника, короткая цитата по делу.
- Вне репозитория: сырьё и дампы — в `<data_root>/audit-cache/<задача>/`.
- Гейт: `scripts/check_third_party_data.py` (R1/R2 блокируют, R3 advisory).
- Лицензия: дословная копия чужого текста притаскивает чужую лицензию (NC/share-alike).

### Параллельные сессии
1. Одно рабочее дерево = одна сессия = одна задача. Параллельно — свой `worktree`.
2. Ветка = территория; не переключать её в чужом дереве.
3. Реестры принадлежат одной сессии; остальные пишут предложение в
   `experiments/<задача>/PENDING_LEDGER.md`.
4. `git worktree list` + `git status` перед коммитом; гейт
   `scripts/check_parallel_sessions.py` блокирует чужой файл в индексе.
5. Worktree не в `%TEMP%` — только рядом с репозиторием.
6. «Нет в моём дереве» ≠ «нет нигде»: сначала спросить все деревья и историю git.

---

## §7. Самопроверка перед завершением

1. Индекс обновлён после правок (`notify_change` → `codebase(action="index", path="status")`).
2. Пути в правильном формате (Windows для MCP, POSIX для терминала).
3. Код production-ready: нет заглушек, TODO, мёртвых веток.
4. `python -m pytest tests/ -q` — зелёный. Помнить: `pyproject.toml` добавляет
   `-m 'not slow and not benchmark'`; **slow-тесты запускать отдельно**
   (`-m "not benchmark"`), иначе их падения не видны.
5. `ruff check src/ tests/ scripts/` — чисто (или `scripts/ruff_gate.py`).
6. Хуки: `.githooks/pre-commit` активен (`core.hooksPath = .githooks`). Он гоняет
   12 гейтов, включая gate-zero (полный pytest) — для docs-only коммитов gate-zero
   пропускается автоматически.
7. CI проверен не «на словах»: `gh run list --branch <ветка>` и
   `gh run view <id> --log-failed`. Джобы: `test` (ubuntu + windows, Python 3.14),
   `clean-state`, `manifest-parity`, `docker-build`, `transport-equiv-e2e`; шаг
   `Docs references` внутри `test` проверяет дифф документации (§8).
8. Для изменений в индексе/провайдерах — живой smoke:
   `python scripts/smoke_e2e.py --project .` (реальные сервисы, без моков).
9. `bash scripts/verify_clean_state.sh` (clone + venv + install + полный прогон) →
   строка `CLEAN STATE VERIFICATION: PASSED`.
10. Реестры: `AGENT_DIARY.md` обновлён, `KNOWN_ISSUES.md` синхронизирован, у новых
    записей есть стабильный ID (`EXP-N`, `ADR-NNN`, `YYYY-MM-DD-slug`).
11. Корень чистый (§0.6): нет новых одноразовых файлов и логов.
12. Отчёт по форме: что сделано → гипотеза/эксперимент (команда + сырой вывод) →
    изменённые файлы → подводные камни → числа (замер или «не измерено») → DoD →
    `verified_from_clean_state` → следующий шаг.

---

## §8. Документация и реестры

- **Канон:** `README.md` (EN) + `docs/ru/README.md` + `docs/zh/README.md`;
  `docs/en/ARCHITECTURE.md`, `docs/en/SEARCH_PIPELINE.md`, `docs/en/INSTALL.md`,
  `docs/en/CLIENTS.md`, `docs/en/DATA_MAP.md`, `docs/en/CONFIGURATION.md`,
  `docs/FACTS.md`.
- **Документация = код.** Каждое утверждение в `.md` выводимо из кода, и правка
  документации в PR ссылается на факт кода (`файл:символ`), который она отражает.
  Правка «только цифра» без ссылки отклоняется до коммита (чек-лист
  `.github/pull_request_template.md`).
- **Guard изменения docs:** `scripts/check_docs_refs.py --base <sha>` (шаг CI
  `Docs references`; локально вручную `--staged`) требует, чтобы изменённый `.md`
  добавил **проверяемую** ссылку: существующий путь внутри репо (`.githooks/…` тоже),
  `path::symbol` — символ **объявлен** в файле (`def`/`class`/присваивание), а не
  упомянут; `path:NNN` — строка в пределах файла; `install.py --flag` — флаг известен;
  имя переменной, которое код **читает** из окружения (`os.getenv`/`process.env`).
  Косметика допускается только в файле, который уже ссылался на код и не вносит новых
  утверждений (новая цифра/путь/флаг; перенесённая строка с уже существующей цифрой —
  не новое утверждение). Тесты: `tests/test_docs_refs_gate.py` (35), включая матрицу
  обхода: выдуманный путь/символ/флаг/переменная, префикс реального имени, `::return`,
  traversal, junction, C-quoted не-ASCII путь, лимиты 200 файлов/20 000 строк.
  Гейт доказывает существование факта, **не** его релевантность утверждению —
  эту границу держит ревьюер.
- **Guard дрейфа флагов/клиентов:** `scripts/check_docs_vs_installer.py` — каждый
  `--flag` и `--client X` из `README.md`/`docs/*/{INSTALL,CLIENTS,DATA_MAP}.md`
  обязан существовать в `install.py`/`adapters/clients/snippets.py` (`tests/
  test_docs_vs_installer.py`). Колонка **Entry point** в «What works today»
  обязательна.
- **Три языка обязательны** для канонических страниц: EN / RU / ZH. Перевод — полный
  документ, не фрагмент; заголовки и числа совпадают с EN.
- **Числа** (инструменты, чанки, качество, тайминги) живут только в `docs/FACTS.md`
  вместе с командой перевывода. Остальные документы на него ссылаются.
- **Историческое** (`docs/blog/**`, `docs/research/**`, `docs/archive/**`,
  `docs/en/ARCHITECTURE_DEEP.md`) не переписывается под сегодняшний день: у него
  баннер статуса и дата. Переписывать историю = терять провенанс.
- **Ссылка на факт** — `(файл, SHA коммита, ID записи)`, не `file:line`: живые логи
  ротируются и номера строк сгнивают.
- **Ротация:** `KNOWN_ISSUES.md` ≤300 строк, закрытые записи уезжают в
  `docs/archive/KNOWN_ISSUES_YYYY_MM.md` (гейт `scripts/check_known_issues.py`;
  удалять месячные архивы нельзя — они часть контракта гейта).
- **Дрейф версий** в доках ловит `scripts/stale_detector.py --staged` (pre-commit) и
  `.opencode/plugin/mscodebase_gate.ts` при `git commit`.
- **OpenCode-команды** для типовых циклов: `.opencode/command/{research,experiment,
  redteam,postmortem,audit,done}.md`.
