# Experiment 1-L — 30-Day Longitudinal Study (дизайн)

> Дата: 2026-08-14 · Тип: дизайн-документ (запуск сбора — по решению владельца).
> Ответ на ревью: *«детерминированный proxy-агент вместо живой модели — headline-числа
> (100% adoption) берутся оттуда; с живым Claude или GPT-4o цифры будут другими»*.

## Зачем

Exp 1-V / 1-V-REP дали архитектурное доказательство на синтетике + proxy-агенте.
1-L должен дать **реальный % adoption и ложных отзывов на ЖИВОЙ модели** в
production-цикле 30 дней. Статья Part 4 пишет себя сама из этих данных.

## Ключевая поправка (ответ на критику)

- **Arm A (live)** — те же 50 фактов 1-V прогоняются через живую модель
  (Claude/GPT-4o; API-ключ владельца) с теми же якорями. Гипотеза: adoption
  memory_first упадёт с синтетических 0.16/0.24 к реальному числу; false REFUTED
  могут вырасти (живая модель «читает» иначе, чем эвристика).
- **Arm B (proxy, контроль)** — детерминированный агент 1-V, для калибровки.
- **Правило контрольной группы (§1 AGENTS.md):** обе руки — те же 50 фактов, те же
  якоря, та же сессия, та же методика подсчёта. Сравнение «было/стало» — только в
  одном прогоне.

## Метрики (ежедневный снимок, 30 дней)

| Метрика | Источник | Ожидание |
|---|---|---|
| memory statuses (V/A/R/S) | `IntelligenceStore.memory_metrics()` | дрейф распределения |
| false_retraction_rate | `memory_metrics()` | рост = ложные отзывы на живых данных |
| refuted_total / причины | `intel_get_project_memory` | распределение причин отзыва |
| verify latency (first/steady) | VOR-ресипт | бюджет ≤50ms |
| checked/total (пол Тома) | VOR-ресипт | не 0 |
| adoption (live arm) | прогон 1-V harness на живой модели | реальный %, не 0.16/0.24 |
| revision (git HEAD) | snapshot | привязка к коду (revision gate) |

## Сбор данных

- `scripts/collect_memory_snapshot.py` — append JSONL
  `data_root/experiments/longitudinal_1L.jsonl` (только чтение memory store, MCP не нужен).
- `scripts/run_1L_live_arm.py` — Arm A (live model, deepseek-v4-flash): вердикты по тем же
  50 фактам (memory_first / code_first), ключ только из env (DEEPSEEK_API_KEY/LLM_API_KEY),
  без ключа — честный exit 2 (не молча, не фейк). Результат — JSON в data_root/experiments/.
- Автозапуск: по решению владельца (планировщик/начало сессии) — оба скрипта безопасны.

## Расписание

- **День 1 (baseline):** первый снимок + live-arm прогон на 50 фактах 1-V.
- **Дни 2–30:** ежедневный снимок метрик.
- **День 30 (разбор):** adoption_live vs adoption_proxy, false_retraction_trend,
  сравнение с таблицей 1-V («было/стало»), статья Part 4 + запись в EXPERIMENTS_LOG.

## DoD (закрытие эксперимента)

- [ ] ≥30 снимков в JSONL
- [ ] Live-arm прогон минимум 1 (рекомендация 3 — по неделе)
- [ ] Отчёт: реальные числа vs 1-V, таблица «было/стало», вердикт по гипотезе ревью
      («цифры будут другими» — насколько другими, измерить, не гадать)

## Связи

`EXPERIMENTS_LOG.md#2026-08-11-1-V` · `docs/blog/verify-on-read.md` ·
`scripts/collect_memory_snapshot.py` · ревью (комментарий dev.to, Part 3).
