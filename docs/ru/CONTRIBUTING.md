# Участие в разработке — MSCodeBase Intelligence

> Перевод: 2026-11-08, источник — docs/en/CONTRIBUTING.md. Английская версия — канон.

[English](../en/CONTRIBUTING.md) · [Русский](CONTRIBUTING.md) · [中文](../zh/CONTRIBUTING.md)

> Версия 3.5.0 · Python >= 3.14 · MIT

Локальный MCP-сервер: он индексирует репозиторий через Tree-sitter, хранит текст
чанков в SQLite FTS5 плюс PropertyGraph и отвечает на вопросы о коде по MCP.
Прочитайте `AGENTS.md` (в корне репозитория) перед первой правкой — там правила
работы и контракт гигиены корня (§0.6: разрешённый набор корня).

## 1. Структура

```
src/core/        индекс, поиск, граф, intelligence, guards (никогда не импортирует mcp)
src/mcp/         сервер, классы инструментов, транспорты (зависит от core, не наоборот)
src/providers/   реализации эмбеддера / реранкера (llama.cpp, LM Studio, ONNX)
src/config/      settings.py — каждая настройка это env-переменная со значением по умолчанию
scripts/         операционные и гейтовые скрипты (reindex, verify_clean_state, lint)
tools/           инструментарий разработчика (гейты проверки, проверки знаний, пайплайны)
experiments/     пробы и замороженные входы; исключены из индексации и из pytest
tests/           ~240 тестовых модулей верхнего уровня плюс tests/e2e и tests/fixtures
docs/            каноническая документация; docs/FACTS.md владеет всеми цитируемыми числами
```

Слоистость проверяется принудительно: `scripts/check_layer_boundaries.py` падает
на импортах `core → mcp` и на зависимостях слоя инструментов в обход core.

## 2. Настройка

```powershell
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence
python -m venv venv; venv\Scripts\activate; pip install -e ".[dev]"
```

`pip install -e .` достаточно для text-first runtime. Модели опциональны и
никогда не скачиваются молча: `python install.py` спрашивает перед каждым
скачиванием и принимает `--skip-models`; `--sync-only` копирует код в каталог
расширения, не трогая pip и модели.

## 3. Тесты и линт

`pyproject.toml` задаёт `addopts = "-v --tb=short -m 'not slow and not benchmark'"`.
Этот дефолт важен:

```bash
python -m pytest tests/ -q                    # slow + benchmark исключены (addopts)
python -m pytest tests/ -m "not benchmark"     # включает slow-тесты
python -m pytest tests/ -q -n auto --cov=src   # то, что делает CI (порог покрытия: 38%)
```

Зелёный `pytest tests/ -q` **не** означает, что slow-тесты проходят. CI прогоняет
выборку `not slow and not benchmark` с `--cov=src --cov-fail-under=38` на
ubuntu-latest и windows-latest, только Python 3.14. Линт: `ruff check src/ tests/`
(CI) или `python scripts/ruff_gate.py` (pre-commit).

## 4. Добавление инструмента

Инструмент — это класс, запись регистрации и решение о профиле.

```python
class MyTool(MCPTool):
    def __init__(self, services):
        super().__init__(services, tool_name="my_tool")

    async def execute(self, query: str) -> str | dict:
        indexer = self.resolve_indexer()   # per-project, not a global singleton
        ...
```

1. **Класс** — наследник `MCPTool` в `src/mcp/tools/<area>.py`. Правила,
   проверяемые ревью и гейтами: зависимости через `self._services` (DI), никаких
   глобальных переменных уровня модуля; готовность из `RuntimeCoordinator` /
   `require_index()`, а не собственной проверкой; возвращайте `str` или
   JSON-сериализуемый `dict`; на сбоях выбрасывайте `ToolError` (или
   `IndexNotReadyError` / `RateLimitError`), чтобы вызывающий получил `status`
   (`error`/`warning`/`timeout`) и флаг `recoverable`; декорируйте `execute`
   через `@error_boundary("<tool>", timeout_ms=...)`.
2. **Записи** — идут через `WriteTool.execute` (`src/mcp/tools/write_tools.py`),
   декорированный `@modification_guard(pagerank_min=0.05, blast_min=10, ack_ttl=600)`.
   Гейт запрещает записи в несущие файлы, пока `ack_impact` не предъявит
   валидный impact-токен; не добавляйте второй, недекорированный путь записи.
3. **Регистрация** — добавьте класс в `tool_classes` в
   `src/mcp/server_tools.py::register_all_tools()`. Не регистрируйте его напрямую
   в MCP-приложении где-либо ещё: фильтр профилей срабатывает после регистрации
   всех групп.
4. **Профиль** — поместите его в `CORE_PROFILE` (дефолтная поверхность из 17
   инструментов, одна запись на намерение) или оставьте видимым только при
   `MSCODEBASE_MCP_PROFILE=full`. Счётчики зафиксированы в docstring модуля:
   36 core + 16 intel + 13 inline + 4 dev = 69.
5. **Тест и документация** — добавьте unit-тест в `tests/`; всё, что касается
   поиска или индекса, нуждается в кейсе, который упал бы, если бы инструмент
   молча вернул пусто. Если поверхность изменилась, обновите текст, видимый в
   `tool_help`, и любой документ, перечисляющий инструменты.

## 5. Коммиты и pull request

Conventional Commits, императив, атомарно:

```
feat(search): add code-aware BM25 term field

Restate the diff, not the intent. Explain why when the why is not obvious.
```

- Subject <= 72 символов, без точки в конце, пустая строка перед телом; breaking
  change — как `type(scope)!:` плюс футер `BREAKING CHANGE:`.
- Индексируйте файлы явно (`git add src/core/x.py tests/test_x.py`). `git add -A`,
  `git add .` и `git commit -a` запрещены — checkout может быть общим с другим
  агентом или worktree, и массовый add затянет их незавершённую работу. Сначала
  выполните `git worktree list` и `git status`; файл, изменённый в другом месте,
  блокируется `scripts/check_parallel_sessions.py`.
- Никаких сгенерированных артефактов и одноразовых файлов:
  `docs/generated/MODULE_INDEX.md` не трекается, `experiments/**/results` не
  индексируется, а набор корня зафиксирован в `AGENTS.md` §0.6. Одна тема на PR;
  перед запросом ревью проведите self-review диффа: каждая удалённая строка
  намеренная, описание не богаче диффа.

## 6. Гейты

`core.hooksPath = .githooks`; `.githooks/pre-commit` запускает следующее (бюджет
900 s на гейт, `MSCB_PRECOMMIT_GATE_TIMEOUT`):

| Гейт | Скрипт |
|---|---|
| gate-zero + дневник | `scripts/verify_diary.py` (полный `pytest tests/`; пропускается для коммитов только с документацией или при `--skip-gate-zero`) |
| дрейф версий | `scripts/stale_detector.py --staged` |
| имена инструментов | `scripts/check_tool_names.py` |
| негативные контроли | `scripts/negative_controls_runner.py` |
| границы слоёв | `scripts/check_layer_boundaries.py` |
| архитектурные инварианты | `scripts/architecture_linter.py` |
| git-локи (advisory) | `scripts/lock_guard.py` |
| размер known-issues | `scripts/check_known_issues.py` |
| сторонние данные | `scripts/check_third_party_data.py` |
| параллельные сессии | `scripts/check_parallel_sessions.py` |
| линт | `scripts/ruff_gate.py` |

CI добавляет `bump_version.py --check`, `disk_guard.py --check`, `pip-audit`,
`verify_clean_state.sh --no-clone`, `manifest_parity.py` и e2e-задачу проверки
эквивалентности транспортов. Проверяйте CI через `gh run list --branch <branch>` и
`gh run view <id> --log-failed`, а не по предположению.

## 7. Документация и реестры

- Числа (чанки, файлы, узлы, рёбра, качество, тайминги) живут **только** в
  `docs/FACTS.md`, вместе с командой, которая их пересоздаёт.
- Канонические страницы существуют на трёх языках (`docs/en`, `docs/ru`,
  `docs/zh`); изменение одной — это изменение трёх файлов. Исторический материал в
  `docs/blog`, `docs/research`, `docs/archive` сохраняет свой баннер и дату — не
  переписывайте его. Ссылайтесь на факт как `(file, commit SHA, record ID)`, а не
  `file:line`: номера строк гниют.
- Реестры: `AGENT_DIARY.md` (один дневник; `DEV_DIARY.md` — редирект),
  `KNOWN_ISSUES.md` (<= 300 строк, старые записи уезжают в
  `docs/archive/KNOWN_ISSUES_YYYY_MM.md`), `EXPERIMENTS_LOG.md`, `WISDOM.md`.
  Обновляйте их в том же коммите; второй дневник или второй `KNOWN_ISSUES.md` —
  дефект, а не вариант.

**Verified against:** `pyproject.toml`, `.github/workflows/ci.yml`,
`.githooks/pre-commit`, `src/mcp/server_tools.py`, `src/mcp/tools/base.py`,
`src/core/modification_guard.py`, `src/core/error_handler.py`, `install.py`,
`AGENTS.md` (§0.6), directory listing of `src/`, `tests/`, `scripts/`, `tools/`,
`experiments/`.
