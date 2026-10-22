# RESEARCH: архитектура «Главный агент → изолированные одноразовые субагенты» в OpenCode

**Дата:** 2026-10-20
**Режим:** research-only. Код не писался, существующие файлы проекта не изменялись.
**Единственный созданный файл:** этот отчёт.
**Локальная версия:** OpenCode CLI `1.18.23` (npm `opencode-ai@1.18.23`), plugin SDK `@opencode-ai/plugin@1.18.18`.
**Источники:** локальный `--help`, локальный resolved config, локальный бинарь, официальная документация opencode.ai, GitHub issues/PR, внешние статьи. Ссылки — в конце.

---

## 0. Как читать статусы

| Маркер | Значение |
|---|---|
| `[V]` Verified | Проверено командой/чтением в этой сессии. |
| `[E]` Estimate | Оценка: `tiktoken` (`o200k_base`/`cl100k_base`) для файлов, `chars/4` для грубых срезов. Не tokenizer Tīrtha/Qwen. |
| `[U]` Unverified | Взято из документации/внешнего источника, но не проверено на локальной 1.18.23. |
| `[C]` Contradiction | Локальный факт расходится с документацией/конфигом. |

---

## 1. Краткий итог (TL;DR)

1. **Нативные субагенты в OpenCode уже есть**: `task`-tool, `mode: subagent`, `permission.task`, `subagent_depth`, `hidden`, `steps`. Отдельный «spawn»-механизм писать не обязательно.
2. **CLI `opencode run` не имеет** `--yes/-y`, `--max-steps`, `--no-save`, `--system-prompt`, `--max-tokens`, `--max-cost`, `--worktree`. Есть `--auto`, `--agent`, `--format json`, `--file`, `--attach`, `--dir`, `--variant`.
3. **Лимит шагов задаётся не флагом, а конфигом агента**: `agent.<name>.steps` (legacy `maxSteps`). Лимит output — env `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX`.
4. **История не отключается**: каждый `opencode run` создаёт сессию в SQLite. Штатный путь — сохранить `sessionID`, затем `opencode session delete <id>`.
5. **Главное ограничение для «брифа на 2 000 токенов»**: глобальный `AGENTS.md` (~15.4–21.2k токенов `[V]`) + проектный `AGENTS.md` (~9.3–11.0k `[V]`) дают ~24.7–32.2k ещё до брифа. Флага отключения глобального `AGENTS.md` нет (`OPENCODE_DISABLE_GLOBAL` в бинаре отсутствует `[V]`). Измеренный baseline в lab-проекте (без проектного AGENTS) — **43–46k на один запрос**; Σ двух шагов ~92k — это стоимость, а не контекст. Лимит 79k — на запрос, поэтому baseline оставляет ~33–36k на Brief + tool-output.
6. **MSCodeBase уже содержит заготовку Brief-builder**: `get_context` с `TOKEN_LIMIT = 2000` и бюджетами секций (`source 1200`, `symbols 800`, ...). Но в CLI-режиме он падает в `project_not_ready` на холодном процессе `[V]`.
7. **Рекомендация**: Вариант A (Python-оркестратор) как целевой, Вариант B (CLI) как быстрый bootstrap, Вариант C (custom tool/MCP) как тонкая UX-обёртка. Не делать C основным: блокирующий вызов + риск рекурсии.
8. **Замер стоимости субагента `[V]`**: `task`-ребёнок наследует глобальный baseline — **44.6–47.5k input на одном запросе**. Одно чтение строки через `task` = **327 431 input суммарно по 7 запросам** (parent 95 903 + child 231 528), ~$0.18 по Base. Это дороже прямого чтения, а не дешевле; 327k — не размер контекстного окна.
9. **Изоляция `[V]`**: `OPENCODE_CONFIG` не заменяет глобальный конфиг (4 MCP и `permission` остаются). Нужен отдельный config-root: `USERPROFILE`/`HOME`/`XDG_CONFIG_HOME`/`XDG_DATA_HOME`/`XDG_CACHE_HOME` → пустой temp-home. Только тогда input падает с ~46k до **3.9–6.9k** на шаг.
10. **Наследование инструкций — intended, не баг `[V]`**: `system` заменяет только base prompt, `AGENTS.md` всё равно добавляется; `task` наследует `InstanceContext` родителя (cwd, `.opencode`, AGENTS-walk-up). Штатного per-agent отключения нет; проверенный в этой сессии обход — отдельный процесс с изолированным config-root.

---

## 2. Внешнее исследование

### 2.1. Фактические возможности локального CLI 1.18.23

Проверено `opencode --help` и `opencode run --help` `[V]`.

| Флаг | Короткий | Что делает | Критичное замечание |
|---|---|---|---|
| `--agent` | — | Выбрать агента | Принимает ли `subagent` — не проверено `[U]` |
| `--model` | `-m` | `provider/model` | Локально доступны `tirtha/auto`, `opencode/*`, `opencode-go/*` |
| `--variant` | — | reasoning preset | Провайдер-специфично |
| `--format` | — | `default` или `json` (raw events) | JSON — поток событий, не финальная JSON-схема |
| `--file` | `-f` | Прикрепить файл(ы) к сообщению | Основной способ передать Brief без argv-лимита |
| `--title` | — | Заголовок сессии | Полезно для трассировки |
| `--attach` | — | Подключиться к `opencode serve` | Убирает cold boot MCP на каждый вызов |
| `--dir` | — | Рабочая директория | Позволяет запускать в worktree |
| `--auto` | — | Авто-подтверждение всего, что не запрещено | Опасно; это не `--yes` |
| `--pure` | — | Без внешних плагинов | Отключает и проектный gate-плагин |
| `--continue` | `-c` | Продолжить последнюю сессию | Противоположность one-shot |
| `--session` | `-s` | Продолжить конкретную сессию | Нужен для resume |
| `--fork` | — | Форк при продолжении | Наследует контекст |
| `--share` | — | Поделиться сессией | Не нужно для one-shot |
| `--thinking` | — | Показать thinking | Только для отладки |
| `--interactive` | `-i` | Split-footer режим | Не для автоматизации |
| `--command` | — | Запустить команду | Аргументы — в message |

**Чего нет в `opencode run` 1.18.23** `[V]`:

| Ожидаемый флаг | Факт | Обход |
|---|---|---|
| `--yes` / `-y` | Нет | `--auto` + `permission` deny-list |
| `--max-steps` | Нет | `agent.<name>.steps` в конфиге |
| `--no-save` / `--ephemeral` | Нет | `session delete` после запуска |
| `--system-prompt` | Нет | `agent.<name>.prompt` + `--file` Brief |
| `--max-tokens` | Нет | `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX` |
| `--max-cost` | Нет | Внешний учёт по JSON-событиям |
| `--worktree` / `--isolate` | Нет | `git worktree add` + `--dir` |

### 2.2. Конфигурация, лимиты и изоляция

| Параметр | Где | Значение/лимит | Статус |
|---|---|---|---|
| `agent.<name>.steps` | `opencode.jsonc` | Макс. число агентных итераций | `[U]` docs; `maxSteps` в бинаре есть `[V]` |
| `agent.<name>.temperature` | config | 0.0–1.0 | `[U]` |
| `agent.<name>.prompt` | config | Путь к системному промпту | `[U]` |
| `agent.<name>.permission` | config | `allow` / `ask` / `deny` + glob | `[U]` |
| `agent.<name>.mode` | config | `primary` / `subagent` / `all` | `[U]` |
| `agent.<name>.hidden` | config | Скрыть из `@`-меню | `[U]` |
| `permission.task` | config | Какие субагенты доступны | `[U]` |
| `subagent_depth` | config | default `1`; `0` запрещает всех субагентов | `[V]` строка есть в бинаре |
| `permission` (global) | config | По умолчанию **allow all** | `[U]` docs |
| `compaction.auto` | config | default `true` | `[U]` |
| `compaction.prune` | config | default `false` | `[U]` |
| `compaction.reserved` | config | default `10000` токенов | `[U]` |
| `provider.options.timeout` | config | default `300000 ms` | `[U]` |
| `provider.options.chunkTimeout` | config | default `900000 ms` | `[U]` |
| `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX` | env | Макс. output токенов | `[V]` строка есть в бинаре |
| `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` | env | Таймаут bash | `[V]` строка есть в бинаре |
| `OPENCODE_CONFIG_CONTENT` | env | Inline JSON-конфиг на запуск | `[V]` строка есть в бинаре |
| `OPENCODE_CONFIG` | env | Путь к альтернативному конфигу | `[V]` строка есть в бинаре |
| `OPENCODE_CONFIG_DIR` | env | Альтернативная директория агентов/плагинов | `[V]` строка есть в бинаре |
| `OPENCODE_DISABLE_PROJECT_CONFIG` | env | Не читать проектный `AGENTS.md` | `[V]` строка есть; поведение `[U]` |
| `OPENCODE_DISABLE_GLOBAL_*` | env | **Отсутствует** | `[V]` строки в бинаре нет |

**Вывод по изоляции:** OpenCode изолирует *контекст сессии* (новая сессия на каждый `run`, отдельная сессия у субагента), но **не изолирует файловую систему**. Для write-задач нужен `git worktree` вручную: upstream-флаг per-agent worktree в 1.18.23 отсутствует (в issue #49842 это описано как форк-фича).

### 2.3. Нативные субагенты: что именно поддерживается

Из docs `[U]` и локального `opencode agent list` `[V]`:

- `mode: subagent` + вызов через `task` tool.
- `@mention` для ручного вызова.
- `permission.task` с glob-паттернами (`"*": "deny"`, `"oneshot-*": "allow"`).
- `hidden: true` — скрыт из autocomplete, но доступен через `task`.
- `steps` — жёсткий лимит итераций.
- `subagent_depth` — защита от рекурсии.
- Встроенные субагенты локально: `explore`, `general` (и `scout` в docs).
- Кастомных агентов локально **нет**: `~/.config/opencode/agents/` отсутствует, `debug config` показывает `"agent": {}` `[V]`.

**Что именно наследует `task`-ребёнок (docs + issues):**

- **История родителя не передаётся.** Субагент получает fresh context в child-сессии; prompt конструируется динамически из `task`-описания. Docs v2: «Subagents run with fresh context»; maintainer в #1668: «yes thats correct» на вопрос о fresh context. То есть «не тянуть промт родителя» в части *диалога* уже выполнено.
- **Инструкции наследуются.** `system`/Markdown-body заменяет только provider base prompt; docs v2 прямо добавляют: «Project instructions, skills, references, and other instruction sources are still added». `AGENTS.md` и `instructions` не отключаются кастомным prompt.
- **`task` наследует `InstanceContext` родителя:** cwd, локальный `.opencode`, AGENTS-walk-up, agents, skills. Issue #29271 просит добавить `task({directory})` именно потому, что сейчас ребёнок привязан к контексту родителя; параметр не входит в 1.18.23.
- **#4483 — intended behavior, не баг.** Автор issue после проверки Claude Code отозвал заявление: субагенты там тоже получают `CLAUDE.md`/`AGENTS.md`; maintainer подтвердил, что OpenCode следует этой же модели. Открытый запрос «не давать `AGENTS.md` explore-субагенту» остаётся нереализованным.
- **Штатного per-agent `instructions: false` нет.** `OPENCODE_DISABLE_PROJECT_CONFIG=1` по docs пропускает проектные `AGENTS.md`, но **не** глобальный; глобальный убирается только сменой config-root. Nested `AGENTS.md` подгружаются при чтении файлов и тоже расходуют контекст (issue #52625 просит отключить эту инъекцию — open).

### 2.4. Опыт сообщества: почему одноразовые субагенты работают

| Источник | Наблюдение | Следствие для нас |
|---|---|---|
| Thoughtworks, «bounded context» | Субагент = context firewall: один job, изолированное окно, сжатый результат | Brief должен содержать **только** цель + факты, без истории |
| Stackness / CliffCompaction (2026-09-22) | Tool results — 56% контекста, tool calls — 28%; thinking — 13.6% | Чтение файлов и логи уводить в субагента, возвращать вывод |
| Stackness / LangWatch | Fresh subagent ~30k токенов, forked subagent ~523k | Не использовать `--fork`/`--continue` для one-shot |
| CodeDelegator (arXiv 2601.14914) | Разделение планировщика и исполнителя; typed specs вместо lossy-пересказа; эфемерное состояние исполнителя | Brief = типизированная спецификация, а не чат |
| Simon Willison | Субагент получает свежий контекст и возвращает только результат | Главный агент не должен видеть промежуточные чтения |
| Cline `spawn_agent` | Свой prompt/context, возвращает отчёт; субагент не получает MCP tools | Аналог: ограничить tools и запретить рекурсию |
| Aider Architect/Editor | Разделение reasoning и editing дало SOTA на benchmark | Разделять «понять/спланировать» и «отредактировать» |
| OpenCode issue #4483 | Субагенты наследуют `AGENTS.md` (позже признано intended) | Глобальные правила неизбежно попадут в субагента |

**Практический вывод:** «одноразовый атомарный субагент» — это не «маленький чат», а **детерминированный контракт**: вход (Brief ≤ 2000 токенов), выход (JSON по схеме), лимит шагов, запрет рекурсии, удаление сессии.

---

## 3. Внутренний аудит

### 3.1. OpenCode: конфигурация

Файл: `%USERPROFILE%\.config\opencode\opencode.jsonc` (62 строки, JSONC) `[V]`.

| Что | Факт |
|---|---|
| `autoupdate` | `false` |
| Провайдер `tirtha` | `@ai-sdk/openai-compatible`, `baseURL: https://api.tirtha.ai/v1` |
| Модель по умолчанию | `tirtha/auto` |
| Секрет | API-ключ Tirtha лежит **в открытом виде** в конфиге (значение здесь намеренно не приводится) |
| MCP | 3 local (`mscodebase-intelligence`, `community-memory`, `arclux`) + 1 remote (`msp-portfolio`) |
| `agent` | Не задан; resolved config: `"agent": {}` `[V]` |
| `permission` | Не задан; действует дефолт «allow all» `[U]` |
| `subagent_depth` | Не задан; действует default `1` `[U]` |
| `compaction` | Не задан; default `auto=true`, `prune=false` `[U]` |
| `instructions` | Не задан |
| Плагин | `file:///D:/Project/MSCodeBase/.opencode/plugin/mscodebase_gate.ts` `[V]` |

Противоречие `[C]`:

- В конфиге модель по умолчанию — `tirtha/auto`.
- Текущая сессия и системный контекст используют `opencode/deepseek-v4.1-flash-free`.
- `opencode models` показывает провайдеров `opencode/*` и `opencode-go/*`, которых нет в `opencode.jsonc`.
- Вывод: фактическая модель сессии задаётся клиентом/десктопом и может не совпадать с `model` в конфиге. Для субагентов это надо фиксировать явно через `agent.<name>.model` или `--model`.

### 3.2. OpenCode: окружение и накопленное состояние

| Метрика | Значение | Команда |
|---|---|---|
| Версия CLI | `1.18.23` | `opencode --version` |
| Plugin SDK | `1.18.18` | `package.json` |
| DB | `%LOCALAPPDATA%\..\.local\share\opencode\opencode.db` | `opencode db path` |
| Размер DB | `1 044 410 368` bytes (~996 MiB) | `Get-Item` |
| Сессий за 7 дней | `312` | `opencode stats --days 7` |
| Сообщений за 7 дней | `2 209` | то же |
| Средние токены/сессия | `475.6K` | то же |
| Медиана токенов/сессия | `45.1K` | то же |
| Input / Output за 7 дней | `20.6M` / `591.3K` | то же |
| Cache Read | `126.3M` | то же |
| Cost за 7 дней | `$0.13` | то же |
| Топ-инструменты | bash `790` (52.5%), read `204` (13.6%), write `160` (10.6%), edit `155` (10.3%), grep `61` (4.1%) | то же |
| `OPENCODE_CLIENT` | `desktop` | env |
| `OPENCODE_SERVER_PASSWORD` | задан (значение не приводится) | env |
| `MSCODEBASE_ALLOW_SELF_INDEX` | `1` | env |

**Наблюдение:** 312 сессий за 7 дней при 2 209 сообщениях — это очень много коротких сессий (в среднем ~7 сообщений на сессию). То есть one-shot паттерн уже де-факто используется, но без очистки и без единого контракта.

### 3.3. Вес инструкций — главный барьер для «2 000 токенов»

| Файл | Размер | `o200k_base` | `cl100k_base` |
|---|---:|---:|---:|
| `%USERPROFILE%\.config\opencode\AGENTS.md` (глобальный) | 80 549 B | 15 396 | 21 240 |
| `%USERPROFILE%\.config\opencode\FULL AGENTS.md` (legacy) | 139 215 B | 27 288 | 37 524 |
| `D:\Project\MSCodeBase\AGENTS.md` (проектный) | 40 632 B | 9 318 | 10 968 |
| `D:\Project\MSCodeBase\WISDOM.md` | 26 982 B | 6 346 | 7 721 |
| `D:\Project\MSCodeBase\AGENT_DIARY.md` | 200 866 B | 47 997 | 56 985 |
| `D:\Project\MSCodeBase\KNOWN_ISSUES.md` | 84 854 B | 20 045 | 24 511 |

Токены — `tiktoken`, два токенизатора как границы `[V]`; точный tokenizer Tīrtha/Qwen не измерялся. `bytes/4` для русского занижает: у глобального файла 80 549 B, но 48 674 символа и 15.4–21.2k токенов.

**Сумма только двух `AGENTS.md`: ~24.7–32.2k токенов `[V]`.** В lab-проекте проектного `AGENTS.md` не было, поэтому измеренный baseline **45.7–46.2k input на шаг** (3.7) = глобальный `AGENTS.md` + MCP-схемы/настройки + system prompt, а не сумма двух файлов.

Дрейф: глобальный `AGENTS.md` изменился **во время этой сессии** — 79 618 B → 80 549 B (mtime `2026-10-20 18:32:52`). Прогоны до 18:32 использовали 79 618 B; таблица выше — актуальный размер на момент записи (разница <1k токенов, на выводы не влияет). Это не моя правка; файл не трогался.

Следствия:

1. Brief на 2 000 токенов — это ~5% промпта. Цель «весь контекст субагента ≤ 2 000» **недостижима** при текущих глобальных правилах.
2. Проектный `AGENTS.md` прямо предписывает читать `AGENT_DIARY.md` (50k токенов) и `WISDOM.md` (6.7k). Если субагент послушен — контекст раздувается ещё до работы.
3. Глобальный `AGENTS.md` нельзя отключить флагом: в бинаре нет `OPENCODE_DISABLE_GLOBAL*` `[V]`; внешнее исследование подтверждает, что глобальный файл читается всегда `[U]`.

**Варианты решения (не применялись):**

- A. Отдельный `AGENTS.subagent.md` + `OPENCODE_DISABLE_PROJECT_CONFIG=1` для запуска субагента (глобальный всё равно останется).
- B. Отдельный config-root (`USERPROFILE`/`HOME`/`XDG_CONFIG_HOME`/`XDG_DATA_HOME`/`XDG_CACHE_HOME` на чистую папку) для дочернего процесса — **проверено на Windows**: input падает до 3.9–6.9k/шаг (3.7). Подводный камень PowerShell: `$HOME` — read-only, использовать `$isoHome`.
- C. Перенести глобальные правила в `agent.<primary>.prompt` (файл), оставив `AGENTS.md` минимальным.
- D. Принять baseline и считать 2 000 токенов бюджетом **брифа**, а не всего промпта.

### 3.4. Гигиена конфиг-каталога

В `%USERPROFILE%\.config\opencode\` лежат `[V]`:

- `AGENTS.md` (78 KB, актуальный)
- `AGENTS<битое-имя>.md` (58 KB, битое имя/кодировка)
- `FULL AGENTS.md` (139 KB, legacy)
- `commands-REMOVED.md`, `gates-REMOVED.md`
- `RESEARCH-2026-09-30.md`
- `memory/`, `skills/`, `tools/`, `node_modules/`

Это не влияет на runtime напрямую (кроме `AGENTS.md`), но затрудняет аудит «какой файл — источник истины». Кандидат на очистку/архивацию.

### 3.5. MSCodeBase: что уже умеет AST-слой

Живой MCP `[V]`:

| Метрика | Значение |
|---|---|
| Индекс | `active` |
| Chunks | `12 964` |
| Files | `840` |
| Symbols | `12 231` |
| Embedder | `llama_cpp` |

Проверенные инструменты и их выдача:

| Инструмент | Что вернул | Вывод |
|---|---|---|
| `get_symbol_info("get_progress_file")` | 1 definition, 4 callers, 8 callees; точный `file:line` (302) | Готовый источник для Brief |
| `impact_analysis("get_progress_file", depth=1)` | `1160 ms`; 2 direct callers; 3 affected files; risk `medium`, score `31` | Готовый blast radius |
| `read_live_file(start=296, end=312)` | Точный срез исходника + `total_lines`, `total_chars` | Готовый source-блок |
| `lsp_document_symbols("src/core/artifact_paths.py")` | Timeout `15007 ms` | LSP не поднят/не отвечает; **не полагаться** |
| `lsp_get_type_info` / `lsp_find_references` | Не проверялись | Тот же риск таймаута |
| `graph_query(action="flow")` | Не проверялся | Потенциальный dataflow-блок |
| `structural_search` | Не проверялся | Потенциальный поиск паттернов |

**Ключевой факт:** `lsp_document_symbols` по контракту отдаёт `name (kind) L<start>..L<end>`, но в этой сессии он не ответил за 15 с. Для точных границ функций нужен fallback на Python `ast`/tree-sitter внутри MSCodeBase (сейчас границы приходится добирать через `read_live_file` + эвристику).

### 3.6. `get_context` — уже существующий Brief-builder

`src/mcp/tools/context_tool.py` `[V]`:

- `TOKEN_LIMIT = 2000`.
- Бюджеты: `source 1200`, `symbols 800`, `git 300`, `memory 400`, `fallback 200`, `dataflow 500`, `writes 300`, `receipts 400`, `tests 300`.
- Intent-профили: `explain`, `modify`, `debug`, `test`, `prepare_change`, `verify_change`, ...
- Секции дедуплицируются по сигнатуре, обрезка — `chars/4`.

Это ровно тот контракт, который нужен для one-shot брифа. Но:

| Проблема | Факт |
|---|---|
| Не в default MCP allowlist | `get_context` в списке hidden core tools |
| CLI-путь холодный | `python -m src.cli get_context` дал `project_not_ready` / `UNINITIALIZED` `[V]` |
| Время | 18 014 ms на один символ (включая 15 030 ms внутренней работы) `[V]` |
| Выдача | 2 727 chars (~682 токена `[E]`), но доминирует текст ошибок, а не source |
| CLI allowlist | Содержит `get_context`, `graph_query`, `stale_detector`, но **не содержит** `get_symbol_info`, `impact_analysis`, `read_live_file` `[V]` |

**Вывод:** `get_context` — правильная архитектура, но в CLI-режиме требует прогрева/инициализации. Для оркестратора нужен **долгоживущий процесс** (MCP-сервер или in-process сервис), а не `python -m src.cli` на каждый Brief.

### 3.7. Анатомия 46k и реальная цена `task`-субагента (замеры 2026-10-20)

Все прогоны — свежая сессия, один и тот же `hello.txt` (`MAGIC-TOKEN-42`), `tirtha/auto`, `--format json`. Токены — из `step_finish.tokens.input` (провайдерские), не оценка `chars/4`. Стенд: `%TEMP%\opencode\tirtha-lab`.

**Два разных стенда, их нельзя смешивать:**

- **Фоновый `opencode serve`** (`server_probe.py`, `subagent_probe.py`, `disable_probe.py`): `subprocess.Popen([... "serve", "--port", ...], cwd=PROJECT, env=os.environ.copy())`; менялся только `OPENCODE_CONFIG` (плюс `OPENCODE_DISABLE_PROJECT_CONFIG=1` в `disable_probe.py`). `HOME`/`XDG_*` **не** подменялись → загружался глобальный config-root: глобальный `AGENTS.md`, 4 MCP, глобальные permissions. Это источник baseline 43–46k и `task`-замера 327k.
- **Чистый `opencode run`** (`iso_build.txt`, `iso_run2.txt`): не `serve`, а CLI-процесс с `USERPROFILE=HOME=tirtha-lab\home`, `XDG_CONFIG_HOME`/`XDG_DATA_HOME`/`XDG_CACHE_HOME` → пустой temp-home; `cwd=tirtha-lab\project` содержит только `hello.txt`, без `AGENTS.md`. Это источник 3.9–6.9k.
- **«Без промта» означает без глобальных инструкций/MCP, а не без user-prompt.** Минимальный prompt всё равно был: «прочитай `hello.txt`, верни токен, без преамбулы».
- **`task` в чистом config-root не замерялся.** Гипотеза: если запустить `serve` с теми же HOME/XDG-подменами, child унаследует slim-baseline; это требует отдельного прогона и сейчас не утверждается.

| Конфиг | Агент | Шаги (input) | Σ input | Ответ | Wall |
|---|---|---:|---:|---|---:|
| глобальный (4 MCP + AGENTS) | `build` | 46 077 + 46 172 | 92 249 | верный | не замерен |
| глобальный | `oneshot-read`, `steps: 2` | 45 773 + 46 039 | 91 812 | упёрся в лимит шагов | 40.6 s |
| изолированный | `build` | 6 826 + 6 921 | 13 747 | верный | 3.9 s |
| изолированный | `oneshot-read`, `steps: 3` | 3 966 + 3 962 | 7 928 | верный | 25.2 s |

**Per-request vs Σ.** В колонке `Σ input` — сумма по всем шагам; лимит 79k относится к **одному запросу**. Максимальный per-request в таблице — 46 172 (`build`) и 46 039 (`oneshot-read`). Контрольный `global_oneshot3` (`steps: 3`, cwd = temp-проект) дал 42 913 + 43 030 = 85 943 Σ, per-request 43 030; отличие от 45.8k не объяснено (вероятно, другой набор AGENTS/инструкций), поэтому в baseline не включаю.

**Изоляция.** `USERPROFILE`/`HOME`/`XDG_CONFIG_HOME`/`XDG_DATA_HOME`/`XDG_CACHE_HOME` → пустой temp-home, `OPENCODE_CONFIG` → temp-конфиг. `OPENCODE_CONFIG` сам по себе **не** изолирует: `GET /config` всё равно показывает 4 глобальных MCP (`arclux`, `community-memory`, `mscodebase-intelligence`, `msp-portfolio`) и глобальный `permission`; `"mcp": {}` в конфиге их не удаляет. Глобальный `AGENTS.md` (~15–21k токенов) и глобальные MCP-настройки исчезают только при смене config-root.

**Вклад инструментов.** `GET /experimental/tool?provider=tirtha&model=auto` отдаёт 14 built-in схем, 26 090 символов ≈ 6.5k токенов (оценка `chars/4`): `bash` 5 933, `task` 3 931, `todowrite` 2 692, `edit` 1 958, `gate` 1 845, `read` 1 735, `question` 1 542, `webfetch` 1 292. Это верхняя граница: `permission: deny` фильтрует часть схем — изолированный `oneshot-read` (read/glob/grep/list allow, остальное deny) дал 3 966 input против 6 826 у `build`, то есть ~2.9k токенов экономии на шаг.

**Субагент через `task`.** Родитель `build` → `task(subagent_type="general")` → чтение `hello.txt`:

| Сессия | Шаги (input) | Σ input | Output |
|---|---:|---:|---:|
| parent `build` | 49 493 + 46 410 | 95 903 | 59 |
| child `general` | 47 316 + 47 391 + 47 466 + 44 630 + 44 725 | 231 528 | 132 |
| **итого** | | **327 431** | **191** |

Ребёнок унаследовал глобальный baseline: 44.6–47.5k input **на каждом** из 5 шагов. Пять шагов вместо двух: Tīrtha трижды прислал `read` с `limit: "null"`, `offset: "null"` (строки вместо null); `read` вернул `status=error`, успешный вызов — только 4-й. Это подтверждает известный риск Tīrtha «tool call как текст/невалидные аргументы», но точная причина отказа не логировалась.

Стоимость только по input: Base `$0.56/M` → `327 431 × 0.56 / 1e6 = $0.183`; Plus `$1.10/M` → `$0.360`. Output 191 токенов добавляет <$0.001. Запросов: 2 parent + 5 child = **7**; при free beta 100 req/month это ~14 таких задач. Без ретраев (~190k input) — ~$0.10 и 4 запроса. Если и родитель, и ребёнок в slim-конфиге: ~13.7k + ~7.9k = ~21.7k input, ~$0.012.

**Вывод.** `task`-субагент сам по себе **не** экономит: он наследует тот же baseline (system prompt + глобальный `AGENTS.md` + глобальные MCP-настройки). Экономия появляется только при (а) отдельном config-root без глобальных инструкций/MCP и (б) узком `permission`/tool-set. Без этого «одноразовый субагент» стоит дороже, чем чтение файла главным агентом.

Практический рецепт: отдельный пустой config-root + `OPENCODE_CONFIG`, в котором только `provider` и `oneshot-*` агент; реальный проект задаётся через `--dir`. MCP в этом конфиге нет — весь нужный код должен быть в Brief.

**Verification Ledger (3.7):**

| # | Гипотеза | Проверка | Вердикт |
|---|---|---|---|
| 1 | Глобальный baseline ~46k/шаг | `build`: 46 077 + 46 172 | CONFIRMED |
| 2 | `task`-ребёнок наследует baseline | child: 44.6–47.5k на каждом из 5 шагов | CONFIRMED |
| 3 | Изоляция config-root даёт <8k/шаг | `build` 13 747; `oneshot-read` 7 928 | CONFIRMED |
| 4 | `OPENCODE_CONFIG` достаточно для изоляции | `/config` показал 4 глобальных MCP | REFUTED |
| 5 | `json_schema` работает через Tīrtha | `StructuredOutputError` | REFUTED |
| 6 | `steps: 2` хватает на read + ответ | упёрся в лимит шагов | REFUTED |

**Аномалия, не объяснённая.** Input child падал с 47 466 до 44 630 при растущей истории. Правдоподобная причина — router Tīrtha сменил served-модель/токенизатор между шагами, но `served_model_id` в OpenCode-прогоне не логировался; это гипотеза, а не вывод. Нужен отдельный замер с логом модели на каждом шаге.

**Ограничения замеров.** Tīrtha — router, поэтому input-токены шагов не идеально сопоставимы; это не бенчмарк латентности. `format: json_schema` на 1.18.23 + Tīrtha по-прежнему падает: `StructuredOutputError: Model did not produce structured output`, 43 193 input, 0 tool parts. `steps: 2` недостаточно для «read + финальный ответ» — нужен ≥3.

---

## 4. Что должен содержать Brief (AST-контракт)

### 4.1. Принцип

Brief — это **данные**, а не пересказ. Субагент не должен делать `read_file` всего проекта: ему дают точный срез, сигнатуры, связи и критерии приёмки. Всё, что не влезло в бюджет, перечисляется как `omitted` с хэшем/путём, чтобы главный агент мог дозапросить.

### 4.2. Предлагаемая схема

```json
{
  "brief_version": 1,
  "task_id": "oneshot-2026-10-20-001",
  "intent": "modify",
  "repo": {
    "root": "D:/Project/MSCodeBase",
    "commit": "<sha>",
    "dirty": false
  },
  "target": {
    "file": "src/core/artifact_paths.py",
    "symbol": "get_progress_file",
    "kind": "function",
    "start_line": 302,
    "end_line": 304,
    "signature": "def get_progress_file(project_path: Path) -> Path",
    "docstring": "progress.json — file-contract для агента (см. AGENTS.md §0)."
  },
  "source": "def get_progress_file(project_path: Path) -> Path:\n    \"\"\"progress.json ...\"\"\"\n    return get_project_dir(project_path) / \"progress.json\"",
  "callers": [
    {"symbol": "NotificationBroker._write_progress_file", "file": "src/core/notification_broker.py", "line": 98},
    {"symbol": "ProjectIntelligenceLayer.intel_get_runtime_status", "file": "src/core/intelligence/layer.py", "line": 565}
  ],
  "callees": [
    {"symbol": "get_project_dir", "file": "src/core/artifact_paths.py", "line": 304}
  ],
  "impact": {
    "risk": "medium",
    "score": 31,
    "affected_files": [
      "src/core/artifact_paths.py",
      "src/core/intelligence/layer.py",
      "src/core/notification_broker.py"
    ]
  },
  "tests": ["tests/test_artifact_paths.py::test_progress_file"],
  "constraints": [
    "Не менять сигнатуру get_progress_file",
    "Не трогать файлы вне affected_files",
    "Не добавлять зависимости"
  ],
  "acceptance": [
    "pytest tests/test_artifact_paths.py -q",
    "python -m src.cli get_task_status '{}'"
  ],
  "output_contract": {
    "type": "json_schema",
    "schema": {
      "type": "object",
      "required": ["status", "changed_files", "summary", "tests"],
      "properties": {
        "status": {"enum": ["done", "blocked", "failed"]},
        "changed_files": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "tests": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}}
      }
    }
  },
  "budget": {
    "max_input_tokens": 2000,
    "max_steps": 4,
    "max_output_tokens": 1200
  },
  "omitted": [
    {"reason": "symbols_over_budget", "count": 3, "how_to_request": "get_symbol_info(<name>)"}
  ]
}
```

### 4.3. Что извлекать из AST до запуска

| Поле | Источник | Обязательность |
|---|---|---|
| `file`, `symbol`, `kind` | `get_symbol_info` | P0 |
| `start_line`, `end_line` | `lsp_document_symbols` (сейчас timeout) / Python `ast` fallback | P0 |
| `signature`, `docstring` | `lsp_get_type_info` / AST | P1 |
| `source` (точный срез) | `read_live_file(start, end)` | P0 |
| `callers`, `callees` | `get_symbol_info` | P0 |
| `impact.risk`, `affected_files` | `impact_analysis` | P1 |
| `tests` | `impact_analysis` / `search_code` | P1 |
| `dataflow` | `graph_query(action="flow")` | P2 |
| `git` (commit, dirty) | `git rev-parse` / `codebase(action="git")` | P1 |
| `memory` (ADR/known issues) | `intel_get_project_memory` | P2 |
| `omitted` | расчёт бюджета | P0 |

**Не включать в Brief:** весь файл, `AGENT_DIARY.md`, `KNOWN_ISSUES.md`, полный список инструментов, историю предыдущих попыток. Это либо шум, либо утечка контекста.

### 4.4. Бюджет под 79k (на один запрос)

79k — это **контекст одного запроса**, а не сумма шагов. Формула:

`79000 >= B_system + B_tools + B_brief + B_tool_outputs + B_output + B_safety`

| Компонент | Глобальный baseline | Изолированный config-root |
|---|---:|---:|
| system + instructions + tool schemas | 43–46k | 4–7k |
| output reserve | 6–8k | 6–8k |
| safety | 4k | 4k |
| **остаётся на Brief + tool-outputs** | **~21–27k** | **~60–65k** |

Практические пороги:

- Brief: **≤8k токенов**, целевой диапазон 2–5k.
- Tool-outputs: **≤12k**, максимум 3 чтения/команды на задачу.
- `steps`: 3–5; каждый шаг добавляет вывод инструментов в контекст, поэтому «ещё одно чтение» — не бесплатно.
- Если оценка `Brief + tool-outputs` > 28k — дробить задачу.
- `len(json.dumps(brief)) / 4 <= 2000` — только грубый pre-check; финальные числа брать из `step_finish.tokens.input`.
- Nested `AGENTS.md` подгружается при чтении (docs), поэтому в изолированном runner ставить `OPENCODE_DISABLE_PROJECT_CONFIG=1`; глобальный `AGENTS.md` убирается только отдельным config-root.

### 4.5. Микрозадача: контракт и декомпозиция

Правило: **одна микрозадача = один символ/функция + его прямые тесты + одна acceptance-команда**. Не «модуль», не «файл», не «исследуй проект».

1. **Read-task:** один символ + прямые callers + тесты; вернуть JSON, без права редактирования.
2. **Write-task:** один function/class, ≤1 файл, ≤100 строк diff, одна тест-команда; запускать в `git worktree`.
3. **Brief содержит точные `file:line`-срезы.** Ребёнок не ищет по репозиторию: поиск — это неоплаченные токены и главный источник расползания контекста.
4. **Parent строит DAG и контекст детерминированно** (MSCodeBase `get_context` / `graph_query`), а не через LLM-«поищи сам».
5. **Child-политика:** `task: deny` (без рекурсии), `webfetch: deny`, MCP выключен в slim-конфиге, `steps: 4`, read только по разрешённым путям, bash только acceptance-команда.
6. **Выход:** JSON `{status, summary, files_changed, tests, blockers}`; parent хранит его в ledger, а не весь transcript.
7. **Дробление:** если Brief >8k или нужно >3 чтений — делить по символу/тесту, а не по «модулю».
8. **Structured output:** `format: json_schema` на Tīrtha падает (`StructuredOutputError`); требовать fenced JSON в тексте и валидировать парсером.

### 4.6. Один запуск = одна микрозадача

- **`opencode run` = новый процесс + новая сессия + новый чистый агент.** После возврата результата процесс завершается; следующая микрозадача запускается заново, без истории предыдущей.
- **Запрещены** `--continue`, `--session`, `--fork`: они как раз переиспользуют контекст.
- **Parent-runner может быть одной командой** (`python microtask_runner.py plan.json`), но внутри она делает N отдельных запусков — по одному на микрозадачу.
- **Нативный `task` — другой режим:** child-сессия внутри parent-сессии, наследует `InstanceContext` и глобальные инструкции. Для strict isolation он не используется.
- **`serve --attach` — только для скорости.** Сервер может жить, но каждая задача = новый `POST /session`, не `--continue`; после результата сессия удаляется. Если нужна абсолютная чистота — отдельный процесс на задачу.

---

## 5. Три варианта реализации

### Вариант A — Python-оркестратор (внешний процесс)

**Как работает:** долгоживущий Python-сервис (внутри MSCodeBase) инициализирует индекс один раз, собирает Brief через in-process tool-классы, затем вызывает `opencode run --agent oneshot --format json --file brief.json` через `subprocess`, парсит события, сохраняет `sessionID`, удаляет сессию, пишет отчёт.

| Плюс | Минус |
|---|---|
| Полный контроль над Brief (AST, бюджет, хэши) | Нужен новый код и lifecycle |
| Можно запускать N параллельно | Cold boot `opencode` на каждый процесс; MCP в slim-конфиге нет |
| JSON-события → метрики/стоимость | Windows: `subprocess` + pipes + kill process tree |
| Можно удалять сессии и чистить DB | Риск рекурсии (opencode → MCP → opencode) |
| Можно изолировать worktree | Секреты/права надо прокидывать явно |

**Сложность:** средняя (1 сервис + 1 runner + тесты).
**Токены:** baseline 4–7k в slim config-root + Brief 2–8k + output ≤1.2k. Без изоляции baseline снова ~43–46k.
**Латентность:** высокая на процесс; снижается `--attach` к `opencode serve`.
**Когда выбирать:** batch, миграции, «прогнать 50 файлов», воспроизводимые эксперименты.

### Вариант B — нативный CLI/Bash-пайплайн

**Как работает:** `opencode run --agent oneshot --format json --file brief.md "..."` в цикле; при необходимости `--attach http://127.0.0.1:4096`.

| Плюс | Минус |
|---|---|
| Ноль нового кода | Brief собирается вручную/скриптом |
| Использует штатные агенты/права | Хрупкие кавычки PowerShell (`Get-Content | ...`) |
| Легко проверить вручную | Нет структурированного retry/валидации |
| `--attach` убирает cold boot | Нет управления сессиями/очисткой из коробки |

**Сложность:** низкая.
**Токены:** те же baseline + Brief; `--attach` экономит время, не токены.
**Латентность:** средняя; cold boot без `--attach` высокий.
**Когда выбирать:** быстрый старт, 1–3 задачи, отладка промпта.

### Вариант C — custom tool / MCP `spawn_subagent`

**Как работает:** либо `.opencode/tools/spawn_subagent.ts` (Bun, вызывает SDK/`opencode run`), либо MCP-инструмент в MSCodeBase. Главный агент вызывает как функцию с типизированными аргументами.

| Плюс | Минус |
|---|---|
| Естественный UX: «вызови субагента» | Блокирующий вызов; долгий tool call |
| Типизированные args/result | Риск рекурсии (субагент снова вызывает spawn) |
| Может использовать SDK `session.create/prompt` + `json_schema` | MCP-сервер должен спавнить opencode — сложный lifecycle |
| Централизованная политика прав | Таймауты MCP/агента; нет стриминга |
| | Дублирование с нативным `task` tool |

**Сложность:** высокая (custom tool + SDK + обработка ошибок).
**Токены:** Brief + baseline; результат можно вернуть компактным JSON (плюс).
**Латентность:** высокая (вложенный процесс).
**Когда выбирать:** если нужен именно in-session вызов «одной кнопкой»; иначе нативный `task` уже покрывает 80%.

### Сравнение

| Критерий | A: Python | B: CLI | C: custom/MCP |
|---|---|---|---|
| Новый код | Средний | Нет | Высокий |
| Контроль Brief | Максимальный | Ручной | Высокий |
| Изоляция файлов | Через worktree | Через `--dir` | Через worktree |
| Параллелизм | Да | Да (шелл) | Ограничен |
| Наблюдаемость | JSON + метрики | JSON | JSON |
| Риск рекурсии | Средний | Низкий | Высокий |
| Латентность | Высокая | Средняя | Высокая |
| Токен-стоимость | Baseline + Brief (снижается config-root) | Baseline + Brief (снижается config-root) | Baseline + Brief (снижается config-root) |
| Лучше всего для | Batch/воспроизводимость | Bootstrap | UX в сессии |

### Рекомендация

0. **Не пытаться изолировать через `agent.prompt`/`system`.** Docs v2: кастомный system prompt заменяет только provider base, а project instructions/skills/references всё равно добавляются. `task` вдобавок наследует `InstanceContext` родителя. Для strict isolation нужен **отдельный процесс** с пустым config-root, а не новый агент в той же сессии.
1. **Сейчас:** Вариант B — создать два профиля (`oneshot-read`, `oneshot-write`) на `tirtha/auto` **в отдельном config-root** (3.7; иначе baseline ~46k/шаг) и прогнать 1–3 задачи, замерить реальные токены/латентность.
2. **Целевой:** Вариант A — долгоживущий Brief-builder + runner с `--attach`, изолированным config-root, очисткой сессий и JSON-схемой выхода.
3. **Позже:** Вариант C — тонкая обёртка над A/SDK, только если нативный `task` неудобен. Не делать C основным.

---

## 6. Чеклист недостающих элементов

Приоритеты: P0 — без этого схема не работает; P1 — нужна для надёжности; P2 — улучшение.

| # | Элемент | Зачем | Где | Проверка | P |
|---|---|---|---|---|---|
| 1 | `agent.oneshot-read` + `agent.oneshot-write` (mode `primary` для CLI, `subagent` для Task), model `tirtha/auto` | Фиксированные `steps`, temperature, prompt, model | `opencode.jsonc` / `agents/oneshot-*.md` | `opencode agent list` | P0 |
| 2 | `permission`: read-профиль — `edit: deny`, `bash: deny`, `task: deny`, `question: deny`; write-профиль — `edit: allow` только в worktree, `bash` whitelist, `task/question: deny`, `external_directory: deny` | Не дать субагенту делать лишнее | config | `opencode debug config` | P0 |
| 3 | `subagent_depth: 0` или `1` | Запрет рекурсии | config | `debug config` | P0 |
| 4 | Brief-builder endpoint с точными `start/end` | Без него Brief — догадка | MSCodeBase (in-process, не CLI) | положительный/отрицательный контроль | P0 |
| 5 | Fallback границ символа на Python `ast`/tree-sitter | `lsp_document_symbols` таймаутит 15 с | MSCodeBase | тест на 3 функциях | P0 |
| 6 | Бюджет Brief ≤ 2000 токенов + `omitted` | Контроль контекста | Brief-builder | `len/4` + assert | P0 |
| 7 | Захват `sessionID` и `session delete` | Не копить 300+ сессий/неделю | runner | `opencode session list` до/после | P0 |
| 8 | Явный `--model tirtha/auto` для обоих профилей | Текущая модель сессии ≠ config | runner | лог модели в отчёте | P0 |
| 9 | `OPENCODE_DISABLE_PROJECT_CONFIG=1` (проверено: скрывает и проектного агента) | Убрать 10k проектных правил | env runner | агент должен лежать в config-root, не в проекте | P1 |
| 10 | Отдельный `AGENTS.subagent.md` (≤100 строк) | Заменить 30k baseline на 2–3k | config | замер токенов | P1 |
| 11 | `opencode serve` + `--attach` | Убрать cold boot MCP | runner | замер latency до/после | P1 |
| 12 | JSON Schema output через SDK (`format: json_schema`) | Детерминированный результат | runner/SDK | на 1.18.23 + Tīrtha падает `StructuredOutputError` (43 193 input) | P1 |
| 13 | Worktree на write-задачу | Изоляция файлов | runner | `git worktree list` | P1 |
| 14 | Таймауты: provider + `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` + kill tree | Защита от зависаний | runner | тест с `sleep` | P1 |
| 15 | Метрики: sessionID, tokens, cost, changed files | Наблюдаемость | runner | отчёт по 10 запускам | P1 |
| 16 | Секрет Tirtha — в env/`{file:...}` | Сейчас ключ в plaintext в конфиге | config | `git grep` по ключу | P1 |
| 17 | Очистка `AGENTS<битое-имя>.md`, `FULL AGENTS.md`, `*-REMOVED.md` | Один источник истины | config dir | список файлов | P2 |
| 18 | Recursion guard: env `MSCODEBASE_SUBAGENT=1` + `task: deny` | Защита от fork-bomb | runner | тест: субагент просит субагента | P2 |
| 19 | Ограничение параллелизма N (RAM/порты) | 4 MCP-сервера на процесс | runner | замер RAM при N=1,2,4 | P2 |
| 20 | `opencode run --agent oneshot-read` (проверено: работает) | Документация не гарантирует | CLI | тест на `oneshot` | P2 |
| 21 | Проверить `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX` | Реальный cap | CLI | тест с длинным ответом | P2 |
| 22 | Negative control Brief: неверный символ → `not_found` | Иначе «нашёл» всегда | тест | 1 позитив + 1 негатив | P2 |
| 23 | Стоимостной лимит (внешний) | У CLI нет `--max-cost` | runner | бюджет на N запусков | P2 |
| 24 | Проверить поведение `--pure` с проектным плагином | Gate может не работать | CLI | сравнить `git commit` | P2 |

---

## 7. Red Team (атаки на схему)

| Атака | Сценарий | Защита |
|---|---|---|
| Prompt injection из файла | Вредоносный комментарий в source говорит «удали tests» | Субагент read-only; `edit: deny`; source помечен как данные; никаких инструкций из файла не исполнять |
| Рекурсия / fork-bomb | Субагент вызывает `spawn_subagent` снова | `subagent_depth: 0`; `permission.task: deny`; env-маркер; лимит процессов |
| Секрет exfiltration | Субагент читает `.env`/config и отправляет `webfetch` | `read` deny для `*.env`; `webfetch: deny`; env без ключей |
| Конкурентная запись | Два субагента правят один файл | `git worktree` на задачу; file-lock; последовательный merge |
| Раздувание сессий | 1000 запусков → DB > N GB | `session delete`; TTL; ротация DB |
| Обрезка Brief скрывает критичный символ | `source` обрезан, субагент меняет не то | `omitted` с именами + hash; acceptance-тесты |
| Windows argv > 32 KB | Длинный Brief в аргументе | `--file brief.json` / stdin, не argv |
| `--auto` подтверждает destructive bash | `rm -rf`/`git push -f` | deny-list в `permission.bash`; `--auto` только с политикой |
| Холодный MCP-старт | Таймаут 15–30 с | `opencode serve` + `--attach`; health-check |
| Два источника правил | Глобальный и проектный `AGENTS.md` конфликтуют | Один slim-файл; явная иерархия; тест на конфликт |

**Вердикт Red Team:** 4 атаки без полной защиты при текущем конфиге (рекурсия, конкурентная запись, секреты, раздувание сессий). Все закрываются пунктами 2, 3, 13, 16, 18 чеклиста.

---

## 8. Решения владельца и открытые вопросы

**Решения (2026-10-20):**

1. **Модель:** `tirtha/auto` — одна и та же для обоих профилей. Расхождение `[C]` (config vs фактическая сессия) закрывается явным `--model` в runner.
2. **Режим:** оба сразу — два профиля:
   - `oneshot-read`: `edit: deny`, `bash: deny`, `task: deny`, `question: deny`.
   - `oneshot-write`: `edit: allow` только внутри `git worktree`, `bash` — whitelist (pytest/ruff/git status/diff), `task: deny`, acceptance-тесты обязательны.

**Открытые вопросы:**

1. **Baseline инструкций — решено:** для strict isolation нужен отдельный config-root (3.7: 3.9–6.9k/шаг). `task` для этого не подходит: он наследует global baseline и `InstanceContext`; `system` не отключает `AGENTS.md`. Открыто: готовы ли мы платить cold boot/латентность отдельного процесса на каждую микрозадачу?
2. **Параллелизм:** сколько одновременных субагентов допустимо на этой машине (RAM/порты)?
3. **Где хранить Brief'ы:** `experiments/**/frozen/` (по §17) или временная папка вне репо?
4. **Разрешён ли `--auto`** для write-субагентов, или только ручное подтверждение?
5. **Кто владеет сессиями:** главный агент удаляет их сразу или хранит N дней для аудита?

---

## 9. Приложение: команды и сырые факты

### 9.1. CLI

```powershell
& "$env:APPDATA\npm\opencode.cmd" --version
# 1.18.23

& "$env:APPDATA\npm\opencode.cmd" run --help
# --agent, --model, --variant, --format, --file, --title, --attach,
# --dir, --port, --auto, --pure, --continue, --session, --fork,
# --share, --thinking, -i/--interactive, --password, --username
# НЕТ: --yes, --max-steps, --no-save, --system-prompt, --max-tokens
```

### 9.2. Локальный конфиг

```powershell
& "$env:APPDATA\npm\opencode.cmd" debug config
# "model": "tirtha/auto"
# "agent": {}
# plugin: file:///D:/Project/MSCodeBase/.opencode/plugin/mscodebase_gate.ts
```

### 9.3. Использование

```powershell
& "$env:APPDATA\npm\opencode.cmd" stats --days 7 --tools 5
# Sessions 312, Messages 2209, Avg Tokens/Session 475.6K,
# Input 20.6M, Output 591.3K, Cost $0.13
```

### 9.4. MSCodeBase

```text
codebase(action="index", path="status")
# Chunks 12964 | Files 840 | Symbols 12231 | Embedder llama_cpp

get_symbol_info("get_progress_file")
# 1 defs, 4 callers, 8 callees; D:/Project/MSCodeBase/src/core/artifact_paths.py:302

impact_analysis("get_progress_file", depth=1)
# Completed (1160ms); direct callers 2; affected files 3; risk medium, score 31

read_live_file(start_line=296, end_line=312)
# status ok; total_lines 436; точный срез

lsp_document_symbols("src/core/artifact_paths.py")
# Timeout after 15000ms
```

### 9.5. CLI-мост MSCodeBase

```powershell
$json='{"targets":["get_progress_file"],"intent":"modify"}'
$json | & "D:\Project\MSCodeBase\venv\Scripts\python.exe" -m src.cli get_context -
# elapsed 18014 ms; ~682 tokens (chars/4);
# project_not_ready / UNINITIALIZED; get_symbol_info timeout 5005 ms
```

### 9.6. Ссылки

- OpenCode CLI: https://opencode.ai/docs/cli/
- OpenCode Config: https://opencode.ai/docs/config/
- OpenCode Agents: https://opencode.ai/docs/agents/
- OpenCode Tools: https://opencode.ai/docs/tools/
- OpenCode Rules: https://opencode.ai/docs/rules/
- OpenCode Custom Tools: https://opencode.ai/docs/custom-tools/
- OpenCode SDK: https://opencode.ai/docs/sdk/
- OpenCode v2 Instructions: https://opencode.ai/v2/docs/instructions/
- OpenCode v2 Agents: https://opencode.ai/v2/docs/agents
- Issue #4483 (subagents inherit AGENTS.md): https://github.com/anomalyco/opencode/issues/4483
- Issue #1668 (fresh dynamic prompt for subagents): https://github.com/anomalyco/opencode/issues/1668
- Issue #29271 (`task({directory})` / InstanceContext): https://github.com/anomalyco/opencode/issues/29271
- Issue #52625 (disable AGENTS.md injection into read results): https://github.com/anomalyco/opencode/issues/52625
- Issue #49842 (background subagents/worktree): https://github.com/anomalyco/opencode/issues/49842
- Thoughtworks, bounded context: https://www.thoughtworks.com/en-us/insights/blog/architecture/designing-agentic-delivery-for-bounded-context-and-bounded-human-attention
- Stackness, context rot: https://stackness.dev/blog/when-more-context-makes-your-coding-agent-worse-subagent-compact-clear-or-a-headless-loop
- CodeDelegator (arXiv 2601.14914): https://ar5iv.labs.arxiv.org/html/2601.14914
- Simon Willison, subagents: https://simonwillison.net/guides/agentic-engineering-patterns/subagents/
- Cline subagents: https://github.com/cline/cline/blob/main/docs/features/subagents.mdx
- Aider architect/editor: https://aider.chat/2024/09/26/architect.html
- OpenCode ACP (v2): https://opencode.ai/v2/docs/cli/acp
- ACP session setup: https://agentclientprotocol.com/protocol/v2/session-setup
- Claude Code subagents (`omitClaudeMd`): https://code.claude.com/docs/en/sub-agents
- Cursor subagents: https://cursor.com/docs/subagents
- GitHub Copilot subagents: https://docs.github.com/en/copilot/how-tos/copilot-in-your-ide/use-copilot-agents/use-subagents
- Codex MCP interface (`thread/start`): https://github.com/openai/codex/blob/main/codex-rs/docs/codex_mcp_interface.md

### 9.7. Команды замеров 3.7

```powershell
# baseline: глобальный config-root
& "$env:APPDATA\npm\opencode.cmd" run --agent build --model tirtha/auto `
  --format json --dir "$lab\project" `
  "Use the read tool to read hello.txt and return its exact contents. No preamble."

# изоляция: пустой config-root
$isoHome = "$lab\home"
$env:USERPROFILE = $isoHome; $env:HOME = $isoHome
$env:XDG_CONFIG_HOME = "$isoHome\.config"
$env:XDG_DATA_HOME  = "$isoHome\.local\share"
$env:XDG_CACHE_HOME = "$isoHome\.cache"
$env:OPENCODE_CONFIG = "$lab\opencode.json"
$env:TIRTHA_API_KEY = "<from global config, not printed>"
# для реального проекта: $env:OPENCODE_DISABLE_PROJECT_CONFIG = "1"  # не читать проектные AGENTS.md
& "$env:APPDATA\npm\opencode.cmd" run --agent oneshot-read --model tirtha/auto `
  --format json --dir "$lab\project" `
  "Use the read tool to read hello.txt and return its exact contents. No preamble."

# схемы и субагент: HTTP API
& "$env:APPDATA\npm\opencode.cmd" serve --port 4100 --hostname 127.0.0.1
# GET /config
# GET /experimental/tool?provider=tirtha&model=auto
# POST /session -> POST /session/{id}/message -> GET /session/{id}/children
```

Скрипты стенда: `schema_dump.py`, `subagent_probe.py`, `acp_probe.py` в `%TEMP%\opencode\tirtha-lab` (вне репозитория).

---

## 10. Готовые решения: fresh session без переоткрывания процесса

### 10.1. Главный вывод

`opencode acp` — один процесс, много ACP-сессий. Это ровно тот механизм, который нужен: не надо перезапускать OpenCode на каждую микрозадачу; клиент открывает `session/new`, получает новый `sessionId`, отправляет `session/prompt`, затем закрывает/удаляет сессию. Процесс живёт, пока клиент не закроет stdin.

Проверено локально на 1.18.23, без LLM-вызова: один процесс, два `session/new` → два разных ID. `session/delete` в 1.18.23 не реализован (`-32601 Method not found`); удаление — CLI `opencode session delete <id>`. В docs v2 `delete` уже указан в capabilities, в локальном `initialize` его нет.

Ограничение: `session/new` использует конфиг `cwd` — models, agents, commands, skills, instructions, plugins, MCP. Новая сессия чиста по истории, но **не** по глобальным/проектным instructions. Чтобы получить «без глобальных правил»: запускать `opencode acp` с пустым `HOME`/`XDG_*` и `cwd` без `AGENTS.md` (или `OPENCODE_DISABLE_PROJECT_CONFIG=1`). Иначе глобальный `AGENTS.md` останется.

MCP-изоляция отдельная: серверы, переданные в `session/new`, добавляются в директорию на всё время жизни ACP-процесса, и другие сессии этой директории могут их использовать. Для строгого режима — `mcpServers: []` и без глобальных MCP в config-root.

Схема:

```text
opencode acp (один процесс, изолированный config-root)
  initialize
  session/new {cwd: worktree A, mcpServers: []} -> ses_A
  session/prompt {ses_A, brief} -> JSON
  session/delete/CLI delete ses_A
  session/new {cwd: worktree B} -> ses_B
  ...
```

`session/new` принимает `cwd` на сессию; один ACP-процесс может обслуживать разные worktree. `additionalDirectories` — для внешних путей.

### 10.2. Сравнение

| Решение | Процесс | Чистая история | Глобальные инструкции |
|---|---|---|---|
| `opencode acp` | один, много сессий | да, `session/new` | да, если пустой config-root + cwd без AGENTS |
| `opencode run` на задачу | новый процесс | да | да, если пустой config-root |
| native `task` | родительский | да, child fresh | **нет**: наследует InstanceContext/AGENTS |
| Claude Code subagent | один | да | `omitClaudeMd: true`; managed policy остаётся |
| Cursor subagent | один | да | не гарантировано; fresh context, но rules/AGENTS не описаны как отключаемые |
| Copilot subagent | один | да | не гарантировано; тот же model/tools, isolated context |
| Codex MCP/app-server | один | `thread/start` | зависит от конфига; MCP server помечен legacy |

### 10.3. Claude Code как ориентир

`omitClaudeMd: true` — существующий флаг: subagent стартует без user/project/local `CLAUDE.md`; managed policy остаётся. Built-in Explore/Plan и так стартуют без `CLAUDE.md`. Это подтверждает: «fresh context» и «без глобальных правил» — разные переключатели, и второй уже реализован в зрелом продукте.

### 10.4. Рекомендация

Для OpenCode не нужен внешний process-per-task runner. Базовый вариант:

- один `opencode acp` на раннер, изолированный config-root;
- `session/new` на каждую микрозадачу (cwd = worktree);
- `session/prompt` с Brief ≤8k;
- результат — JSON; сессию закрыть/удалить;
- никаких `session/resume`/`fork` для микрозадач;
- parent не читает transcript child, только JSON/дифф.

Если ACP-клиент писать не хочется — fallback `opencode run` per task (процесс на задачу), но это уже переоткрывание. `serve` + `POST /session` — тот же long-lived вариант, но ACP чище: stdio, без порта, один private server.

---

## 11. Границы этого исследования

- `[U]`-пункты, которые остались: поведение `--agent` с subagent (проверен только `oneshot-read` как primary), точный смысл `steps` vs `maxSteps` (`steps: 2` упёрся в лимит до финального ответа), `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX`.
- **Версии:** локально 1.18.23; часть docs — v2. Семантика `system`/instructions проверена по v2-докам, но не все пункты прогнаны на 1.18.23. `task`-наследование `InstanceContext` — docs/issues (#29271), не рантайм-замер этой сессии.
- **`OPENCODE_DISABLE_PROJECT_CONFIG=1`:** docs говорят, что пропускает проектные `AGENTS.md`; локально проверено только, что скрывает проектного агента. Для глобального `AGENTS.md` этот флаг бесполезен.
- Токены в 3.7 — провайдерские `step_finish.tokens.input`, не оценка `chars/4`. Оценки `chars/4` оставлены только для размеров файлов и tool-схем.
- Латентность: server health 1.2 s; CLI-прогоны 3.9–40.6 s; parent+child 192.6 s (child 138.6 s). Это единичные прогоны, не бенчмарк.
- `format: json_schema` проверен и падает (`StructuredOutputError`, 43 193 input); structured output через CLI не проверялся.
- ACP: на 1.18.23 проверены только `initialize` и два `session/new` в одном процессе (разные ID); `session/prompt` не запускался, токены не мерились, `session/close` не проверялся. `session/delete` в 1.18.23 отсутствует; CLI `opencode session delete <id>` работает.
- Секреты в отчёт не включены; ключ Tirtha остаётся в конфиге и должен быть ротирован/перенесён.
- Существующие файлы проекта не изменялись, кроме этого отчёта; `AGENT_DIARY.md`/`KNOWN_ISSUES.md` не обновлялись — research-only по ТЗ. Глобальный `AGENTS.md` изменился внешне во время сессии (79 618 → 80 549 B) — это не моя правка.
