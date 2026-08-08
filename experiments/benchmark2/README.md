# Benchmark 2.0 — Repository Reasoning under Evidence

> Статус: scaffold v1 (2026-08-08). Основание: RepoReason (ACL 2026 — integration
> width, а не «сколько файлов прочитано») и Active-SWE (proactive bug discovery).
> Старый бенчмарк «query → 5 results → latency» не измеряет качество рассуждения.

## Уровни

| Level | Что измеряем | Пример |
|-------|-------------|--------|
| L1 | find symbol | `search_code("class Indexer")` |
| L2 | find relevant implementation | поиск по смыслу |
| L3 | explain architecture | почему notify_change может быть stale |
| L4 | impact analysis | что затронет изменение сигнатуры |
| L5 | find hidden bug | дефект без issue (см. MSC-2-005 — реальный) |
| L6 | propose patch | фикс + тест |
| L7 | verify patch | пост-верификация (Execution Contract) |

Benchmark 2.0 фокусируется на **L3–L5**: именно они дифференцируют нас и
коррелируют с ограничениями, вскрытыми RepoReason/Active-SWE.

## Каталог задач

`tasks.jsonl` — 12 задач (архитектура / impact / история / скрытые баги / consistency).
Каждая задача: `question`, `evidence` (файлы для сверки), `probes` (инструменты
для сбора улик), `check` (критерий ответа).

## Короткие запросы (CoREB-находка)

`keywords.jsonl` — 8 коротких keyword-запросов ("email", "auth", "db", "notify",
"rerank", "pid", "fts5", "embed"). CoREB (arXiv 2605.04615): короткие запросы
обрушивают nDCG@10 почти до нуля у всех моделей. Прогон: `runner.py --keywords`.
Результаты сверяются вручную/LLM-judge по hint в каждом кейсе.

## Харнесс

`runner.py` — собирает улики по probes в `out/evidence.jsonl` (in-process поиск
через DI; не-поисковые probes помечаются как manual).

**Внимание (найдено 2026-08-08):** live-фаза падает в manual, если MCP запущен —
PID-lock на LanceDB (30s ожидания, RuntimeError). Для live-прогона нужен
остановленный MCP или отдельный `MSCODEBASE_DATA_DIR`.

## Протокол оценки (LLM judge)

1. Запустить `python experiments/benchmark2/runner.py` (улики) + пройти probes вручную.
2. Для каждой задачи судья (LLM) оценивает ответ агента по 4 осям:
   - **Correctness** (0-1): соответствует ли `check`;
   - **Evidence** (0-1): использованы ли файлы из `evidence`;
   - **Integration width** (0-1): связал ли ответ ≥2 зависимых факта (RepoReason);
   - **Token cost** (0-1): минимальность контекста для ответа.
3. Итог: mean по задачам + отдельно latency (cold/warm).

## Отчётность

Результаты — в `out/report.md` (не в корень проекта, §0.6). Запись в
EXPERIMENTS_LOG.md с сырым выводом runner.
