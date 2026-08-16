# Exp 2-E — Evidence Ladder: что делает evidence-контекст для верификации memory claims

**Лестница evidence:** claim без контекста → anchor → file content → graph → graph + git-провенанс.
Один контролируемый матричный прогон (5 arm'ов × модели × те же факты), per-rung анализ.

**Статус:** 🟡 дизайн (2026-08-15) → **реализация E3-машинерии** (builder + arm готовы, тесты 48/48, ruff clean).
Live-прогоны E1–E3 блокированы отсутствием OPENROUTER_API_KEY в .env.

---

## 1. Мотивация (что закрываем)

Серия 1 показала два полюса поведения LLM при верификации claims из памяти:

| Наблюдение | Числа (Exp 1-L) |
|---|---|
| present-trap слепота: модель доверяет памяти без кода | memory_first adoption на trap ≈ priors (1-V-REP: 0.24) |
| fail-closed: модель с кодом режет правду вместе с ложью | qwen3.6 code_first: recall(real) = **0.08** |
| fail-open: модель принимает ложь | glm-4.7-flash FA 0.24–0.30, nemotron FA 0.38 |

Вопрос лестницы: **какой формат evidence реально двигает и FA ↓, и recall(real) ↑ одновременно** —
и, главное, закрывает ли структурный слой (graph) present-trap, который «существование ≠ использование».

## 2. Лестница (arm'ы)

Один harness, один датасет, один промпт-скелет (нейтральная инструкция v2-стиля),
различается только блок evidence. Сравнимость с 1-L — бесплатно: `memory_first`/`code_first`/`file_content_first` уже реализованы в `scripts/run_1L_live_arm.py`.

| Rung | Arm | Evidence в промпте | Целевой вопрос | Реализация |
|---|---|---|---|---|
| 0 | `memory_first` | ничего (только claim) | priors модели = базовая линия | ✅ есть (1-L) |
| 1 | `code_first` | support_patterns (якоря-строки) | хватает ли минимального evidence | ✅ есть (1-L) |
| 2 | `file_content_first` | 25 строк файла вокруг якоря | фактический контекст > anchor? | ⚙️ есть (V4), нужен полный прогон |
| 3 | `graph_first` | сериализованный граф: ownership / imports / callers / callees | структура устраняет present-trap? | ❌ новый |
| 4 | `temporal_first` | graph + commit + branch + timestamp | «было правдой тогда» ≠ «правда сейчас»? | ❌ новый |

**Сравнимость (правило контрольной группы §1):** все arm'ы на ОДНОМ наборе моделей в ОДНОЙ
сессии с одинаковыми seed/temperature/порядком фактов. Числа из прошлых прогонов 1-L
в матрицу не подмешиваются (у них другой набор моделей/промптов) — 1-L даёт только
предсказания, не контрольную группу.

## 3. Датасет

- **E1–E3:** `experiments/1V_memory_contamination/memory_contamination_facts_v4_rep.json`
  (N=50: 25 real / 16 absent / 6 present_trap / 3 silent; fingerprint `820bbbf60a0fc930`).
  Категория `present_trap` (реальные импорты, ложные claims про использование) — целевая
  для Rung 3: в graph-контексте видно реальное владение/использование, а не только
  существование.
- **E4:** новый генератор temporal-claims (git-археология):
  - `git log --diff-filter=D` — символы, удалённые после коммита C: claim «X существует» был
    true при C, false на HEAD;
  - `git log --diff-filter=M -- <file>` — перенос владения/смена реализации: claim «X — в Y»;
  - ground truth: `git show C:<file>` / `git grep` на HEAD — детерминированно, без LLM.
  - N≈30–50, те же 4 категории + новая `temporal` (true@C / false@HEAD).
  - Формат — как v4_rep (id/truth/kind/claim/support_patterns/contra_patterns) + поля
    `valid_at_commit` и `evidence_git` (hash/date/branch коммита, в котором факт был правдой).

## 4. Вердикты и метрики

Схема вердикта НЕ меняется: `{"verdict": "true"|"false"|"unknown"}` (как в 1-L) —
иначе числа не сравнимы. Декомпозиция ошибок через `unknown`:

- evidence отсутствует (якорь не резолвится) и модель честно сказала `unknown` → **правильно**;
- evidence содержит ответ, но модель сказала `unknown` → **evidence ignored** (слабость модели);
- evidence противоречит claim, модель сказала `true` → **present-trap / prior override**.

Метрики (те же, что в summarize_1L_categories.py + per-category):

| Метрика | Смысл |
|---|---|
| `accuracy_decided` | точность на решённых (true/false) |
| `false_accept` (FA) | fail-open: ложь принята |
| `recall(real)` | fail-closed: правда не отвергнута |
| `trap_accuracy` | точность на категории present_trap (главная для Rung 3) |
| `unknown_rate` per category | честность vs evidence ignored |
| Wilson 95% CI | все доли |

## 5. Модели и бюджет

Базовая тройка (из опыта 1-L) + агентская семья:

| Модель | Зачем | Цена |
|---|---|---|
| `qwen/qwen3.7-flash` | дефолт, дешёвая | ~$0.0003/вызов |
| `deepseek/deepseek-v4-flash` | семья текущего агента — поведение «себя» | ~$0.0005/вызов |
| `z-ai/glm-4.7-flash` | fail-open контраст (FA 0.24–0.30) | ~$0.0005/вызов |
| `qwen/qwen3.8-max` (опционально) | только Rung 1/3/4 — сильная модель на интересных arm'ах | ~$0.01/вызов |

Матрица: 50 × 5 × 3 = 750 вызовов; graph/temporal промпты ~2–6k токенов → **$1–3**.
qwen3.8-max добавляет ~$3. `--resume` + progress-файлы вне проекта — как в 1-L.

## 6. Решения, которые НЕ подгоняем (pre-registered)

Результаты фиксируются как есть, любое из исходов — знание (запись в EXPERIMENTS_LOG с raw output):

1. **graph ≈ file** (расхождение в пределах CI) → структурный контекст не окупается для LLM-верификации;
   evidence = 25 строк файла; граф остаётся для машинных проверок (VOR-якоря), не для промпта.
2. **graph > file именно на `present_trap`** → структурный слой закрывает конкретный failure mode —
   графовое evidence встраивается в VOR-контекст.
3. **graph > file на real/absent** → структура нужна везде (включая дешёвые модели).
4. **temporal > static на temporal-claims** → провенанс окупается; направление — bitemporal-граф
   (идея #2 из DEV_EXP.md) как источник evidence, а не ручной git-разбор.
5. **qwen3.8-max на rung 3/4 не лучше flash** → сильные модели не нужны, дешёвая тройка достаточна.

Запрещено: подбор моделей «под красивый результат», повторные прогоны до «приемлемого» числа,
ручная правка вердиктов. Повторный прогон — только при крашах/таймаутах (документируется).

## 7. План файлов

```
experiments/2E_evidence_ladder/
├── README.md                  ← этот дизайн
├── temporal_facts_generator.py  ← E4: git-археология claims (детерминированный ground truth) — [pending]
├── graph_context_builder.py   ← ✅ E3: anchor → сериализованный граф (реализован 2026-08-15)
└── graph_contexts_594dae2a.json ← ✅ 50 контекстов (19 decoy), сгенерён builder'ом
scripts/run_1L_live_arm.py     ← ✅ + arm graph_first (--ev-contexts); temporal_first — E4
scripts/summarize_2E_ladder.py ← матричная сводка: rung × model → метрики — [pending]
tests/test_graph_context_builder.py ← ✅ 7 тестов
+tests graph_first в test_run_1L_live_arm.py ← ✅ 2 теста
```

Реализация graph-контекста: резолв якорей через PropertyGraph проекта (graph_adapter.SymbolIndexAdapter);
fallback на grep-вхождения (src/**/*.py). Для нерезолвящихся якорей — декой (контрольный символ
InstructionScan), evidence:"decoy" в метаданных — та же политика, что в V4.

## 8. Порядок запуска

1. **E1** (`code_first`) + **E2** (`file_content_first`) — полный прогон на тройке моделей
   (завершает V4, даёт базовую линию для E3).
2. **E3** (`graph_first`) — тот же датасет, сравниваем с E2 по per-category метрикам.
3. **E4** — генератор temporal-claims → `temporal_first` против `graph_first` на temporal-датасете.
4. Сводка: `summarize_2E_ladder.py` → EXPERIMENTS_LOG.md (raw вывод, команды, вердикты по §1.6).

## 9. Связи

- Серия 1: [1-L](../1L_live_arm/README.md), [1-V/1-R](../1V_memory_contamination/README.md), [1-M](../1M_manifest_anchoring/README.md)
- Датасет: `memory_contamination_facts_v4_rep.json` (N=50)
- EXPERIMENTS_LOG.md — 2026-08-11..15 (memory contamination серия)
- ADR-0002/0003/0005 — ретракция, verify-on-read, pkg-якоря

---

## 10. Результаты E1+E2+E3 (прогон 2026-08-15, 450 вызовов, $0.007)

| модель | arm | recall(real) | acc(decided) | unknown | FA absent/16 | FA trap/6 | FA silent/3 |
|---|---|---|---|---|---|---|---|
| qwen3.7-flash | code_first | 0.24 | 0.763 | 0.24 | 0 | 0 | 0 |
| qwen3.7-flash | file_content | 0.92 | 0.940 | 0.00 | 0 | 1 | 0 |
| qwen3.7-flash | **graph_first** | 0.76 | 0.913 | 0.08 | 0 | **0** | 0 |
| deepseek-v4-flash | code_first | 0.04 | 0.500 | 0.96 | 0 | 0 | 0 |
| deepseek-v4-flash | file_content | 0.84 | 0.875 | 0.36 | 0 | 3 | 0 |
| deepseek-v4-flash | graph_first | 0.44 | 0.824 | 0.66 | 0 | 2 | 0 |
| glm-4.7-flash | code_first | 0.60 | 0.704 | 0.46 | 3 | 3 | 2 |
| glm-4.7-flash | file_content | 0.68 | 0.750 | 0.04 | 0 | 5 | 0 |
| glm-4.7-flash | graph_first | 0.84 | 0.787 | 0.06 | 0 | 6 | 0 |
| qwen3.7-flash | file_graph (E3b) | 0.84 | 0.900 | 0.00 | 0 | 1 | 0 |
| deepseek-v4-flash | file_graph (E3b) | 0.88 | 0.857 | 0.16 | 0 | 4 | 0 |
| glm-4.7-flash | file_graph (E3b) | 0.84 | 0.820 | 0.00 | 0 | 5 | 0 |

**E4 temporal (датасет temporal_facts_e3c1fdd4.json, N=48: 12 removed / 28 real / 8 absent):**

| модель | acc(decided) | FA removed/12 | real acc/28 | FA absent/8 |
|---|---|---|---|---|
| qwen3.7-flash | 0.896 (43/48) | **5** | 28 | 0 |
| deepseek-v4-flash | **1.000** (48/48) | 0 | 28 | 0 |
| glm-4.7-flash | **1.000** (48/48) | 0 | 28 | 0 |

**Выводы (полный разбор — EXPERIMENTS_LOG 2026-08-15):**
1. file_content — лучший recall у всех моделей; graph закрывает present-trap (FA trap 1→0 у qwen3.7) ЦЕНОЙ recall (0.92→0.76).
2. deepseek: структура усиливает скептицизм (unknown 0.66, recall 0.44) — сомнение вместо проверки.
3. glm: ни одна форма evidence не лечит fail-open (FA trap 6/6) — свойство модели, не evidence.
4. **E3b (гибрид file+graph) — НЕ аддитивен:** qwen3.7 FA trap вернулся (R45), acc 0.900 < file 0.940; deepseek FA 0.08 > graph 0.04. Фрагмент доминирует — VOR выбирает ОДИН формат.
5. **E4 (temporal, git-провенанс):** deepseek/glm 48/48 (FA=0.00), qwen3.7 5/12 removed принято (путает «existed until» с «exists»). Git-сигнал работает у 2/3 моделей.
6. Следующий arm: — серия 2-E завершена (E1-E4).
7. Данные: progress-файлы `live_arm_1L_progress_2e_e{1..5}_*.json` (вне проекта).
