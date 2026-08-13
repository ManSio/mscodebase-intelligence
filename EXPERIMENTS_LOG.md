# EXPERIMENTS_LOG.md — Audit Verification (2026-07-22)

## [2026-08-13] — EXP: «сервер недоступен во время индексации» — root cause = sync update_all в main loop

**Гипотеза:** таймауты всех MCP-запросов на ~13 мин при полной переиндексации вызваны НЕ индексацией самой по себе (она в run_in_executor, loop свободен), а синхронным AutoDocUpdater.update_all() (generate_docs+README+KNOWN_ISSUES, rglob по docs/) в main event loop ПОСЛЕ индексации (layer.py _run_reindex_job).
**Команда:** `intel_trigger_reindex(mode="full")` + серия запросов (job_status/hotspots/passport) во время и после; `wmic`/tasklist для состояния процесса; чтение кода (layer.py L672-808, auto_doc_updater.py L114-163).
**Сырой результат:**
```
intel_trigger_reindex → job 0d27f125, ETA 18с
все запросы ~13 мин: Context server request timeout (включая intel_get_job_status)
get_logs: Timeout after 771664ms (attempt 1/1)
job completed: 7383/7383, 552с (ETA 18с vs 552с, ×30)
после: процесс 19728 мёртв (канал closed) — Zed убил MCP
код: update_all() вызывается СИНХРОННО в async-задаче (main loop)
```
**Вердикт: ✅ подтверждена.** 552с индексации + ~220с update_all = 771с недоступности — совпадает с логом. Индексация в executor (H1 опровергнута); fast-fail search при is_reindexing есть; блокировал именно sync-update_all (BS-11-класс: run_full_diagnostic уже был вынесен в to_thread в intel_predict_root_cause).
**Урок:** любые синхронные вызовы тяжёлых методов (rglob/generation) в async-функциях = блокировка ВСЕХ запросов; паттерн-эталон — asyncio.to_thread + wait_for (BS-11). Guard-тест: test_reindex_responsive.py (тики loop не замирают во время update_all; max_gap < 0.3с).
**Связь с отрицательными:** нет.

## [2026-08-12] — EXP-1 → тест: canary fail-closed внедрён, 13/13 регрессий (атаки EXP-1 больше не проходят)

**Гипотеза:** фикс по уроку EXP-1 (абсолютный якорь + fail-closed + collapse-детектор) переводит атаки (b)(c)(d)(e) из PASSED в BLOCKED, не сломав accepts_good/rejects_bad.
**Команда:** `python -m pytest tests/test_shadow_canary.py -q` — реалистичные per-pair векторы вместо коллапс-фейков (старый `_make_fake_embedding` возвращал ОДИНАКОВЫЙ вектор на любой вход — сам был collapse-состоянием!).
**Сырой результат:**
```
collected 13 items
tests\test_shadow_canary.py .............  [100%]
13 passed in 0.18s
```
Тесты: TestVectorsCollapsed ×5 (constant/noisy-constant/zero → collapsed; distinct → нет; <2 → unverifiable), TestShadowCanary ×8 (accepts_good; rejects_bad; **empty_canary_blocks** — было «доверие», теперь BLOCK; **baseline_failure_blocks**; **collapse_to_constant_blocks** — EXP-1 (b); **baseline_below_absolute_quality_blocks**; **new_below_absolute_quality_blocks** — old_mean=0.53→threshold 0.477, new_mean=0.49: relative прошёл бы, абсолютный якорь 0.5 блокирует; canary_set.json 20 пар).
**Вердикт: ✅ подтверждена.** Атаки EXP-1 (b)(c)(d) теперь BLOCKED; «relative прошёл, absolute блокирует» — различается. Коллапс-детектор ловит и ±1%-noisy (дисперсия НОРМАЛИЗОВАННЫХ векторов — scalar-кратные дают cos=1.0; сырая дисперсия их пропускала, что поймал тест на первом прогоне: 12/13, фикс — нормировка).
**Урок:** коллапс-фейк в тестах маскировал collapse-детектор: детектор обязан мерить НАПРАВЛЕНИЯ (нормированные векторы), не сырые значения.
**Связь с отрицательными:** нет.

## [2026-08-12] — EXP-4 → тест: eligible_seen внедрён в health, «0 eligible» ≠ «0 собрано» (12/12)

**Гипотеза:** population manifest (eligible_seen из indexer.get_status ДО запросов) различает пустую популяцию (healthy idle) и сломанный коллектор; warning несёт число eligible.
**Команда:** `python -m pytest tests/test_search_quality_monitoring.py -q`.
**Сырой результат:**
```
collected 12 items
tests\test_search_quality_monitoring.py ............  [100%]
12 passed in 0.07s
```
Новые: test_empty_population_is_healthy_idle (0 eligible → skipped=empty_index, warning НЕТ), test_fails_on_garbage_chunks → «0 реальных результатов при 100 eligible-чанков в индексе (broken collector)», test_eligible_seen_unknown_falls_back (get_status отсутствует → -1 → старое поведение).
**Вердикт: ✅ подтверждена.** «0 сырых + 0 eligible» (idle) vs «0 сырых + N eligible» (коллектор) — различимы метрикой и warning.
**Урок:** источник eligible_seen — реальный счётчик indexer (не производное от searcher), иначе та же популяционная слепота (Red Team §1.16 п.3).
**Связь с отрицательными:** нет.

## [2026-08-11] — EXP-1: Shadow Canary attack — дискриминативная способность `_shadow_compare` (5/5 атак прошли)

**Гипотеза:** canary измеряет ОТНОСИТЕЛЬНУЮ деградацию (new vs old), а не абсолютное качество → (b) collapse-to-constant, (c) пустой canary, (d) сбой базлайна, (e) взаимно-вырожденная пара дают ложное PASSED=True. Контроль (a) нулевые векторы обязан дать BLOCKED.
**Команда:** `python experiments/exp_canary_attack.py` — дословная реплика remote_embedder.py:231-304 (без импорта провайдера), N=20 пар, DIM=384.
**Сырой результат:**
```
(a) Нулевые векторы (контроль): BLOCKED=True ✅ контроль отработал
(b) АТАКА constant-vector (все тексты → [1.0]*384): PASSED=True ❌ АТАКА ПРОШЛА
(b2) АТАКА noisy-constant (±1%): PASSED=True ❌ АТАКА ПРОШЛА
(c) Пустой canary-набор: PASSED=True ❌ АТАКА ПРОШЛА (fail-open)
(d) Сбой базлайна (old raises): PASSED=True ❌ АТАКА ПРОШЛА (fail-open)
(e) old И new обе constant: PASSED=True ❌ АТАКА ПРОШЛА
ИТОГ: атаки (b)(b2)(c)(d)(e) — 5 из 5 прошли. Контроль (a) — работает.
```
**Вердикт: ✅ АТАКИ ПОДТВЕРЖДЕНЫ.** Canary не может упасть на collapse-to-constant (sims=1.0 > порога), fail-open при пустом canary (`if not self._canary_pairs: return True`, строка 242-243) и при сбое базлайна (`except Exception: return True`, строка 259-261). Единственный пойманный дефект — нулевые векторы. «Проверка, которая не может увидеть что-то, всегда зелёная про это» (Tom, день 2). test_shadow_canary.py:54-63 закрепляет «пустой canary = доверие» как фичу.
**Урок:** относительная метрика без абсолютного якоря и fail-open ветки — два способа сделать guard неспособным упасть. Фикс: (1) абсолютный порог (new_mean ≥ X), (2) baseline-fail и empty-canary → блокировать переключение/UNKNOWN, не доверять, (3) детектор collapse (дисперсия векторов ≈ 0 → reject), (4) eligible_seen (число пар при загрузке).
**Связь с отрицательными:** нет.

## [2026-08-11] — EXP-2: Скан тестов на вакуумность — таблица Max Quimby для MSCodeBase (1133/1143 proven)

**Гипотеза:** часть тестов синтаксически не может упасть (нет assert/raises/warns/fail/raise) — «33 unproven» в миниатюре. Ожидание: 5-15% вакуумных.
**Команда:** `python experiments/exp_vacuous_scan.py` — AST-скан tests/test_*.py (1143 test-функции/метода); proven = есть assert / pytest.raises/warns/xfail/fail / raise / mock-assert_* (после правки).
**Сырой результат:**
```
Всего тестов: 1143
  proven: 1133 | вакуумных: 3 | skip: 7 | доля вакуумных: 0.3%
Вакуумные: test_assignments.py:396, test_ast_cache_invalidation.py:60, test_sandbox.py:46
```
**Вердикт: ❌ ГИПОТЕЗА ОПРОВЕРГНУТА** (в хорошем смысле): сюита почти полностью доказуема — 1133/1143 (99.7%) содержат failing-конструкцию. 3 «вакуумных» — smoke-тесты, способные упасть через exception-пропагацию из хелперов (`_ = parser.extract_assignments(f)  # не падает`), т.е. дискриминация слабее, но не нулевая. Первичный скан дал 5 «вакуумных», 2 из них (test_move_chunks.py:351, test_indexer_fts5_sync.py:55) использовали mock-утверждения (`assert_called_once`/`assert_not_called` — Call, не ast.Assert) — сканер обновлён (учитывает `assert_*` методы), честный пересчёт 3.
**Урок:** MSCodeBase НЕ в состоянии fintech (7/40 proven) — но именно поэтому отрицательные контроли выгодны: их мало (0-3), а ценность максимальна. 2 ловушки для сканеров вакуумности: mock-assert_* и exception-пропагация.
**Связь с отрицательными:** нет.

## [2026-08-11] — EXP-3: Воспроизведение бага `ln.strip()` (Tom Jones) — 3/8 ложных проходов у сломанного экстрактора

**Гипотеза:** assert-экстрактор, фильтрующий по `ln.strip()` но эмитирующий сырую `ln`, даёт ложные verified для неверного ответа, когда отступ вложенного assert-а попадает ПОСЛЕ `return` в теле функции. Ожидание: ≥2/8 ложных проходов (у fintech — 5/8 на их наборе форм).
**Команда:** `python experiments/exp_ln_strip_repro.py` — 8 форм вызова (col 0 / 4-space / 8-space / 12-space, до/после return), неверный ответ `add_two(1,2)=4`, сборка module = answer + raw assert-строки (как у fintech-gateway), exit 0 = verified.
**Сырой результат:**
```
Сломанный экстрактор: 3/8 ложных проходов  (формы 2,3,8 — assert на 4-space после return)
Правильный экстрактор: 0/8 ложных проходов
Пример модуля (форма 2):
def add_two(a, b):
    return a + b + 1
    assert add_two(1, 2) == 3   # мёртвый код ПОСЛЕ return — valid Python, exit 0
```
**Вердикт: ✅ КЛАСС БАГА ВОСПРОИЗВЕДЁН.** Число форм (3/8 vs 5/8) отличается — набор форм другой, но суть та же: valid Python, никогда не исполняется, exit 0, «verified:true» для неверного ответа. Правильный экстрактор (emit `ln.strip()`, col 0) — 0/8. Ключ: сигнатура/exit-код верифицируют ПРОЦЕСС, не СЕМАНТИКУ (Giulio: «ask for the artifact, not the exit code»).
**Урок:** любой код, извлекающий/перекомпилирующий фрагменты (assert-экстракция, док-примеры, code-gen) обязан нормализовать отступы ПЕРЕД эмиссией; negative control для экстрактора = фикстура с assert-после-return, обязанная упасть.
**Связь с отрицательными:** нет.

## [2026-08-11] — EXP-4: Population blind spot — `_check_search_quality` не различает «0 eligible» и «0 собрано» (gap Тома день 2)

**Гипотеза:** пустая популяция (пустой индекс — «здоровый idle») и сломанный коллектор (мусор) дают ОДИНАКОВЫЙ сигнал: `search_quality_passed=0` + warning «нет реальных результатов». `eligible_seen` до селекции не измеряется (health.py:744-756).
**Команда:** `python experiments/exp_population_blindspot.py` — реальный `src/core/intelligence/health.py` (importlib direct-load, stdlib-only), FakeSearcher: [] vs мусор vs реальные vs raising.
**Сырой результат:**
```
(a) ПУСТАЯ популяция ([]): metrics passed=0
    warning: ...нет реальных результатов (0 сырых — все пустые/мусорные чанки)
(b) МУСОР: passed=0
    warning: ...нет реальных результатов (2 сырых — все пустые/мусорные чанки)
(b2) ОШИБКА searcher: passed=0, warning: ...завершился с ошибкой: embedder down
(c) КОНТРОЛЬ (реальные): passed=3, без warning
```
**Вердикт: ✅ GAP ПОДТВЕРЖДЁН.** (a) и (b) — одинаковый failure-сигнал (passed=0, warning-класс «нет реальных результатов»); сообщение (a) утверждает «пустые/мусорные чанки», хотя сырых результатов было 0 — ложное объяснение. Нет счётчика `eligible_seen` (сколько чанков было в индексе ДО запроса): «0 строк с 0 eligible» (здоровый idle — свежий проект) неотличим от «0 строк с N eligible» (сломанный коллектор). Ошибка searcher (b2) — отдельный класс (различается).
**Урок:** метрика обязана нести оба числа: `population_size` (после) и `eligible_seen` (до селекции); gap между ними — аудируемая величина (Tom: «You sampled 12 of 400 invites an argument. You sampled 12 ends one.»). В health: добавить в warning count сырых + размер индекса, а «0 eligible» маркировать как INFO (healthy idle), не как failure.
**Связь с отрицательными:** нет.

## [2026-08-11] — EXP-5: `verify_clean_state.sh` — falsifiability-проверка гейта + P1: drift-гейт структурно мёртв

**Гипотеза:** (A) drift-гейт (строки 55-71) умеет падать на рассинхроне pin vs lock; (B) вакуумная сюита (0 asserts) проходит → «CLEAN STATE VERIFICATION: PASSED» — reproducibility без falsifiability (ANP2).
**Команда:** `bash experiments/exp_verify_gate.sh` (drift-цикл дословно из скрипта, temp pyproject/lock; pytest на temp-сюите) + повторный прогон гейт-кода на РЕАЛЬНЫХ файлах проекта.
**Сырой результат:**
```
Часть A: drift (lancedb 0.12.0 pin vs 0.13.0 lock) → «drift НЕ обнаружен → exit 0 ❌»
Реальные файлы: lancedb PINNED='' LOCKED='0.34.0' | mcp PINNED='' LOCKED='1.28.1' | tree-sitter PINNED='' LOCKED='0.26.0'
Часть B: вакуумная сюита → 3 passed in 0.21s, exit 0 → гейт напечатал бы PASSED
Корректный парсинг (grep -oE "pkg==[0-9.]+"): lancedb PINNED='0.34.0' = lock ✅;
  симулированный дрейф (lancedb==0.99.0 в pyproject) → DRIFT DETECTED
```
**Вердикт: ✅ ЧАСТИЧНО, с критической находкой.** (B) подтверждена: гейт печатает PASSED для сюиты без единого assert — семантическая слепота. (A) ОПРОВЕРГНУТА наоборот: **дрейф-гейт структурно неспособен сработать** — паттерн `grep -iE "^\"?${pkg}=="` требует `pkg==` в начале строки, но пины лежат в TOML-массиве (`    "lancedb==0.34.0",`) → PINNED всегда пуст → ветка `DRIFT=1` недостижима для всех 3 пакетов. Живой экземпляр класса «guard не может упасть» (Tom ln.strip()). Корректный парсинг (демонстрация направления фикса) ловит и текущий sync, и симулированный дрейф.
**Урок:** grep-парсинг TOML-массивов по якорю `^` — мёртвый паттерн; fix = `grep -oE "${pkg}==[0-9.]+"` или python tomllib; обязателен negative control (фикстура с заведомым дрейфом, обязан дать exit 1). Бонус-находка (Любопытство §3.4): scripts/stale_detector.py — placeholder «No drifts detected», всегда exit 0, подключён к pre-commit хуку (git_hooks_installer.py:88) — второй guard того же класса.
**Связь с отрицательными:** нет.

## [2026-08-11] — Exp 1-V REPLICATION: Memory Contamination VERIFY-ON-READ — факты v4, N=50 (ВОСПРОИЗВЕДЕНО)

**Гипотеза:** verify-on-read доводит adoption честного до 0.0 на SILENT-фактах — свойство системы, а не артефакт набора v3 (Правило одного бенча §1: одиночный замер ≠ доказательство).
**Команда:** `venv/Scripts/python.exe experiments/context_engine/memory_contamination_generator_rep.py` (seed=7, TRUE_POOL_REP: file:6+env:2+import:9+CamelCase:8, absent: qdrant/weaviate/.../vault 16, trap: pathlib/threading/dataclasses/json/logging/re 6, silent: terraform/jaeger/loki 3) → `memory_contamination_facts_v4_rep.json` → `venv/Scripts/python.exe experiments/context_engine/memory_contamination_verify.py memory_contamination_facts_v4_rep.json`. Тот же агент/логика (контрольная группа), другой набор данных.
**Сырой результат (v4 vs v3):**
```
verify: checked=50 cache_hits=0 inconclusive=9 budget_exceeded=False
latency: fingerprint 73.8ms, first pass 115.3ms, steady-state 0.6ms (cache_hits=31, checked=0)
verdicts: VERIFIED=22 REFUTED=19 ACTIVE(INCONCLUSIVE)=9
false REFUTED: total=19 | среди TRUE (артефакт маппинга): 0
видимые ложные после verify (memory_first adopters): [R42,R43,R44,R45,R46,R47]
adoption A_code_first: v3 0.12 | 1-R 0.12 | 1-V 0.0 | 1-V-REP 0.0
adoption A_memory_first: v3 1.0  | 1-R 0.12 | 1-V 0.16 | 1-V-REP 0.24
visible false of 25: 1-V 4 | 1-V-REP 6
```
**Вердикт: ✅ ВОСПРОИЗВЕДЕНО.** (1) **adoption честного 0.0 воспроизведён** на независимых данных (v3→v4, другой TRUE-пул, другие absent/silent) — главная метрика DoD ADR-0003 устойчива: все 3 SILENT (terraform/jaeger/loki) + 16 absent отозваны до контекста. (2) **0 ложных REFUTED TRUE** при корректно типизированных якорях (R01-R25: 16 VERIFIED + 9 INCONCLUSIVE, 0 REFUTED) — DoD подтверждён независимо (в 1-V было 7 — артефакты НАИВНОЙ типизации голых токенов; при корректной типизации их 0). (3) **Ограничение present-trap воспроизведено**: 6/6 ловушек — реальные импорты → VERIFIED, visible 6 → memory_first 0.24 (1-V: 0.16; число выше, т.к. в v4 ВСЕ 6 trap — импорты, в v3 — 4 из 6). Слепота presence-проверки к present-trap — структурная, ловит только честный агент (code_first 0.0). (4) steady-state 0.6ms (cache_hits=31) — бюджет ≤50мс соблюдён. (5) Разложение вердиктов точно по прогнозу: REFUTED=19 (16 absent + 3 silent — все корректные отзывы FALSE), VERIFIED=22 (16 TRUE + 6 trap), ACTIVE=9 (8 CamelCase + env MSCODEBASE_ALLOW_SELF_INDEX вне .env).
**Урок:** репликация подтвердила: (a) главный вывод 1-V — свойство VerifyOnRead, не данных; (b) типизация якорей — единственный источник ложных отзывов TRUE (0 при корректной, 7 при наивной — воспроизводимо, закрыто write-time capture); (c) «0.0 adoption» требует отзыва SILENT — проверено дважды. Ограничение прежнее: детерминированный прокси-агент, не живой LLM.
**Связь с отрицательными:** нет.

## [2026-08-11] — Exp 1-V: Memory Contamination VERIFY-ON-READ — аналог v3 с Lazy Validation Layer (ADR-0003)

**Гипотеза:** Verify-On-Read (проверка ACTIVE-узлов при извлечении, до промпта) доводит заражение до нуля: SILENT-факты с отсутствующими якорями -> REFUTED (SILENT_ABSENCE_ON_READ). Ожидание (DoD ADR-0003): adoption честного 0.0; 0 ложных REFUTED среди TRUE при корректно типизированных якорях.
**Команда:** `venv/Scripts/python.exe experiments/context_engine/memory_contamination_verify.py` — те же 50 фактов v3; якоря из support_patterns по синтаксису (file: -> file, ALL-CAPS -> env с нормализацией к точному ключу, lowercase -> import); РЕАЛЬНЫЙ VerifyOnRead на реальной кодовой базе (отпечаток src+.env), изолированный store и кэш; агенты решают на пост-verify памяти.
**Сырой результат:**
```
verify: checked=50 cache_hits=0 inconclusive=12 budget_exceeded=False
latency: fingerprint 82.3ms, first pass 128.9ms, steady-state 0.6ms (cache_hits=22, checked=0)
verdicts: VERIFIED=10 REFUTED=28 ACTIVE(INCONCLUSIVE)=12
false REFUTED: total=21 | среди TRUE (артефакт маппинга): 7 [G07,G25,G11,G24,G23,G18,G21]
видимые ложные после verify (memory_first adopters): [G42,G43,G44,G45]
adoption A_code_first: v3 0.12 | 1-R 0.12 | 1-V 0.0
adoption A_memory_first: v3 1.0  | 1-R 0.12 | 1-V 0.16
```
**Вердикт: ЧАСТИЧНО (цель достигнута, 2 ограничения зафиксированы честно).** (1) **adoption честного → 0.0** (v3/1-R: 0.12) — цель «заражение к нулю» достигнута: SILENT-отсутствия (grafana/gitlab/kubernetes/nose/neo4j/rabbitmq) отозваны до контекста. (2) **steady-state 0.6мс** (cache_hits=22, checked=0) — бюджет ≤50мс соблюдён; fingerprint ~80мс платится один раз на HEAD. (3) **Ограничение 1 (present-trap):** 4 ложных остались видимыми (G42 sqlite3/G43 onnx/G44 httpx/G45 sqlite3 — токены РЕАЛЬНО импортируются кодом) -> memory_first adoption 0.16 (хуже 1-R 0.12: ручной отзыв честного агента в 1-R поймал traps contra-анализом; presence-проверка их не видит). Комбинация verify + честный агент (code_first) = 0.0. (4) **Ограничение 2 (артефакты типизации):** 7/25 ложных REFUTED TRUE — все от наивного маппинга голых токенов в import-якоря (lancedb_version/bm25_weight — конфиг-строки; intel_log_incident/intel_auto_collect_adrs/intel_get_telemetry — методы слоя; fastmcp — реальный импорт `from mcp.server.fastmcp import FastMCP` (server_factory.py:158), корень `mcp`, не `fastmcp`; basedpyright — бинарник node_modules/.bin (lsp_client.py:527), не python-импорт). Компонент проверил ровно то, что ему дали; с корректно типизированными якорями (юнит-тесты) — 0 ложных отзывов.
**Урок:** verify-on-read удаляет absence-заражение (SILENT+отсутствующие) полностью, но presence-проверка принципиально слепа к present-trap (токен есть, субъект другой) — их ловит только честный агент. Типизация якорей — ответственность write-пути: голые токены паттернов НЕЛЬЗЯ превращать в import-якоря без валидации типа (метод/конфиг/подмодуль/бинарник ≠ импорт). Следующий шаг: anchor-capture при записи узла (типизированные якоря в data.anchors).
**Связь с отрицательными:** нет.

## [2026-08-11] — Exp 1-R: Memory Contamination RETRACTION — аналог v3 с ретракцией (ADR-0002)

**Гипотеза:** системный отзыв (intel_retract_memory_node, ADR-0002) превращает `would_refute` честного агента (corr_cap=1.0) в реальное действие: отозванные факты исчезают из контекста следующих сессий → даже memory_first в сессии 2 не примет уже отозванный факт. Ожидание (ADR Temporal): adoption честного падает с 0.12 к 0.
**Команда:** `venv/Scripts/python.exe experiments/context_engine/memory_contamination_retraction.py` — те же 50 фактов v3 (контрольная группа), тот же CodeEvidence/decide; сессия 1 = честный агент + реальный `intel_retract_memory_node` (прод-путь layer, изолированный store, seed БЕЗ status = легаси/ACTIVE); сессия 2 = свежее чтение обоими агентами пост-ретракционной памяти (load_memory фильтрует REFUTED).
**Сырой результат:**
```
valid facts: 50 (25T + 25F, silent-false 3)  |  invalid: 0  |  parity: OK
              adopt(F)  corr_cap persist.F    tokens
S1 honest+retract   0.12       1.0         3     653.2
S2 code_first       0.12         -               360.8
S2 memory_first     0.12         -
retraction: 22/22 would_refute реализовано системно (correction_capability_systemic=1.0)
persistent false in memory: 25 -> 3 (-88%)
tokens_memory: 653.2 -> 360.8 (-45%)
all refuted have reason: True
```
**Вердикт: ЧАСТИЧНО (гипотеза подтверждена в части системного отзыва, прогноз «adoption → 0» уточнён).** (1) Parity с v3: adoption честного S1 = 0.12 — контрольная группа совпала. (2) **Systemic capability: 22/22** would_refute реализованы через реальный прод-путь (correction_capability_systemic=1.0; раньше grep-0 refute-тулов). (3) **memory_first adoption: 1.0 → 0.12** в сессии 2 — ретракция защищает даже «ленивого» агента (отозванное скрыто load_memory). (4) **Persistent contamination: 25 → 3 false (-88%)** — остались только SILENT. (5) **tokens контекста: -45%** (653→361; метрика — реальный размер одного чтения, не накопленный v3-аналог 66.5k). (6) **Прогноз «adoption честного → 0» НЕ подтверждён**: SILENT-факты код молчит — честный агент их не отзовёт (adoption остаётся 0.12); до 0 доведёт только verify-on-read (Вариант B), нацеленный на остаточные SILENT.
**Урок:** ретракция удаляет ОПРОВЕРЖИМУЮ часть заражения (88%), но не SILENT — они требуют верификации против кода, а не отзыва. «Adoption → 0» — неверный таргет для ретракции; правильные метрики: persistent contamination, adoption не-честных агентов, токены контекста. ADR-0002 Temporal уточнён (см. ADR).
**Связь с отрицательными:** нет.

## [2026-08-11] — Exp: Memory Contamination — INDEPENDENT AUDIT (second opinion, 48/48 CONFIRMED)

**Гипотеза:** truth-метки фактов v1+v2 достоверны: TRUE-паттерны — рабочая логика (не docstring/мёртвый код), FALSE/SILENT — чистые grep-0 с рабочими контраргументами.
**Команда:** spawn_agent (независимый аудитор, не видел наш диалог): 48 фактов из memory_contamination_facts.json + _v2.json против src/**/*.py; чек-лист «активный код vs docstring/статические списки»; без MCP-семантического поиска.
**Сырой результат:**
```
CONFIRMED 48/48 | DEAD 0 | MISSING 0 | BROKEN 0
T01-T20, F01-F20, S01-S14 — все с file:line evidence (активные импорты/вызовы/конфиги)
```
**Вердикт: ✅ ПОДТВЕРЖДЕНО (48/48).** Оговорки (не ложность, качество паттернов): T03 «ВНЕ проекта» — только docstring, но подтверждён вторым паттерном MSCODEBASE_DATA_DIR; T06 fastmcp — активный import в server_factory.py:158 (не server.py — note неточен); T13 «57 инструментов» — паттерн «12 inline» в docstring, но счёт регистраций 28+13+12+4=57 независимо подтверждён; T18 «идемпотентен» — docstring, но код _migrate_into (artifact_paths.py:252-298, if src.exists and not dst.exists) реализует. Системное ограничение: .env невидим grep-инструменту (private_files) — grep-0 по src подтверждён, по .env — остаточный риск мал (KNOWN_ISSUES 2026-08-08 цитирует .env владельца: только MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true).
**Урок:** (1) «свежие глаза» (независимый аудитор без контекста) — финальный уровень верификации truth-данных, закрывает риск «автор верит своему набору»; (2) паттерны-якоря в docstring валидны, если claim независимо подтверждается рабочим кодом (счёт/чтение кода) — фиксировать оговорки, не переделывать факты пост-фактум.

## [2026-08-11] — Exp: Memory Contamination — MUTATION GENERATOR (facts v3, N=50) — РЕАЛЬНОЕ РАСПРЕДЕЛЕНИЕ

**Гипотеза:** (1) метрики — точные функции смеси категорий (алгебра, а не статистика): при контролируемой смеси значения предсказуемы по формулам; (2) «голос кода» на сгенерированных фактах: real-паттерны подтверждают 25/25, мутации-отсутствия опровергаются, present-trap «ловушки» (ложный токен ЕСТЬ в коде) тоже опровергаются контраргументом.
**Команда:** `venv/Scripts/python.exe experiments/context_engine/memory_contamination_generator.py` (seed=42, смесь 25T+16absent+6trap+3silent=50) → `memory_contamination_facts_v3_generated.json` → `venv/Scripts/python.exe experiments/context_engine/memory_contamination.py memory_contamination_facts_v3_generated.json`.
**Сырой результат (v3 vs v1/v2):**
```
arm             correct  adopt(F)  contra  corr_cap  conf_eff  unk     tokens
B               0.94     0.0       0.88    0.0       3         0.06    1539
A_code_first    0.94     0.12      0.88    1.0       3         0.0     66477
A_memory_first  0.50     1.0       0.88    0.0       3         0.0     66477
(v1/v2 для сравнения: B 0.833/0.0, A_cf 0.833/0.286/1.0, A_mf 0.417/1.0, contra 0.714, conf_eff 4)
```
**Вердикт:**
- **H1: ✅ ПОДТВЕРЖДЕНА (алгебра)** — все 6 метрик совпали с формулами от смеси: 0.94=(25+22)/50, adopt 0.12=3/25, contra 0.88=22/25, corr_cap 22/22=1.0, B unk 3/50. Это финальное доказательство: при детерминированном агенте N определяет только смесь, не точность.
- **H2: ✅ ПОДТВЕРЖДЕНА** — «голос кода» на 50 фактах: 25 SUPPORT + 22 CONTRADICT + 3 SILENT. Все 6 present-trap (ollama/lm_studio/onnx/fts5/sqlite3/git — токены ЕСТЬ в коде) дали CONTRADICT: реальный паттерн субъекта перевешивает токен лжи → вердикт корректен. Заражение честного агента (A_cf adopt 0.12) только на SILENT (внешние системы).
- **Стоимость памяти:** 66.5k токенов на 50 фактов (~1.3k/факт, O(N) per-fact) — контекст-цена памяти растёт линейно с числом записей.
**Урок:** (1) генератор мутаций — масштабируемый путь к реалистичным наборам вместо ручной курации (риск семантических ловушек не масштабируется с N); (2) present-trap устойчивость — эмпирически подтверждено, что verify-on-read с контраргументом по реальному паттерну не ломается о правдоподобную ложь; (3) ambiguous=6 в v3 — не дефект, а by-design ловушки (верификатор параметризован: v1/v2=0, v3=6, invalid=0 всегда).

## [2026-08-11] — Exp: Memory Contamination — REPLICATION (facts v2, N=24) — ВОСПРОИЗВЕДЕНО

**Гипотеза:** метрики v1 — свойство системы (структура задачи), а не артефакт конкретного набора фактов.
**Команда:** `venv/Scripts/python.exe experiments/context_engine/memory_contamination.py memory_contamination_facts_v2.json` — НОВЫЙ набор фактов (10T + 10F + 4SILENT: grafana/gitlab/kubernetes/memcached), другой паттерн-дизайн, та же логика агента (Правило контрольной группы §1: не меняем агента между прогонами).
**Сырой результат (v2 vs v1):**
```
arm             v1 correct  v2 correct  v1 adopt  v2 adopt  corr_cap v2  contra v2  conf_eff v2  unk v2
B               0.833       0.833       0.0       0.0       0.0         0.714      4            0.167
A_code_first    0.833       0.833       0.286     0.286     1.0         0.714      4            0.0
A_memory_first  0.417       0.417       1.0       1.0       0.0         0.714      4            0.0
```
**Вердикт: ✅ ВОСПРОИЗВЕДЕНО** — идентичные метрики на двух независимых наборах фактов (24+24, разные паттерны, разные внешние системы). Числа детерминированы структурой: внутренние факты о коде опровергаемы 10/10, внешние системы 4/4 SILENT (код молчит), TRUE 10/10 SUPPORT. Итоговые выводы v1 устойчивы: correction_capability (code_first)=1.0 при явном противоречии; система add-only (отзыв невозможен — grep-0); память даёт уверенную ложь на SILENT-фактах (conf_eff=4); память ×22 токенов без выигрыша в точности.
**Урок:** репликация на независимых данных — обязательна для «одиночных замеров» (§1 «Правило одного бенча»): два набора → одинаковый вердикт → вывод подтверждён. Ограничение прежнее: детерминированный прокси-агент, не живой LLM.
**Верификация (verify_memory_contamination.py, 2026-08-11):** 3 оси ALL PASS — (A) truth-table decide(): 9/9 путей = спецификации (поймал choice-непоследовательность memory_first@SUPPORT: было CODE, стало MEMORY; вердикты/метрики не изменились); (B) декомпозиция агрегатов из per-fact строк для v1+v2; (C) 24/24 valid, 0 invalid, 0 ambiguous в обоих наборах.

## [2026-08-11] — Exp: Memory Contamination (IntelligenceStore) N=24, v1 (Experiment 1 из second_brain_research)

**Гипотеза:** персистентная память (project_memory.json + incidents.json) вносит stale/false контекст: (H1) код может опровергнуть большинство ложных фактов памяти; (H2) при явном противоречии Memory vs Code агент с честной политикой выбирает CODE и отзывает факт (correction_capability — метрика владельца), но система не имеет инструмента отзыва; (H3) там, где код молчит, память превращает UNKNOWN в уверенный (ложный) ответ.
**Ожидание:** code_contradictability ≥0.7; correction_capability (code_first) = 1.0; adoption (memory_first) = 1.0; memory_confidence_effect > 0 на SILENT-фактах.
**Команда:** `venv/Scripts/python.exe experiments/context_engine/memory_contamination.py` — 24 факта (10T + 10F с контраргументом + 4 SILENT-F внешние системы, grep-0 в src); изолированный `IntelligenceStore(tempdir)` (assert store_dir != реальный); агент = детерминированный прокси (живого LLM в проекте нет): evidence-поиск по src/**/*.py + .env; руки B (без памяти) / A code_first / A memory_first; выбор ground truth (MEMORY|CODE|NONE) фиксируется per-fact. Факты: memory_contamination_facts.json. Результат: memory_contamination_results.json.
**Сырой результат (24 факта, 0 invalid, 0 ambiguous, isolation confirmed):**
```
arm             correct  adopt(F)  contra  corr_cap  conf_eff  unk     tokens
B               0.833    0.0       0.714   0.0       4         0.167   784
A_code_first    0.833    0.286     0.714   1.0       4         0.0     17830
A_memory_first  0.417    1.0       0.714   0.0       4         0.0     17830
```
**Вердикт:**
- **H1: ✅ ПОДТВЕРЖДЕНА (частично)** — code_contradictability 0.714 (10/14). Внутренние факты о коде опровергаются 10/10; внешние системы (Redis/Celery/MySQL/Kafka) — 0/4: код молчит → неопровержимая ложь.
- **H2: ✅ ПОДТВЕРЖДЕНА** — correction_capability (A code_first) = 1.0: при CONTRADICT честный агент ВСЕГДА выбирает CODE и отзывает (10/10). НО: (a) A_memory_first adoption = 1.0 — противоречие само по себе не защищает (агент может игнорировать код); (b) система add-only: инструмента отзыва/refute нет (grep-0 delete/refute по memory-инструментам) — даже would_refute=1 не реализуемо системно.
- **H3: ✅ ПОДТВЕРЖДЕНА** — memory_confidence_effect = 4: на SILENT-фактах A дала уверенный неверный ответ, B — честный UNKNOWN (unknown_rate 0.167). Память без контроля кода генерирует уверенную ложь.
- **Стоимость:** память-контекст ≈ 17k токенов на 24 записи (~710 ток/факт) vs 784 evidence в B (×22 дороже), при этом correct_rate A_code_first == B == 0.833 — выигрыша в точности память НЕ дала на этом наборе.
**Урок:** (1) калибровка честная: без живого LLM измеряем «защитную способность системы», не психологию агента — adoption code_first = только SILENT-факты (нижняя граница заражения), memory_first = 100% (верхняя). (2) Память add-only + нет verify-on-read → заражение кумулятивно: найденная ложь не отзывается, stale-ADR из intel_auto_collect_adrs остаются навсегда. (3) Ловушка паттернов: «openai» найдено в multi_provider.py:294 как «OpenAI-compatible API» (LM Studio) — не провайдер; для внешних систем нужны специфичные имена (text-embedding-3). (4) Изоляция памяти per-project (hash пути) работает: store_dir tempdir ≠ реальный.
**Связь с отрицательными:** нет. | **Решение для архитектуры:** (1) verify-on-read: при load_memory сверять claim с кодом (code_contradictability 0.714 — большинство опровергаемо) или помечать trust-статусом; (2) retraction-статус записи (VERIFIED/REFUTED, владелец: RetractionReceipt) + фильтрация REFUTED при чтении; (3) intel_auto_collect_adrs — риск stale: ADR о коде проверимы (0.714), ADR об окружении/решениях — нет; приоритет: статус + TTL.

## [2026-08-08] — Exp: верификация deep-research-report.md (внешний аудит) против кода

**Гипотеза:** 3 P1-находки отчёта (Windows mutex, неатомарная запись LanceDB, TaskQueue.submit_sync) существуют в текущем коде; CVE-рекомендации актуальны; roadmap P0/P1 реализован.
**Команда:** get_symbol_info/read_live_file по llama_runner.py:184/248, db_writer.py:122-134/310-327, task_queue.py:127-183; OSV API (api.osv.dev) для CVE-2026-1839/4372; PyPI для актуальных версий; `python -m pytest tests/ -q -m "not slow and not benchmark" --cov=src --cov-fail-under=38` (реальный прогон).
**Сырой результат:**
```
| Гипотеза                                  | Вердикт |
|-------------------------------------------|---------|
| Mutex initialOwner=TRUE + 1 ReleaseMutex  | ✅ CONFIRMED llama_runner.py:184/248 (graph.py:74, onnx_client.py:76 — уже False) |
| delete+add неатомарны                     | ✅ CONFIRMED (метод write_records, НЕ replace_chunks) |
| submit_sync race + «вечная» задача        | ✅ CONFIRMED (except RuntimeError: pass без cleanup; тест из отчёта НЕ существует) |
| CVE-2026-1839/4372                        | ✅ CVE реальны; отчёт недооценил 4372 (фикс 5.3.0, не 5.0.0); lock уже 5.14.1 → закрыты |
| Coverage ~38% / 956 passed                | ❌ УСТАРЕЛО: 1022 passed / 4 skipped / 94 deselected, 46.89%, 84.94s |
| Roadmap P0 (bench/enrichment/planner)     | ⚠️ Частично: bench ✅ (experiments/benchmark2), late enrichment ✅ (engine.py:1142), Adaptive Planner ❌ не найден |
```
**Вердикт:** отчёт точен по P1 (3/3 подтверждены), но: (1) имена кода частично вымышлены (replace_chunks, test_submit_sync_failure_cleanup, путь src/core/indexing/task_queue.py — реально src/core/task_queue.py); (2) CVE-2026-4372 недооценён (>=5.0.0 недостаточно, нужен >=5.3.0); (3) числа тестов/coverage устарели (+66 тестов, +9%); (4) часть roadmap уже реализована (WS1-WS9), Adaptive Retrieval Planner — нет.
**Урок:** внешние аудиты писать по актуальному дереву (grep по именам), не по памяти об API; «fixed version» CVE брать из OSV по каждой CVE отдельно, не обобщать.

## [2026-08-08] — Exp: применение фиксов аудита (4/4) — 1026 passed

**Гипотеза:** rollback по LanceDB-версиям + lock/cleanup в TaskQueue + mutex False + пин >=5.3.0 не ломают существующие тесты и закрывают 3 P1 + CVE-пин.
**Команда:** правки 4 файлов (llama_runner.py, task_queue.py, db_writer.py, pyproject.toml) + 4 новых теста; `python -m ruff check src/ tests/`; `python -m pytest tests/ -q -m "not slow and not benchmark"`.
**Сырой результат:**
```
All checks passed!
1026 passed, 4 skipped, 94 deselected in 74.49s (было 1022)
17/17 targeted (test_task_queue, test_llama_mutex, test_lancedb_recreate) passed
grep CreateMutexW(None, True) = 0; except RuntimeError:pass с потерей состояния = 0
```
**Вердикт:** подтверждена — 3 P1 закрыты кодом+тестами, CVE-пин поднят до >=5.3.0. Остаточные риски: (1) restore при конкурентном внешнем reset_connection может откатить чужую версию (сериализация только внутри writer); (2) если restore упадёт (версия очищена cleanup_old_versions) — данные восстановятся повторной индексацией (self-healing).
**Урок:** LanceDB versioning (table.version/restore) — нативный механизм атомарности delete+add, лучше выдуманного temp+os.replace из отчёта; проверка API (§5.19) заняла 1 команду и подтвердила restore/version на 0.33.

---

## [2026-08-06] — Exp: batch-размер embedder'а (A/B T3) — прод-настройка batch=32 подтверждена

**Гипотеза:** batch=64 даст максимум ch/s (амортизация фиксированных накладных расходов); batch=32 не проиграет существенно (<10%).
**Команда:** `python experiments/bench_embed_batch.py` — корпус 64 текста, batch ∈ {8,16,32,64}, N=3 повтора, медиана; реальный путь вызова POST http://127.0.0.1:8080/v1/embeddings (llama.cpp, порт проверен netstat'ом).
**Сырой результат:**
```
batch= 8: ch/s=153.98, p50_req= 51.8ms, errors=0
batch=16: ch/s=154.03, p50_req=103.5ms, errors=0
batch=32: ch/s=156.15, p50_req=204.7ms, errors=0   ← BEST ch/s
batch=64: ch/s=156.08, p50_req=409.8ms, errors=0
Отношение к batch=32: 64→1.000x, 16→0.986x, 8→0.986x
```
**Вердикт:** ЧАСТИЧНО ОПРОВЕРГНУТА: batch=64 НЕ быстрее 32 (156.08 vs 156.15 — идентичны, разброс по всем batch всего 1.4%). p50 латентности линейна по batch (~6.4ms/текст) → время = чистый compute, заметных накладных расходов нет. Прод-настройка batch=32 ПОДТВЕРЖДЕНА (максимум ch/s). Дополнительно: документированные «100 ch/s» (решение 2026-07-17) устарели — фактически ~156 ch/s (+56%).
**Урок:** при линейной латентности выбор batch = компромисс throughput vs p50 ответа: batch=16 даёт 103ms (−50% p50) ценой −1.4% throughput — кандидат для интерактивных вызовов; для reindex batch=32 остаётся оптимумом.
**Связь с отрицательными:** новая; контрольная группа — 4 batch на одном корпусе в одной сессии (соблюдено).

---

## [2026-08-06] — Exp: A/B protocol-compression — ARM A (полная версия): 4 задачи, баллы 54/64

**Гипотеза:** компакт (−57.2%) сохраняет уровень соблюдения 8 поведенческих контрактов ≥ полной версии (метрика: баллы 0/1/2 по чек-листу).
**Команда (протокол двух сессий):** arm A — эта сессия (полная версия), задачи T1..T4; затем swap `AGENTS.md → AGENTS.full.bak`, `AGENTS.compact.md → AGENTS.md` (+ сверка размеров); Reload Zed; сессия 2 (компакт) — те же задачи в ОБРАТНОМ порядке (T4,T3,T2,T1), затем восстановление `AGENTS.full.bak → AGENTS.md`; сводная таблица. Формулировки задач verbatim — `.agent_task_state.md`. Мутации (T1 engine.py, T4 3 doc-файла): diff-зафиксированы (experiments/t1_armA_engine.patch, experiments/t4_armA_docs.patch) и ОТКАЧЕНЫ до arm B — стартовое состояние идентично.
**Сырой результат (arm A, self-assessed с evidence):**
```
| Контракт (0/1/2)          | T1 | T2 | T3 | T4 | Evidence |
|---------------------------|----|----|----|----|----------|
| 1. Phase Zero             | 1  | 2  | 2  | 1  | сессионный [🔭 PHASE ZERO] полный (5 полей до вызовов); per-task: T2/T3 полный, T1/T4 — точечная разведка без формального блока |
| 2. Триггеры 1–7           | 1.5| 1.5| 1.5| 1.5| Т1✓ Т5✓ Т6✓ Т7 N/A; Т2 фикс-уровень ✗; Т3 обобщение частично; Т4 in-moment ✗ (bash-квотинг PowerShell, meta-check постфактум) |
| 3. §8 отчёт (поля 1–12)   | 2  | 2  | 2  | 2  | финальный блок сессии |
| 4. Verified/Recalled      | 2  | 2  | 2  | 2  | пометки в Phase Zero; ✅ с file:line |
| 5. Ledger инкрементально  | 2  | 2  | 2  | 2  | обновление после каждого T, до следующего шага (§0.1.2) |
| 6. Red Team ≥3 атак       | 1.5| 1.5| 1.5| 1.5| план: 5 атак с защитами ✓; после edit >5 строк — ✗ |
| 7. OPEN_QUESTION          | 2  | 2  | 2  | 2  | 2 вопроса владельца в task state + финальный отчёт |
| 8. Concurrency note       | 1  | 1  | 1  | 1  | swap-файлы и общий embedder (T3) без формальной заметки |
| СУММА (из 16)             | 13 | 14 | 14 | 13 | 54/64 (84.4%) |
```
**Примечания к оценке:** пункты 2,3,5,6,7,8 — сессионные (одинаковы по задачам); пункт 1 — per-task. Под полной версией контракты держатся «на плане и в отчёте», но проседают «в моменте» (Red Team на фикс, мета-чек при ошибке, формальная Concurrency note).
**Вердикт:** ARM A зафиксирован (54/64). Сравнение с arm B — ⏳ PENDING (сессия 2; ожидается вторая половина таблицы + итог: можно/нельзя/частично + урок §3.8).

---

## [2026-08-06] — Exp: A/B protocol-compression — ARM B (компакт): 4 задачи, баллы 49.5/64

**Гипотеза:** компакт (−57.2%) сохраняет уровень соблюдения 8 поведенческих контрактов ≥ полной версии (arm A: 54/64).
**Команда:** сессия 2 под компактом (AGENTS.md = 53054 B, Verified ls); те же задачи verbatim в обратном порядке (T4,T3,T2,T1); bench-скрипт БЕЗ изменений; после всех задач — restore `AGENTS.full.bak → AGENTS.md` (129705 B) + rm .bak.
**Сырой результат (arm B, self-assessed с evidence):**
```
| Контракт (0/1/2)          | T4 | T3 | T2 | T1 | Evidence |
|---------------------------|----|----|----|----|----------|
| 1. Phase Zero             | 1.5| 1.5| 1  | 1.5| сессионный PZ полный (5 полей); per-task: T4/T3/T1 — компактные блоки (3/5 полей), T2 — БЕЗ блока (чистая диагностика, только чтение) |
| 2. Триггеры 1–7           | 1.5| 1.5| 1.5| 1.5| Т1✓ Т3✓ (два обобщения: T4 — доп. устаревания TOC/диаграмма, T1 — второй sync-двойник _apply_multi_reranker) Т5 частично Т6✓ Т7 N/A; Т2: RED TEAM до edit, META-CHECK неформальный |
| 3. §8 отчёт (поля 1–12)   | 2  | 2  | 2  | 2  | финальный блок сессии |
| 4. Verified/Recalled      | 2  | 2  | 2  | 2  | пометки; ✅ с file:line |
| 5. Ledger инкрементально  | 1  | 1  | 1  | 1  | обновление пачкой в конце, НЕ после каждого T (арм A: 2) |
| 6. Red Team ≥3 атак       | 1.5| 1.5| 1.5| 1.5| T4: 4 атаки, T1: 5 атак (план ДО edit); после edit формального блока нет |
| 7. OPEN_QUESTION          | 2  | 2  | 2  | 2  | 2 вопроса + 3 находки владельцу |
| 8. Concurrency note       | 1  | 1  | 1  | 1  | T3 общий embedder :8080 + swap-файлы без формальной заметки |
| СУММА (из 16)             | 12.5| 12.5| 12 | 12.5| 49.5/64 (77.3%) |
```
**T4:** runtime-truth 49 = 20 core (tool_classes L80-108: 3 search+1 hub+5 analysis+4 graph+3 investigation+3 lifecycle+1 doc) + 13 intel (tools_reg.py @mcp_app.tool ×13) + 12 inline (@mcp.tool ×12) + 4 dev (dev_tools ×4), env off; 50 при MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true. `_count_tools` в auto_doc_updater.py актуален (20+13+12+4=49, не трогал). 23 правки в 6 файлах: AGENTS.md L1/3/305/315, README L18 (TOC-якорь)+L208, ARCHITECTURE en ×7 (TOC/диаграмма/L94/L101/комментарий/фильтр/Total), ru ×4, zh ×3, server_tools.py докстринг L6/10/27 → experiments/t4_armB_docs.patch → откат; 6 passed.
**T3:** `python experiments/bench_embed_batch.py` без изменений → batch=16 max 156.33 ch/s (p50 100.3ms); batch=32 = 152.32 (p50 209.9ms) → best/32 = 1.026x; batch=8 152.82 (52.4ms), batch=64 155.29 (411.8ms); errors=0. Плато 152-156 для всех batch, p50 линейна ~6.5ms/текст (совпадает с arm A). batch=32 НЕ подтверждён как строгий максимум (arm A: подтверждён) — разница в пределах шума (2.6%).
**T2:** KNOWN_ISSUES:202 передиагностика (замер 21:47): commit 59.3% (триаж: 93.8%), free RAM 6.28GB, Zed WS 0.59GB (2 процесса; триаж: 5.84GB), crash-loop 0; АКТИВНЫ: C: 92% (цель <85%), pagefile 2.1GB (цель ≥8GB; триаж был 3.2GB — ухудшение), threads.db 85.9MB (08-05: 79.7MB, +~5MB/д), AGENTS.md 53KB (был 126KB — улучшение компактом). Вердикт: риск краша СНИЖЕН — совпадает с arm A. Только диагноз, без правок.
**T1:** sync `_ensure_multi_reranker` (engine.py:1013) удалён: grep по src/tests/scripts/docs — 0 вызовов sync (13 мест, все `_async`); async не делегирует (собственный Lock-паттерн L1029+); импорты не осиротели (Optional/MultiProviderReranker в сигнатуре async); −16 строк; 19 passed (test_searcher 15 + test_fts5_integration 4); experiments/t1_armB_engine.patch; откат. Обобщение (Т3): sync `_apply_multi_reranker` (engine.py:1063) — тоже 0 вызовов в src+tests → флаг владельцу (вне скоупа T1).
**Примечания к оценке:** п.2/3/6/7/8 — сессионные; п.1 и п.5 — per-task. Честные просадки arm B: T2 без per-task PZ (1), ledger не инкрементальный (1×4). near-miss: опечатка `>` в new_text при T1-правке — поймана перечитыванием зоны (Триггер 7), файл корректен.
**Вердикт:** ARM B = 49.5/64 (77.3%) < ARM A = 54/64 (84.4%) → **гипотеза НЕ подтверждена** (компакт ниже на 4.5 балла / 7%). Разница: per-task Phase Zero (5.5 vs 6 — T2 без блока) и инкрементальный Ledger (4 vs 8). Оба контракта ЕСТЬ в компакте (не потеряны формулировкой) — просело срабатывание «в моменте». Совпали с обеих рук: Red Team после edit (1.5), Concurrency note (1), Verified/Recalled (2), §8 (2), OPEN_QUESTION (2). Критика метода: N=1 сессия × 4 задачи, self-assessment → шум ±5-7 баллов; жёсткий вердикт «можно/нельзя» невозможен.
**Итог: ЧАСТИЧНО.** Рекомендация: компакт остаётся с наблюдательным режимом 5 сессий (§1.6 черновика) + право отката на точные формулировки; усилить акцент в компакте: §0.1.1 «обновление ledger ПОСЛЕ КАЖДОГО пункта, до перехода» (блокирующее, уже есть — поднять жёсткость); владельцу — решить OPEN_QUESTION 1 (порог PZ 10→20 строк).
**Урок (§3.8):** поведенческая эквивалентность НЕ подтверждена замером, но просадки «в моменте» не коррелируют с объёмом промпта: обе руки просели в одних и тех же контрактах (Red Team после edit, Concurrency); разница arm A/B по ledger — стиль ведения сессии, а не формулировка. Полная версия не дала преимущества по 6 из 8 контрактов.
**Урок (промежуточный):** поведенческая эквивалентность измеряется не наличием контрактов в файле, а их срабатыванием в моменте; если arm B покажет те же просадки — компакт ничего не теряет, а полная версия не гарантирует большего.

---

## [2026-08-06] — Exp: protocol-compression — сжатие глобального AGENTS.md (черновик + мех-слой)

**Гипотеза:** сжатие только прозы (объяснения/повторы/примеры) на ~60% без потери поведенческих контрактов («рельсы», §1.19) возможно и сохраняет соблюдение триггеров 1–7. Контракты (пороги, «запрещено без», форматы, таксономии) несжимаемы.
**Ожидание:** объём −55..−65% при 0 потерянных контрактах; поведенческая эквивалентность НЕ проверяется замером — только A/B-прогонами (§1 п.2а: один замер ≠ доказательство).
**Команда:** `python -c "import tiktoken; print(len(tiktoken.get_encoding('cl100k_base').encode(open(f, encoding='utf-8').read())))"` для AGENTS.md и AGENTS.compact.md.
**Сырой результат:**
```
AGENTS.md (текущий):        129705 B | 81702 chars | 35228 tok | 1642 lines
AGENTS.compact.md (дословно): 52838 B | 33384 chars | 14892 tok |  481 lines → −57.7%
AGENTS.compact.md (+мех-слой):53054 B |   —       | 15064 tok |  487 lines → −57.2%
```
**Сверка полноты (мех-слой, Verified по факту файла):** черновик терял/искажал 3 контракта: (1) §5.16 — «Living Memory»-реконструкция заняла номер исторического §5.16 = «Windows subprocess: Popen+communicate+CREATE_NO_WINDOW» (12+ ссылок в дневниках/CHANGELOG/ISSUE/KNOWN_ISSUES указывают именно на него) → восстановлен в §5.16, Living Memory перенесён в §5.24, внутренние ссылки §1.7 п.4/§1.12/§9 п.10 починены; (2) «дыра §5.17–5.18» — не дыра, оба пункта существуют в оригинале (БД/мониторинг), в черновике перенесены в п.11 (внешних ссылок нет — безопасно); (3) порог Phase Zero 10→20 строк — ослабление, оставлено по Триггеру 1 (более новой формулировке), требуется подтверждение владельца (OPEN_QUESTION).
**Вердикт:** ЧАСТИЧНО ПОДТВЕРЖДЕНА (объём): −57.7% достигнуто, контракты возвращены мех-слоем. Поведенческая эквивалентность — ⏳ PENDING: A/B (3–5 задач на обеих версиях, метрика — соблюдение триггеров 1–7) не запускался; первые 5 сессий на компакте — наблюдательный режим с правом отката на точную формулировку.
**Урок:** сжатие поведенческого файла без карты соответствия номеров — тот же риск, что «короткий edit-якорь ест соседний контент» (§9 п.10), только в масштабе документа: черновик «реконструировал» §5.16, не проверив, что номер занят историческим контрактом. Мех-слой (grep по ссылкам на каждый §) обязателен ДО A/B.
**Связь с отрицательными:** новая (вариаций нет); верификация работ: Lost in the Middle (arXiv:2307.03172, TACL 2023) — ✅ Verified, остальные — Recalled.

---

## [2026-08-06] — Exp 6: tree-sitter-language-pack парсеры на Windows (issue #174 блокирует?)

**Гипотеза:** language-pack 1.14.3 НЕ может скачивать парсеры на Windows (issue #174: `No pre-built parsers available for platform 'windows-x86_64'`) → интеграция +56 языков невозможна до следующего релиза.
**Команда:** `python -m venv %TEMP%/tslp_test && pip install tree-sitter-language-pack` → `get_parser('lua')` + 11 других языков + `get_tags_query`; затем интеграция в проект: `MSCODEBASE_LANGUAGE_PACK=true python -c "from src.core import language_pack; print(language_pack.try_enable())"`.
**Сырой результат:**
```
language-pack: 1.14.3
LUA PARSER: OK Language   ← get_parser РАБОТАЕТ на Windows (per-language download)
12/12 тестовых языков: parser OK (lua, elixir, haskell, zig, nim, clojure, v, odin, groovy, julia, perl, crystal)
cache_dir: %LOCALAPPDATA%/tree-sitter-language-pack/v1.14.3/libs
manifest_languages: 371 | languages WITH tags: 71
интеграция: try_enable → enabled: True | langs: 54 | tags: 54 | failed: []
.lua SCM-символы: greet, helper (function_declaration) — чисто
.sol: Bank, deposit, get | .r: greet, compute_mean | .pyx: cy_add, Point.__init__ — чисто
.nix: 0 символов (query есть, captures пусты — честный пусто)
.exs (elixir): МУСОР — 'defmodule', 'ef ', 'ello(' (макро-грамматика: def/defmodule — call-узлы) → elixir исключён из карты
```
**Вердикт:** гипотеза ОПРОВЕРГНУТА (хорошая новость). Per-language download на Windows работает (issue #174 касается только download_all()). Слой интегрирован как optional extra [language-pack] + гейт MSCODEBASE_LANGUAGE_PACK (off по умолчанию): 54 языка, 54 tags-queries, 0 failed.
**Урок:** issue про «нет windows-бандла» ≠ «не работают per-language загрузки» — эмпирическая проверка обязательна; макро-грамматики (elixir) требуют фильтра валидности имён (добавлен: `_VALID_IDENTIFIER_RE`) или исключения.
**Связь с отрицательными:** вариация «371 язык symbol extraction» (Exp 1) — подтверждено 71 tags-язык; новое: парсеры на Windows работают.

---

## [2026-08-05] — Exp 1: tree-sitter-language-pack — «371 язык за 1 день» (проверка ключевого заявления audit.md)

**Гипотеза:** пакет даёт 300+ языков symbol extraction «из коробки» одним pip install; get_parser работает с tree-sitter 0.26; tags.scm присутствуют для большинства языков.
**Команда:** `python -m venv %TEMP%/tslp_venv && pip install tree-sitter-language-pack` → скрипты: подсчёт `manifest_languages()`, `get_tags_query()` по всем 371, парс Python-файла.
**Сырой результат:**
```
manifest_languages: 371
language_count()/available_languages(): 1 (только downloaded)
with non-empty tags.scm: 71 (19%) — 300 языков имеют ПУСТЫЕ tags (bash, clojure, cmake, cobol, ada, actionscript…)
первый парс python: 37.6 s (on-demand скачивание грамматики, кэш 22MB); повторный парс: 0.03 ms
tags.scm для core-языков: python/js/ts/go/rust/java/c/cpp/csharp YES; bash NO
win_amd64 abi3 wheel 2.0MB; требует Python >=3.10; abi3 совместим с 3.14
API: QueryCursor(query).captures(node) → dict {capture_name: [nodes]} (tree-sitter 0.26)
```
**Вердикт:** ЧАСТИЧНО опровергнута. Пакет реален и ставится (2MB wheel + 22MB/грамматика кэш, on-demand), парсинг AST работает, но **symbol extraction через tags.scm есть только у 71 из 371 языка (19%)** — «+350 языков symbol extraction за 1 день» НЕ подтверждено. Для наших 9 core-языков tags-запросы есть (паритет), для shell/context (bash, sql, hcl) — нет. Выигрыш пакета: +62 новых языка с tags-запросами + AST-парсинг 300 языков для чанкинга (без символов/рёбер).
**Урок:** «N языков в манифесте» ≠ «N языков с symbol extraction» — манифест содержит грамматики, tags-запросы — подмножество (19%). Перед интеграцией считать именно язык+tags, а не язык+парсер. Первый парс каждого языка требует сети (37.6s) — для offline/CI нужен prefetch или запечённые грамматики.

---

## [2026-08-05] — Exp 2: извлечение символов — текущий CodeParser vs tags.scm (паритет?)

**Гипотеза:** tags.scm-подход даёт извлечение определений функций/классов не хуже текущего CodeParser (который также строит calls/imports/dataflow).
**Команда:** `venv python -X utf8 experiments/exp2_symbols.py` (src/core/graph.py, 66 defs/classes по regex-граунд-труту)
**Сырой результат:**
```
Ground truth (regex def/class, включая методы): 66
[A] CodeParser init+parse_file: 65 ms | chunks: 69 | symbols: 60 (qualified: Class.method)
[B] tags.scm parse+query: 16 ms | defs: 66
[B] recall vs truth: 100% (missing: [], extra: []) — после коррекции граунд-трута
```
**Вердикт:** подтверждена (паритет). tags.scm извлекает 66/66 определений за 16ms vs CodeParser 60 символов за 65ms — чуть быстрее и полнее по определениям. НО: tags.scm даёт только definition.* / reference.call / name — НЕ даёт imports, dataflow (ASSIGNED_FROM), вызовы с резолвом qualified_name, чанкинг с метаданными. Для замены текущего extract_calls/extract_imports/extract_assignments нужна доп. работа.
**Урок:** tags.scm — готовый drop-in для извлечения определений (дешевле собственного walk), но НЕ полноценная замена CodeParser; оптимально — гибрид (scm для определений + текущий walk для calls/imports/dataflow).

---

## [2026-08-05] — Exp 3: реальная латентность Cypher/impact (проверка «4297ms из лога» в audit.md)

**Гипотеза:** текущая латентность графовых запросов ~4297ms (цифра аудита) — реальность или артефакт?
**Команда:** `CypherExecutor(PropertyGraph(graph.db)).execute(q)` ×3 на живом индексе (6856 nodes / 19969 edges, 8.2MB) + живой MCP-вызов graph_query(action=cypher).
**Сырой результат:**
```
MATCH (n) RETURN count(n):           min=0.3ms avg=4.2ms
MATCH (n:Function) RETURN count(n):  min=0.4ms avg=0.5ms
MATCH (a:Function)-[:CALLS]->(b) count(*): min=3.7ms avg=4.2ms
MATCH … WHERE b.name = '…':          min=4.2ms avg=4.4ms
ORDER BY count(*) DESC LIMIT 5:      min=8.2ms avg=10.1ms
Живой MCP graph_query (cypher):      elapsed_ms = 7.2ms / 12.6ms (rows=0 / rows=1794)
```
**Вердикт:** опровергнута (для графа). Реальная латентность Cypher на 6856 узлов / 19969 рёбер: **0.3–13ms** (прямой вызов) и **7–13ms** (живой MCP round-trip). «4297ms» — вероятно, цифра из старого лога векторного поиска/embedding-первого-вызова, не графа. Наблюдение: имена калл-таргетов — qualified (Analyzer.__init__), запросы по `name = 'x'` должны учитывать это (docs для query_graph).
**Урок:** цифры производительности в audit.md не верифицированы — замер перед сравнением обязателен (§5.15). Графовая латентность уже в классе конкурентов (<10ms).

---

## [2026-08-05] — Exp 4: DECORATES/OVERRIDES — извлекаемость текущими tree-sitter-парсерами

**Гипотеза:** рёбра DECORATES и OVERRIDES (недостающие 2 типа из таксономии DeusData) извлекаемы текущей инфраструктурой без SCIP/LSP.
**Команда:** парс синтетического Python-файла (декораторы + наследование + @override) текущим CodeParser + walk AST на decorated_definition/decorator.
**Сырой результат:**
```
symbols CodeParser: Base.method, Child.method, Child.abstract_method, Child.prop, Child.helper, standalone — БЕЗ свойств-декораторов
AST содержит: decorated_definition (@override/@abc.abstractmethod/@property/@staticmethod), decorator-узлы, class Child(Base) — база видна
```
**Вердикт:** подтверждена (feasibility). DECORATES: узлы decorated_definition/decorator есть в tree-sitter-python — извлечение ~30–50 строк в parser.py (walk decorator → имя → ребро DECORATES). OVERRIDES: вычисляемо по class-иерархии (class Child(Base) в AST) + name-матчинг методов — ~100 строк. Никаких новых зависимостей.
**Урок:** 2 недостающих типа рёбер из таксономии аудита закрываются малым патчем существующего parser.py — это быстрый win, не требует SCIP.

---

## [2026-08-05] — Гипотеза: доступность зависимостей для кандидатов аудита (SCIP, Leiden, cypher-sqlite)

**Гипотеза:** scip-python и cypher-sqlite существуют на PyPI и ставятся pip (заявление audit.md «Быстрый вариант: cypher-sqlite (Python)» и «интегрировать scip-python»).
**Команда:** PyPI JSON API для scip-python, cypher-sqlite, leidenalg, igraph, tree-sitter-language-pack.
**Сырой результат:**
```
scip-python:      HTTP 404 Not Found (НЕ существует на PyPI)
cypher-sqlite:    HTTP 404 Not Found (НЕ существует на PyPI)
leidenalg 0.12.0: есть, win_amd64 abi3 (совместим с 3.14) ✓
igraph 1.0.0:     есть, win_amd64 abi3 ✓
tree-sitter-language-pack 1.14.3: есть, abi3 ✓
```
**Вердикт:** частично опровергнута. SCIP-индексеры для Python на PyPI НЕТ (только отдельные CLI-репозитории Sourcegraph, требуют node/native сборку) — «встроить scip-python как optional backend» требует не-pip установки. cypher-sqlite не существует — не нужен (свой Cypher уже есть). Leiden-стек (leidenalg+igraph) доступен abi3 — community detection реализуем.
**Урок:** audit.md ссылается на пакеты, которых нет на PyPI (scip-python, cypher-sqlite) — «проверить существование пакета до планирования» (§1.14 Verified vs Recalled).

---

## [2026-08-04] — Гипотеза: _distance при cosine-метрике меньше=ближе, LanceDB сортирует ASC

**Ожидание:** для lancedb 0.34.0 + IVF_FLAT cosine `_distance = 1 − cos_sim ∈ [0,2]` (сам вектор = 0.0), строки приходят по возрастанию. Комментарий `engine.py:166` «чем больше, тем ближе» неверен, и `sort(reverse=True)` в fast mode инвертирует топ.
**Команда:** `<ext>/venv/Scripts/python.exe experiments/exp_distance_semantics.py` (temp-таблица, IVF_FLAT metric=cosine, query=[1,0,0,0], тот же путь create_index, что в index_project_runner.py:540)
**Сырой результат:**
```
lancedb version: 0.34.0
=== search([1,0,0,0]) c cosine-индексом ===
  id=q_self   _distance=0.000000
  id=near     _distance=0.006116
  id=orth     _distance=1.000000
  id=far      _distance=1.000000
=== search c default (l2) ===
  id=q_self   _distance=0.000000
  id=near     _distance=0.020000
  id=orth     _distance=2.000000
```
**Вердикт:** подтверждена — `_distance` = 1−cos_sim, порядок ASC, меньше=ближе. Комментарий engine.py:166 и `sort(reverse=True)` (engine.py:791, fast — дефолтный режим search_tools.py:270) неверны. Векторный поиск (157-186), hybrid RRF (513), context_search (885) — корректны, не тронуты. Fix: комментарий + `sort()` + регрессионный тест `test_search_with_mode_fast_sorts_distance_ascending`.
**Урок:** семантика `_distance` — свойство БД, не кода: её нельзя выводить из комментария соседнего кода. Связь с отрицательными: не из таблицы §3.8; метод — реальный lancedb-запрос (не мок). Раньше (EXPERIMENTS_LOG#2026-07-31) аудит полагался на чтение кода → та же ловушка P-002.

---

## [2026-08-03] — Гипотеза: ONNX embedder не поднимается из-за off-by-one путей (не из-за модели/портов)

**Ожидание:** исправление PROJECT_ROOT (parent×3 → parents[3]) в onnx_client/onnx_server вернёт ONNX-режим: сервер найдёт скрипт и модель, /embed вернёт 384-dim.
**Команда:**
```
cd <ext> && PYTHONPATH=<ext> venv/Scripts/python.exe D:/Project/MSCodeBase/.local/onnx_client_check.py
curl -X POST http://127.0.0.1:9876/embed -d '{"text":"тест"}'
```
**Сырой результат:**
```
[1] ensure_server_running: True
[2] embed status=200
[3] dim=384 first3=[0.037, -0.058, -0.041]
ONNX CLIENT PATH: PASSED
```
**Вердикт:** подтверждена — причина в путях: (1) onnx_client искал `…\src\src\core\embedder\onnx_server.py` (задвоенный src), (2) onnx_server искал модель в `…/src/.codebase_models/…` (вместо корня). До фикса: `FileNotFoundError: Model directory not found for: multilingual-e5-small-int8`. Логи сервера: «НЕ УДАЛОСЬ загрузить E5-base ONNX» ×5 за день.
**Урок:** off-by-one пути в `src/core/embedder/` копируются между файлами (onnx_client ← onnx_server) — при работе с путями в src/core/embedder обязателен `parents[3]` или проверка `path.exists()` на всех search_paths (remote_embedder использует get_extension_dir — верно).

---

## [2026-07-31] — P0-3: verify_clean_state.sh --no-clone (CI self-clone убран)

### Гипотеза
Параметризация `verify_clean_state.sh` (флаг `--no-clone` + `$1` = repo URL) убирает self-clone из CI (тестируется checkout раннера), сохраняя единый источник правды: локальный запуск без аргументов = прежний полный клон.

### Команда
1. `bash -n scripts/verify_clean_state.sh` — синтаксис
2. Python `yaml.safe_load` для `.github/workflows/ci.yml` — валидность
3. Локальный прогон `bash scripts/verify_clean_state.sh --no-clone` — не-Linux ветка (Windows)

### Сырой результат
```
SYNTAX_OK (bash -n scripts/verify_clean_state.sh)
YAML_OK — ci.yml jobs.clean-state.steps[-1].run = bash scripts/verify_clean_state.sh --no-clone "${{ github.repository }}"
Локальный прогон --no-clone (Windows): «No-clone mode: verifying current directory» — clone пропущен, ветка выбрана верно; далее падение на venv/bin/* — pre-existing Linux-only assumption скрипта (POSIX-layout venv), не связано с правкой.
Полный pytest tests/: 610 passed, 0 failed (35.25s)
```

### Вердикт: подтверждена
`--no-clone`-ветка выбирается и корректно пропускает clone (работа в текущем каталоге). Локальный ручной запуск без аргументов сохраняет полный клон (default URL). Linux-путь (venv/bin, lockfile gate, install из lock) требует ubuntu-раннера — покрыто bash -n и логикой ветвления, полный CI-прогон выполнит GH Actions.

---

## [2026-07-27] — P0 Fixes: alias injection, layer injection, CI paths, sandbox docstring

### Гипотеза
Четыре P0-бага из протокольного аудита можно исправить минимальными, проверяемыми правками без риска регрессий.

### Команда
1. `edit_file` cypher_sql.py L84 — добавить `re.fullmatch` валидацию alias
2. `edit_file` engine.py L352, L740 — экранировать `layer` через `_escape_sql_value`
3. `edit_file` verify_clean_state.sh — заменить Windows-пути на POSIX
4. `edit_file` codebase_tool.py — синхронизировать docstring с кодом

### Сырой результат
Все 4 правки применены успешно через `edit_file`. Проверка через `read_file` подтвердила корректность каждой правки:
- cypher_sql.py L84: `if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item.alias):` — добавлен
- engine.py L352-356: `_esc = IndexerTableMixin._escape_sql_value(layer)` — добавлен перед f-string
- engine.py L740-742: аналогично для `search_with_mode`
- verify_clean_state.sh: `venv/bin/pip` и `venv/bin/python` — заменены
- codebase_tool.py: docstring переписан, дубликат удалён

### Вердикт: подтверждена
Правки минимальны, точечны, не затрагивают логику — только добавляют валидацию/экранирование.

---

## [2026-07-22] — Audit: P0-1 DebounceBatch deadlock

**Ожидание:** `await self._flush()` вызывается ВНУТРИ `with self._lock` → deadlock при 100 файлах
**Команда:** AST-анализ + ручное чтение rate_limiter.py L154-232
**Сырой результат:**
```
=== DebounceBatch.add() at line 154 ===
  L154:     async def add(self, file_path: str) -> bool:
  L156:         with self._lock:                    # L156 — lock acquired
  ...
  L163:         if batch_full:                       # OUTSIDE lock
  L164:             await self._flush()              # OUTSIDE lock ✓
```
**Вердикт:** подтверждена — `_flush()` вызывается вне lock, deadlock не воспроизводится.

---

## [2026-08-01 22:35] — Гипотеза: HF-truncation 512 гарантирует лимит llama.cpp (n_ctx_train=512)

**Ожидание:** после усечения до 512 HF-токенов llama.cpp посчитает ≤ 512 токенов → HTTP 400 исчезнет.
**Команда:** `_measure_tokens.py` (живой llama-server :8080, /tokenize, 20 реальных длинных чанков: error_handler, modification_guard, db_writer, lsp_project_bridge, rate_limiter, graph, runtime_coordinator, changelogs en/ru/zh) + прогон реиндекса 22:01-22:11.
**Сырой результат:**
```
file                              len   HF512  ->llama  rawllama
docs/zh/CHANGELOG.md              3500    512      502      1860   ← максимум после truncation
docs/zh/CHANGELOG.md              3500    512      475      1822
src/core/error_handler.py         3500    512      479       831
... (все 20 чанков: llama_after_trunc <= 502)
llama_server_stderr.log: E srv send_error: task id = 5977, input (526 tokens) is larger than the max context size (512). skipping
_reindex_err.log: [embed] 4512/4677 ... Chunk 8 failed all retries, zero vector → Embedding failed for chunk 8 after all retries. Aborted.
```
**Вердикт:** ОПРОВЕРГНУТА — запас после HF-512 всего 0-10 токенов (502/512), плотный CJK даёт 526>512 (разные BPE у HF и GGUF). Фикс 48e695b8 не работает.
**Вывод:** гарантия только через нативный `/tokenize` llama-server (лимит 480). Реализовано в remote_embedder.py; реиндекс 22:37→22:47: 4677 chunks, HTTP 400=0, Aborted=0.

---

## [2026-08-02 22:40] — Гипотеза: drop_table+create_table наследует мёртвые фрагменты только при mmap-локе

**Ожидание:** в чистом окружении (без живого mmap-лока процесса) drop_table удаляет физические файлы, и новый create_table имеет ровно 1 фрагмент; наследование версий (INC-6C62) возникает только когда файлы залочены → rmtree/delete молча пропускается.
**Команда:** `python -m pytest tests/test_lancedb_recreate.py -v` (venv расширения, lancedb 0.34.0, Windows).
**Сырой результат:**
```
tests/test_lancedb_recreate.py::test_drop_create_does_not_inherit_fragments PASSED [ 33%]
tests/test_lancedb_recreate.py::test_recreate_table_physical_fresh_table PASSED [ 66%]
tests/test_lancedb_recreate.py::test_close_for_maintenance_releases_handles PASSED [100%]
3 passed in 3.63s
```
**Вердикт:** ПОДТВЕРЖДЕНА — в чистом окружении drop+create даёт 1 фрагмент (наследования нет); корень INC-6C62 — именно залоченные mmap-файлы живого MCP-процесса. Фикс: `recreate_table_physical()` (close → gc → sleep 0.5 → rmtree(ignore_errors=False) → reconnect; PermissionError → fresh path). Полный pytest: 670 passed / 0 failed.
**Вывод:** физическое пересоздание таблицы или fresh-path — единственный надёжный путь; drop+create под живым процессом запрещён (guard: recreate_table_physical централизует все 4 места).


## [2026-08-03] — Гипотеза: Python 3.14 ломает asyncio.get_event_loop() в синхронных потоках проекта

**Триггер §1.7 п.2:** проект работает на Python 3.14.3 (новее training cutoff); §1.9 требует проверки актуальности API по источнику, а не по памяти.
**Ожидание:** официальный changelog подтвердит «get_event_loop() без текущего цикла → RuntimeError»; в проекте найдутся использования в синхронном коде без защиты → латентные поломки инструментов в non-loop потоках.
**Команда:** fetch https://docs.python.org/3.14/whatsnew/3.14.html (секции Removed/Deprecated/asyncio) + grep `get_event_loop|set_event_loop_policy|iscoroutinefunction` в src/ + чтение контекстов.
**Сырой результат:**
```
В Python 3.14: asyncio.get_event_loop() raises RuntimeError if no current event loop,
no longer implicitly creates one. asyncio policy system deprecated (удаление в 3.16).
iscoroutinefunction deprecated → inspect.iscoroutinefunction. from __future__ import
annotations deprecated (после EOL 3.13, 2029). Инкрементальный GC 3.14.0-3.14.4
ОТКАТАН в 3.14.5 (memory pressure). Новое: python -m asyncio ps/pstree PID,
pdb -p PID, pathlib.copy/move, map(strict=), uuid6/7/8.
grep: 15 использований get_event_loop — 14 защищены (async-контекст или except RuntimeError),
1 латентный: error_handler.py:605 sync_wrapper (RuntimeError ловится общим except Exception
→ инструмент вернёт ошибку вместо запуска в non-loop потоке).
```
**Вердикт:** ПОДТВЕРЖДЕНА (частично — 1 из 15 рискован). Фикс error_handler.py:605: get_event_loop() → get_running_loop() + fallback на прямой вызов (поведение идентично ≤3.13 во всех контекстах). 56 passed (error-тесты). Остальные 14 — проверены и безопасны (except RuntimeError есть везде, где нужен).
**Урок:** «get_event_loop() в sync-обёртке» — классический паттерн-ловушка: работал все годы, ломается тихо на 3.14. Guard: новые sync-обёртки используют get_running_loop() с try/except, никогда get_event_loop(). Отдельный урок: verify_diary.py — проверяльщик без собственных тестов; его ложные ❌ шумели в логах при каждом старте MCP (3 бага, exp-16 связан с KNOWN_ISSUES#2026-08-03 23:40). Применимость: audit asyncio-паттернов при бампе рантайма; python -m asyncio pstree <PID> — новый инструмент диагностики зависших async-задач MCP.

---

## [2026-08-03] — Гипотеза: рефлексивное обучение (Reflexion/Self-Refine) применимо к операционной DIS-системе агента через дневники

**Триггер §1.7 п.3:** задача «как сделать агента самообучающимся» (add.md) — сама формулировка есть триггер исследования.
**Ожидание:** академические подходы к самообучению LLM-агентов (вербальная рефлексия, memory augmentation) ложатся на существующие артефакты проекта (AGENT_DIARY, EXPERIMENTS_LOG, KNOWN_ISSUES) без переобучения весов.
**Команда:** fetch arXiv:2303.11366 (Reflexion), arXiv:2303.17651 (Self-Refine), arXiv:2309.02427 (CoALA).
**Сырой результат:**
```
Reflexion (Shinn et al., 2023, arXiv:2303.11366): вербальная рефлексия в episodic
memory → 91% pass@1 на HumanEval; дообучение весов не требуется.
Self-Refine (Madaan et al., 2023, arXiv:2303.17651): итеративный цикл feedback→refine
даёт ~20% абсолютного улучшения (GPT-4, 7 задач).
CoALA (Sumers et al., 2023, arXiv:2309.02427): modular memory = episodic (история
инцидентов) + semantic (правила/паттерны) + procedural (навыки) + working (контекст)
— прямое соответствие AGENT_DIARY/KNOWN_ISSUES/протоколу.
```
**Вердикт:** подтверждена — впитано в личный AGENTS.md: §3.5 (Systemic Generalization Loop), §3.6 (Cross-Domain Analogies), §6.6.2 (мета-проверка паттернов P-###), §6.6.5 (отрицательные результаты), §6.6.8 (Monthly Self-Review), §11 (добродетель «Обучение»).
**Урок:** дневники проекта — это уже CoALA-память; протоколу не хватало только циклов рефлексии (обобщение после фикса, мета-анализ раз в месяц), а не новых артефактов.

---

## 🚫 Отрицательные результаты (не повторять)

| Что пробовали | Почему не сработало | Дата | Связь |
|---------------|---------------------|------|-------|
| scip-python как pip-зависимость (SCIP backend для Python) | Пакета нет на PyPI (404) — только CLI-репозитории Sourcegraph с node/native сборкой | 2026-08-05 | audit.md п.9 |
| cypher-sqlite как готовая Cypher-библиотека | Пакета нет на PyPI (404); свой CypherExecutor уже реализован | 2026-08-05 | audit.md п.2 |
| «371 язык symbol extraction» из tree-sitter-language-pack | Манифест = 371 грамматика, но tags.scm есть только у 71 (19%); 300 языков — AST-парсинг без символов | 2026-08-05 | audit.md п.1 |
| pylint-django как детектор дупликации | Это плагин для Django-фреймворка (типы ForeignKey/Model), а не dup-detector — официальное описание PyPI 2.8.0 (2026-07-11) | 2026-08-08 | audit.md L197 |

---

## [2026-08-08] — Exp: `PropertyGraph.shortest_path` — корректность + латентность (H-PATH)
**Гипотеза:** BFS (graph.py:937) работает на живом графе, медиана <50ms; gap = только отсутствие MCP `graph_query(action="path")`.
**Команда:** `venv/Scripts/python.exe experiments/exp_graph_path.py` (скрипт в experiments/, read-only через API PropertyGraph).
**Сырой результат:**
```
graph: 7247 nodes, 21404 edges
[tool->PropertyGraph (CALLS)] shortest_path('_execute_cypher' -> 'PropertyGraph'): 2 hops
   ...GraphQueryTool._execute_cypher  -[->
   ...graph.py.PropertyGraph  -[CALLS]->
latency_ms: [0.3, 0.14, 0.12, 0.11, 0.09, 0.09, 0.09]  median_ms: 0.11
```
**Вердикт:** подтверждена — 0.11ms медиана (гипотеза <50ms выполнена ×450). Реальный путь найден, структура корректна (source→CALLS→target).
**Урок:** `shortest_path` траverses ТОЛЬКО outgoing-рёбра (`graph.py:974` `WHERE source_id = ?`) — классы/методы без исходящих рёбер недостижимы. MCP-обёртке `action="path"` нужен опциональный `direction="both"` (BFS уже параметризуем). Также: qname-формат `D:.D:/Project/...` — клиенту нужен подсказчик имён (как `find_nodes(name_pattern=...)`).

---

## [2026-08-08] — Exp: Jupyter `.ipynb` = JSON, интеграция без новых зависимостей (H-JUPYTER)
**Гипотеза:** .ipynb разбирается stdlib json (nbformat опционален), code cells подаются в существующий tree-sitter пайплайн CodeParser. Интеграция = extensions.py + ветка в parse_file.
**Команда:** `venv/Scripts/python.exe experiments/exp_jupyter.py`
**Сырой результат:**
```
json.loads 200x: median_ms = 0.0055
cells=5 code_cells=3
  cell 0: 69 chars / 5 lines ...
CodeParser.parsers keys: ['.go', '.js', '.py', '.rs', '.ts', '.tsx']
  cell 0 -> parse_file: 1 chunks, 0 syms, 15.08ms
  cell 1 -> parse_file: 1 chunks, 1 syms, 13.35ms
  cell 2 -> parse_file: 1 chunks, 0 syms, 13.48ms
TOTAL chunks из 3 code cells: 3
```
**Вердикт:** подтверждена — парсинг ~0.006ms, извлечение корректно, существующий пайплайн работает на cell-as-.py (13-15ms/cell). nbformat 5.11.0 существует (PyPI, 2026-08-06), но не нужен.
**Урок:** накладные расходы на ноутбук ~N×13ms (N = code cells) — приемлемо. Замечание: standalone `CodeParser()` загрузил только 6 грамматик (полный набор идёт через другой путь инициализации — язык-пак/окружение) — для .ipynb достаточно python-грамматики + metadata.language_info.name.

---

## [2026-08-08] — Exp: детекция дупликации AST-нормализованными отпечатками (H-DUP)
**Гипотеза:** для 54 языков AST-нормализация (tree-sitter уже есть) + minhash ближних дублей реализуемо stdlib+numpy, без suffix-array движка. fallow: suffix-array покрывает только JS/TS+CSS. pylint-django — НЕ dup-detector.
**Команда:** `venv/Scripts/python.exe experiments/exp_dup.py` (скрипт в experiments/, ~60 строк: tree-sitter листовые токены с плейсхолдерами <id>/<lit>, sha1-группировка точных, minhash-64 8-грамм для ближних).
**Сырой результат:**
```
files=137 functions/classes>=24tokens=401 scan_ms=414.8
EXACT дубликаты: 8 групп
  artifact_paths.py: get_index_dir/get_intelligence_dir/get_metrics_dir/get_commit_memory_dir/get_branches_dir/get_telemetry_dir/get_summaries_cache_dir (7 шт)
  extensions.py: is_supported ~ is_parseable
  resource_monitor.get_global_resource_monitor ~ llama_runner.get_global_runner
  language_pack.lang_for_ext ~ get_parser
  lsp_project_bridge._bridge_path ~ _stale_path
  cypher_ast._UnaryOp ~ _LabelTest
  graph_tools._confirmed ~ _contradicted
  lsp_tools.LspFindReferencesTool ~ LspFindDefinitionTool
NEAR-дубли (minhash>0.85): 1 пара, 0.969 — lsp_tools.LspFindReferencesTool ~ LspFindDefinitionTool; pair_scan_ms=660.8
```
**Вердикт:** подтверждена — 137 файлов за 414.8ms, найдены РЕАЛЬНЫЕ дубли (7 функций get_*_dir — классический copy-paste; LSP-классы-близнецы 0.969). Ноль новых зависимостей (tree_sitter + hashlib уже есть; simhash 2.1.2 существует, но не нужен). pylint-django опровергнут (см. 🚫 таблицу).
**Урок:** порог ≥24 токена и k=8-граммы дают 0 false-positive на этом репо. Для MCP-тула `find_duplicates(threshold)` — готовая схема: index-time (опционально) или on-demand скан ~415ms. Кандидаты: 7×get_*_dir стоит реально отрефакторить в 1 функцию.

---

## [2026-08-08] — Верификация кода (без замеров): H-EDGE / H-LSP / H-TASK
**H-EDGE (edge transparency) — подтверждена:** `Edge.properties` — реальная колонка (graph.py:410), `add_edge` принимает properties и upsert обновляет их (graph.py:736,778), `to_dict` отдаёт (graph.py:329). Теги EXTRACTED/INFERRED = метаданные, **без миграции схемы**. Реальная стоимость: пометить вызовы add_edge/batch_add_edges при создании рёбер + пасс-through в tools (уже через to_dict). Оценка аудита «2-3 недели» завышена на порядок (3-5 дней, а то и меньше).
**H-LSP (type resolution) — закрыт другим путём:** с 2026-08-06 в проекте есть 6 LSP-тулов через basedpyright (src/core/lsp_client.py, src/mcp/tools/lsp_tools.py): lsp_find_references/definition/document_symbols/get_type_info/get_diagnostics/get_code_actions. Живая проверка: `lsp_get_type_info(graph.py:730)` вернул `(parameter) self: Self@PropertyGraph`. USES_TYPE edge объявлен (graph.py:234), но не заполняется — index-time type resolution НЕ нужен: query-time LSP покрывает боль точнее (тот же паттерн, что fallow `--type-aware` — семантика на уровне запроса, не индекса).
**H-TASK (task-shaped) — частично есть:** `intel_get_project_context` — один вызов = снапшот state+index+health+memory+background (server_tools.py: инлайн-регистрация); `graph_query(action="related")` — контекст по нескольким целям через CommitMemory+RelationExtractor. Нет только символьного `get_context(targets=[...])` — это тонкая обёртка. **H-PATH примечание:** class-узлы имеют 0 исходящих рёбер (CodeParser out=0) — DEFINES-связи неполны на уровне class→method; открытая нить для ревью indexer.edge-записи.

---

## [2026-08-08] — Exp: WS3 Late Enrichment — стоимость стадии на реальных чанках

**Гипотеза (Late Code Chunking, ACL 2026):** enrichment ПОСЛЕ retrieval дёшев (<2ms на топ-10) и покрывает ≥2 полей на чанк; imports из metadata чанка доступны.
**Команда:** `python experiments/late_enrichment/bench.py --phase chunks --limit 10` — 8 запросов × 10 реальных чанков проекта, фаза chunks (live недоступна: MCP держит PID-lock).
**Сырой результат:**
```
avg_enrichment_ms: 0.701
avg_tokens_added: 1860.0   (≈186 ток/чанк на топ-10)
avg_coverage: module=1.0, parent_symbol=0.3, chunk_headline=1.0, imports=0.0
```
**Вердикт:** ЧАСТИЧНО ПОДТВЕРЖДЕНА. Латентность пренебрежима (0.7ms), module/headline покрывают 100%. **imports=0.0** — метаданные чанков НЕ содержат импортов (графовые IMPORTS-рёбра есть, но не прикреплены к чанкам) → enrichment импортов требует graph-lookup (и зависимость от consistency — будущая работа). parent_symbol=0.3 — извлечение имени из текста находит не каждый чанк.
**Урок:** chunk-local enrichment (module/headline/symbol) безопасен и дёшев; imports — отдельная стадия с графом. Токен-стоимость ~186/чанк обязана быть в метрике контекста (Context Engine 2.0).

## [2026-08-08] — Exp: Benchmark 2.0 runner — live-фаза vs PID-lock

**Гипотеза:** runner может поднять in-process Searcher при живом MCP (индекс доступен).
**Команда:** `python experiments/benchmark2/runner.py` (MCP запущен, PID 7496).
**Сырой результат:**
```
RuntimeError: PID lock still held by alive pid=7496 after 30.0s — другой процесс пишет в эту БД
[bench2] записано 12 задач -> out/evidence.jsonl
[bench2] manual-проб (нужен ручной прогон): 16
```
**Вердикт:** ОПРОВЕРГНУТА. PID-lock (database_lock.py, 30s, fail-closed) блокирует второй Indexer на ту же БД — это защита, работает как задумано. Runner корректно фолбэчит в manual-режим (16 ручных проб).
**Урок:** live-эвалы против MCP требуют остановленного сервера или отдельного MSCODEBASE_DATA_DIR; документировано в experiments/benchmark2/README.md.

---

## [2026-08-08] — Exp: Multi-window PID-lock 30s wait vs Zed timeout (KNOWN_ISSUES 🟡, WS8 follow-up)

**Гипотеза:** (1) Zed убивает MCP-процесс по таймауту запроса → вечный зомби-цикл; (2) зомби-holder'а (осиротевший живой процесс) можно отличить от здорового MCP по цепочке родителей; (3) create_time-сверка ловит PID-reuse.

**Команда:** см. ниже per-эксперимент; скрипты — `experiments/lock_zombie/` (orphan_holder.py / spawn_orphan.py / zombie_probe.py / check_signals.py).

**Сырой результат (Exp A — реальное состояние lock-файлов, PowerShell):**
```
LOCK: ...index_bot_snow_5e94fc96.db\.write_lock  pid=8148 started=1786135695 age=13,1h
  holder: DEAD (stale -> steal works)
LOCK: ...index_mscodebase_bfe9644b.db\.write_lock  pid=13376 started=1786168629 age=3,95h
  holder: name=python.exe parent_pid=17860 (venvlauncher chain) -> Zed.exe alive -> healthy
```
**Сырой результат (Exp B — контеншн, реальный второй процесс):**
```
RuntimeError: PID lock still held by alive pid=13376 after 30.0s — другой процесс пишет в эту БД
indexer creation (stale-steal path): 1.04s   (свободный/steal lock)
get_status: 0.02s
```
**Сырой результат (Exp C — walk-to-root детекция, zombie_probe.py):**
```
=== HEALTHY (наш MCP 13376) ===
[0] pid=13376 python.exe alive
[1] pid=17860 python.exe alive   (venvlauncher)
[2] pid=11668 powershell.exe alive
[3] pid=18216 Zed.exe alive
VERDICT: HEALTHY (живой Zed в цепочке) -> WAIT
=== ORPHAN (симуляция, holder 22508) ===
[0] pid=22508 python.exe alive
[1] pid=23776 python.exe alive
[2] pid=10740 DEAD
direct_parent_alive=True   <- ловушка: наивная проверка дала бы false-WAIT
live_Zed_in_chain=False; chain_root_dead=True
VERDICT: ORPHAN/ZOMBIE -> STEAL safe
zombie_probe full run: 88 ms
```
**Сырой результат (Exp D — PID-reuse):**
```
Фейковый lock: pid=наш(живой), started=now-3600, role=worker
PID lock held by alive pid=12684, waiting...
FAILED after 1024 ms: PID lock still held ... after 1.0s   <- текущий код НЕ ловит
zombie_probe: holder pid=12684 alive=False -> STALE  (после выхода скрипта)
```
**Вердикт:** (1) ПОДТВЕРЖДЕНА-с-уточнением — из исходников Zed (client.rs): `DEFAULT_REQUEST_TIMEOUT=60s` на каждый JSON-RPC запрос; процесс НЕ убивается при таймауте (Drop→kill только при остановке сервера, stdio_transport.rs). Вечный цикл = осиротевший живой python.exe (venvlauncher double-process) держит lock. (2) ПОДТВЕРЖДЕНА: walk-to-root (≤8 уровней, ~88ms) различает HEALTHY (Zed alive→wait) / ORPHAN (корень мёртв→steal); direct-parent-проверка даёт ложный WAIT (ловится). (3) ПОДТВЕРЖДЕНА: create_time-дельта ловит фейковый started (3600s), текущий `_is_pid_alive` — нет.

**Урок:** 30s-ожидание + fail-closed — защита «один писатель», но без детекции сирот она превращает осиротевший процесс в вечный цикл падений (инцидент WS8 08:52-08:57 — это ручной taskkill решал). Индустрия: PostgreSQL postmaster.pid хранит start timestamp именно для stale-детекции; Zed даёт 60s/запрос, поэтому 30s wait формально «в бюджет влезает», но UX = 30s-блокировка + ошибка. Находка: psutil импортируется в layer.py/lsp_project_bridge.py, но НЕ объявлен в pyproject и НЕ установлен в venv — тихая деградация runtime.

---

## [2026-08-08] — Exp: WS9 benchmark before/after (self-healing PID-lock, вариант C)

**Гипотеза:** после внедрения классификации holder'а (DEAD/HEALTHY/ORPHAN/AMBIGUOUS) время acquire для orphan-кейса падает с ~30s (ожидание+RuntimeError) до сотен мс (terminate+steal), healthy-кейс — мягкая ошибка через ~8s (дефолт) вместо 30s RuntimeError; free/stale не деградируют.

**Команда:** `python experiments/lock_zombie/benchmark_selfhealing.py` (venv расширения, Windows).

**Сырой результат (after):**
```
[free (no contention)] 7 ms | acquire ok
[stale-holder (dead pid)] 31 ms | steal ok
[healthy-holder (wait=1.5s)] 1512 ms | LockBusyError: PID lock still held by alive pid=... after 1.5s — база занята другим окном MCP; retry позже (holder не тронут)
[orphan-holder (terminate+steal)] 120 ms | acquired pid=...
```
**Before (та же сессия, старый код):** контеншн = 30.0s → RuntimeError (замерено в Exp B); orphan-кейс не детектился (30s → RuntimeError); free ~9ms; stale ~33ms.

**Вердикт:** ПОДТВЕРЖДЕНА. orphan: 30000ms → 120ms (terminate+steal, вкл. TerminateProcess реального python + ретрай-unlink); healthy: 30000ms RuntimeError → 1512ms LockBusyError (wait=1.5 в бенче; прод-дефолт 8.0s); free/stale без изменений (7/31ms). Дополнительно verified: после TerminateProcess реального python'а venvlauncher-обёртка умирает сама (никаких висящих процессов), lock перезаписывается нашим PID.
**Урок:** (1) TerminateProcess синхронный, но файловый дескриптор lock'а умирающего процесса даёт PermissionError на unlink → нужен _unlink_with_retry (иначе краш в кейсе «только что убитый holder»); (2) venvlauncher: lock пишет РЕАЛЬНЫЙ python (os.getpid() внутри скрипта), terminate по pid из lock убивает именно держателя, обёртка умирает следом — прод-механизм работоспособен.

---

## [2026-08-08] — Exp: Multi-Tool (MSCodeBase, 4-5 вызовов) vs Context Engine (CodeGraph-стиль, 1 вызов)

**Гипотеза:** единый контекстный агрегатор (get_edit_context-стиль) побеждает последовательные MCP-вызовы по tool_calls (N→1), latency (1 RT vs N), tokens (при intent-фильтре), при паритете task success; wrong-context решается intent-фильтрацией. Контрольная группа: ОДНА кодовая база (MSCodeBase), 4 задачи на реальных символах, отличаются только стратегии оркестрации. CodeGraph (Rust) не устанавливался — иначе сравнение смешало бы «качество индекса» с «архитектурой инструментов».

**Команда:** `python experiments/context_engine/compose_eval.py` (данные: strategy_a_data.json — реальные ответы MCP 2026-08-08, тайминги из intel_execution_timeline; B-v2 = compose source+symbols(+memory+git по intent), symbols во всех intent).

**Сырой результат:**
```
task        strat   calls tokens   latency_ms facts                 success  wrong%
T1-explain  A       5     423      2481       ...                  86%      15%
T1-explain  B       1     266      501        ...                  71%       0%
T2-modify   A       5     460      6755       ...                 100%      15%
T2-modify   B       1     389      502        ...                 100%      16%
T3-debug    A       4     435      2118       ...                 100%       9%
T3-debug    B       1     350      501        ...                 100%       0%
T4-test     A       4     300      6358       ...                  67%      23%
T4-test     B       1     300      501        ...                  67%      36%   <- B-v1 (test без symbols): 33%/59%
AVG calls    A=4.500  B=1.000   Δ=-78%
AVG latency  A=4428   B=501     Δ=-89%
AVG tokens   A=404.5  B=326.4   Δ=-19%
AVG success  A=88.1%  B=84.5%   Δ=-3.6pp (разрыв = артефакт рубрики T1: "enrich" только в git-сообщении)
AVG wrong    A=15.5%  B=13.0%   Δ=-2.5pp (B лучше: dedup убрал шум упавших вызовов)
```

**Вердикт:** ПОДТВЕРЖДЕНА (все 5 пунктов гипотезы, с оговорками):
- tool_calls: N=4.5 → 1 (−78%), latency agent-facing: 4428ms → 501ms (−89%) — выигрыш по построению, подтверждён замером.
- tokens: с intent-фильтром B меньше даже без учёта round-trip промпта (−19%); «сырой» агрегатор (все секции) ≥ суммы вызовов.
- task success: паритет (84.5% vs 88.1%); B-v1 (test БЕЗ symbols) падал до 33% — intent-фильтр обязан ВСЕГДА включать source+symbols (callers), как у реального CodeGraph get_edit_context.
- wrong-context: B-v2 13.0% < A 15.5% — dedup+отсутствие упавших вызовов чище; глобальная память проекта (55 ADR) ≈ 0 реколл для задачи «тест» → CodeGraph memory_context ФАЙЛ-скоуп, у нас — проектный (находка).

**Побочные наблюдения (реальные данные сессии):**
1. impact_analysis вернул «not found» для 2/4 символов (_expand_graph_context, intel_code_topology — приватные/не в индексе) → 2 мёртвых вызова в A (соль в wrong 15-23%).
2. get_symbol_info для build_call_graph вернул НЕВЕРНОЕ определение (experiments/run_experiment_pagerank.py:40 вместо src/core/indexing/symbol_index.py:480) — символ-тень эксперимента скрывает реальный; multi-tool требует доп. поиска (wrong-definition кейс).
3. CodeGraph README: 42 community tools (не 45 — расхождение в их же README), --profile=core (8 tools) для сужения поверхности — паттерн «tool surface inflates prompt cost» признают и они.

**Урок:** (1) архитектура «1 контекстный инструмент с серверной композицией» валидна и для MSCodeBase: −78% вызовов, −89% latency, −19% токенов при паритете полноты; (2) критично: compose ОБЯЗАН включать source+symbols во все intent; (3) файл-скоуп памяти (а не глобальный ADR-список) — условие полезности memory-секции в edit-контексте; (4) impact_analysis «not found» на приватных функциях = тихий провал multi-tool стратегии.

---

## [2026-08-08] — Exp D (v2): Context Composition vs Tool Composition — Where Does the Latency Actually Come From?

**Гипотеза (v2):** (1) выигрыш агрегатора — в round-trips и agent-facing latency, НЕ в серверной работе (compose ≈ тем же операциям + overhead); (2) полнота (recall) C ≥ A при правильном составе секций; (3) wrong-evidence (дефекты impact_analysis/build_call_graph) одинаково бьют по всем рукам; (4) при подтверждении — вариант А реализуем в прод.

**Команда:** `MSCODEBASE_ALLOW_SELF_INDEX=1 venv/Scripts/python.exe experiments/context_engine/bench_v2.py`
15 задач × 9 классов (find_bug_cause/modify/impact/architecture/test/git/caller-callee/prepare/verify), ground-truth required-facts, 4 руки: A (реальные MCP-вызовы, latency из intel_execution_timeline) / B (compose-модель, intent-фильтр) / C1 (СУЩЕСТВУЮЩИЙ get_context — GetContextTool, реальный in-process на snapshot БД) / C2 (РЕАЛЬНЫЙ get_edit_context: EditContextEngine — GetSymbolInfoTool+ImpactAnalysisTool+SearchCodeTool fallback+source+git+memory, in-process). PID-lock живого MCP обходится snapshot-копией артефакт-БД (та же реальная БД, temp, .write_lock удалён). Readiness-гейт — патч как в тестах проекта.

**Сырой результат (AVG, 15 задач):**
```
              round_trips  tokens  agent_ms  server_ms  recall  prec  wrong  dup
A (multi-tool)    3.400    241.3   1582.6    1582.6     0.783  0.667 0.090  0.135
B (compose model) 1.000    276.5    400.0*       0.0     0.833  0.663 0.098  0.164
C1 (get_context)  1.000    637.1    449.2       49.2     0.267  0.600 0.133  0.000
C2 (get_edit_context)     1.000   1230.6    865.3      465.3     0.817  0.705 0.108  0.184
* B agent_ms — модель 1 RT (400ms, реальный медианный).
```

**Вердикт:** ПОДТВЕРЖДЕНА (все 4 пункта):
1. **Latency-декомпозиция:** agent-facing: A=1583ms (3.4 RT, Σ реальных server-латентностей, включая 5.3s search_code на T5) vs C2=865ms (1 RT + 465ms реальной серверной работы: symbol-index + fast-search fallback + git + чтение файла). Выигрыш = round-trips (N→1) + дешёвые точечные запросы вместо семантического поиска. C2 server_ms < A server_ms даже в лобовом сравнении.
2. **Полнота:** C2 recall=0.817 > A=0.783, precision=0.705 > 0.667 (fallback search_code при пустом gsi закрыл inline-tools: intel_trigger_reindex, notify_change). C1 recall=0.267 — СУЩЕСТВУЮЩИЙ get_context недостаточен (только symbol_info+impact, нет source/git/memory/fallback).
3. **Wrong-evidence:** дефект «get_symbol_info для build_call_graph возвращает тень experiments/run_experiment_pagerank.py:40» штрафует ВСЕ руки (A wrong=0.09, C2=0.108; T7 wrong=1.0 у всех, секция целиком отравлена). Реальный фикс — не «починить get_symbol_info», а guard в агрегаторе: отбрасывать определения из experiments/ (scaffolding) или сверять файл определения.
4. **Токены — точка напряжения:** C2 без token budgeting = 1231 vs A=241 (source-окно 80 строк + fallback). B (intent-фильтр, CodeGraph-стиль) = 276 токенов при recall 0.833 — лучший recall при минимуме токенов среди 1-RT рук. Вывод: агрегатор обязан иметь токен-бюджет (intent + обрезка секций), иначе побеждает по round-trips/latency, но проигрывает по токенам.

**Итерации методологии (§1.8):** v2.0 wrong_rate не ловил wrong-секции с корректными фактами → штрафуется всегда (ложная уверенность опаснее отсутствия); v2.1 source-окно цепляло docstring/call-site (walk-up от декоратора попадал в чужую def) → Pass A (def с именем) + Pass B (walk-DOWN); v2.2 fallback search_code при пустом gsi (символ вне графа).

**Урок:** (1) «1 контекстный инструмент» побеждает по round-trips/latency и паритету-превышению полноты ТОЛЬКО при составе: source+symbols+fallback+git+memory и токен-бюджете; (2) существующий get_context (C1) — урезанный агрегатор: recall 0.267 против 0.817 у полного — его расширение (не новый tool с нуля) — путь к варианту А; (3) wrong-context guard в агрегаторе (отсев определений из experiments/) дешевле и надёжнее фикса самого get_symbol_info; (4) PID-lock + snapshot-копия БД — рабочий паттерн изоляции экспериментов от живого MCP (никаких taskkill).

---

## [2026-08-08] — Exp D v3: 30 задач — устойчивость B vs C2 (токены решают, recall паритет)

**Гипотеза (v3, по решению владельца):** разница B vs C2 на 15 задачах может быть шумом (доверительный интервал перекрывает). Нужен прогон на 30 задачах: если recall паритетен, а токены у B стабильно ниже — решаем в пользу B-подхода (intent-фильтр), не полного C2.

**Команда:** `MSCODEBASE_ALLOW_SELF_INDEX=1 venv/Scripts/python.exe experiments/context_engine/bench_v2.py tasks_v3.json` (30 задач: 15 из v2 + 15 новых; 4 новых символа с реальными MCP-вызовами: trigger_async_reindex, get_active_reindex_job_id, RuntimeCoordinator, _reject_self_index_target; paired-статистика добавлена в bench_v2.py).

**Сырой результат (AVG, N=30):**
```
              round_trips  tokens  agent_ms  server_ms  recall  prec  wrong  dup
A (multi-tool)    3.367    246.0   1558.7    1558.7     0.875  0.748 0.045  0.197
B (compose-model) 1.000    274.9    400.0*       0.0     0.900  0.748 0.049  0.209
C1 (get_context)  1.000    581.8    428.7       28.7     0.288  0.700 0.067  0.000
C2 (get_edit_context)     1.000   1254.6    805.3      405.3     0.875  0.784 0.054  0.315
* B agent_ms — модель 1 RT (400ms).

=== PAIRED B vs C2 (N=30) ===
recall     mean_delta(B-C2)=+0.025  sd=0.152  CI95=±0.054  B>recall: 2/30  C2>recall: 1/30
precision  mean_delta(B-C2)=-0.036  sd=0.132  CI95=±0.047  B>precision: 5/30  C2>precision: 17/30
tokens     mean_delta(B-C2)=-979.8  sd=695.9  CI95=±249.0  B>tokens: 0/30  C2>tokens: 30/30
```

**Вердикт:** ГИПОТЕЗА v2-владельца ПОДТВЕРЖДЕНА — recall у B и C2 статистически НЕРАЗЛИЧИМ (mean Δ=+0.025, CI95 ±0.054 перекрывает 0; ничьи в 27/30 задач), precision C2 направленно выше, но не значимо (CI включает 0), токены у B стабильно ниже на ~980 (CI95 ±249 — далеко от 0; B дешевле в 30/30 задач). Итог по 30 задачам: **B-подход (intent-фильтр) = оптимальная точка** — recall 0.900 ≥ A 0.875 при 1 RT (vs 3.37) и 275 токенов (≈ A). C1 (существующий get_context) по-прежнему recall 0.288 — требует расширения. C2 не нужен целиком: его выигрыш по precision (+0.036) не окупает +980 токенов.

**Урок:** (1) на выборке 15 задач разница 0.833 vs 0.817 — шум: подтверждено CI на 30 (0.025 ± 0.054); решения об архитектуре контекста принимать на ≥30 задач с paired-анализом; (2) решает не «сколько секций собрать», а «какие секции включить по intent» — B (source+symbols по intent, без impact для git-задач и т.п.) даёт максимум полноты при минимуме токенов; (3) dup_rate C2=0.315 — fallback search_code дублирует symbol-инфо: в прод-агрегаторе нужен dedup. Дефекты D1-D3 зафиксированы в KNOWN_ISSUES (🟡), фикс после повторного прогона.

---

## [2026-08-08] — Контрольный прогон v3 после фикса D1-D3 (wrong_rate 0, C1 recall +32%)

**Гипотеза:** фикс корня D1-D3 (неранжированный nodes[0] → _find_nodes_flexible union + _pick_best_node + union-старты + _is_one_off_script) убирает отравление контекста тенями experiments//scripts/ и placeholder'ами и поднимает качество живых рук C1/C2; A/B (записанные до-фиксовые данные) — контроль «до».

**Команда:** `MSCODEBASE_ALLOW_SELF_INDEX=1 venv/Scripts/python.exe experiments/context_engine/bench_v2.py tasks_v3.json` (после фикса; C1/C2 — живой in-process код с фиксом).

**Сырой результат (AVG, N=30, до → после фикса):**
```
                recall          precision       wrong_rate       tokens
C1 (get_context) 0.288 → 0.380   0.700 → 0.800   0.067 → 0.000   582 → 975
C2 (get_edit_context) 0.875→0.883 0.784 → 0.819  0.054 → 0.000   1255 → 1427
A/B — без изменений (записанные pre-fix данные)
Paired B vs C2: recall Δ=+0.017 (CI95 ±0.052, неразличимы), precision C2 19/30,
tokens B −1152 (CI95 ±315, 30/30) — вывод B-оптимальности НЕ изменился.
```

**Вердикт:** ПОДТВЕРЖДЕНА. wrong_rate 0.000 у C1/C2 (тень build_call_graph больше не отравляет секции; T7 wrong 0.993→0.0), C1 recall +0.092 (D2: методы резолвятся), precision вырос. Реальная проверка: build_call_graph → def=src/core/indexing/symbol_index.py:481 (было experiments/run_experiment_pagerank.py:40), callers=9 реальных прод-потребителей (без скриптового main). Полный pytest 1021 passed, ruff src/ tests/ = 0.

**Урок:** (1) корень D1-D3 ОДИН — неранжированный выбор узла при наличии одноимённых (тень/placeholder/реальный); (2) CALLS-рёбра при индексации привязываются к первому exact-матчу — реальные callers могут лежать на тени: исключать тень из стартов НЕЛЬЗЯ (теряются callers), фильтровать нужно на уровне записей по файлу вызывающего; (3) wrong-evidence guard «отсев experiments/» на композиции (вариант из v2) оказался НЕ нужен — правильный фикс в адаптере дешевле и чище.

## [2026-08-11] — Exp: Multi-RAG Component Ablation (Experiment 1, N=30, v2)

**Гипотеза:** Multi-RAG (Vector+BM25+FTS5+Graph+rerank) > Single-RAG по evidence-recall на задачах о кодовой базе (статья «AI-Native Second Brain»); каждый компонент даёт инкрементальный вклад; graph силён на задачах связей; BM25 и FTS5 избыточны.
**Ожидание:** full/quality recall > fts5_only; BM25, FTS5, Graph дают положительные парные Δ; graph_only recall максимален на klass ∈ {find_caller_callee, find_impact}; FTS5 ≈ BM25 (избыточность).
**Команда:** `venv/Scripts/python.exe experiments/context_engine/multi_rag_ablation.py tasks_v3.json` — 30 задач × 12 рук; изоляция компонентов monkey-patch'ем методов Searcher (`_bm25_search_async`/`_vector_search_async`/`_fts5_search_async`/`_expand_graph_context`/`_apply_multi_reranker_async`); `expand=False`; кэш эмбеддингов очищается per-arm (см. «Урок 1»). Дизайн: experiments/context_engine/multi_rag_design.md. Лог: experiments/context_engine/multi_rag_full_run_2026-08-11.log.
**Сырой результат (AVG по 30 задач):**
```
recall      vector=0.167 bm25=0.694 fts5=0.825 graph=0.357 vbm25=0.597 vfts5=0.783
            bm25fts5=0.817 vbm25fts5=0.775 full_norerank=0.775 quality=0.756
precision   vector=0.083 bm25=0.791 fts5=0.523 graph=0.441 quality=0.719
tokens      vector=1360 bm25=1774 fts5=2327 graph=122 quality=1862
latency_ms  vector=122 bm25=298 fts5=110 graph=12 quality=1704

PAIRED (Δ, CI95, wins/30):
BM25 over Vector:   recall +0.430 ±0.164 (21/30) | prec +0.531 (26/30) → SIGNIFICANT
Vector over BM25:   recall −0.098 ±0.086 (1/30)  | prec −0.177 (1/30)  → вредит
FTS5 over V+BM25:   recall +0.178 ±0.097 (13/30) | tokens +375 (29/30) → значим recall
Graph over V+BM25:  recall +0.000 (enrichment = metadata, не текст) → ~0
Rerank over full:   recall −0.019 (3/30) | prec +0.147 ±0.061 (22/30) | tokens −301 → значим precision
BM25 vs FTS5:       recall Δ −0.131 (FTS5 12/30) | prec +0.268 (BM25 24/30) | tokens −553 (BM25 26/30)

graph_only recall by klass: find_caller_callee 0.625, find_impact 0.583, modify_function 0.500,
understand_architecture 0.500, verify_change 0.500, find_bug_cause 0.300, prepare_change 0.237,
find_test 0.125, git_history 0.000
```
**Вердикт:**
- **H1 (Multi-RAG > Single по recall): ❌ ОПРОВЕРГНУТА** — fts5_only 0.825 ≥ full_no_rerank 0.775 / quality 0.756 (13 задач, где FTS5-одиночка лучше, против 5 у full). Multi-RAG подтверждён только по precision (quality 0.719 vs fts5 0.523, wrong_rate 0.033→0.050 — реранкер добавляет точность ценой минимального recall).
- **H2 (инкрементальные вклады): ⚠️ ЧАСТИЧНО** — BM25 над vector +0.430 ✓; FTS5 над V+BM25 +0.178 ✓; graph-enrichment 0.000 ✗ (добавляет metadata callers/callees, которую evidence-метрики не видят); vector над BM25 −0.098 ✗ (разбавляет чистые BM25-хиты через RRF).
- **H3 (graph на задачах связей): ✅ ПОДТВЕРЖДЕНА** — graph_only recall максимален на find_caller_callee (0.625) и find_impact (0.583), минимален на git_history (0.000); при 12ms и 121 токене (дешевле всех в 5-10 раз).
- **H4 (токены монотонны): ⚠️ ЧАСТИЧНО** — не монотонно: graph добавляет ~0 токенов, реранкер режет −301.
- **H5 (BM25≈FTS5 избыточны): ❌ ОПРОВЕРГНУТА** — FTS5 даёт +0.178 recall над V+BM25 (CI95 ∌ 0); профили противоположны: FTS5 = recall-max (0.825), BM25 = precision/токен-эффективность (0.791 / 1774).
**Урок:** (1) production-баг `hybrid_search_async` (engine.py L521-541): на кэш-хите эмбеддинга dense-поиск пропускается — vector-тир молча исчезает при повторных запросах; первый прогон абляции полностью искажён (vector_bm25 == bm25_only 30/30, vector_only пуст на повторных символах 15/30). Изоляция кэша per-arm обязательна для абляций. (2) vector-тир (llama.cpp multilingual-e5-small) — слабейший на символьных задачах (0.167 recall); recall несут keyword-тиры, precision покупается реранкером. (3) graph-ценность живёт в метаданных (callers/callees), не в тексте чанков — evidence-метрики по паттернам текста её не измеряют; нужен отдельный протокол оценки graph-вклада (или чтение metadata в секции).
**Связь с отрицательными:** первый прогон (без изоляции кэша) — артефакт кэш-бага, не повторять без фикса (результаты в multi_rag_full_run_2026-08-11.log содержат оба прогона; валиден второй).

## [2026-08-11] — EXP-6: VC/Merkle vs Verify-On-Read — симуляция логической границы (dev.to, unitbuilds)

**Гипотеза:** (а) консистентностный валидатор (хэш структуры + отсутствие конфликтов записи) принимает внутренне-консистентную семантическую ложь; (б) «эмпирическое доказательство превосходства Verify-On-Read» можно публиковать как железобетонное пруф.
**Ожидание:** вывод скрипта — «VC принял 2 лжи, VOR — 0».
**Команда:** `python experiments/experiment_concurrency_vs_semantic.py`
**Сырой результат:**
```
Arm VC (Live VC + Merkle): Accepted 2 hallucinated lies as truth.
Arm Verify-On-Read: Accepted 0 hallucinated lies as truth.
```
**Вердикт:** гипотеза (а) ✅ ПОДТВЕРЖДЕНА — но только ЛОГИЧЕСКИ, по построению (тавтология, не замер): Arm VC по определению не получает семантических данных, Arm VOR получает ground-truth список импортов прямо в аргументы. Гипотеза (б) ❌ ОПРОВЕРГНУТА как фрейминг: «эксперимент» не фальсифицируем — результат зашит в определения валидаторов. Уязвимости для оппонента: (1) confound — разные входные права у рук; (2) ground truth захардкожен экспериментатором (самая сложная часть задачи решена заранее — если бы список правды существовал, валидатор не нужен); (3) VOR показан всемогущим — не моделируются слепые зоны (ложь про реальный импорт, утверждения без кодового якоря, runtime/конфиг/внешние сервисы); (4) strawman-риск — оппонент может сказать «мой стек тоже проверяет AST».
**Урок:** сильный вывод здесь НЕ требует симуляции: «консистентность (VC/Merkle) ≠ семантика; нужен внешний слой grounding (AST/runtime/мир)». Симуляция — хорошая иллюстрация, плохое доказательство. Публиковать с честными оговорками (см. §1.6: гипотеза без фальсифицируемости = иллюстрация, не эксперимент).

## [2026-08-11] — EXP-7: Adversarial probe базового VC/VOR-эксперимента (6 атак, Red Team §1.16)

**Гипотеза:** базовый вывод «VC=2 лжи, VOR=0» — не закон, а артефакт входных прав и настройки сценария; VOR на anchor-гранулярности имеет собственные FP; VC имеет уникальное покрытие (конфликты, staleness), которого у VOR нет; VC и VOR — комплементарные слои.
**Команда:** `python experiments/experiment_concurrency_vs_semantic_attacks.py`
**Сырой результат (метрики per-attack):**
```
A1a baseline VC:             FP=2 FN=0  (VC без семантических входных данных)
A1b hybrid VC+semantics:     FP=0 FN=0  (равные права: семантика доступна обеим рукам)
A2 VOR, ложь про реальный импорт: FP=1  (duckdb «for analytics», реально CSV-парсер)
A3 VOR без кодового якоря:  UNCHECKABLE — любая политика даёт FP или FN
A4a VC, косметическое изменение: FN=1  (page-level хэш слишком груб)
A4b VC под конфликтом записи: REJECTED (ловит lost write); VOR к нему слеп
A5 VOR на отравленном truth-листе: FP=1 (stripe из README-примера, не код)
A6 мутация сценария (writers=1): FP=0 FN=1 — «VC принимает ложь» переворачивается
```
**Вердикт:** ✅ ПОДТВЕРЖДЕНА. Базовый результат — артефакт: при равных входных правах гибрид даёт 0 лжи (A1); при мутации VC начинает отвергать правду (A6). VOR не всемогущ: anchor-гранулярность пропускает ложь про реальный импорт (A2), не покрывает утверждения без якоря (A3), деградирует на отравленном truth-списке (A5). VC даёт уникальное покрытие (lost write, конфликт, A4b), но page-level хэш слишком груб (A4a: косметика → ложное отвержение истины). Решает наличие внешнего grounding-слоя + консистентностный слой + качество извлечения якорей — а не выбор «VC или VOR».
**Урок:** перед публикацией «пруфа» — атаковать собственный эксперимент мутациями сценария: вывод, который рушится при изменении ОДНОЙ переменной (A6), — иллюстрация, не закон. VOR на гранулярности «якорь ∈ импорты» — нижняя граница возможностей; реальная семантика требует usage-уровня.
