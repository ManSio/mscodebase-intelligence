<div align="center">

<img src="../logo/baner.png" alt="MSCodeBase Banner" width="100%"/>

[English](../../README.md) · [Русский](README.md) · [中文](../zh/README.md)

# MSCodebase Intelligence

**Локальный code intelligence для OpenCode и Zed: один вопрос — параллельный поиск по всем каналам, лексический поиск, граф вызовов, impact analysis, память проекта и безопасные правки через MCP.**

*Переписано: 2026-11-08. Описывает код в его текущем состоянии; канон — английская версия, здесь — полный перевод ключевых разделов.*

</div>

---

## Что это

Локальный MCP-сервер, который даёт ИИ-ассистенту в OpenCode (или Zed) обоснованное представление о кодовой базе. Это не чат-модель и не замена языковому серверу редактора. Он отвечает на четыре типа вопросов:

- Где определён символ, кто его вызывает и что сломается при изменении?
- Какие файлы важны для вопроса — код, тесты или документация?
- Что проект уже решил и какие инциденты ещё открыты?
- Можно ли безопасно выполнить rename/move/replace и увидеть последствия заранее?

По умолчанию сервер работает **text-first**: SQLite FTS5/BM25 по разобранным чанкам плюс индекс Tree-sitter/PropertyGraph. Эмбеддинги и реранкер опциональны; GPU, сеть и векторная БД для ответа на вопрос о коде не нужны.

## Что работает сегодня

| Область | Что делает | Точка входа (entry point) |
|---|---|---|
| **Один вызов на вопрос** | Вопрос → параллельно поиск + символы + grep, затем impact + вызывающие + тесты + память проекта; слияние по file:line с провенансом и `degraded[]` | `investigate` |
| Поиск по коду | BM25/FTS5 по чанкам; короткое замыкание по графу для идентификаторов; опциональный rerank верхних кандидатов | `search_code` |
| Поиск по документации | Отдельный FTS-канал по `docs/**`, включается по margin BM25 (без LLM-роутера) | `search_code` |
| Regex-поиск | Regex с AST-фильтром `scope=code`, который пропускает комментарии и строки (проверка по каждому совпадению) | `grep_code` |
| Символы | Определение, вызывающие, вызываемые, ссылки, impact, структурный поиск | `get_symbol_info`, `impact_analysis` |
| Граф | PropertyGraph с рёбрами call/import/assignment/decorator/override | `graph_query`, `codebase` |
| Память проекта | ADR, инциденты, известные проблемы, retract/supersede | `intel_*` (скрыты по умолчанию) |
| Безопасные правки | Rename/move/delete/replace/insert с impact-guard и квитанциями | `codebase(action=…)` |
| Диагностика | Health, статус индекса, логи, счётчики, предсказание правки | `get_health_report`, `predict_change` |
| Обнаружение | Активный профиль, видимые и скрытые инструменты | `tool_help` |

## Как отвечается вопрос

`investigate` — точка входа по умолчанию. Модель не выбирает инструмент; сервер сам запускает нужные каналы и сливает ответы.

```
investigate("как индексатор решает, что файл надо переиндексировать")
        │
        ├─ проход 1 (параллельно)   search ─ symbols ─ grep
        ▼
        ├─ проход 2 (параллельно)   impact ─ callers ─ tests ─ память
        │                            только для того, что нашёл проход 1
        ▼
   слияние по (file, line): одна строка на попадание, каналы объединены
   провенанс у каждого пункта, degraded[] для медленного/упавшего канала
```

Правила:

- Медленный канал **деградирует** ответ (`degraded: grep:timeout`), а не валит вызов.
- Нет совпадений — явное «ничего не найдено», без правдоподобных догадок.
- Ответ ограничен (8 строк, 180 символов текста), чтобы не заливать контекст.
- `search_code`, `grep_code`, `get_symbol_info` и `impact_analysis` остаются для точного уточнения.

## Качество поиска: измерено, с границами

Цифры из внутренней **панели из 48 запросов** (33 реальных вопроса по проекту + 15 из docstring), на чистом индексе без `experiments/**`. Слепок: **2026-10-25**; перед публикацией перезапускать харнессы в `experiments/`.

| Путь | hit@1 | hit@5 |
|---|---:|---:|
| Код, quality mode | 0.825 | 0.900 |
| Общий, quality mode | 0.688 | 0.750 |
| Общий, авто-роутинг в docs | 0.792 | 0.875 |
| Fast mode | 0.542 | 0.729 |
| Docs, точный путь | 0.000 | 0.125 |
| Docs, по basename | 0.750 | 0.750 |

Чего эти числа **не** означают:

- Это **не** 95%. Статический retrieval на этой панели до 95% не дошёл; двухканальная карта репозитория упиралась в ~40% / 62% / 73% при 1k / 2k / 4k токенов даже при идеальном роутинге.
- Не значит, что любой реранкер улучшает: несколько локальных были измерены и отклонены.
- Не значит, что docs сломан: он часто возвращает верный документ на другом языке (`docs/ru/X` вместо `docs/en/X`). Это свойство золотой разметки, а не провал поиска.

Все публичные числа и команда перевывода — в **[docs/FACTS.md](../FACTS.md)**.

## Быстрый старт

Требования: Windows — проверенная платформа; Python 3.14+; любой MCP-хост
(OpenCode, Zed, Claude Code, Cursor или универсальный `mcpServers`-клиент).

```bash
cd <repo-root>
python install.py                        # venv + зависимости + код: text-first, без моделей
python install.py --with-models          # опционально: + ONNX/GGUF модели (~657 МБ)
python install.py --sync                 # после правки кода — только копирование кода
```

Установка нейтральна к хосту: на диск кладётся обычное Python-окружение (по умолчанию
`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence` — имя историческое). Другой
путь задаётся `MSCODEBASE_INSTALL_ROOT`. Затем напечатайте конфиг для своего хоста
вместо того, чтобы писать его руками:

```bash
python install.py --print-config --client generic      # хосты формы mcpServers
python install.py --print-config --client opencode
python install.py --print-config --client claude-code
python install.py --print-config --client cursor
python install.py --print-config --client zed
```

Каждая команда печатает один JSON-объект: интерпретатор, `-u -m src.main`,
`PYTHONPATH`, `PROJECT_PATH`, `PYTHONUTF8=1`; вставьте его в MCP-конфиг хоста.
Секции для каждого клиента и проверка запуска
(`python scripts/verify_client_snippets.py`) — в [docs/ru/CLIENTS.md](CLIENTS.md).
После настройки перезапустите хост.

Проверка из панели агента:

```text
tool_help()                        # профиль, видимые и скрытые инструменты
get_health_report()                # индекс, embedder, ресурсы
codebase(action="index", path="status")
```

Если текстовый индекс отсутствует или устарел — пересобрать чанки и граф без эмбеддингов (замер: 498 файлов, 7 375 чанков, 262–266 с):

```bash
python scripts/reindex_text_only.py --project .
```

Если пуст только граф, а чанки есть:

```bash
python scripts/rebuild_graph.py
```

Затем перезапустить MCP-сервер, чтобы новый процесс открыл пересобранные хранилища.

## Инструменты и профиль

Сервер регистрирует **69 инструментов** (36 core + 16 intel + 13 inline + 4 dev); `execute_script` — опциональный 70-й при `MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`. Для модели это слишком много, поэтому клиент видит **профиль**:

| Профиль | Видимо | Содержимое |
|---|---:|---|
| `core` (по умолчанию) | **17** | по одному входу на намерение + 4 обслуживающих |
| `full` | **69** | всё зарегистрированное |

`MSCODEBASE_MCP_TOOLS` по-прежнему работает как явный allowlist и перекрывает профиль. `tool_help()` показывает профиль, видимые инструменты с назначением и имена скрытых.

Видимые 17: `investigate`, `search_code`, `grep_code`, `get_symbol_info`, `impact_analysis`, `graph_query`, `codebase`, `read_live_file`, `notify_change`, `get_health_report`, `intel_get_project_memory`, `predict_change`, `tool_help`, `generate_docs`, `bump_version`, `auto_update_docs`, `install_git_hooks`.

Индексация асинхронна: `codebase(action="index", path="project_dir", project_root=...)` запускает
фоновую задачу и сразу возвращает управление; прогресс — `codebase(action="index", path="progress",
...)` (`state` / `files` / `elapsed`). Неиндексированный проект отклоняется быстро с точной
подсказкой, а не после 5-секундного ожидания.

Скрыты по умолчанию: шесть `lsp_*`, `plan_search`, `structural_search`, 16 `intel_*` (мутации/жизненный цикл), `submit_background_task` / `get_task_status` / `verify_action` / `get_action_receipt`, `ack_impact`, служебные frame/rank/scan. Включаются `MSCODEBASE_MCP_PROFILE=full`; из сервера ничего не удаляется, фильтруется только клиентская поверхность.

## Архитектура

```text
MCP-хост: OpenCode (основной) или Zed
 │
 ├── встроенный LSP хоста (автодополнение, диагностика)
 │
 └── MCP-клиент
      │
      ▼
 MSCodebase MCP server
  ├── investigate   двухпроходный параллельный fan-out, слияние с провенансом
  ├── Search        SQLite FTS5/BM25, сигналы символов/путей, роутинг docs
  ├── Graph         PropertyGraph: calls, imports, assignments, decorators, overrides
  ├── Index         parser → chunks → FTS5 + граф; инкрементальная свежесть
  ├── Memory        ADR, инциденты, known issues, retract/supersede
  ├── Writes        rename/move/delete/replace/insert с impact-guard
  ├── Diagnostics   health, jobs, логи, телеметрия, предсказание правки
  └── Optional      embedders, reranker, LSP rename
```

Канонические расположения данных (вне репозитория):

- `%LOCALAPPDATA%/mscodebase/projects/<hash>/` — граф проекта, память, состояние задач, commit memory, телеметрия.
- `%LOCALAPPDATA%/mscodebase/logs/` — логи сервера.
- `<project>/.mscodebase/chunks.db` — хранилище текстовых чанков для пути по умолчанию.

LanceDB относится к опциональному векторному пути и не требуется в text-first конфигурации.

## Конфигурация

Настройки — переменные окружения с дефолтами в `src/config/settings.py`. Главные:

| Переменная | Дефолт | Эффект |
|---|---|---|
| `MSCODEBASE_DENSE_OFF` | `true` | Не использовать dense/vector; только FTS5, символы, граф |
| `MSCODEBASE_SQLITE_CHUNKS` | `true` | Использовать SQLite/FTS5 хранилище чанков |
| `MSCODEBASE_ONDEMAND_RERANK` | `false` | Реранк верхних кандидатов живыми эмбеддингами; на вызов: `investigate(rerank=true)` |
| `MSCODEBASE_DOCS_MARGIN` | `4.0` | Порог роутинга в docs (docs − code) |
| `MSCODEBASE_AUGMENT_CHUNKS` | `true` | Префикс FILE/SYMBOLS/DOC в тексте чанка |
| `MSCODEBASE_TESTS_SIGNAL` | `false` | Добавлять покрывающие тесты к результатам по символу |
| `MSCODEBASE_CODE_BM25` | `false` | BM25 с учётом идентификаторов |
| `MSCODEBASE_RU_SYNONYMS` | `false` | Расширение RU → EN кодовых терминов |
| `MSCODEBASE_MCP_PROFILE` | `core` | Поверхность: 17 видимых или все 69 (`full`) |
| `MSCODEBASE_MCP_TOOLS` | — | Явный allowlist; перекрывает профиль |

`experiments/**` намеренно исключён из индексации: там frozen-панели и артефакты прогонов, и их индексация раньше заставляла BM25 возвращать саму панель вместо кода. Файлы при этом остаются в git.

## Поддерживаемые языки

Python — основной, полностью отработанный язык. Tree-sitter разбирает JavaScript, TypeScript/TSX, Rust, Go, Java, C#, Ruby, PHP, Kotlin, Swift, C, C++, Scala и Dart; SQL, YAML, TOML, HTML, CSS и HCL/Terraform индексируются как контекст без той же глубины графа. Текущая сборка загружает **31 грамматику**; глубина графа и data-flow зависит от грамматики.

<!-- stale-ignore -->
Версии закреплены для воспроизводимости: `tree-sitter==0.26.0` (последняя Python-привязка на PyPI), `tree-sitter-language-pack==1.25.0` и по одному пину на грамматику. Обновление грамматики меняет нарезку на чанки, поэтому требует переиндексации и сравнения числа символов, а не «просто апгрейда».
<!-- stale-ignore -->

## Ограничения

Осознанные границы, а не скрытое поведение:

- **Docs-gold и язык:** канал docs может вернуть `docs/ru/X.md`, когда золото — `docs/en/X.md`. При оценке нормализуйте по basename.
- **Авто-роутинг в docs эвристичен:** запрос по коду с сильными «документационными» словами может уйти в docs; `intent="code"` — выход.
- **Полный векторный reindex заблокирован** при `MSCODEBASE_DENSE_OFF=true`: граф — `scripts/rebuild_graph.py`, чанки — `scripts/reindex_text_only.py`.
- **Заявки на 95% нет:** статический retrieval и проверенные локальные реранкеры до неё не дошли; LLM-планировщик — отдельный эксперимент, не дефолт.
- **Fast mode — не quality mode:** быстрее, но заметно менее точен на смешанных вопросах.
- **Видимость инструментов — профиль:** 69 зарегистрировано, 17 видимо. Нет ожидаемого — `tool_help()` и смена профиля.
- **LSP-тулы требуют working basedpyright:** при отсутствии падают быстро и понятно, результат кешируется на 30 с.

## Разработка

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Точечные тесты поиска
pytest tests/test_search_docs.py tests/test_query_plan.py tests/test_searcher.py -q

# Полный прогон (integration/benchmark выбираются маркерами)
pytest tests/ -m "not integration and not benchmark"

# Живой smoke: реальные сервисы, без моков
python scripts/smoke_e2e.py --project .
```

Репозиторий использует Conventional Commits, хранит входы экспериментов в `experiments/**/frozen/` и фиксирует результаты в `EXPERIMENTS_LOG.md`, `AGENT_DIARY.md`, `KNOWN_ISSUES.md`.

## Сообщить о баге

Полезный отчёт — маленький эксперимент:

1. Точный вызов и параметры (`query`, `mode`, `intent`, `limit`).
2. `tool_help()` / `get_health_report()` и `codebase(action="index", path="status")`.
3. Пересобирался ли граф и какие флаги стояли (`MSCODEBASE_DENSE_OFF`, `MSCODEBASE_ONDEMAND_RERANK`, профиль).
4. Ожидаемый файл и фактический, и является ли совпадение точным путём или только basename.
5. Хвост лога из `%LOCALAPPDATA%/mscodebase/logs/`.

Это разделяет четыре похожие поломки: плохой ранжировщик, отсутствие кандидата, устаревший/пустой индекс и ошибка золотой разметки.

## Карта документации

| Документ | О чём |
|---|---|
| [docs/FACTS.md](../FACTS.md) | Все публичные числа и команды перевывода |
| [docs/ru/ARCHITECTURE.md](ARCHITECTURE.md) | Слои, DI, границы модулей, профиль инструментов |
| [docs/ru/SEARCH_PIPELINE.md](SEARCH_PIPELINE.md) | Retrieval, ранжирование, docs-роутинг, fan-out `investigate` |
| [docs/ru/INSTALL.md](INSTALL.md) | Установка, цикл sync+restart, doctor/clean, диагностика |
| [docs/ru/DATA_MAP.md](DATA_MAP.md) | Каждый путь, созданный установщиком/сервером: размеры и политики хранения |
| [docs/ru/CONFIGURATION.md](CONFIGURATION.md) | Все переменные окружения и их значения по умолчанию |
| [docs/ru/CLIENTS.md](CLIENTS.md) | OpenCode, Zed, Claude Code, VS Code, CLI, Docker |
| [docs/ru/HOOKS_AND_GATES.md](HOOKS_AND_GATES.md) | Хук OpenCode, 12 гейтов pre-commit, джобы CI |
| [docs/ru/FAQ.md](FAQ.md) | Короткие ответы на первые вопросы |
| [docs/ru/SECURITY.md](SECURITY.md) | Модель угроз локального MCP-сервера |
| [docs/ru/GRACEFUL_DEGRADATION.md](GRACEFUL_DEGRADATION.md) | Поведение при недоступных провайдерах |
| [docs/ru/ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md) | Windows-поведение, общее для обоих хостов |
| [docs/ru/CHANGELOG.md](CHANGELOG.md) | История версий |
| [AGENTS.md](../../AGENTS.md) | Правила для ИИ-агентов в этом репозитории |
| [KNOWN_ISSUES.md](../../KNOWN_ISSUES.md) | Открытый техдолг и наблюдения |
| [EXPERIMENTS_LOG.md](../../EXPERIMENTS_LOG.md) | Гипотезы и сырые результаты экспериментов |

Английские оригиналы — в `docs/en/`, китайские переводы — в `docs/zh/` с теми же именами файлов.

Исторические материалы (блоги, research-заметки, архивные дневники) сохранены для провенанса и помечены баннерами; это не описание сегодняшнего состояния.

## Лицензия

MIT. См. [LICENSE](../../LICENSE).
