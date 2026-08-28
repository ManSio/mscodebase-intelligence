# E2 — Live pilot: search_code fast vs quality, категорийная утечка (2026-08-25)

Цель: проверить на живом индексе две гипотезы категорийной идеи.
Запускается ТОЛЬКО при статусе индекса ✅ (не reindexing). Метод: живые MCP-вызовы,
по одному поиску; GT — факты этой сессии (верифицированы grep/read ранее).

## Гипотезы
- H2.1 Категорийная утечка: quality по кодовому запросу тянет чужие домены (docs/JSON),
      а fast — нет. (Уже поддержано M3: Q1 quality → results_tasks_v3.json + CHANGELOG.md.)
- H2.2 Маршрут «форма запроса → режим»: идентификаторные запросы выигрывают у fast,
      прозаические — у quality (с категорийным фильтром). (Поддержано абляцией 2026-08-11:
      B=501ms/одна стратегия vs A=2-6.8s, но wrong растёт на explain/test.)

## Запросы и ground truth (GT)
| # | Запрос | GT-файл | Категория |
|---|--------|---------|-----------|
| Q1 | `_get_stale_warning search_tools` | src/mcp/tools/search_tools.py | code (символ) |
| Q2 | `lock_guard acquire release stale` | scripts/lock_guard.py | code (файл) |
| Q3 | `tool_metrics load error_handler telemetry json` | src/mcp/server_tools.py (диагностика) | config/data |
| Q4 | `почему MCP замерзает full reindex get_status loop потоrок` | src/core/indexing/* (IndexStatusReporter) | code (проза) |
| Q5 | `verify_on_read matched delivered starved budget` | memory verify_cache (src/core/intelligence/*) | docs/code |
| Q6 | `smoke e2e real services llama reranker lance` | scripts/smoke_e2e.py | docs/script |

Уже измерено (M3): Q1 fast = 75ms, top-1 = GT (HIT); Q1 quality = 3666ms, top-3 мимо GT (MISS, утечка в JSON/CHANGELOG).

## Оставшийся прогон (8 вызовов, когда индекс ✅)
- fast: Q2, Q3, Q4, Q5, Q6 (5 вызовов, limit=3)
- quality: Q4, Q5, Q6 (3 вызова, limit=3) — прозаические, где качество должно выигрывать

## РЕЗУЛЬТАТ (2026-08-25/26, индекс 9089 chunks после reindex)
| # | Запрос | GT | fast | quality |
|---|--------|-----|------|---------|
| Q1 | `_get_stale_warning search_tools` | search_tools.py | HIT top-1, 75ms (M3, тёплый) | **MISS 3666ms — утечка в JSON/CHANGELOG** (M3) |
| Q2 | `lock_guard acquire release stale` | scripts/lock_guard.py | HIT top-1, 3779ms (холодный старт) / 161ms тёплый | — |
| Q3 | `tool_metrics load error_handler telemetry json` | error_handler.py | HIT домен (get_tool_metrics + JSON в top-3), 161ms | — |
| Q4 | `почему MCP замерзает full reindex get_status loop потоrок` | src/core/indexing/indexer.py | **MISS 190ms — top-1 = мой E2-док (само-загрязнение)** | **HIT домен 6638ms — indexer.py top-2** |
| Q5 | `verify_on_read matched delivered starved budget` | verify_on_read.py | HIT top-3, 172ms | HIT top-3 (+фрагмент matched/delivered), 284ms |
| Q6 | `smoke e2e real services llama reranker lance` | scripts/smoke_e2e.py | HIT top-3, 166ms | HIT top-3, 2638ms (top-1 — incident_dataset) |

## Вердикт E2
- **H2.1 (утечка между категориями) — ПОДТВЕРЖДЕНА, но с нюансом:** quality по кодовым запросам чаще тянет документы/JSON (Q1 miss → JSON+CHANGELOG; Q4/Q6 top-1 → incident-датасеты), но инцидент-датасеты семантически релевантны, а не мусор. Быстрый фикс — категорийный фильтр/приоритет (kernel: эксперименты/docs ниже кода при кодовом интенте).
- **H2.2 (форма запроса → режим) — ЧАСТИЧНО:** fast 5/6 (83%), единственный fast-MISS (Q4, проза) спасён quality (HIT домен) — но ценой 6638ms (fast 190ms), т.е. ~35×. quality НЕ универсален: Q1 quality тоже MIS (3666ms). Вывод: бинарный роут fast/quality — не панацея; эффективнее каскад: fast-hit → стоп; fast-MISS → quality с категорийным фильтром и бюджетом.
- **Новая находка: само-загрязнение индекса своими же доками** (experiments/mech_orch/*: top-1 в Q4 fast). Дешёвый фикс: исключать `experiments/**` и `docs/**` из кодового ранга или понижать вес; валидировать на tasks_v3.json.
- **Латентность (тёплая): fast 75–190ms; quality 284ms–6638ms (медиана ~2.6s, холод 6.6s).** Для сравнения методология 2026-08-11: стратегия B (1 вызов) 501ms vs A (многошаг) 2-6.8s.

## Рубрика (для каждого вызова)
- lat_ms (из ответа) + top-N файлы
- hit: GT-файл в top-3?  domain: домен GT в top-3?
- leak: топ-N содержит чужие домены (JSON/docs для кода и наоборот)?
- вердикт по H2.1/H2.2 на строке таблицы

## Ограничения
- N=6, пилот, не статистика; CI не считаем. Цель — направить E3 (категорийный роутер
  на datasets/context_engine/tasks_v3.json, 30 задач с GT).
- Индекс прогрет после полного reindex 2026-08-25 (9082 чанка).

## Зафиксированная находка (мониторинг реиндекса)
Лог-сводка фазы «Индексация завершена» (362с, 9082 чанка) появляется ДО того, как
job-статус дойдёт до 100% (runtime_status показывал 75% после финальной сводки лога;
search гейтился «reindexing»). Рассинхрон «фаз лога vs job-прогресса» — строка для
telemetry-доработки (прогресс из job-хранилища, а не из лога; ~2-4 мин отставания).