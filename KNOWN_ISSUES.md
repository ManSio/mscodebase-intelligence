# KNOWN ISSUES — MSCodeBase Intelligence

> Синхронизируется из `AGENT_DIARY.md` при каждом [🏁 ИТОГ].
> Формат: дата | что было | статус | fix

---


**35 entries** — compressed per §4.8 R3 (conclusion-first; dedup 2026-09-08, 2026-09-21)

## 2026-09-25 — Reindex deadlock: `_bounded_link` ran `bulk_write` on a new thread while the caller held the write RLock (Fixed)

- **Источник:** live job `090149f1` (stuck 52% "running", 0 CPU); `py-spy dump 6780` → поток `bounded-bulk_write` idle на `db_writer.py:336` (`with self._table_write_lock:`), поток `asyncio_1` ждёт его в `_bounded_link`; `reindex_ledger.jsonl` записал `RuntimeError: bulk_write exceeded 300s`.
- **Root Cause:** `run()` держит глобальный RLock (`db_manager.begin_write()`) весь reindex на своём потоке; `_bounded_link` (timeout-фикс 2026-09-25) запускал `bulk_write` в НОВОМ daemon-потоке, а `bulk_write` берёт ТОТ ЖЕ RLock → дедлок. Тот же класс для `prune`/`verify` (`recreate_table_physical`).
- **Fix:** `_bounded_link` оборачивает bounded-вызов в `_suspend_write_lock()` (уже применённый для `_safe_ivf_index`) — единая точка, покрывает все звенья.
- **Fix (итог):** разделены два мьютекса — `run()` держит отдельный `begin_run()` (non-reentrant, взаимное исключение запусков), а `_table_write_lock` берётся только на операцию. `_bounded_link` больше не освобождает write-lock. Это закрыло и дедлок, и параллельные индексаторы (auto-index + manual trigger) — они теперь сериализуются.
- **Guard:** `tests/test_bounded_link_deadlock.py` (write-lock на другом потоке не дедлочит + структурный контракт), `tests/test_run_singleflight.py` (begin_run ≠ begin_write; второй run блокируется).
- **LIVE verified (2026-09-25):** full reindex job `c09c2e22` → **completed за 858.5с** (ledger: parsing→embedding→finalizing→complete→end). Индекс: **19653 → 10103**, path-duplication **668 → 0**, dup(file_path,chunk_index) **144 → 0**.
- **Статус:** ✅ Fixed + live-verified.

## 2026-09-25 — Падения не фиксировались: zombie-job + глушение исключений + нет ledger (Fixed) / Open (server hard-death)

- **Источник:** job `e4977ded` (running, но py-spy: 0 воркеров), `layer.py:863` `"Exception suppressed at layer.py: ..."` без стека; `job_manager` — in-memory.
- **Fix:** `src/core/reindex_ledger.py` (durable JSONL start/phase/error+traceback/zombie/end, никогда не бросает); `layer.py` — `finally` гарантирует терминальный статус, `_watchdog_reindex` терминализирует застрявший job (task done / нет прогресса > `MSCODEBASE_REINDEX_STALL_SEC`=900), полный traceback вместо «suppressed». Guard `tests/test_reindex_ledger.py` (6, с negative control).
- **Open:** 22:09 наш MSCodeBase-сервер **умер жёстко** (ledger: start без end; драйвер `ClosedResourceError`) в момент, когда поднялся MCP-сервер для **devbase** и занял фиксированные :8080/:8081. Класс «фиксированные порты / мультиокно / разделяемый эмбеддер без ref-count» — причина «постоянно падает».
- **Статус:** ✅ Fixed (recording) / 🔬 Open (server hard-death при мультиокне; нужен supervisor/динамические порты/ref-count).

## 2026-09-25 — Раздувание индекса ~×2: full-reindex писал `\`, incremental — `/` (один файл = две строки) (Fixed)

- **Источник:** снимок индекса (`experiments/misc_probes/exp_index_dedup_probe.py`): `file_path` distinct raw=**1378** vs normalized=**710** (path-duplication **668**); код: `index_project_runner._parse_worker` (`str(relative_to)` → `\`), `freshness.py:96` (`.replace(os.sep,"/")`), `db_writer` id=`md5(rel_path)_i`, `indexer._parse_file_only` (`known_hashes.get(rel_path_str)`).
- **Root Cause:** полный reindex писал пути с `\`, hot-reload/freshness — с `/`. `known_hashes` и id строки строятся по **буквальному** `file_path` → формы не совпадали → incremental **пере-добавлял** уже проиндексированные файлы каждый прогон → рост ~×2. Измерено: `9991 → 19653` чанков.
- **Вторая причина:** data-JSON — **5272 чанка (27%)**, крупные `results_*.json` (до 1002 чанков на файл).
- **Fix:** канонический POSIX через `src/core/relpath.py::normalize_rel_path`, применён в `indexer._parse_file_only` (choke: rel + известные хэши), `db_writer.write_records`/`prepare_records`, `index_project_runner` (known_hashes load), `indexing_tools.notify_change`. **T3-свип (обобщение) нашёл ещё 2 критичных индекс-питающих места:** `indexer.index_file` (`:837`) и `index_project_runner._parse_worker` → `current_files_on_disk` (вход prune) — без нормализации prune-множество (`\`) не совпало бы с БД (`/`) (спасал safety-guard >50%); нормализованы. Прочие `str(relative_to)` — doc/display (не индекс), к ревизии отдельно.
- **Guard:** `tests/test_relpath.py` (5); resume-тест обновлён под канонический путь; 27 passed; ruff clean.
- **Статус:** ✅ Fixed + **live-verified collapse**: full reindex → 19653 → **10103** rows, path-duplication **668 → 0**, dup(file_path,chunk_index) **144 → 0**. Исключение data-JSON (5272 чанка) — отдельно.

## 2026-09-25 — graph.db lock заваливал reindex: named mutex владеется ПОТОКОМ, внутрипроцессного lock не было (Fixed)

- **Источник:** reindex `cb8305f7` failed «Could not acquire cross-process lock for graph.db within 30000ms»; `src/core/graph.py:46-128`; `experiments/misc_probes/exp_graph_mutex_cross_thread.py`; `tests/test_graph_lock_threadsafe.py`
- **Root Cause:** `_cross_process_lock` использовал **только** Windows named mutex. Named mutex принадлежит **потоку-владельцу** и не реентерабелен между потоками → второй поток того же MCP-процесса (реиндекс-finalize vs живая graph-операция) не получает мутекс и падает ровно по таймауту. Эксперимент: при удержании 3с второй поток отказал на **0.80с** (=его таймаут). Значит любая graph-операция >30с заваливала реиндекс.
- **Fix:** добавлен внутрипроцессный `threading.RLock` на `db_path` (`_local_graph_lock`) **ПЕРЕД** named mutex → потоки сериализуются (ждут, не падают); мутекс теперь арбитрирует только между процессами.
- **Guard:** `tests/test_graph_lock_threadsafe.py` (второй поток ждёт и acquires после release, `A-out` < `B-in`); 121 graph-related passed; ruff clean.
- **Статус:** ✅ Fixed (live-проверка требует reload MCP — процесс несёт старый `graph.py`).

## 2026-09-25 — Chain-map: 8 незащищённых нативных звеньев индексатора закрыты `run_bounded` (Fixed)

- **Источник:** `docs/research/indexer_chain_map_2026-09-25.md`, `tests/test_reindex_link_bounds.py`
- **Описание:** карта цепочки `run()` (триггер→конец) нашла **8 звеньев того же класса**, что `_safe_optimize`: `_verify_and_repair_table_integrity`, known_hashes `to_lance()`, `embed_batch`, `bulk_write`, prune, BM25 `searcher.reindex`, `summarizer.save_cache`, `save_symbol_index`. Любое зависание нативного вызова = вечная фаза (0 CPU, без сигнала).
- **Fix:** `_bounded_link(fn, label, fatal=)` (обёртка над `run_bounded`, таймаут `MSCODEBASE_LINK_TIMEOUT_SEC`, default 300): non-fatal (verify/known_hashes/prune/BM25/summarizer/symbol) → skip+log; **fatal** (`embed_batch`/`bulk_write`) → `RuntimeError` (resume-safe: инкрементальные чекпойнты). Обёрнуты все 8.
- **Guard:** `tests/test_reindex_link_bounds.py` (4: value/пропуск/fatal-raise/propagate) + 18 связанных + 78 indexer/search passed; ruff clean.
- **Статус:** ✅ Fixed.

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

## 2026-09-19 — Прод-инцидент: миграция колонок lanceDB молча не выполнялась + db_writer разрушал БД при schema-mismatch (Fixed)

- **Источник:** AGENT_DIARY.md#2026-09-19
- **Описание:** два бага, найденные при E10-исследовании поиска (индекс строился на свежей БД, миграция молча не срабатывала):
  1. Старый `db_manager` импортировал `_migrate_text_full_inplace` / `_migrate_add_metadata_columns` из `indexer_table.py` как module-level функции, а это методы класса `IndexerTableMixin` (indexer_table.py:17,66,94) → ImportError → миграция НЕ выполнялась.
  2. `db_writer.is_table_missing` трактовал `"in table schema"` (schema-mismatch) как «таблица отсутствует» → ПОЛНЫЙ rebuild (drop + re-embed ~13 мин) вместо soft-миграции.
- **Fix:** `db_manager` — локальные `_migrate_text_full_inplace(table)` / `_migrate_add_metadata_columns(existing_fields, table)` с `pa.field(name, field.type)` из `self.schema`; `db_writer` — `is_table_missing` исключает `"in table schema"` (recreate только при реальном отсутствии таблицы). +200 строк тестов (`tests/test_lancedb_recreate.py`): миграция legacy→file_mtime_ns/file_size, идемпотентность, «НЕ пересоздавать при schema-mismatch».
- **Статус:** ✅ Fixed (подготовлен к PR в этом коммите). Тесты: test_lancedb_recreate 12 passed, фокус-группа 43 passed.

## 2026-09-19 — E10 (search quality): full-text-эмбеддинг + e5-префиксы + пул reranker 50 → REFUTED (N=10)

- **Источник:** EXPERIMENTS_LOG.md#2026-09-19
- **Описание:** три «выключателя» качества (E10a full-text чанка в эмбеддинг, e5 `query:`/`passage:`-префиксы в llama.cpp-ветке — ONNX/OpenVINO уже имели `_ensure_prefix`, E10c пул reranker 30→50) не дали подтверждаемого сдвига. Чистый прогон (599 файлов / 9514 чанков, 799.9s): fast hit@1=0% hit@5=50%; quality hit@1=20% hit@5=40%; baseline автора 0/50% и 30/30%. Дельта — в пределах шума N=10.
- **Fix (предотвращение):** изменённый код откален к HEAD (поведение клиента = прод); остаток — env-тумблер `MAX_RERANKER_INPUT` с default=30 (нейтрален). Платo «pure-vector» подтверждено повторно (ср. Exp-29 ceiling ~0.23).
- **Статус:** ❌ REFUTED (закрыт, записан в lab exp-43). Следующий ход — AST/Graph-hybrid re-ranking, не эмбеддинговые твики.

## 2026-09-18 — Фаза 1: Incremental Hot-Reload — FreshnessChecker оживлён, hot-reload зашит (AST+FTS5+граф)

- **Источник:** AGENT_DIARY.md#2026-09-18
- **Описание:** FreshnessChecker был мёртв (0 вызовов) и сломан: `to_pandas(columns=)` падает на lancedb 0.34 (рабочее — `to_lance().to_pandas`, 102.2ms/10366 напр.); пропускал НОВЫЕ файлы (KI-109 — файл без notify_change не попадал в индекс); передавал `project_path` вместо `rel` в `_index_single_file`. Хот-reload существовал, но оставлял 3 дыры: FTS5 (incremental_update_fts5 только добавляет), PropertyGraph (remove_file не вызывался), schema (не было mtime/size для stat-first).
- **Fix:** schema + `file_mtime_ns`/`file_size` (db_manager/indexer_table/db_writer/index_pipeline/indexer); FreshnessChecker.verify переписан: stat-first (mtime+size → skip без hash), hash-подтверждение для несовпадений/legacy, новые файлы индексируются, debounce (`FRESHNESS_INTERVAL_SEC`, 0=выкл) + Lock + `is_reindexing`-гейт, фильтрация через real FileGuard; `_index_single_file`: +remove_file (граф) +remove_from_fts5 (FTS5) перед переиндексацией; search-хук `_maybe_hot_reload` (await `asyncio.to_thread`). Полный reindex остаётся fallback (срабатывает при пустом индексе). 6 новых тестов + 233 регресс-прохода.
- **Статус:** ✅ Fixed локально (ветка не запушена, verified_from_clean_state не прогонялся). 7 новых тестов (включая concurrency-стресс N=16) + 1748 полный pytest green. Полный reindex-запуск после миграции существующих БД не выполнялся — запрос владельцу на live-check.

## 2026-09-18 — PRE-EXISTING: tests/test_lsp_vfs_indexing.py broken (MagicMock.embedding_dim truthy)

- **Источник:** попутная находка во время Фазы 1
- **Описание:** `MagicMock().embedding_dim` truthy → `_target_dim = self.embedder.embedding_dim or 768` (db_writer.py:59) = MagicMock → вектор обрезается до zero → `Zero vector ... skipping` → все чанки пропущены → пустая таблица → 8/8 тестов FAIL. В CI не ловится: `pytestmark = slow`, addopts `-m "not slow"` → никогда не гоняется.
- **Fix:** не внесён (выходит за рамки Фазы 1); мой тест `tests/test_freshness_checker.py` обходит через явный `embedding_dim=1024`. Типовое исправление для lsp_vfs: задать `embedding_dim` в mock.
- **Статус:** 🔬 открыт (P2, низкий приоритет)

## 2026-09-11 — Burst-rename: fail-closed VOR отзывает узлы по rename-sweep; 1 ЛОЖНЫЙ отзыв (ADR-7232a6e2ba34)

- **Источник:** AGENT_DIARY.md 2026-09-11 + EXPERIMENTS_LOG 1-B/1-C/RT
- **Описание:** VOR (ADR-0003) проверяет path-якоря против HEAD: rename/move = старый путь отсутствует = SILENT_ABSENCE. Real: 24 авто-REFUTED = 13 мусор якорей + 10 настоящих удалений + 1 ЛОЖНЫЙ (ADR-7232a6e2ba34 жив, отозван по старому пути src/utils/paths.py из prose тела). Synthetic 1-C: git mv 30 файлов одним коммитом → 30/30 REFUTED (100%); body-hash → 30/30 уцелели. Red-Team: batch-по-коммиту спасает настоящие удаления (e661861f = D+R083 в одном коммите).
- **Статус:** 🔬 открыт — решение не принято (вопрос владельцу: body-hash carry против стоимости)

## 2026-09-02 20:51 — drift_gate заблокировал коммит: контроль остановил самого автора

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ? Fixed (коммит A 08281f37 приземлился; B — отдельная незакоммиченная квитанция)
**Root Cause:** предсуществующий BROKEN drift_gate: GitBash bin/ (C:\Program Files\Git\bin) НЕ в PATH проце...
- **Статус:** автоматически синхронизировано

## 2026-09-02 21:40 — COMMIT B (head-freshness) приземлился: cb88c961; + cp1251 encoding-инцидент

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит B cb88c961; все 5 pre-commit hook'ов OK; рабочее дерево чистое)
**Root Cause 1 (B):** после A (fail-closed symbol, никогда REFUTED) свежесть индекса не проверялась — отсутс...
- **Статус:** автоматически синхронизировано

## 2026-09-03 — Fake reindex ETA "~8s" + frozen progress in Finalizing (fixed 32f11662)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (коммит 32f11662; все 5 pre-commit hook'ов OK; полный pytest 1587 passed, 2 pre-existing env_extractor fail)
**Root Cause 1:** `_enrich_job_response` — мёртвая ветка истории (job.project_size никогда не присваивается) + сломанная линейная экстраполяция первых 2с → ложный ETA «~8с». **Fix 1:** единый парсер `_embed_progress_from_log` + реальная скорость из лога (remaining/speed), честный None без данных.
**Root Cause 2:** `_safe_ivf_index` без единого progress-колбэка → бар застывал на 0.8, чанки не росли. **Fix 2:** emission «finalizing» колбэка до/после IVF, отображение 0.8→0.95, честная строка в get_job_status.
- **Статус:** автоматически синхронизировано

## 2026-09-03 19:30 — CI RED: circular import layer ↔ tools_reg (fixed f210ed7c)

- **Источник:** AGENT_DIARY.md#2026-09-03-1930
- **Описание:** My ETA refactor added `tools_reg → layer` import for `_embed_progress_from_log`, closing existing `layer → tools_reg` cycle. `architecture_linter.py` caught it as `[CIRCULAR]`. Fix: extracted parser into neutral `src/core/intelligence/embed_progress.py`. CI run 33796959353 all-jobs green (ubuntu+windows).
- **Статус:** ✅ Fixed

## 2026-09-04 — CI RED: ruff lint errors caught only after push (fixed 986c9be7)

- **Источник:** INC-A35A, CI runs 33847347263/33847972948
- **Описание:** Pre-commit hook did not run ruff, so lint errors (F401, W292) passed locally but failed CI. Repeated 3 times across commits (5a771789, b121ab19, 3dd79ba2).
- **Fix:** Added `scripts/ruff_gate.py` (step 9 in PRE_COMMIT_HOOK template, git_hooks_installer.py). Also fixed stray `\"\"\"` in template introduced by bb05d9af that caused SyntaxError in generated hook.
- **Статус:** ✅ Fixed

## 2026-09-04 — PRE-EXISTING: hook template SyntaxError (bb05d9af)

- **Описание:** Commit bb05d9af added `\"\"\"` (stray triple-quote) after step 8 in PRE_COMMIT_HOOK docstring, creating double `\"\"\"` in generated hook (line 17-18). Hook never compiled — was installed via MCP after commits pushed, so never caught.
- **Fix:** Removed stray `\"\"\"` in same commit 986c9be7.
- **Статус:** ✅ Fixed

## 2026-09-05 — Process leak: hung git cat-file leaks git+git.exe+conhost chains (RAM 81%, ~200 procs)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (code only, не запушено) — verify_diary.py + git_hooks_installer.py
**Root Cause:** `check_commit_exists` (verify_diary.py:361): `proc.communicate(timeout=30)` на таймауте НЕ убивает процесс, `except: pass` глотает TimeoutExpired → Popen утекает навсегда. Git for Windows re-exec (git → git.exe) теряет DETACHED_PROCESS → каждый зависший `cat-file` = 3 вечных процесса (git + git.exe + conhost); стартовая Contradiction Ledger-проверка при CPU/Defender contention.
**Fix:** `_kill_git_tree()` (`taskkill /F /T /PID`) на TimeoutExpired в check_commit_exists + то же в run_script (git_hooks_installer.py:93). Снято на живой цепочке 9660→24156→24428. Тесты: 9 passed (5 commit_guard + 2 subprocess_windows + 2 ledger slow); ruff clean по новым строкам.
- **Статус:** ✅ Fixed

## 2026-09-05 — stale_detector + predict_change стабильно -32001 через MCP (fixed code only)

- **Источник:** AGENT_DIARY.md#2026-09-05-1230
- **Описание:** `error_boundary` применяет `asyncio.wait_for(timeout_ms)`, но внутри `execute` вызывается синхронный блокирующий код (`stale_run` 10-29s, `static_predict` git-subprocess). На Windows wait_for НЕ может отменить работающий синхронный блок → event loop заблокирован, клиент отваливается по -32001 до ответа. Эксперимент: wait_for(10s) вокруг sync stale_run НЕ прервал (24.7s); `asyncio.to_thread` + wait_for(5s) → реальный таймаут, loop жив.
- **Fix:** оба инструмента обёрнуты в `asyncio.to_thread` (doc_tools._scan_docs, predict_tools.static_predict/ChangePreview.run); таймауты 10s→60s (stale), 60s→120s (predict). Прямые вызовы: stale OK 13.0s, predict OK 1.4s; 62 теста passed.
- **Статус:** ✅ Fixed (code only, MCP reload требуется)

## 2026-09-06 — lock_guard acquire/release падал ThreadExpired: таймаут 60s < pre-commit hook 5-10min (fixed)

- **Источник:** AGENT_DIARY.md#2026-09-06-2100
- **Описание:** `scripts/lock_guard.py` (`_run`) использовал `timeout=60s` для `git commit`, но любой commit прогоняет pre-commit hook (verify_diary → полный pytest), занимающий 5-10 мин на Windows. 60s давал TimeoutExpired даже когда коммит успешно создавался в фоне → ложное ощущение провала протокола `.locks` при параллельной работе агентов.
- **Fix:** `_run` timeout 60→900s. Проверено полным циклом acquire→status→release на `README.md`, `scripts/lock_guard.py`, тестовом ресурсе: exit 0, коммиты+push проходят hook. INC-CD6E.
- **Статус:** ✅ Fixed

## 2026-09-06 — [P] sync-subprocess в async-MCP вызовов (context_tool, system_tools) — fixed

- **Источник:** AGENT_DIARY.md#2026-09-06-2130; кандидаты: `context_tool.py:280` subprocess.run в get_context (30s), `system_tools.py:370/408/446` (dual_arm, mutmut-WSL 180s).
- **Fix:** `_section_git` стал async, `subprocess.run` обёрнут в `asyncio.to_thread` (context_tool.py); wsl_check/`_run_mutmut_in_wsl`/`_verify_mutmut_can_fail` — через `asyncio.to_thread` (system_tools.py). `git_tools._git_run` уже был async (эталон, не тронут). Проверено: test_context_tool 2 passed, ruff clean, импорты OK, реальный `_section_git` возвращает git-history.
- **Статус:** ✅ Fixed (code only, MCP reload требуется)

## 2026-09-06 — [P-001 рецидив] cmd-окна при запуске/открытии проекта: powershell/nvidia-smi БЕЗ CREATE_NO_WINDOW (fixed)

- **Источник:** AGENT_DIARY.md#2026-09-06-2200
- **Описание:** Повтор P-001 (фикс 2026-08-14 пропустил сайты): `resource_monitor.py:303` (powershell Get-CimInstance RAM) и `:503` (nvidia-smi) БЕЗ creationflags; `llama_runner.py:1338/1366/1394` (powershell Get-NetTCPConnection/Get-CimInstance/taskkill в kill_process_on_port) БЕЗ флага. Дочерние консольные процессы (git/netstat) защищены, а powershell/nvidia-smi из фоновых сервисов — открывали видимое окно cmd при каждом открытии/запуске проекта (pythonw не подавляет создание консоли).
- **Fix:** CREATE_NO_WINDOW добавлен во все 5 сайтов (3 файла: resource_monitor.py ×2, llama_runner.py ×3). Guard: `tests/test_subprocess_windows.py` — из placeholder'ов превращён в реальный статический тест (grep по всем src/**/*.py за консоль-спавнами powershell/wsl/wmic/netstat/taskkill/nvidia-smi без флага → fail) + тест daemon-потоки без capture_output. Прогон: 2 passed.
- **Статус:** ✅ Fixed

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

## 2026-09-08 — B4: статический цикл parser ⇄ language_imports (осознанный техдолг, lazy, allowed)

- **Источник:** `architecture_linter` (Invariant 3) после деривации `LANGUAGE_IMPORT_NODES` из `CodeParser.IMPORT_NODE_MAP` (B4).
- **Описание:** `src.core.language_imports` импортирует `src.core.indexing.parser` (для деривации карты), а `parser._extract_fallback_imports` импортирует `language_imports` (fallback-режим 2). Статически — цикл; в рантайме ни один импорт при загрузке модулей не выполняется: parser импортирует language_imports только локально в функции; language_imports импортирует parser только лениво (module `__getattr__` → `_derive_language_import_nodes`, PEP 562) при первом обращении к `LANGUAGE_IMPORT_NODES`.
- **Fix:** пара добавлена в `_ALLOWED_CORE_CYCLES` (scripts/architecture_linter.py) с комментарием; `LANGUAGE_IMPORT_NODES` переведён на ленивую деривацию (кэш `_LANGUAGE_IMPORT_NODES_CACHE`, `__getattr__`), прямое обращение к карте внутри модуля заменено на `_get_language_import_nodes()`. Удалить из allowlist после выноса `IMPORT_NODE_MAP` в нейтральный модуль (не историю карт в parser) — тогда language_imports сможет импортировать parser односторонне.
- **Статус:** ✅ Fixed (allowed tech debt, deferred refactor; целевые 68 passed, architecture_linter 4/4 OK)
- **Дедлайн рефактора:** 2026-10-01 · **Owner:** ManSio

## 2026-09-08 — B3: grammar-карты parser.py (imports/calls/assigns/conditions) внесены + живые фиксы

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed / **Root Cause и итог:** внесены из study 05 карты CALL_NODES/IMPORT_NODE_MAP/ASSIGNMENT_NODE_MAP/CONDITIONAL_NODE_MAP (пер-язычные) в `src/core/indexing/parser.py`. Живые tree-sit...
- **Статус:** автоматически синхронизировано

## 2026-09-08 12:35 — B4: import-экстракция через language_imports (деривация карт + флаг-гейт)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed / **Root Cause:** два источника node-типов импортов (parser.IMPORT_NODE_MAP и литерал LANGUAGE_IMPORT_NODES) расходились (kt/dart/php); ungated fallback-2 в мосте.
**Fix:** LANGUAG...
- **Статус:** автоматически синхронизировано

## 2026-09-09 19:35 - .h заголовки C не индексируются (SUPPORTED_EXTENSIONS без .h)

- **Источник:** AutoCoder аудит/E-S1 live-проба 2026-09-09 (внешняя сессия, репо не изменялось до этой записи)
- **Описание:** **Status:** ✅ Fixed (2026-09-09, commit 0301fa93). CodeParser.SUPPORTED_EXTENSIONS/parsers не содержали ".h" (есть .hpp/.cxx/.cpp) - заголовки C-проектов выпадали из AST-индексации (импорты/вызовы/присваивания). Эмпирика E-S1 (shallow-клоны, кап 300 файлов/язык): curl - 65/300 файлов с явными #include дали 0 рёбер (преимущественно .h), dart-http .c-папка 0/9. Бонус-результат той же пробы: импорт-карты живые на 6 языках (java 0.867 / php 0.797 / c 0.680 / kotlin 0.853 / dart 0.940 / ruby 0.618), вызовы php 0.813 / ruby 0.562 / c 0.250 / dart 0.080 - синтетический дефект "вызовы PHP/Ruby/C/Dart" снят.
- **Fix:** ".h" добавлен в PARSE_EXTENSIONS (src/core/extensions.py) + C-парсер для ".h" (parser.py) + карты: env (".h":"c"), IMPORT_NODE_MAP (preproc_include), ASSIGNMENT_NODE_TYPES (init_declarator/assignment_expression), CONDITIONAL_NODE_TYPES (if/for/while/... как у ".c"). Пояснение: ".h" уже был в INDEX_EXTENSIONS (вектор индексировался), не хватало именно AST-слоя ⇒ map_lies. +1 тест (test_h_header_preproc_include). Повтор E-S1 пробы на curl (ожидание: map_lies .h -> ~0) — отложен, verified на уровнеunit-теста C-парсера.
- **Статус:** ✅ Fixed

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
  - Ревизия всех 18 репо `D:\Project\` (субагент): лучшие «чистые» кандидаты — `gemma_agent` (1102 py / 464 test_*.py / git), `456789/ARCLUX` (TS), `bench_projects` (black/httpbin/headroom). До этого детектор и TESTS-рёбра проверялись только на собственном репо.
  - `bootstrap_entities.detect_entities` обобщается: **black(src)=16 dataclass / 2 NT / 73 classes**, **gemma_agent/core=65 dc / 228 classes**, gemma_agent/modules=1 dc, httpbin=0 (старый код без dataclass). Найдена слепота: детектор жёстко завязан на подкаталог `src/` — gemma_agent использует `core/`/`libraries/`/`modules/`, нужен явный `src_dir` (параметр уже есть).
  - **[РЕШЕНО 2026-09-17]** Хардкод `src/` устранён: `resolve_src_root()` — детерминированный приоритет (явный `src_dir` → env `MSCODEBASE_BOOTSTRAP_SRC_DIR` → известные раскладки `src/lib/core/libraries/modules` → каталог с именем проекта → статистический fallback с исключением `tests/docs/venv`). Валидация: MSCodeBase→src, gemma_agent→core (ранее требовал источник), black→src, httpbin→httpbin. Результаты совпадают с ручным `src_dir` (1:1). Тесты 14/14, в т.ч. 6 новых (core-layout/имя-проекта/статистика/env/приоритет-env/пустой-прогон). Red Team 3/3 (venv-tests не захватываются статистикой, битый env не ломает, относительный src_dir работает).
  - **[Шаг 3 (Dynamic Trace command) — РЕАЛИЗОВАН, 2026-09-18]**
    - `git mv experiments/bootstrap/dynamic_trace_plugin.py src/core/bootstrap_trace_plugin.py` — плагин штатный; импорт `-p src.core.bootstrap_trace_plugin`.
- `src/core/bootstrap_pipeline.py` (оркестратор: resolve_src_root → detect_entities → pytest subprocess §5.16-safe → index_src_functions → build_tests_edges) + `bootstrap_tool.py` (`bootstrap_pipeline`, MCP+CLI). Подводные камни — AGENT_DIARY 2026-09-18: PYTHONPATH только по авто-детекту `_plugin_importable` (namespace shadowing `src`-пакета), BOM-guard `utf-8-sig`.
     - Тесты: `tests/test_bootstrap_pipeline.py` (5 интеграц., без моков) + 3 на `index_src_functions`; 28/28 green + полный suite passed. Клиент параметризован по env (`TRACE_SRC_ROOT`/`TRACE_OUT`) → чужие проекты: gemma_agent 2737/2882 (95.0%) тестов имеют ≥1 src-функцию; black скомпилирован в `.pyd` → sys.settrace не ловит нативные кадры (fallback на статику Exp 9 обязателен).
- **Веб-исследование и audit «гиблых мест» (2026-09-15, всё ПРОВЕРЕНО эмпирически):** (1) **sysmon+dynamic_context — ОПРОВЕРГНУТА**: верные контексты даёт pytest-коллекция, ручной `switch_context` → пустые `['']` (coverage.py 7.14.1); (2) **контексты ≈3-7% — НЕ воспроизвелось**: Exp 8 (2026-09-16) overhead **+19.96%** (221.78 vs 184.88s) > нашего sys.settrace (+13.6%) → штатный драйвер Шага 3 = `dynamic_trace_plugin.py`, coverage остаётся валидационным оракулом (контексты качественные: 1548/1549, 75.5% src-строк привязаны); (3) **Tarantula — Exp 7b**: rank≤3 у 22.6% тестов (далеко от 60-70%), НО precision низких рангов высока (все rank1-3 верны) → аннотация confidence (~16%), не селектор; TESTS-ребро строится из полной трассы; (4) **mutation-testing как ground truth — дорого/хрупко** (FSE'20, Google 33M; флаки раздувают score); (5) **pytest-testmon — не копируем** (line-based, сужение рерана ≠ граф-ребро TESTS для LLM-контекста); (6) **dev.to-кросс-чек**: «TRUE Coverage» (Dawson, 2026-07-22) подтверждает плато статики и шум shared-utils (наш safe_mkdir/get_data_root кейс 1:1; CI 43min→4min, precision 15%→95%); «Empirical Failure Modes» (Arthur, 2026-07-31) — Pass-Through Test Mirage (наш «фантомный код»), Python 3.14 sys.monitoring reachability = наш бэкенд, AST orphan-detection = наш Шаг 1; **ниша TESTS-рёбер для LLM-контекста ими не занята** (per-test coverage используется только для selection/rejection); (7) edge-case (Gemini): без тестов → статика; бинарники → Docker+microtrace; async → OpenTelemetry по trace_id.

## 2026-09-11 — Burst-rename: fail-closed VOR отзывает 100% при ONE rename-sweep (ответ Statewave на dev.to)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Closed (эксперименты, ответ опубликован)
**Root Cause:** VOR (ADR-0003) проверяет ПУТЬ-якоря против текущего HEAD. Rename/move = старый путь отсутствует = SILENT_ABSENCE = отзыв, хотя файл...
- **Статус:** автоматически синхронизировано

## 2026-09-11 — VOR read-path fix (PR #34) + «8-минутный коммит» = НЕ баг (решение владельца)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ PR #34 создан, hooks green; скорость тестов — осознанное решение, код НЕ менялся.
**Root Cause:** (1) read-path VOR ре-сканировал prose тела ADR через `_PATH_RE`, хотя явные `data.anchor...
- **Статус:** автоматически синхронизировано

## 2026-09-10 — Exp 1 (Catch-up Rate) + Exp 3 (HEAD polling): VOR масштабирование и внешний дрифт

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fix (замеры, кода не менялось). **Root Cause (KNOW ISSUES «Lazy-only верификация»):** вопрос, успевает ли VOR проверить ACTIVE-узлы в рамках budget_ms=50 (read-path) / 250 (background id...
- **Статус:** автоматически синхронизировано

