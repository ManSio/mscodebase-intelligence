# KNOWN ISSUES — MSCodeBase Intelligence

> Синхронизируется из `AGENT_DIARY.md` при каждом [🏁 ИТОГ].
> Формат: дата | что было | статус | fix

---

## 2026-09-28 — Ретриевер-замеры без сброса реранкер-кэша недействительны (Open)

- **Правило:** все retriever-замеры и A/B-тесты — только в свежем процессе либо с явным сбросом реранкер-кэша (`Searcher._reranker_cache.clear()`). Ключ кэша включает текст запроса (engine.py:1646): повтор того же запроса в том же процессе отдаёт закэшированные скоры, а не измеряет код.
- **Эвристика void-замера:** wall <2s на `hybrid_search_async` при ожидании полного пайплайна (embed+BM25+FTS+rerank) = подозрение на cache hit; сверяться с `Searcher._last_rerank_timing` (пусто = реранкер не работал). Холодный FTS-билд (~2.5s) — обратная ловушка: ПЕРВЫЙ замер в свежем процессе молча теряет FTS-тир (2s `wait_for`), нужен discarded warm-up на чужом запросе.
- **Статус:** 🟡 Open (процедурное правило; guard-скрипт `scripts/o1_holdout_gate.py` — fresh-process + warm-up + void-флаг).

**21 entries** — compressed per §4.8 R3 (conclusion-first; dedup 2026-09-08, 2026-09-21). Closed entries moved to docs/archive/KNOWN_ISSUES_2026_09.md on 2026-09-27 (R1 size guard; second batch on merge experiment/4a-unit-of-return).

## 2026-09-27 — Import-time os.environ mutation in scripts breaks xdist workers (Fixed)

- **Симптом:** 6 plugin-тестов (`test_plugins_subprocess/registry`) падали под `-n auto` с `ModuleNotFoundError: No module named 'src'` в runner-subprocess, серийно (`-n0`) — зелёные.
- **Root Cause (Verified, бисекцией до чанка из 24 файлов):** `scripts/f5_judged_run.py` делал `os.environ.setdefault("PYTHONPATH", <EXT>)` на уровне импорта; импорт модуля в `tests/test_f5_judged_verdict.py` загрязнял весь xdist-воркер, и `setdefault(PYTHONPATH)` в `proxy.py` становился no-op с мусорным значением.
- **Fix:** side effects переехали в `_ensure_importable()`, вызываемую только из `if __name__ == "__main__"`. T3: аналогичный паттерн есть в `benchmark_search_stages.py`, `f5_retrieve_arms.py`, `live_search_audit.py` — ни один не импортируется тестами, не трогали.
- **Правило-ловушка:** скрипты с import-time мутацией `os.environ`/`sys.path` нельзя импортировать в тестах — только через `__main__`-guard.
- **Статус:** ✅ Fixed.

## 2026-09-27 — F5 judge verdict parsing takes first regex match (Open)
- **Локация:** `scripts/f5_judged_run.py:238-246` (`_parse_verdict`): сначала первый regex-матч `"verdict"\s*:\s*"?(correct|incorrect|uncertain)"?`, иначе первое вхождение в порядке (incorrect, correct, uncertain).
- **Симптом / риск:** Haiku-style самокоррекция судьи («incorrect… actually correct, final answer: correct») оценивается по ПЕРВОМУ слову — вердикт инвертируется. Fallback-порядок (incorrect перед correct) корректен как подстрока-защита, но не как семантика: первое упоминание ≠ финальное решение. Ошибка тихая (verdict всегда парсится, `uncertain` по умолчанию недостижим при любом упоминании).
- **Аудит (2026-09-27, выполнено при записи):** `experiments/4A_unit_of_return/results/f5judged/judged_raw.json` (sha256 `4be6d79d2012a5c5…`, 16 запросов × 4 плеча × 10 trials = 640 answers): ответов с ≥2 verdict-словами (correct/incorrect/uncertain, границы слов, case-insensitive) — **0**; с ≥1 — **0** (reader-ответы: «I don't know» / код, verdict-слов не содержат). Латентный риск на текущих данных не сработал, но сырого текста судьи в judged_raw.json НЕТ (только reader answers + распарсенные verdicts) — самокоррекцию судьи задним числом проверить нечем.
- **Fix options (решение владельца):** (a) писать judge raw text в judged_raw.json + парсить explicit-final (последний матч / маркер «final verdict:»); (b) решить first/last/explicit-final как контракт парсера и зафиксировать тестом с самокоррекцией pos/neg; (c) минимум: warning-счётчик ответов с ≥2 verdict-строками в агрегатор.
- **Backfill (2026-09-27, выполнено):** judge-CoT восстановлен из `opencode.db` (ro) → `results/f5judged/judged_cot_backfill.json` (sha256 `834ae07a…`, скрипт `scripts/reconstruct_judge_cot.py`, уровень qid — trial-джойн невозможен). 1014 сессий, колебаний `has_flip` 61/1014 (6.0%), пик F5S-10 25/60 при вердиктах 30/30. Проверки: count 1014/1014, unmatched 0, reader-negative-control чист, 3/3 ручных сверки байт-в-байт.
- **Fix (2026-09-27, выполнено):** explicit-final контракт в `_parse_verdict` — последний JSON-матч, иначе последнее verdict-слово (было: первый матч + порядок incorrect>correct). Замер на backfill: last==final 842/1014 (было 820), на 61 flip 53/61 (87%) против 34/61 (56%) у first. Явный маркер `final verdict:` в дикой природе отсутствует (0/61) — last-match и есть контракт. Плюс будущие прогоны пишут `judge_texts` (сырой ответ судьи на trial) в `judged_raw.json` — класс «потеря raw» закрыт. Guard `tests/test_f5_judged_verdict.py` (7: синтетика pos/neg JSON+words + регрессия на backfill 1014/61 с порогами 840/50). Dry-run проверен (`judge_texts` в схеме).
- **Статус:** ✅ Fixed.

## 2026-09-27 — Ранкер `bge-reranker-v2-m3` оценивает целевой файл ниже порога фильтра (Open)

- **Симптом / контекст:** positive-контроли P2 и P3 (`experiments/token_reduction_v3_lancedb`) не находят целевой файл, positive controls 1/3. Стадия потерь локализована бисекцией — теряет только реранкер, MMR / `_boost_exact_name_matches` / `_dedupe_by_symbol` теряют 0:
  ```
  P3:        MMR 10→10 | reranker 10→2   (цель поз.4 -> None)
  R2:        MMR 10→10 | reranker 10→1   (цель поз.6 -> None)
  R2@limit=30:          30→30 | reranker 30→1
  ```
- **Root Cause (Verified):** модель `bge-reranker-v2-m3` (`llama_install.py:266-278`, `DEFAULT_RERANKER_MODEL`) даёт целевому чанку P3 сырой логит **-0.99** → после нормализации **0.271** < `MIN_RERANK_SCORE=0.3` → отсекается. R2: -2.60 → 0.069. Это проблема ранжирования/калибровки модели, **не** шкалы. Модель оценивает верный файл как нерелевантный; любой положительный порог такое удержать не может.
- **Уже исправлено (2026-09-27):** нарушение контракта шкалы. llama.cpp `/v1/rerank` отдаёт сырые логиты, а не [0,1] по Cohere-контракту (`ggml-org/llama.cpp#9510`, собственный пример: 5.97 / -11.03). Добавлена сигмоида `1/(1+e^-x)` в ветке `llama_cpp` (`multi_provider.py`), `MIN_RERANK_SCORE=0.3` сохранён. **P3 это не восстановило** — цель осталась на 0.271. Правка чинит контракт, но не полноту выдачи.
- **Делать НЕЛЬЗЯ:** понижать порог по результатам на тех же 16 frozen-правилах. Проверено: 0.3→5 hits, 0.05→7, 0.02→8 на том же наборе, которым меряется результат — это перебор на оценочной выборке, а не улучшение. Для калибровки нужен отдельный holdout.
- **Что нужно:** holdout для калибровки порога, либо замена/дообучение ранкера, либо отказ от абсолютного порога в пользу top_n. Решение за владельцем.
- **Guard:** `tests/test_reranker.py` — `test_sigmoid_matches_reference_values` (4 кейса), `test_sigmoid_is_numerically_stable_at_extremes`, `test_llama_cpp_scores_normalized_to_unit_interval`, `test_llama_cpp_negative_logit_does_not_leave_unit_interval`. Проверено мутацией (`_sigmoid` → identity): **7 failed / 38 passed**; чисто — 45 passed.
- **T3 (обобщение):** иных мест с абсолютным порогом по логитам в `src/` нет. `_DEFAULT_THRESHOLD = 0.85` в `duplication.py:37` — порог по Jaccard (по определению в [0,1], `clamp` на строке 136), другой механизм.

## 2026-09-27 — P2: целевой файл не доходит до финального пула; причина не установлена (Open)

- **Симптом:** для запроса P2 (`hybrid_search_async reciprocal_rank_fusion FTS5 BM25`) целевой `src/core/search/engine.py` не найден. Top-хиты — собственные артефакты эксперимента: `experiments/**/*.txt`, `results.json`, `docs/zh/SEARCH_PIPELINE.md`. Реранкер ни при чём — цели нет в пуле ещё до него.
- **Root Cause: НЕ УСТАНОВЛЕН.** Зафиксировано открытое противоречие: отдельный standalone-прогон BM25 вернул цель на **rank 0**, что несовместимо с утверждением «цель не находится вовсе». Расхождение между standalone BM25 и путём внутри `hybrid_search_async` не изучено. **Причину не утверждать** до разбора построения пула и RRF-слияния.
- **Побочно (Verified):** индекс содержит вывод собственных экспериментов, что загрязняет lexical-выдачу по общим терминам — это отдельная проблема индексации, не фильтра.
- **Что нужно:** разобрать построение pre-rerank пула и слияние RRF; выяснить, почему BM25 rank-0 не доходит до финального пула.

## 2026-09-25 — Падения не фиксировались: zombie-job + глушение исключений + нет ledger (Fixed) / Open (server hard-death)

- **Источник:** job `e4977ded` (running, но py-spy: 0 воркеров), `layer.py:863` `"Exception suppressed at layer.py: ..."` без стека; `job_manager` — in-memory.
- **Fix:** `src/core/reindex_ledger.py` (durable JSONL start/phase/error+traceback/zombie/end, никогда не бросает); `layer.py` — `finally` гарантирует терминальный статус, `_watchdog_reindex` терминализирует застрявший job (task done / нет прогресса > `MSCODEBASE_REINDEX_STALL_SEC`=900), полный traceback вместо «suppressed». Guard `tests/test_reindex_ledger.py` (6, с negative control).
- **Open:** 22:09 наш MSCodeBase-сервер **умер жёстко** (ledger: start без end; драйвер `ClosedResourceError`) в момент, когда поднялся MCP-сервер для **devbase** и занял фиксированные :8080/:8081. Класс «фиксированные порты / мультиокно / разделяемый эмбеддер без ref-count» — причина «постоянно падает».
- **Статус:** ✅ Fixed (recording) / 🔬 Open (server hard-death при мультиокне; нужен supervisor/динамические порты/ref-count).

## 2026-09-25 — IVF finalize hang: timeout-guard не может сработать (shutdown(wait=True) join'ит зависший optimize) (Fixed / Open)

- **Источник:** live job `31f5a9a7` (завис на «Finalizing 95%», 0 CPU у всех процессов, `.write_lock` залочен); эксперименты `experiments/misc_probes/exp_timeout_cancel_mechanism.py` + `exp_ivf_guard_negative_control.py`; `index_project_runner.py:666-755`
- **Root Cause:** `_safe_optimize` не может ограничить `table.optimize()`: `Future.result(timeout=)` **не отменяет** запущенный поток (в Python поток нельзя убить), а `finally: _opt_ex.shutdown(wait=True)` (`:687`) **join'ит** тот самый зависший вызов; `wait=False` в `except` немедленно перекрыт `wait=True` в `finally` → job висит вечно. Замер (timeout 1с, worker 6с): result сработал на 1.01с, `shutdown(wait=True)` заблокировал ещё 4.99с (итого 6.00с вместо 1.0с). In-code negative control: `_safe_ivf_index(timeout=1)` при `optimize`=5с вернулся за **5.00с** — guard не сработал.
- **Почему guard не поймал:** существующий `tests/test_reindex_finalizing_deadlock.py::test_safe_ivf_index_create_index_timeout...` покрывал зависший **create_index** (там `finally` = `wait=False`), а `_SlowTable.optimize` возвращался мгновенно → случай optimize не тестировался (слепое пятно guard'а).
- **Fix:** новый `_call_with_timeout(fn, timeout, label)` — daemon-thread + `Event.wait(timeout)`, БЕЗ join; на таймауте worker abandoned (job не блокируется), `_safe_optimize` → False → create_index не стартует на неопределённом состоянии. +тест `test_safe_ivf_index_optimize_timeout_does_not_hang` (и AssertionError, если create_index пойдёт после abandon). Проверка: negative control **5.00с → 1.01с (PASS)**; 3/3 deadlock-файла, 12/12 смежные с IVF; ruff чист.
- **Red Team (остаточное):** фикс убирает **зависание job навсегда**, но НЕ чинит корень зависания нативного `optimize()` (LanceDB/Windows) — abandoned daemon-thread висит до рестарта процесса (утечка при повторных зависаниях). Open: решение владельца — process-isolated optimize (killable) либо авто-disable IVF после N abandons.
- **КЛАСС-АУДИТ (`experiments/misc_probes/exp_timeout_class_audit.py`, in-code controls, 2026-09-25):** тот же дефект подтверждён ещё в 4 местах — **(#2)** `agentic_search.py:551-562` `with ThreadPoolExecutor` + `result(timeout=60)` → `__exit__` джойнит зависший воркер (5.00с вместо 1с); **(#3)** parse-фаза `index_project_runner.py:360-365` `fut.result()` БЕЗ таймаута → неограничен; **(#4)** `error_handler.py:649-654` `future.cancel()` на running-задаче → False (не отменяет, утечка); **(#5)** воркеры `ThreadPoolExecutor` non-daemon → `concurrent.futures` atexit `_python_exit` джойнит → блок завершения процесса/MCP. Все 4 — **FIXED 2026-09-25** системным helper'ом `src/core/run_bounded.py` (daemon-thread + `Event.wait`, без join; abandon→default). Заменены: #2 `agentic_search` (timeout 60), #3 parse-фаза (`MSCODEBASE_PARSE_TIMEOUT_SEC`, default 60), #4 `error_handler` sync-wrapper (пул `_SYNC_POOL` больше не используется на hot-path), engine `hybrid_search` sync-wrapper (timeout 30). Guard-инструменты: `tests/test_run_bounded.py` (5), `exp_in_situ_agentic_timeout.py` и `exp_in_situ_parse_timeout.py` теперь ассертят BOUNDED (1.00с / run() возвращается). Прогон: run_bounded 5 + finalizing 3 + agentic-search 25 (без addopts) + error/searcher/hybrid/deep 70 passed; ruff clean. **Остаточное:** корень зависания самого нативного `optimize()` не устранён (process-isolated вариант — отдельное решение).
- **LIVE in-situ (A+, 2026-09-25):** (#2) реальный `agentic_code_search` вернулся за **5.01с** при наблюдаемом таймауте 1с — `exp_in_situ_agentic_timeout.py`; (#3) реальный `IndexProjectRunner.run()` **не вернулся за watchdog 6с** при зависшем `_parse_file_only` — `exp_in_situ_parse_timeout.py` (принудительный `os._exit` для обхода atexit-join — косвенно подтверждает и #5). (#4) подтверждён на живом `Future.cancel()` (running→False), но не через реальный декоратор; (#5) daemon=False проверен вживую.
- **Статус:** ✅ Fixed (job-зависание устранено + regression guard) / 🔬 Open (корневое зависание optimize и утечка потока)

## 2026-09-25 — ETA/прогресс покрывает только фазу эмбеддинга; нарезка маскируется, хвост не считается (Open)

- **Источник:** live-разбор job `31f5a9a7` (full reindex 2026-09-25), `layer.py:1985-2045`, `embed_progress.py:12-58`, `store.py:195-271`, `tools_reg.py:288-359`
- **Описание:** `job.progress` — взвешенная фазовая шкала с разными знаменателями на фазу: `parsing/scanning 0.1+ratio*0.4` (10–50%), `embedding 0.5+ratio*0.3` (50–80%), `finalizing 0.8+ratio*0.15` (80–95%), `ratio=files_done/files_total` (`layer.py:761-775`). Embed-фаза имеет **собственный** счётчик чанков в %, с другим знаменателем → на экране одновременно два несопоставимых процента (live: job 54% при chunks 7% — это 0.5-пол парсинга + 0.07*0.3, т.е. арифметика, не баг). ETA считается **только** для embed (парсер `[embed] done/total … ch/s`, `embed_progress.py`); `finalizing` (LanceDB optimize+IVF) — грубый rolling-average из `job_history.json` (`store.py:249-271`, fallback 120с); write/граф/SymbolIndex/auto-doc не измеряются вовсе. Итог: total wall-clock превышает ETA (прецедент exp-13: ETA 18s vs 552s actual).
- **Требование владельца:** ETA должен учиться на данных и показывать общее время, покрывая все фазы (parse → embed → write → finalize → graph/symbols → docs).
- **Fix (план):** (1) пер-фазные записи в `job_history.json` {phase, size(files/chunks), duration}; (2) модель на фазу (медиана/регрессия по размеру) вместо одного общего среднего; (3) total ETA = сумма фаз с измеримым драйвером, где драйвера нет — честный None / «фаза без ETA», не число; (4) UI: текущая фаза отдельно от embed-бара; (5) negative control: ETA не показывать без данных фазы (guard от фейкового числа).
- **Статус:** 🔬 Open (P1 — искажает ожидания по времени; инцидент exp-13)

## 2026-09-22 — TESTS-рёбра транзитивны, а не «тесты про функцию»; E17 LLM-pilot сломан на извлечении кода (Fixed / Open)

- **Источник:** AGENT_DIARY.md#2026-09-22 (E17 Post-Mortem), `bootstrap_tests.py:216-244`
- **Описание:** (1) dynamic-trace линкует тест с *каждой исполненной* функцией → `_ensure_data_root` имеет 234 TESTS-ребра при 0 прямых вызовов в `tests/` (`check_disk_space` — 3). Для LLM-контекста сэмпл из 234 — шум, поэтому B-арм ≈ D-арм. (2) `e17_pilot_{answers,judge}.py` извлекали код наивным `f"def {name}"`, а граф хранит qualifed-имена (`Class.method`, `Class::test`) → `# FUNC NOT FOUND` для всех методов, `C_static` пуст 30/30.
- **Fix:** AST-извлечение в `experiments/bootstrap/e17_extract.py` + 13 тестов (Fixed). Фильтр TESTS по специфичности (прямой вызов / малый coverage-set) и пересборка pilot_data — не сделаны.
- **Статус:** Fixed (extraction) / Open (specificity-фильтр блокирует валидный E17 LLM-pilot). v3.5.0 retrieval hit@1 не задет.

## 2026-09-18 — PRE-EXISTING: tests/test_lsp_vfs_indexing.py broken (MagicMock.embedding_dim truthy)

- **Источник:** попутная находка во время Фазы 1
- **Описание:** `MagicMock().embedding_dim` truthy → `_target_dim = self.embedder.embedding_dim or 768` (db_writer.py:59) = MagicMock → вектор обрезается до zero → `Zero vector ... skipping` → все чанки пропущены → пустая таблица → 8/8 тестов FAIL. В CI не ловится: `pytestmark = slow`, addopts `-m "not slow"` → никогда не гоняется.
- **Fix:** не внесён (выходит за рамки Фазы 1); мой тест `tests/test_freshness_checker.py` обходит через явный `embedding_dim=1024`. Типовое исправление для lsp_vfs: задать `embedding_dim` в mock.
- **Статус:** 🔬 открыт (P2, низкий приоритет)

## 2026-09-07 — Cypher-движок ломается на анонимных узлах/рёбрах (fixed) + Receipts не писались из write-пути (fixed) + collect() некорректно заявлен (open)

- **Источник:** live-проба против реальной БД `bfe9644b/graph.db` (PropertyGraph, 6435 Variable / 22031 CALLS / 6152 ASSIGNED_FROM рёбер)
- **Описание (Cypher, fixed):** работают только запросы с типизированными узлами: `MATCH (n:Variable) RETURN count(n)` → 6435 (1.1ms). НО `MATCH ()-[e:ASSIGNED_FROM]->()` падал `sqlite3.OperationalError: no such column: e`, а `MATCH ()-[:ASSIGNED_FROM]->()` — `no such column: n0.id`. **Fix внесён:** cypher_sql.py — (1) `from_node_alias` резолвится в `n{path_idx*2}` для анонимного левого узла; (2) переменные ребра `[e:]` регистрируются в `edge_vars` и резолвятся в колонки (`e.type/source_id/target_id`), включён `count(e)`. 10 регресс-тестов (SQL + E2E) + 5 Red Team атак (направления `<-`, WHERE e.target_id, OPTIONAL MATCH, оба анонимных конца, collect) — все защищены, корректность результатов подтверждена (count=2 для 2 рёбер). **⚠️ collect() остаётся нерабочим**: `_translate_return_expr` заявляет `collect` как Supported (стр. 434-438 «Supported: count, sum, avg, min, max, collect»), но SQLite не имеет функции COLLECT (Red Team: `no such function: COLLECT`). Ни одного теста на `RETURN collect(...)` нет — заявка и реализация расходятся.
- **Описание (Receipts, fixed):** ActionReceipt компонент реализован (action_receipt.py, TD §11), но в проекте bfe9644b файла `action_receipts.jsonl` НЕТ — писались только в проектах 48baae8f/98d66cfa (19.08); `change_intents.jsonl` (96 записей) остаётся последней живой записью от 13.08. Receipt-путь для текущего проекта не срабатывал при повседневных MCP-вызовах (заполнялся только через lifecycle-tools reindex-путь).
- **Fix (Cypher):** внесён (см. выше, коммит 80a7acf8). **Fix (collect):** либо реализовать JSON-агрегацию `collect()` (json_group_array в SQLite), либо убрать из списка Supported и добавить негативный тест. **Fix (Receipts):** внесён — `_contract_record` в write_tools.py теперь вызывает новый `_contract_receipt()` (ActionReceipt рядом с ChangeIntent), а сам `_contract_record` добавлен во ВСЕ write-пути: replace, insert_before/after, rename (LSP workspace edit + fallback), safe_delete, move (source/target/refs). Receipt-запись warning-only, не ломает write. Тест `tests/test_write_tools.py::test_apply_records_action_receipt` (создание action_receipts.jsonl из реального write-вызова). Коммит см. git log.
- **Статус:** 🟢 Cypher-часть fixed; 🟢 receipts fixed; 🟢 collect() fixed (2026-09-08: json_group_array + FILTER null-игнор, decode только marked-колонок; 13 новых тестов, полный pytest 1663 passed)

## 2026-09-07 — Lazy-only верификация: память не проверяется без вызова агента; нет TTL/фона (open, эксперимент нужен)

- **Источник:** live-срез project_memory.json текущего проекта (136 узлов) + grep точек вызова VOR/idle-планировщика
- **Симптомы (все Verified):**
  - VOR вызывается ровно из 1 места — `intel_get_project_memory` (layer.py:1097). Таймеров/старт-хуков/idle-подписок нет.
  - У 42 узлов ACTIVE нет ни одного поля TTL/last_checked/next_check — висят без статуса с 2026-08-11 (1 месяц).
  - Узлы без якорей (`file:/import:/env:/pkg:`) → INCONCLUSIVE → VOR **не пишет ничего** (ни статуса, ни verified_at) — их нельзя ни подтвердить, ни отозвать автоматически. Пример: ADRs с commit_hash в data, но без шпилей.
  - IdleScheduler (`enable_idle_scheduler`, task_queue.py:345) включается только из `record_tool_call()` — после вызова инструмента; VOR туда не подключён; из 3 idle-задач 2 — заглушки (`_improve_summaries_batch`, `_check_index_health` — пустые тела, только debug-лог).
  - Со стороны агента: вызвал `intel_get_project_memory` → 110/110 узлов проверено (47 VERIFIED, 63 не-refuted) — работает, но только «по руке».
- **Дизайн-решение для эксперимента (следующий шаг):** непрерывная проверка «без вызова» — (a) idle-тикер VOR в фоне по расписанию с cooldown; (b) react на git/файловые события (HEAD сменился → перепроверка затронутых узлов); (c) TTL/`verified_at` для INCONCLUSIVE → по возрастанию падать в REFUTED label «не подтверждён за N дней». Контр-риск: цена (CPU/disk) непрерывной проверки vs польза свежести — мерить, не угадывать (см. docs/research/universal-engine-study/10-continuous-verification.md).
- **2026-09-09 аудит (Exhibit #23) подтверждает:** цепочка «файл изменён → STALE → VOR → alert агента» не существует ни в одном звене; ConsistencyTracker.mark_stale("memory") никогда не вызывается; system_alerts нет. Red Team: (a) H3 TTL-гниение НЕ применимо к INCONCLUSIVE (VOR статус не меняется без якорей) — нужен idle-ticker H1; (b) lock contention idle-VOR vs agent-VOR — добавить locked()-check; (c) import cycle — локальный импорт внутри try/except. Выбран приоритет: **H1 (idle-ticker в `_check_index_health`, ~15 строк)**.
- **2026-09-09 H1 реализован (коммит в ветке chore/experiments-es1-es2-0909):** `set_idle_vor_callback()` в task_queue.py + вызов из `_check_index_health` (idle-тик, cooldown 120s); `run_background_verify(budget_ms=250)` в layer.py с locked()-guard (Red Team a): общий `_write_lock` и `get_verifier`-регистр → idle-VOR и agent-VOR сериализуются без второй lock/гонки; `_build_symbol_resolver` вынесен из `intel_get_project_memory` (DRY, эквивалентный рефакторинг); регистрация hook в `server_tools._register_intelligence_tools` после создания `intel_layer`. Тесты: 3 idle-hook (test_task_queue) + 3 background-VOR (test_verify_on_read); полный pytest 1674 passed.
- **Статус:** ✅ H1 Fixed (фоновая перепроверка памяти без вызова агента); ✅ system_alerts Fixed (см. ниже — доставка через alert-store реализована); данная дочерняя запись про `.h` закрыта
- **2026-09-10 system_alerts реализован (коммит в ветке chore/experiments-es1-es2-0909):** `AlertStore` (src/core/intelligence/alert_store.py, JSON вне проекта, threading.Lock, дедуп по kind+payload, атомарный collect_and_clear). Источники: stale — `mark_stale("memory")` + одноразовый alert в notify_change (при переходе UNKNOWN/CONSISTENT→STALE); starved — idle VOR-проход (`run_background_verify`) и `intel_get_project_memory` (узлы видимы ≥2 циклов, MATCHED>0, DELIVERED=0). Доставка: `format_system_alerts` в ui_formatter; prepend в `intel_get_project_memory` (tools_reg) + последняя секция в `intel_explain_project_state` (server_tools). Red Team: дедуп предотвращает спам на каждый notify_change; атомарный clear — один alert уходит ровно одному тулу при гонке; limit=5 — токен-бюджет. Тесты: 11 (test_alert_store: push/collect/clear/дедуп/limit/коррапт-json/гонка 2 потоков/per-project/синглтон) + 3 (format_system_alerts); полный pytest 1689 passed.
- **2026-09-11 H3 TTL-гниение реализован (doc 10, H2 закрыт Exp 3):** `last_checked` пишется для КАЖДОГО реально проверенного узла (cache-hit и fresh check, включая INCONCLUSIVE) — физическая запись rate-limited (`VOR_LAST_CHECKED_INTERVAL_SEC`, default 6ч, чтобы H1 idle не переписывал project_memory.json каждый тик); `stale_ttl_nodes` — узлы ACTIVE/VERIFIED, НЕ проверенные в проходе, чей след (`verified_at`/`last_checked`) старше `VOR_TTL_DAYS` (default 30 → label `verification="stale_ttl"` «не подтверждён за N дней»). N=30 из live-распределения verified_at 2026-09-11 (ACTIVE 70 без verified_at, VERIFIED median 22/max 31, коммитовый ритм daily). Статус НЕ меняется (Red Team a2: INCONCLUSIVE неотзываем, guard false_retraction). Нет следа вовсе (новый узел) → НЕ stale (starved ловит систематическое голодание отдельно). Files: verify_on_read.py (const + _persist_transitions + run), layer.py (flag), ui_formatter.py (render). Тесты: 9 новых (test_verify_on_read_ttl.py); полный pytest 1725 passed.
- **Дедлайн:** 2026-09-15 · **Owner:** ManSio

## 2026-09-13 12:00 - H4: свежесть снапшота dev.to KB — «gone» 97.5% без метрики (open)

- **Источник:** EXPERIMENTS_LOG Exp 6 (2026-09-13), exp-37 portfolio lab
- **Описание:** **Status:** ⏳ Open (исследовательский хвост H4). При росте базы (13,519 статей/82,527 комментов) 97.5% хранимых комментариев — gone против live dev.to (live=2,030, gone=80,494), и нет метрики свежести снапшота. Локальная пересборка графа НЕ bottleneck (50,498 тредов за ~3с); узкое место — сетевая фаза capture (refresh own = 10м38с, 134 вызова dev.to API). Гипотеза: инкрементальный/осознанный refresh + быстрая метрика «доля gone» на снапшот вернут точность verify-on-read на частично свежем графе.
- **Fix:** не оптимизировать сборку графа; добавить метрику свежести + запланировать инкрементальный refresh. Эксперимент завершён (verdict confirmed), задача на оптимизацию — открыта.
- **Статус:** ⏳

## 2026-09-15 - [FEATURE] Bootstrap Pipeline: детерминированный импорт репозитория (по результатам Exp-38)

- **Источник:** EXPERIMENTS_LOG Exp 7 (2026-09-15), exp-38 portfolio lab
- **Описание:** Эксперимент exp-38 подтвердил, что статический анализ не способен связать тесты с кодом (0% точности по именам; импорты дают только файловый уровень 77.9%). Dynamic trace через `sys.settrace` (pytest-плагин `experiments/bootstrap/dynamic_trace_plugin.py`) даёт **89.8%** точных тест→функция связей (1551/1727 тестов, 1212 уникальных src-функций) при оверхеде **+13.6%** (198.6s vs 174.8s, та же сессия). Точное имя-попадание внутри динамической выборки — всего 2.7%: ранжирование целевой функции требует дообогащения импортами файла/класса. 176 тестов (10.2%) не исполняют src-функций (моки/фикстуры).
- **Цель:** реализовать разовый плагин/конвейер первичности (bootstrap) для новых проектов.
- **Требуемые доработки:** **(1) Шаг 1 (Data structures):** фильтрация по сигналам `dataclass`/`NamedTuple` (46 чисто); исключить шум регекса `Table(` (90% — `open_table`, не SQL-схемы); pydantic/TypedDict в репо отсутствуют. **(2) Шаг 2 (Decorators enrichment):** обогатить индексатор графа генерацией `DECORATES`-рёбер для `@mcp_app.tool` (22 точки входа сейчас теряют связи; парсер имени `_decorator_name` срезает верно, узел `mcp_app.tool` в графе есть, tool-рёбер нет). **(3) Шаг 3 (Dynamic Trace pass):** интегрировать pytest-плагин как штатную команду `mscodebase bootstrap`. **(4) Шаг 4 (Git→ADR):** интегрировать существующий `intel_auto_collect_adrs` (уже работает).
- **Статус:** ⏳ зафиксировано, реализация не начата (iter-точка по решению владельца)
- **Прогресс Step A (2026-09-16):** **[A1 решён]** драйвер — `dynamic_trace_plugin.py` (sys.settrace, +13.6%); coverage.py — валидационный оракул (Exp 8: sysmon +19.96%, REFUTED). **[A2 реализован]** `src/core/bootstrap_tests.py` + `tests/test_bootstrap_tests.py`: TESTS-рёбра из `trace_result.json` в PropertyGraph. Live-прогон на реальной БД: создано **1595** Test-узлов (label=`Test`), переиспользовано 132 (индексаторные Function-узлы не обёртываются — `get_node` вместо `add_node`, т.к. последний перетирает label через ON CONFLICT), линковано **14985/15669** src-функций (95.7%), **16172** уникальных рёбер TESTS (UPSERT, идемпотентно), multi-match 781 (метод `Class.method` ↔ голый co_name). Не-матчи 684 = `<lambda>`/`<genexpr>` (не имеют узлов). Red Team 5/5 закрытых (границы/дубли/label-перезапись/повторы/параметры). Осталось: команда `mscodebase bootstrap` (Шаг 3), // гейт CI для TESTS-рёбер.

  **[Exp 9, 2026-09-16 — Шаг B пересмотрен фактами]**
  - **[Шаг 2 (DECORATES для @mcp_app.tool) — ЗАКРЫТ, уже реализован].** Живая БД содержит рёбра `DECORATES`: `mcp.tool`→14, `mcp_app.tool`→20 (tools_reg.py, dev_tools.py). Источник — `19378296` («vendor tree-sitter tags.scm + DECORATES/OVERRIDES edges»). Запись выше «tool-рёбер нет» устарела на момент фиксации.
  - **[Шаг 1 (Data structures) — уточнён].** Exp 9 (Static Score Engine vs trace_result.json ground truth, v2 per-test): hit/recall/precision — L1 (прямые вызовы из тела теста): 88.4% / 30.3% / **68.0%** (avg 2.9 кандидата), L2 (токены имени): 17.7% / 3.8% / 12.1%, L3 (импорты): 91.6% / 72.0% / 21.8% (avg 41.4), union: 90.4% / 70.0% / 20.6%. Статика НЕ заменяет динамику (hit≠recall, recall union 70% < 100% dynamic на linked); L1 — точный якорь для ранжирования, L3 — широкий кандидат-пул, L2 — слабый (подтверждает Exp 7 «имя=0%»). Статика = fallback для динамически-пустых тестов (88/176 мок-тестов имеют стат. кандидатов) + pre-filter. Dynamic остаётся драйвером TESTS-edge.
**[Шаг 1 (Data structures) — РЕАЛИЗОВАН, 2026-09-17]**
  - `src/core/bootstrap_entities.py` + `tests/test_bootstrap_entities.py` (8 unit-тестов): AST-детектор data structures по сигналам `@dataclass` (Name/Call/Attribute-формы) и базы `NamedTuple` (Name/Attribute). НЕ регекс — `Table(`-шум априори не виден (это вызовы, не классы).
  - Live-прогон на реальном репо: **49 dataclass** (46 из графа + 3 наших bootstrap-классов: EntityShape/EntitiesBootstrapStats/TestsBootstrapStats — ещё не переиндексированы), **0 NamedTuple** (в репо отсутствуют), **open_table 12 call-сайтов** — не интерпретируются как сущности. Потерь против живого графа 0 (46 полностью покрыты детектором). pydantic/TypedDict/алиасы импортов (`NamedTuple as NT`) — вне скоупа (документировано в docstring).
  - Роль (по Exp 9): статика — не замена динамики; детектор = fallback для динамически-пустых тестов + pre-filter ранжирования (вход для `mscodebase bootstrap`, Шаг 3).
- **Внешняя валидация на чужих Python-проектах (2026-09-17, anti-sleeveness):**
  - Ревизия всех 18 репо `<repos-root>\` (субагент): лучшие «чистые» кандидаты — `gemma_agent` (1102 py / 464 test_*.py / git), `456789/ARCLUX` (TS), `bench_projects` (black/httpbin/headroom). До этого детектор и TESTS-рёбра проверялись только на собственном репо.
  - `bootstrap_entities.detect_entities` обобщается: **black(src)=16 dataclass / 2 NT / 73 classes**, **gemma_agent/core=65 dc / 228 classes**, gemma_agent/modules=1 dc, httpbin=0 (старый код без dataclass). Найдена слепота: детектор жёстко завязан на подкаталог `src/` — gemma_agent использует `core/`/`libraries/`/`modules/`, нужен явный `src_dir` (параметр уже есть).
  - **[РЕШЕНО 2026-09-17]** Хардкод `src/` устранён: `resolve_src_root()` — детерминированный приоритет (явный `src_dir` → env `MSCODEBASE_BOOTSTRAP_SRC_DIR` → известные раскладки `src/lib/core/libraries/modules` → каталог с именем проекта → статистический fallback с исключением `tests/docs/venv`). Валидация: MSCodeBase→src, gemma_agent→core (ранее требовал источник), black→src, httpbin→httpbin. Результаты совпадают с ручным `src_dir` (1:1). Тесты 14/14, в т.ч. 6 новых (core-layout/имя-проекта/статистика/env/приоритет-env/пустой-прогон). Red Team 3/3 (venv-tests не захватываются статистикой, битый env не ломает, относительный src_dir работает).
  - **[Шаг 3 (Dynamic Trace command) — РЕАЛИЗОВАН, 2026-09-18]**
    - `git mv experiments/bootstrap/dynamic_trace_plugin.py src/core/bootstrap_trace_plugin.py` — плагин штатный; импорт `-p src.core.bootstrap_trace_plugin`.
- `src/core/bootstrap_pipeline.py` (оркестратор: resolve_src_root → detect_entities → pytest subprocess §5.16-safe → index_src_functions → build_tests_edges) + `bootstrap_tool.py` (`bootstrap_pipeline`, MCP+CLI). Подводные камни — AGENT_DIARY 2026-09-18: PYTHONPATH только по авто-детекту `_plugin_importable` (namespace shadowing `src`-пакета), BOM-guard `utf-8-sig`.
     - Тесты: `tests/test_bootstrap_pipeline.py` (5 интеграц., без моков) + 3 на `index_src_functions`; 28/28 green + полный suite passed. Клиент параметризован по env (`TRACE_SRC_ROOT`/`TRACE_OUT`) → чужие проекты: gemma_agent 2737/2882 (95.0%) тестов имеют ≥1 src-функцию; black скомпилирован в `.pyd` → sys.settrace не ловит нативные кадры (fallback на статику Exp 9 обязателен).
- **Веб-исследование и audit «гиблых мест» (2026-09-15, всё ПРОВЕРЕНО эмпирически):** (1) **sysmon+dynamic_context — ОПРОВЕРГНУТА**: верные контексты даёт pytest-коллекция, ручной `switch_context` → пустые `['']` (coverage.py 7.14.1); (2) **контексты ≈3-7% — НЕ воспроизвелось**: Exp 8 (2026-09-16) overhead **+19.96%** (221.78 vs 184.88s) > нашего sys.settrace (+13.6%) → штатный драйвер Шага 3 = `dynamic_trace_plugin.py`, coverage остаётся валидационным оракулом (контексты качественные: 1548/1549, 75.5% src-строк привязаны); (3) **Tarantula — Exp 7b**: rank≤3 у 22.6% тестов (далеко от 60-70%), НО precision низких рангов высока (все rank1-3 верны) → аннотация confidence (~16%), не селектор; TESTS-ребро строится из полной трассы; (4) **mutation-testing как ground truth — дорого/хрупко** (FSE'20, Google 33M; флаки раздувают score); (5) **pytest-testmon — не копируем** (line-based, сужение рерана ≠ граф-ребро TESTS для LLM-контекста); (6) **dev.to-кросс-чек**: «TRUE Coverage» (Dawson, 2026-07-22) подтверждает плато статики и шум shared-utils (наш safe_mkdir/get_data_root кейс 1:1; CI 43min→4min, precision 15%→95%); «Empirical Failure Modes» (Arthur, 2026-07-31) — Pass-Through Test Mirage (наш «фантомный код»), Python 3.14 sys.monitoring reachability = наш бэкенд, AST orphan-detection = наш Шаг 1; **ниша TESTS-рёбер для LLM-контекста ими не занята** (per-test coverage используется только для selection/rejection); (7) edge-case (Gemini): без тестов → статика; бинарники → Docker+microtrace; async → OpenTelemetry по trace_id.

## 2026-09-22 — Exp E16: переносимость bootstrap trace на чужие проекты (статья CoderLegion)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Measured (hypothesis CONFIRMED)
**Hypothesis:** динамический трейс (sys.settrace, `src/core/bootstrap_trace_plugin.py`) воспроизводится на чужих Python-репозиториях без правок плагина; lin...
- **Статус:** автоматически синхронизировано


## 2026-09-22 — Exp E14: Embedder A/B — EmbeddingGemma 300M vs e5-small (production)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Measured (hypothesis CONFIRMED)
**Hypothesis:** gemma 300M (768-dim, ctx 2048) значительно сильнее e5-small (384-dim, ctx 512) на кодовом ретривале при цене 3-4× медленнее на CPU.
**Method...
- **Статус:** автоматически синхронизировано


## 2026-09-19 тАФ E10 (search quality): full-text-╤Н╨╝╨▒╨╡╨┤╨┤╨╕╨╜╨│ + e5-╨┐╤А╨╡╤Д╨╕╨║╤Б╤Л + ╨┐╤Г╨╗ reranker 50 тЖТ REFUTED (N=10)

- **╨Ш╤Б╤В╨╛╤З╨╜╨╕╨║:** EXPERIMENTS_LOG.md#2026-09-19
- **╨Ю╨┐╨╕╤Б╨░╨╜╨╕╨╡:** ╤В╤А╨╕ ┬л╨▓╤Л╨║╨╗╤О╤З╨░╤В╨╡╨╗╤П┬╗ ╨║╨░╤З╨╡╤Б╤В╨▓╨░ (E10a full-text ╤З╨░╨╜╨║╨░ ╨▓ ╤Н╨╝╨▒╨╡╨┤╨┤╨╕╨╜╨│, e5 `query:`/`passage:`-╨┐╤А╨╡╤Д╨╕╨║╤Б╤Л ╨▓ llama.cpp-╨▓╨╡╤В╨║╨╡ тАФ ONNX/OpenVINO ╤Г╨╢╨╡ ╨╕╨╝╨╡╨╗╨╕ `_ensure_prefix`, E10c ╨┐╤Г╨╗ reranker 30тЖТ50) ╨╜╨╡ ╨┤╨░╨╗╨╕ ╨┐╨╛╨┤╤В╨▓╨╡╤А╨╢╨┤╨░╨╡╨╝╨╛╨│╨╛ ╤Б╨┤╨▓╨╕╨│╨░. ╨з╨╕╤Б╤В╤Л╨╣ ╨┐╤А╨╛╨│╨╛╨╜ (599 ╤Д╨░╨╣╨╗╨╛╨▓ / 9514 ╤З╨░╨╜╨║╨╛╨▓, 799.9s): fast hit@1=0% hit@5=50%; quality hit@1=20% hit@5=40%; baseline ╨░╨▓╤В╨╛╤А╨░ 0/50% ╨╕ 30/30%. ╨Ф╨╡╨╗╤М╤В╨░ тАФ ╨▓ ╨┐╤А╨╡╨┤╨╡╨╗╨░╤Е ╤И╤Г╨╝╨░ N=10.
- **Fix (╨┐╤А╨╡╨┤╨╛╤В╨▓╤А╨░╤Й╨╡╨╜╨╕╨╡):** ╨╕╨╖╨╝╨╡╨╜╤С╨╜╨╜╤Л╨╣ ╨║╨╛╨┤ ╨╛╤В╨║╨░╨╗╨╡╨╜ ╨║ HEAD (╨┐╨╛╨▓╨╡╨┤╨╡╨╜╨╕╨╡ ╨║╨╗╨╕╨╡╨╜╤В╨░ = ╨┐╤А╨╛╨┤); ╨╛╤Б╤В╨░╤В╨╛╨║ тАФ env-╤В╤Г╨╝╨▒╨╗╨╡╤А `MAX_RERANKER_INPUT` ╤Б default=30 (╨╜╨╡╨╣╤В╤А╨░╨╗╨╡╨╜). ╨Я╨╗╨░╤Вo ┬лpure-vector┬╗ ╨┐╨╛╨┤╤В╨▓╨╡╤А╨╢╨┤╨╡╨╜╨╛ ╨┐╨╛╨▓╤В╨╛╤А╨╜╨╛ (╤Б╤А. Exp-29 ceiling ~0.23).
- **╨б╤В╨░╤В╤Г╤Б:** тЭМ REFUTED (╨╖╨░╨║╤А╤Л╤В, ╨╖╨░╨┐╨╕╤Б╨░╨╜ ╨▓ lab exp-43). ╨б╨╗╨╡╨┤╤Г╤О╤Й╨╕╨╣ ╤Е╨╛╨┤ тАФ AST/Graph-hybrid re-ranking, ╨╜╨╡ ╤Н╨╝╨▒╨╡╨┤╨┤╨╕╨╜╨│╨╛╨▓╤Л╨╡ ╤В╨▓╨╕╨║╨╕.

## 2026-09-18 — Фаза 1: Incremental Hot-Reload (FreshnessChecker оживлён + hot-reload + KI-109)

- **Источник:** AGENT_DIARY.md
- **Описание:** - **Evidence Ladder (2026-08-15, Exp 2-E E1-E3):** форма evidence — переменная; file_content = лучший recall (qwen 0.92), graph = закрытие present-trap ТОЛЬКО у evidence-честных моделей (qwen3.7 FA tr...
- **Статус:** автоматически синхронизировано


## 2026-09-07 — Lazy-only верификация: VOR вызывается только из intel_get_project_memory, нет TTL/фона

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Open — зафиксировано как проблема + план эксперимента (10-continuous-verification.md)
**Root Cause:** По дизайну (ADR-0003) VOR ленивый, но точки вызова всего одна (layer.py:1097); IdleSch...
- **Статус:** автоматически синхронизировано


## 2026-09-09 — Аудит «Active MSCodeBase» (Exhibit #23: MCP tool available but never invoked)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Open — зафиксирован гэп (исследование + план, код НЕ вносился)
**Root Cause:** фундамент (VOR / DebounceBatch / ConsistencyTracker / IdleScheduler / PropagationEngine) существует, но компо...
- **Статус:** автоматически синхронизировано


## 2026-09-05 тАФ Process leak: hung git cat-file leaks git+git.exe+conhost chains (RAM 81%, ~200 procs)

- **╨Ш╤Б╤В╨╛╤З╨╜╨╕╨║:** AGENT_DIARY.md
- **╨Ю╨┐╨╕╤Б╨░╨╜╨╕╨╡:** **Status:** тЬЕ Fixed (code only, ╨╜╨╡ ╨╖╨░╨┐╤Г╤И╨╡╨╜╨╛) тАФ verify_diary.py + git_hooks_installer.py
**Root Cause:** `check_commit_exists` (verify_diary.py:361): `proc.communicate(timeout=30)` ╨╜╨░ ╤В╨░╨╣╨╝╨░╤Г╤В╨╡ ╨Э╨Х ╤Г╨▒╨╕╨▓╨░╨╡╤В ╨┐╤А╨╛╤Ж╨╡╤Б╤Б, `except: pass` ╨│╨╗╨╛╤В╨░╨╡╤В TimeoutExpired тЖТ Popen ╤Г╤В╨╡╨║╨░╨╡╤В ╨╜╨░╨▓╤Б╨╡╨│╨┤╨░. Git for Windows re-exec (git тЖТ git.exe) ╤В╨╡╤А╤П╨╡╤В DETACHED_PROCESS тЖТ ╨║╨░╨╢╨┤╤Л╨╣ ╨╖╨░╨▓╨╕╤Б╤И╨╕╨╣ `cat-file` = 3 ╨▓╨╡╤З╨╜╤Л╤Е ╨┐╤А╨╛╤Ж╨╡╤Б╤Б╨░ (git + git.exe + conhost); ╤Б╤В╨░╤А╤В╨╛╨▓╨░╤П Contradiction Ledger-╨┐╤А╨╛╨▓╨╡╤А╨║╨░ ╨┐╤А╨╕ CPU/Defender contention.
**Fix:** `_kill_git_tree()` (`taskkill /F /T /PID`) ╨╜╨░ TimeoutExpired ╨▓ check_commit_exists + ╤В╨╛ ╨╢╨╡ ╨▓ run_script (git_hooks_installer.py:93). ╨б╨╜╤П╤В╨╛ ╨╜╨░ ╨╢╨╕╨▓╨╛╨╣ ╤Ж╨╡╨┐╨╛╤З╨║╨╡ 9660тЖТ24156тЖТ24428. ╨в╨╡╤Б╤В╤Л: 9 passed (5 commit_guard + 2 subprocess_windows + 2 ledger slow); ruff clean ╨┐╨╛ ╨╜╨╛╨▓╤Л╨╝ ╤Б╤В╤А╨╛╨║╨░╨╝.
- **╨б╤В╨░╤В╤Г╤Б:** тЬЕ Fixed

## 2026-09-11 тАФ VOR read-path fix (PR #34) + ┬л8-╨╝╨╕╨╜╤Г╤В╨╜╤Л╨╣ ╨║╨╛╨╝╨╝╨╕╤В┬╗ = ╨Э╨Х ╨▒╨░╨│ (╤А╨╡╤И╨╡╨╜╨╕╨╡ ╨▓╨╗╨░╨┤╨╡╨╗╤М╤Ж╨░)

- **╨Ш╤Б╤В╨╛╤З╨╜╨╕╨║:** AGENT_DIARY.md
- **╨Ю╨┐╨╕╤Б╨░╨╜╨╕╨╡:** **Status:** тЬЕ PR #34 ╤Б╨╛╨╖╨┤╨░╨╜, hooks green; ╤Б╨║╨╛╤А╨╛╤Б╤В╤М ╤В╨╡╤Б╤В╨╛╨▓ тАФ ╨╛╤Б╨╛╨╖╨╜╨░╨╜╨╜╨╛╨╡ ╤А╨╡╤И╨╡╨╜╨╕╨╡, ╨║╨╛╨┤ ╨Э╨Х ╨╝╨╡╨╜╤П╨╗╤Б╤П.
**Root Cause:** (1) read-path VOR ╤А╨╡-╤Б╨║╨░╨╜╨╕╤А╨╛╨▓╨░╨╗ prose ╤В╨╡╨╗╨░ ADR ╤З╨╡╤А╨╡╨╖ `_PATH_RE`, ╤Е╨╛╤В╤П ╤П╨▓╨╜╤Л╨╡ `data.anchor...
- **╨б╤В╨░╤В╤Г╤Б:** ╨░╨▓╤В╨╛╨╝╨░╤В╨╕╤З╨╡╤Б╨║╨╕ ╤Б╨╕╨╜╤Е╤А╨╛╨╜╨╕╨╖╨╕╤А╨╛╨▓╨░╨╜╨╛

## 2026-09-10 тАФ Exp 1 (Catch-up Rate) + Exp 3 (HEAD polling): VOR ╨╝╨░╤Б╤И╤В╨░╨▒╨╕╤А╨╛╨▓╨░╨╜╨╕╨╡ ╨╕ ╨▓╨╜╨╡╤И╨╜╨╕╨╣ ╨┤╤А╨╕╤Д╤В

- **╨Ш╤Б╤В╨╛╤З╨╜╨╕╨║:** AGENT_DIARY.md
- **╨Ю╨┐╨╕╤Б╨░╨╜╨╕╨╡:** **Status:** тЬЕ Fix (╨╖╨░╨╝╨╡╤А╤Л, ╨║╨╛╨┤╨░ ╨╜╨╡ ╨╝╨╡╨╜╤П╨╗╨╛╤Б╤М). **Root Cause (KNOW ISSUES ┬лLazy-only ╨▓╨╡╤А╨╕╤Д╨╕╨║╨░╤Ж╨╕╤П┬╗):** ╨▓╨╛╨┐╤А╨╛╤Б, ╤Г╤Б╨┐╨╡╨▓╨░╨╡╤В ╨╗╨╕ VOR ╨┐╤А╨╛╨▓╨╡╤А╨╕╤В╤М ACTIVE-╤Г╨╖╨╗╤Л ╨▓ ╤А╨░╨╝╨║╨░╤Е budget_ms=50 (read-path) / 250 (background id...
- **╨б╤В╨░╤В╤Г╤Б:** ╨░╨▓╤В╨╛╨╝╨░╤В╨╕╤З╨╡╤Б╨║╨╕ ╤Б╨╕╨╜╤Е╤А╨╛╨╜╨╕╨╖╨╕╤А╨╛╨▓╨░╨╜╨╛
## 2026-09-20 — Поисковое качество / E13: исследовательские задачи (6 пунктов)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Plan (задачи занесены в ISSUE.md KI-R1..R6, код не тронут)
**Контекст:** исследование поиска/RAG — что именно измерять, прежде чем утверждать результат.
**Решение (приоритет):** KI-R1 (пер...
- **Статус:** автоматически синхронизировано
