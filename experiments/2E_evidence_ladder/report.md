# Exp 2-E — Evidence Ladder: ПОЛНЫЙ ОТЧЁТ (E1–E4 + Red Team)

**Дата:** 2026-08-15 · **Статус:** ✅ завершено (744 вызова OpenRouter, est. $0.014; полный pytest 1265 passed)
**Harness:** `scripts/run_1L_live_arm.py` (arms: code_first / file_content_first / graph_first / file_graph_first / temporal_first) · builder: `graph_context_builder.py` · генератор: `temporal_facts_generator.py`
**Тесты:** `tests/test_run_1L_live_arm.py` (43) · `tests/test_graph_context_builder.py` (9) · `tests/test_temporal_facts_generator.py` (4) — 56 total, ruff clean

---

## 0. Резюме (1 экран)

**Вопрос серии:** какой формат evidence реально помогает LLM верифицировать memory claims —
и закрывает ли структурный слой (граф) present-trap?

**Ключевые результаты:**

1. **Форма evidence решает (E1→E2):** скачок recall при переходе anchor-строк → 25 строк файла у всех 3 моделей (qwen 0.24→0.92, deepseek 0.04→0.84, glm 0.60→0.68). Подтверждено на V4-данных 1-L.
2. **Гибрид file+graph НЕ аддитивен (E3b):** у qwen3.7 фрагмент «забивает» граф — trap-вердикты возвращаются к файловым, acc 0.900 < file 0.940. VOR выбирает ОДИН формат.
3. **Git-провенанс — ОПРОВЕРГНУТО (E4b+E4c):** слепой контроль 48/48 без git; duo-дизайн — temporal present-trap УНИВЕРСАЛЕН (now: qwen/glm 12/12, deepseek 9/12 removed-FA), но past-вопрос решается формулировкой claim (48/48). Existence-claims: evidence = HEAD без истории.
4. **⚠️ RED TEAM: 4/6 present-trap-фактов v4_rep по факту ИСТИННЫ** (R43/R45/R46/R47 — value импортирован И используется в файле субъекта; R44 — ambiguous). «FA trap» в серии завышен; **главный вывод E3 инвертируется** (см. §5).

---

## 1. Методология

### 1.1 Датасеты

| Датасет | N | Состав | Fingerprint |
|---|---|---|---|
| `memory_contamination_facts_v4_rep.json` (E1-E3, E3b) | 50 | 25 real / 16 absent / 6 mutation_present («trap») / 3 silent | `820bbbf60a0fc930` |
| `temporal_facts_e3c1fdd4.json` (E4) | 48 | 12 removed / 28 real / 8 absent (git-археология, ground truth из `git show C~1`) | `e3c1fdd4` |

### 1.2 Arm'ы (единственная переменная — форма evidence)

| Rung | Arm | Evidence |
|---|---|---|
| 0-1 | `code_first` | support_patterns (anchor-строки) |
| 2 | `file_content_first` | 25 строк файла вокруг якоря (V4-политика; декой для absent/silent) |
| 3 | `graph_first` | сериализованный граф: FILE/SYMBOL/OCCURS-блоки (PropertyGraph + ast + grep) |
| 3b | `file_graph_first` | фрагмент + граф |
| 4 | `temporal_first` | граф-блок HEAD + git-трейл («NOT FOUND AT HEAD» / «existed until C» / last commit) |

Промпт-скелет: нейтральная v2-инструкция (EN), `{"verdict": "true"|"false"|"unknown"}`, temp=0, seed=42, max_tokens=100, `--no-reasoning`. Leak-guard: `assert "truth" not in prompt` на каждом факте.

### 1.3 Модели и прогоны

`qwen/qwen3.7-flash`, `deepseek/deepseek-v4-flash`, `z-ai/glm-4.7-flash` × 5 arm'ов. Теги: 2e_e1..2e_e5. Progress: `%LOCALAPPDATA%/mscodebase/projects/bfe9644b/experiments/`. Вызовы: 450 (E1-E3) + 294 (E3b/E4) = 744, errors=0.

---

## 2. Результаты E1–E4 (pre-registered labels — см. §5 для corrected)

### 2.1 E1+E2 (anchor → file_content), v4_rep

| модель | arm | recall(real) | acc(decided) | unknown | FA absent/16 | FA trap/6 | FA silent/3 |
|---|---|---|---|---|---|---|---|
| qwen3.7 | code_first | 0.24 | 0.763 | 0.24 | 0 | 0 | 0 |
| deepseek | code_first | 0.04 | 0.500 | 0.96 | 0 | 0 | 0 |
| glm | code_first | 0.60 | 0.704 | 0.46 | 3 | 3 | 2 |
| qwen3.7 | **file_content** | **0.92** | **0.940** | 0.00 | 0 | 1 | 0 |
| deepseek | file_content | 0.84 | 0.875 | 0.36 | 0 | 3 | 0 |
| glm | file_content | 0.68 | 0.750 | 0.04 | 0 | 5 | 0 |

### 2.2 E3+E3b (graph, hybrid)

| модель | arm | recall(real) | acc(decided) | unknown | FA trap/6 |
|---|---|---|---|---|---|
| qwen3.7 | graph_first | 0.76 | 0.913 | 0.08 | **0** |
| deepseek | graph_first | 0.44 | 0.824 | 0.66 | 2 |
| glm | graph_first | 0.84 | 0.787 | 0.06 | 6 |
| qwen3.7 | file_graph | 0.84 | 0.900 | 0.00 | 1 |
| deepseek | file_graph | 0.88 | 0.857 | 0.16 | 4 |
| glm | file_graph | 0.84 | 0.820 | 0.00 | 5 |

### 2.3 E4 + E4b + E4c (temporal: git-провенанс, слепой контроль, duo now/past)

| Дизайн | qwen3.7 | deepseek | glm | Что измеряет |
|---|---|---|---|---|
| E4 sighted (git-строки) | 43/48, FA rem 5/12 | 48/48, 0 | 48/48, 0 | git-провенанс в evidence |
| E4b blind (без git) | 48/48, 0 | 48/48, 0 | 48/48, 0 | «NOT FOUND AT HEAD» подсказка |
| E4c now (duo, «X определён») | 36/48, **12/12** | 39/48, **9/12** | 36/48, **12/12** | история без подсказки, вопрос про HEAD |
| E4c past (duo, «X был определён») | **48/48**, 0 | **48/48**, 0 | **48/48**, 0 | вопрос явно про историю |

**⚠️ Итог temporal-серии (E4c закрывает, EXPERIMENTS_LOG 2026-08-16):**
1. Git-провенанс для existence-claims не нужен (E4b) и для qwen вредил (суггестия «existed until»).
2. **Temporal present-trap УНИВЕРСАЛЕН:** duo-дизайн без подсказки — ВСЕ модели принимают removed-claims про настоящее (qwen/glm 12/12, deepseek 9/12): «X упомянут в истории» ≠ «X существует сейчас».
3. **Явная временная формулировка claim решает:** past-вопрос («X был определён») — 48/48 у всех.
4. E4b-вывод «deepseek/glm устойчивы» — артефакт подсказки «NOT FOUND AT HEAD».

### 2.4 Pinned-rerun на corrected (каноническая матрица, fp e6ce7b902d0a20a9)

Прогоны 2e_pin_* (qwen→Alibaba, deepseek/glm→DeepInfra; routing-полоса убрана).
FA trap = только R42 (единственный настоящий trap-FA); miss_true = отвергнутые истинные trap-claims.

| arm | qwen recall/FA-tr/miss | deepseek recall/FA-tr/miss | glm recall/FA-tr/miss |
|---|---|---|---|
| file_content | **0.88**/0/**3** | 0.80/1/2 | 0.68/2/1 |
| graph_first | 0.72/0/**4** | 0.48/0/2 | **0.84**/1/**0** |
| file_graph | 0.84/0/3 | **0.92**/1/2 | 0.80/2/1 |
| temporal NOW removed-FA | **12/12** | **9/12** | **12/12** |
| temporal PAST | 40/40 | 40/40 | 40/40 |

**Выводы pinned (стабильны к маршрутизации):** (1) лучший arm — per-model: qwen → file_content (recall 0.88), glm → graph (0.84, miss 0), deepseek → hybrid (0.92); (2) temporal present-trap универсален (NOW 12/12, 9/12, 12/12), past решается формулировкой (40/40); (3) FA absent/silent = 0 во всех evidence-ячейках; (4) glm недетерминирована даже pinned (e3_g: 6FA→2FA→1FA между прогонами) — пининг убирает маршрутизацию, не вариацию модели; (5) ключевой результат серии — **trap miss_true (4/5 у qwen, 2-3 у остальных): fail-closed модели отвергают истинные usage-claims**, невидимый в старых (mislabeled) метриках.

### 2.5 E5 — расширенная trap-категория (P-00X, лейблы по субъекту)

Генератор `trap_facts_generator.py`: false-trap = value в проекте (≥2 файлов) НО НЕ в файле субъекта (grep субъекта=0 — фикс P-00X); true-trap = value у субъекта. N=30 (20 false / 10 true), fp `cb6f822b9eb66afd`. Прогон file_content/graph × 3 модели (pinned, правильные пины):

| arm | qwen FA/recall | deepseek FA/recall | glm FA/recall |
|---|---|---|---|
| file_content | 2/20, 2/10 | **15/20**, 6/10 | 13/20, 7/10 |
| graph_first | 2/20, 3/10 | **8/20**, 5/10 | 14/20, 9/10 |

**Вывод:** (1) present-trap — НЕ артефакт mislabeled: на честных лейблах FA 10-75%; «остаточная дыра» Part 2 была искажена (N=1). (2) **graph evidence реально снижает trap-FA у deepseek вдвое (75%→40%)** — вывод «graph не закрывает trap» на v4_rep был статистическим артефактом; у glm graph не помогает (14/20), у qwen FA и так 2/20 (но recall 2/10 — fail-closed). (3) Ответ ревьюеру (chatgpt): исправленный генератор проверяет отсутствие value у СУБЪЕКТА — тест `tests/test_trap_facts_generator.py` (5 тестов).

---

## 3. Red Team (атаки по протоколу §1.16 — минимум 3 из 5)

**[🔓 RED TEAM] Атака 1 — качество ground truth (mislabeled traps) → ПРОБИТА.**
`PRESENT_VALUES = ["pathlib", "threading", "dataclasses", "json", "logging", "re"]` — значения «реальных импортов»; генератор проверял только `value != real_value`, НЕ отсутствие value у субъекта. Проверка grep-ом:
- R43 «Граф знаний использует re» — `graph.py:31: import re` + 2 usage → **истинен**;
- R45 «Серверная обёртка использует logging» — `server.py:14: import logging` + usage → **истинен**;
- R46 «Сторожевой таймер использует threading» — `watchdog.py:4` + `threading.Lock()` → **истинен**;
- R47 «Загрузка моделей с хаба использует pathlib» — `llama_install.py` 6 matches → **истинен**;
- R44 «Кросс-проектный поиск использует pathlib» — импорт без usage → **ambiguous**;
- R42 «Серверная обёртка использует dataclasses» — 0 вхождений → **верно false**.
Вердикт: 4/6 «trap» по факту true. «FA trap» = модели были ПРАВЫ. Скорректированные метрики — §5.

**[🔓 RED TEAM] Атака 2 — routing-полоса (провайдер-конфаунд) → ЧАСТИЧНО ЗАКРЫТА.**
Данные Tom Jones (комментарий к статье 2): pinned vs unpinned — llama-3.3-70b 95.5% vs 78.2% (swing 17.3 пт). Межмодельные разрывы в серии (qwen 5/12 vs deepseek 0/12 в E4) могут частично быть артефактом маршрутизации (OpenRouter ≥8 апстримов, серверный CSV). Защита: (а) контроль воспроизводимости qwen file_content vs V4 — стабилен (recall 0.92/0.88); (б) `--pin-provider` добавлен в harness (проверен probe: параметр работает, `provider: Alibaba` в ответе, 3/3 стабильно) — полный pinned-rerun доступен по команде (~$0.03).

**[🔓 RED TEAM] Атака 3 — повторяющийся декой = частотная утечка.**
19 фактов получают ОДИН и тот же блок контрольного символа (InstructionScan); модель могла выучить «повторяющийся блок → false». Защита: нет (та же политика, что в V4); FA absent 0/16 у всех моделей подозрительно чистый — НЕ исключено влияние частотности. Зафиксировано как ограничение; митигация — 3 разных decoy-символа в будущих прогонах.

**[🔓 RED TEAM] Атака 4 — «NOT FOUND AT HEAD» подсказывает вердикт (E4) → ПОДТВЕРЖДЕНА И УСИЛЕНА (E4b, 2026-08-16).**
Слепой контроль (те же 48 temporal-фактов, evidence БЕЗ git-строк): **все 3 модели — 48/48, FA=0.000**. Git-провенанс для existence-claims НЕ нужен (deepseek/glm blind=sighted) и АКТИВНО ВРЕДИТ qwen (sighted 43/48, 5/12 removed принято — «existed until C» суггестирует существование; blind 48/48). Вывод E4 «qwen путает было-тогда/сейчас» — артефакт evidence, не модели. Для честного temporal-теста нужны claims без подсказки (E4c).

**[🔓 RED TEAM] Атака 5 — TOCTOU контекстов.**
graph_contexts/temporal_contexts сгенерированы один раз; прогоны в той же сессии — консистентно. Для воспроизводимости: контексты зафиксированы файлами с sha-префиксом, факты — fingerprint'ом.

---

## 4. Provider.order probe (ответ на замечание Tom Jones)

Прямой probe: 3 факта × 3 повтора × {unpinned, pinned[Alibaba]}, qwen3.7-flash, `reasoning.enabled=false`:
- unpinned: все 9 ответов с `provider: "Alibaba"`, вердикты 3/3 стабильны;
- pinned: те же вердикты 3/3, `provider: "Alibaba"` в каждом ответе.
**Вердикт:** параметр `provider.order + allow_fallbacks: false` работает и подтверждается полем `provider` в ответе. Для qwen3.7-flash роутинг и так ложился на Alibaba; полоса ±0.05–0.10 — проблема мультибэкендных моделей (nemotron, glm). Пининг = дешёвая страховка (K≥3 повторов ≈ $2–5 → pinned rerun ≈ $0.03).

---

## 5. ⚠️ СКОРРЕКТИРОВАННАЯ МАТРИЦА (Red Team: corrected labels)

**Машинный flip-линк версий:** `experiments/1V_memory_contamination/flip_ledger_REDTEAM_2026-08-16.json`
(таблица fact → from → to → evidence с file:line; связывает fp `820bbbf60a0fc930` → `e6ce7b902d0a20a9`).

**Лейблы:** R43/R45/R46/R47 → truth=true (value импортирован+использован у субъекта); R44 → excluded (ambiguous); R42 → false (без изменений).
**Пул:** TRUE = 29 (25 real + 4 trap-true), FALSE = 20 (16 absent + 3 silent + R42), AMBIG = 1.

| arm | qwen3.7 recall/FA | deepseek recall/FA | glm recall/FA |
|---|---|---|---|
| code_first | 6/29, 0/20 | 1/29, 0/20 | 18/29, 5/20 |
| file_content | **24/29**, 0/20 | 23/29, 1/20 | 20/29, 1/20 |
| graph_first | 19/29, 0/20 | 13/29, 0/20 | **25/29**, 1/20 |
| file_graph | 22/29, 0/20 | **24/29**, 1/20 | 24/29, 1/20 |

**Пересмотренные выводы:**

1. **«Граф закрывает present-trap» — ОПРОВЕРГНУТО.** qwen3.7 graph «FA trap 1→0» = fail-closed на категории: отвергнуты ВСЕ 4 истинных trap-claim (miss_true 4/4). Это скрытая потеря recall, невидимая при старых лейблах (trap-факты не входили в recall).
2. **«glm fail-open не лечится» — ОПРОВЕРГНУТО.** На corrected labels glm в graph_first — ЛУЧШИЙ arm серии: recall 25/29, FA 1/20 (единственный настоящий FA — R42). Графовое evidence glm использует лучше всех.
3. **file_content остаётся лучшим для qwen3.7** (24/29 vs graph 19/29, FA 0 в обоих).
4. **Гибрид аддитивен для deepseek и glm** (24–25/29, FA 1/20), но не для qwen (22/29 < file 24/29).
5. **Формат evidence выбирается ПОД МОДЕЛЬ, а не глобально:** qwen → фрагмент; glm → граф; deepseek → гибрид.

---

## 6. Ограничения

1. Routing-полоса ±0.05–0.10 (закрыта pin-поддержкой; pinned-rerun воспроизвёл выводы).
2. **RED TEAM 3 (2026-08-16): порядок фактов влияет** — shuffle-контроль (qwen code_first, seed 123): 4/50 вердиктов изменились vs блочный порядок; блочный порядок R01-25=true/R26-50=false НЕ выверен (см. EXPERIMENTS_LOG).
3. **RED TEAM 3: StreamLake — 404 no endpoint, не «битые ответы»** (не держит glm-4.7-flash); unpinned-маршрутизация дрейфует по времени (StreamLake 15-го → DeepInfra 16-го) — часть «недетерминизма» glm между разновременными прогонами.
4. **FA trap — статистика на 1 факте (R42)**: «FA trap» = флаг, не метрика.
5. Языковой конфаунд (RU claims / EN инструкции) — не проверен (Part 2: язык сдвигает unknown).
6. Повторяющийся decoy-блок (частотная утечка не исключена).
7. E4: existence-claims легче usage-claims — датасеты комплементарны.
8. Один язык (Python), один репозиторий.
9. Разновременность unpinned/pinned прогонов (~12ч) — апстримы дрейфуют.
10. Mislabeled trap-факты v4_rep — датасет НЕ исправлен (исторический артефакт 1-V/1-L); corrected-логика здесь и в EXPERIMENTS_LOG.

---

## 7. Рекомендации для VOR

1. **Формат evidence — под модель:** qwen-семейство → фрагмент файла (recall); glm-семейство → граф (recall+FA); deepseek → гибрид. Никакого глобального «лучшего формата».
2. **Гибрид file+graph не включать для qwen** (не аддитивен, acc падает).
3. **Git-провенанс НЕ добавлять в evidence для existence-claims (E4b/E4c):** слепой контроль 48/48 без него; duo-дизайн показывает temporal present-trap у ВСЕХ моделей (qwen/glm 12/12, deepseek 9/12 на removed). **Явная временная формулировка claim («был определён» vs «определён») решает задачу — 48/48.** Для VOR: evidence только текущего HEAD, либо вопрос во времени.
4. **Пинить провайдера** (`--pin-provider`) в боевых VOR-прогонах — дешевле K≥3 повторов.
5. **Датасеты v4_rep требуют ре-лейблинга trap-категории** перед использованием в новых экспериментах.

---

## 8. Воспроизведение

```bash
# контексты
python experiments/2E_evidence_ladder/graph_context_builder.py
python experiments/2E_evidence_ladder/graph_context_builder.py experiments/2E_evidence_ladder/temporal_facts_e3c1fdd4.json
python experiments/2E_evidence_ladder/temporal_facts_generator.py

# прогоны (теги 2e_e1..2e_e5)
python scripts/run_1L_live_arm.py --provider openrouter --arm code_first --models "..." --prompt-version v2 --no-reasoning --tag 2e_e1
python scripts/run_1L_live_arm.py --provider openrouter --arm file_content_first --models "..." --prompt-version v2 --no-reasoning --tag 2e_e2
python scripts/run_1L_live_arm.py --provider openrouter --arm graph_first --ev-contexts experiments/2E_evidence_ladder/graph_contexts_594dae2a.json --models "..." --prompt-version v2 --no-reasoning --tag 2e_e3
python scripts/run_1L_live_arm.py --provider openrouter --arm file_graph_first --ev-contexts experiments/2E_evidence_ladder/graph_contexts_594dae2a.json --models "..." --prompt-version v2 --no-reasoning --tag 2e_e4
python scripts/run_1L_live_arm.py --provider openrouter --arm temporal_first --facts experiments/2E_evidence_ladder/temporal_facts_e3c1fdd4.json --ev-contexts experiments/2E_evidence_ladder/temporal_contexts_e8571628.json --models "..." --prompt-version v2 --no-reasoning --tag 2e_e5

# тесты
python -m pytest tests/ -q          # 1265 passed (2026-08-15)
```
