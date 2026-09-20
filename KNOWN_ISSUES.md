# KNOWN ISSUES — MSCodeBase Intelligence

> Синхронизируется из `AGENT_DIARY.md` при каждом [🏁 ИТОГ].
> Формат: дата | что было | статус | fix

---


**18 entries** — compressed per §4.8 R3 (conclusion-first; dedup 2026-09-08)

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

## 2026-09-07 — Lazy-only верификация: VOR вызывается только из intel_get_project_memory, нет TTL/фона

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (H1, 2026-09-09 — фоновая проверка через IdleScheduler-hook; см. основную запись выше)
**Root Cause:** По дизайну (ADR-0003) VOR ленивый, но точки вызова всего одна (layer.py:1097); IdleSch...
- **Статус:** автоматически синхронизировано


## 2026-09-07 — Cypher-движок: анонимные узлы/рёбра ломали MATCH; ActionReceipt не писался из write-пути

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (оба блока закрыты, тесты зелёные)
**Root Cause:** (1) Cypher: `from_node_alias` дефолтил в `n1`, а генератор создавал `n{path_idx*2}` для анонимного узла → `no such column: n0.id`; ...
- **Статус:** автоматически синхронизировано


## 2026-09-03 — Fake reindex ETA "~8s" + frozen progress in Finalizing (both fixed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (commit 32f11662; 5 pre-commit hooks OK; full pytest 1587 passed, 2 pre-existing unrelated env_extractor failures)
**Root Cause 1 (ETA "~8s"):** `_enrich_job_response` had a dead h...
- **Статус:** автоматически синхронизировано


## 2026-09-03 19:30 — CI RED: circular import layer ↔ tools_reg (architecture_linter)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (commit f210ed7c; CI all-jobs green on ubuntu+windows)
**Root Cause:** My ETA refactor added `tools_reg → layer` import for `_embed_progress_from_log`, closing an existing `layer →...
- **Статус:** автоматически синхронизировано


## 2026-09-04 11:15 — CI RED: ruff lint errors caught only after push (3 commits)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (commit 986c9be7)
**Root Cause:** Pre-commit hook did not run ruff. CI (`ruff check src/ tests/` in ci.yml) caught F401/W292 only after push, forcing fix-commits. Repeated 3 times ...
- **Статус:** автоматически синхронизировано


## 2026-09-05 12:30 — FIX: stale_detector + predict_change стабильно таймаутили через MCP (-32001): блокирующий sync-код в async-контексте

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (code only, не запушено) — src/mcp/tools/doc_tools.py + predict_tools.py
**Root Cause:** `error_boundary` применяет `asyncio.wait_for(timeout_ms)` вокруг `execute`, но внутри `exec...
- **Статус:** автоматически синхронизировано


## 2026-09-06 21:00 — Починка lock_guard: таймаут 60s ломал весь .locks-протокол

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed / **Root Cause:** `scripts/lock_guard.py` `_run` default timeout=60s — любой `git commit` прогоняет pre-commit hook (verify_diary → полный pytest 5-10 мин на Windows), поэтому acqu...
- **Статус:** автоматически синхронизировано


## 2026-09-06 21:30 — sync-subprocess в async-MCP (context_tool, system_tools) — fixed

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (code only) / **Root Cause:** системная проверка после фикса stale/predict: нашлись ещё sync `subprocess.run` внутри async `execute`. `GetContextTool._section_git` (git log через s...
- **Статус:** автоматически синхронизировано


## 2026-09-06 22:00 — P-001 рецидив: cmd-окна при запуске/открытии проекта (powershell/nvidia-smi без CREATE_NO_WINDOW) — FIXED

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed / **Root Cause:** повтор инцидента 2026-08-14 (P-001, «чёрные окна CMD»). Фикс 2026-08-14 добавил CREATE_NO_WINDOW для git/netstat/wmic/taskkill в runtime, но ПОЗВОЛИЛ дыру: `resou...
- **Статус:** автоматически синхронизировано


## 2026-09-08 — B3: grammar-карты parser.py (imports/calls/assigns/conditions) внесены + живые фиксы

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed / **Root Cause и итог:** внесены из study 05 карты CALL_NODES/IMPORT_NODE_MAP/ASSIGNMENT_NODE_MAP/CONDITIONAL_NODE_MAP (пер-язычные) в `src/core/indexing/parser.py`. Живые tree-sit...
- **Статус:** автоматически синхронизировано


## 2026-09-08 12:35 — B4: import-экстракция через language_imports (деривация карт + флаг-гейт)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed / **Root Cause:** два источника node-типов импортов (parser.IMPORT_NODE_MAP и литерал LANGUAGE_IMPORT_NODES) расходились (kt/dart/php); ungated fallback-2 в мосте.
**Fix:** LANGUAG...
- **Статус:** автоматически синхронизировано


## 2026-09-08 19:40 — collect() в Cypher: json_group_array + типизированный декод (fixed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed. / **Root Cause:** KNOWN_ISSUES 2026-09-07 ⏳ — `_translate_return_expr` заявлял `collect` как Supported, но SQLite не имеет функции COLLECT («no such function»); ни одного теста на...
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

## 2026-09-18 — Фаза 1: Incremental Hot-Reload (FreshnessChecker оживлён + hot-reload + KI-109)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (7 тестов свежести включая concurrency-стресс N=16 + 1748 полный pytest green; ветка вне PR — локально)
**Root Cause:** FreshnessChecker (freshness.py) был мёртв (0 вызовов) и СЛОМАН...
- **Статус:** автоматически синхронизировано


## 2026-09-11 — Burst-rename: fail-closed VOR отзывает 100% при ONE rename-sweep (ответ Statewave на dev.to)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Closed (эксперименты, ответ опубликован)
**Root Cause:** VOR (ADR-0003) проверяет ПУТЬ-якоря против текущего HEAD. Rename/move = старый путь отсутствует = SILENT_ABSENCE = отзыв, хотя файл...
- **Статус:** автоматически синхронизировано


## 2026-09-09 — H1: фоновый VOR-проход (IdleScheduler) — память перепроверяется без вызова агента

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (6 новых тестов + 1674 полный pytest green; ветка chore/experiments-es1-es2-0909)
**Root Cause:** VOR вызывался ровно из 1 места (intel_get_project_memory, layer.py:1097); idle-задач...
- **Статус:** автоматически синхронизировано


## 2026-09-09 — H2: .h заголовки C включены в AST-индексацию (PARSE_EXTENSIONS + C-парсер)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (commit 0301fa93; KNOWN_ISSUES 2026-09-09 19:35 закрыт)
**Root Cause:** ".h" был в INDEX_EXTENSIONS (вектор-чанкинг шёл), но НЕ в PARSE_EXTENSIONS → CodeParser.parse_file возвращал [...
- **Статус:** автоматически синхронизировано


## 2026-09-09 — Аудит «Active MSCodeBase» (Exhibit #23: MCP tool available but never invoked)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Open — зафиксирован гэп (исследование + план, код НЕ вносился)
**Root Cause:** фундамент (VOR / DebounceBatch / ConsistencyTracker / IdleScheduler / PropagationEngine) существует, но компо...
- **Статус:** автоматически синхронизировано


## 2026-09-10 — H1 idle-VOR + system_alerts (цепь «файл изменён → STALE → VOR → alert агента» собрана)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed / **Root Cause (Exhibit #23, 2026-09-09):** компоненты цепи существовали по отдельности, но VOR вызывался ровно из 1 места (layer.py:intel_get_project_memory), mark_stale("memory")...
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


## 2026-09-10 — Exp 2 (Agent Behavior) + Exp 4 (Fail-Closed Freshness Gate)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed. **Root Cause (Exhibit #23, 2026-09-09):** inform-the-agent approach insufficient — agent can ignore STALE alerts; PlanFence 30/30 failures confirms action-validation unreliable; s...
- **Статус:** автоматически синхронизировано


## 2026-09-11 — H3 TTL-гниение: last_checked для всех проверенных + label stale_ttl (doc 10 closed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (9 новых тестов + 1725 полный pytest green; doc 10-continuous-verification H1+H2+H3 done)
**Root Cause:** INCONCLUSIVE/непроверенные узлы «висят вечно» без следа проверки: live-срез ...
- **Статус:** автоматически синхронизировано


## 2026-09-13 — H4: agent-memory lifecycle в масштабе dev.to KB — бутылочное горлышко = сетевой capture, не граф

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (эксперимент подтверждён; сопровождение задачи closed)
**Root Cause:** при росте базы 3,989 → 13,519 статей (3.4x), refresh own занял 10м38с на 13.5k статей/82.5k комментов (134 сете...
- **Статус:** автоматически синхронизировано

