# CLAIMS AUDIT — результат (mirror of Tom's 84→107 correction)

**Дата:** 2026-09-30. **Commit:** `ea9b5911`
**Манифест (frozen до прогона):** `experiments/claims_audit/frozen/CLAIMS_MANIFEST.md`, sha256 `6bd0ab75b9067b941d429d164e9583349cf5f3e6af44ba5dc9b40b25b39dec49`
**Правило:** список претензий не менялся после просмотра результатов. Непроверяемое помечено `CANNOT VERIFY`, а не смягчено.

## Сводка

| # | Claim | Verdict |
|---|---|---|
| A1 | E7/F4 valid 10/11, controls 6/6, #16→NONE | ✅ CONFIRMED (арифметика) |
| A2 | F4b arrival 10/11 | ✅ CONFIRMED (арифметика) |
| A3 | F4b symptom 3/11 | ✅ CONFIRMED (арифметика) |
| A4 | F5 judged A 16.3 / B 34.4 / C 97.5 / D 0.0 | ✅ CONFIRMED (арифметика) |
| A5 | F5 relang EN 37.5% vs RU 32.5% | ✅ CONFIRMED (арифметика) |
| A6 | E11 controls 6/6, per-item 11/11 | ✅ CONFIRMED (арифметика) |
| A7 | NodeRAG A 80% / B 70%, 302K/170K tokens | ⚠️ CONFIRMED по числам, ❌ sha входа не байт-воспроизводим |
| A8 | canary 5/5 pre-fix, 13/13 tests post-fix | ✅ CONFIRMED |
| A9 | evalmut 8% → 100% | ⚠️ PARTIAL: 100% (11/11) подтверждён; «8%» не перезапускаемо (нет кода до фикса) |
| A10 | lock orphan 30s → 120ms | ❌ **NOT REPRODUCED** — путь недостижим по дизайну |
| A11 | vacuous 1133/1143, 3 vacuous | ⚠️ 3 vacuous подтверждены дословно; **скрипт сегодня — silent no-op** |
| A12 | ln.strip 3/8 vs 0/8 | ✅ CONFIRMED |
| A13 | population blindspot: EMPTY ≡ GARBAGE | ❌ **NOT RUNNABLE** — скрипт падает |
| A14 | drift-гейт структурно слеп; вакуум → PASSED | ✅ CONFIRMED |
| B1 | E7 live qwen 8/10 vs longcat 4/10 | ⛔ CANNOT VERIFY (нужны живые вызовы) |
| B2 | FA 0.24–0.38 / recall 0.08→0.88 | ⛔ CANNOT VERIFY (живые вызовы, 2026-08) |

**Итог: 11 подтверждено, 1 частично, 2 не воспроизводятся, 1 не запускается, 2 непроверяемы.**

## Три находки уровня «правда на том коммите, мёртвая сегодня»

Это ровно тот класс, который Том нашёл у себя (84 → 107).

### A10 — «orphan 30s → 120ms» путь удалён намеренно

`benchmark_selfhealing.py` падает на кейсе `orphan`:

```
LockBusyError: PID lock still held by alive pid=548 after 8.0s
```

Причина **не** в регрессии. `ORPHAN` удалён из классификатора намеренно:

- `src/core/indexing/database_lock.py:81-84` — «ORPHAN удалён (R3TF 2026-08-26): TerminateProcess по эвристике убивал живые MCP»
- коммит `7974d981` (2026-08-28); поведение введено `3798d6a9` (2026-08-08)

Оставшиеся кейсы воспроизводятся: healthy **1507 ms** (публиковано 1.5 s ✅), stale 19 ms, free 5 ms, тесты **20/20**.

**Вердикт:** число было верным 2026-08-08 и стало недостижимым по дизайну. В портфолио (exp-10) оно
подано как действующая практика — **это устаревшее утверждение, а не ошибка измерения**.
Рекомендация: `SUPERSEDED` с ссылкой на R3TF, а не переписывать.

### A11 — сканер вакуумных тестов сегодня молчит

`exp_vacuous_scan.py:20` жёстко зашит на `experiments/tests` (каталога нет). Сегодня:

```
Всего тестов: 0 / proven: 0 / вакуумных: 0 / доля вакуумных: 0.0%
=== RC=0 ===
```

То есть guard отдаёт «0% вакуумных» и **не падает**. Перезамер с перенаправленным путём
(`a11_vacuous_repro.py`, логика оригинала дословно):

| | published 2026-08-11 | recomputed 2026-09-30 |
|---|---|---|
| total | 1143 | 2053 (+910 — предсказано W4) |
| proven | 1133 | 2032 |
| vacuous | 3 | 6 |
| skip | 7 | 15 |

Три опубликованных вакуумных воспроизвелись **дословно** (`test_assignments.py:396`,
`test_ast_cache_invalidation.py:60`, `test_sandbox.py:46`) + 3 новых от роста суита.
**Вердикт:** измерение 2026-08 корректно; скрипт стал silent no-op — это тот же класс
«guard, который не умеет падать», что и A14.

### A13 — population blindspot не запускается

`exp_population_blindspot.py:24` — тот же off-by-one (`parent.parent` → `experiments/`, а не корень):

```
FileNotFoundError: .../experiments/src/core/intelligence/health.py
```

**Вердикт:** `CANNOT VERIFY` в этой сессии. Утверждение остаётся непроверенным, а не опровергнутым.

## Побочная находка: два одинаковых off-by-one, один класс

A11 и A13 — один и тот же баг: `Path(__file__).resolve().parent.parent` при переносе скрипта
из `src/`-подобного расположения в `experiments/misc_probes/` указывает не в корень репозитория.
**A13 падает громко, A11 — молча.** Это и есть граница опасности: молчащий даёт ложное «0%».

## Что это значит для статьи

Ни одно из 11 подтверждённых чисел не опровергнуто. Но материал для секции «наши находки»
теперь сильнее, а именно: у нас есть **три расходящихся с телом статьи артефакта** — ровно тот
вклад, которого Том ждал от co-author.

**Протокол на будущее, который это дало:** freeze-before-look применяется не только к входным
данным эксперимента, но и к **числу в публикации**. Число, которое нельзя воспроизвести
сегодняшней командой, публикуется как `measured on <commit>, superseded by <X>` — иначе через
месяц оно становится невоспроизводимым всеми.

## Сырьё

- `reaggregate_a1.py` / `a1_reaggregate.json` — A1
- `scripts/f4b_validate.py`, `scripts/f4b_aggregate.py` — A2, A3, A6 (negative control `--selftest` rc=1 ✅)
- `reaggregate_a4_a5.py` — A4, A5
- `a11_vacuous_repro.py` — A11
- `a14_verify_gate_posix.py` — A14
- Прямые перезапуски: `exp_canary_attack.py`, `pytest tests/test_shadow_canary.py`,
  `probe_evalmut_transfer.py`, `exp_ln_strip_repro.py`, `benchmark_selfhealing.py`,
  `pytest tests/test_database_lock_selfhealing.py`
