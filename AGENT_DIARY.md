## Key Historical Decisions

- **PyPI-packaging + user-data isolation (2026-08-28):** wheel теперь содержит `tools.stale_detector`, `adapters`, `locales` (норм. данные в site-packages); бинарники/модели в pip-режиме — `get_data_root()` (`%LOCALAPPDATA%\mscodebase`), гейт-маркер `__mscodebase_ext__.marker` отличает расширение от установленного пакета; CLI `--project-path/--project-dir` → env `MSCODEBASE_PROJECT_PATH` (приоритет НАД CWD, trust_self_index); `PROJECT_PATH` остался после CWD (multi-window сохранён). Live-Smoke из чистого venv: tools-ok, `en (78 ключей)`, корень резолвится. Файлы: `pyproject.toml`, `project_resolution.py`, `main.py`, `llama_install.py`. INC-C4CD.

- **Server freeze during full reindex (2026-08-25):** root cause — `begin_write()` держит `_write_lock` (RLock) весь reindex (~7.5 мин embedding), а `IndexStatusReporter.get_status()` синхронно на event-loop-потоке ждал тот же lock (intel_get_runtime_status/require_ready_project/ProjectContext) → заморозка ВСЕХ MCP-вызовов. Фикс: reindex fast-fail в get_status (кэш + status="reindexing") + asyncio.to_thread в 3 loop-точках + guard в _get_stale_warning.
- **Embedder:** multilingual-e5-small-int8 + batch=32 (100 ch/s sustained) — 2026-07-17
- **Concurrency:** AsyncInferQueue → лок (тихая гонка подмены векторов) — 2026-07-18
- **Cache:** Chunk-level content-addressed cache (skip re-embedding) — 2026-07-18
- **Windows:** subprocess.run(capture_output) в daemon-тредах = deadlock; Popen+communicate (§5.16) — 2026-07-18
- **Артефакты:** progress.json вне проекта, системная папка (Задача 4/5) — 2026-08-03
- **Hub & Spoke:** codebase(action) + DEFAULT-allowlist MSCODEBASE_MCP_TOOLS (скрытые инструменты — через hub) — 2026-07-22
- **Защита:** PID-lock + self-healing + auto-index guard (3-layer defense) — 2026-08-02
- **Security:** SQL injection fixes (alias/layer), FileGuard fail-open → fail-closed в write_tools — 2026-07-27/08-02
- **P0 reindex deadlock:** bulk-загрузка known_hashes вне RLock между потоками — 2026-07-31
- **Multi-window:** CWD-first резолв проекта (per-process сигнал вместо глобального SQLite active_workspace_id) — 2026-08-07
- **Type resolution:** query-time LSP через basedpyright (не index-time USES_TYPE) — 2026-08-06/07
- **Edge transparency:** confidence EXTRACTED/INFERRED + evidence в properties рёбер — 2026-08-08
- **Memory retraction (ADR-0002):** status ACTIVE|VERIFIED|REFUTED + `intel_retract_memory_node` (OWP lifecycle VERIFIED→REFUTED, причина обязательна) — 2026-08-11
- **Memory v2 (2026-08-12):** SUPERSEDED-фильтр в retrieval + verify-on-read не переписывает терминальные статусы + ADR-0004 Propagation Engine (каскадная ретракция) + метрика false-retraction
- **Единый PathManager + GC (2026-08-13):** crash-лог → data_root/logs/crash.json (был ~/.mscodebase_crash_log.json); логи MCP → data_root/logs (были ext/.codebase_indices/logs, стирались при переустановке); fallback моделей → data_root/models (был ~/.cache/mscodebase — Linux-путь на Windows); телеметрия скрипта → data_root; ArtifactGC (30д проекты / 90д телеметрия / 7д логи / пустые сразу); autouse-изоляция data_root в тестах (2481 папка мусора)
- **PID-reuse guard llama_runner (2026-08-13):** _InterProcessLock._is_pid_alive — OpenProcess(SYNCHRONIZE) ложно считал завершённый процесс живым (объект жив, пока у родителя handle) → stale PID блокировал запуск reranker весь день; фикс: GetExitCodeProcess==259 + имя llama-server.exe
- **Дедупликация серверов при 2 окнах (2026-08-13):** lock embedder/reranker держится ДО готовности порта (был — до Popen; llama-server bind'ит через секунды → второй MCP спавнил дубль); ONNX _wait_for_server 30→60s (модель 600MB)
- **LIVE-SMOKE (2026-08-13):** scripts/smoke_e2e.py — реальные сервисы без моков (embed llama.cpp / rerank BGE-M3 / векторный поиск по реальному LanceDB); §7 п.10b: для runtime-изменений ✅ = live-check, не только pytest (инцидент: 7 тестов зелёные по неверной причине)
- **Чёрные окна CMD (2026-08-14):** MCP запускался как `venv\Scripts\python.exe` (console-подсистема) → каждое окно Zed = своё чёрное окно; фикс: `pythonw.exe` в extension.toml + CREATE_NO_WINDOW во ВСЕХ runtime subprocess (13 файлов) — с pythonw (нет консоли) незакрытые git/wmic/netstat мигали бы окнами
- **FA=0.00 ≠ качество guardrail (2026-08-15):** Exp 1-L Day 3 — qwen3.6/3.7 (zero-shot VOR) достигают FA=0.00 ценой recall(real)=0.08–0.20 (code_first: 2/25 правды принято, 7/25 активно отвергнуто) — fail-closed политика, а не «фильтрация лжи»; выбор LLM для verify-on-read = выбор политики (fail-closed qwen vs max-coverage glm), recall(real) обязан быть в метриках. CoT (V3/Part 5) НЕ окупается: только qwen3.6 recall 0.08→0.20 при цене ×30–65
- **Evidence Ladder (2026-08-15, Exp 2-E E1-E3):** форма evidence — переменная; file_content = лучший recall (qwen 0.92), graph = закрытие present-trap ТОЛЬКО у evidence-честных моделей (qwen3.7 FA trap 1→0 ценой recall 0.92→0.76); fail-open (glm-4.7: FA trap 6/6) не лечится ни одной формой — свойство модели. VOR-конвейер: фрагмент файла для recall + графовая проверка субъекта отдельным сигналом; glm-семейство исключить
- **VOR MATCHED/DELIVERED (2026-08-16):** per-node накопительные счётчики matched/delivered в verify_cache.json (ключ node_id — переживают HEAD); starved = виден ≥2 циклов, ни разу не проверен — отличает голодание по бюджету от бага якорей (раунд 2 Тома; «пол Тома» = раунд 1)
- **CONTRADICTION RESOLVED [2026-08-28]:** Агент перезаписал `.agent_task_state.md` чужой задачи (`Port env-access extractor`) при запуске Red Team — нарушение §0.1 (Task State Persistence) + §4.9 (Contradiction Hunting). Исправлено: восстановлен оригинальный `.agent_task_state.md`, Red Team-задача перенесена в `.red_team_state.md`. Root cause: отсутствие проверки содержимого файла перед `write_file`. Guard: перед любым `write_file` на `.agent_task_state.md` — читать первую строку и сверять с ожидаемым заголовком задачи.

---

---

## [2026-09-11] — Burst-rename: fail-closed VOR отзывает 100% при ONE rename-sweep (ответ Statewave на dev.to)

**Status:** Closed (эксперименты, ответ опубликован)
**Root Cause:** VOR (ADR-0003) проверяет ПУТЬ-якоря против текущего HEAD. Rename/move = старый путь отсутствует = SILENT_ABSENCE = отзыв, хотя файл жив. Синтетика (1-C): git mv 30 файлов одним коммитом → 30/30 REFUTED (100%); body-hash carry → 30/30 уцелели. Реальная память (1-B): 24 авто-REFUTED = 13 мусор якорей + 10 настоящих удалений + 1 ЛОЖНЫЙ отзыв (ADR-7232a6e2ba34: узел жив, отозван по старому пути src/utils/paths.py из prose «X → Y» в теле; хранимые якоря adapters/zed/zed_config.py + src/main.py существуют).
**Fix (эксперименты, не код):** burst_rename_audit.py / burst_sweep_exp.py / redteam_burst.py в experiments/1V_memory_contamination/. Решение для производства не принято (вопрос владельцу: body-hash carry-compat против стоимости).
**Guard:** Red-Team показал — «батч по коммиту» (мульти-уёдание = move) смешивает R* с D* (e661861f: init.py удалён + windows.py R083): спасал бы и настоящие удаления. Точный ревью complex: git --diff-filter=R по истории.
**verified_from_clean_state:** ⚠️ не прогонялся (скрипты экспериментов, не runtime-код)

## [2026-09-07] — Lazy-only верификация: VOR вызывается только из intel_get_project_memory, нет TTL/фона

**Status:** Open — зафиксировано как проблема + план эксперимента (10-continuous-verification.md)
**Root Cause:** По дизайну (ADR-0003) VOR ленивый, но точки вызова всего одна (layer.py:1097); IdleScheduler включается только из record_tool_call(), VOR в idle не подключён, 2 из 3 idle-задач — заглушки (_improve_summaries_batch/_check_index_health — пустые тела). Живой срез текущего проекта: 42/136 узлов ACTIVE без verified_at/TTL висят с 2026-08-11; узлы без якорей → INCONCLUSIVE → VOR не пишет ничего → «проверено» = «кто-то когда-то вызвал».
**Fix (план эксперимента, не внесён):** H1 idle-ticker VOR с budget; H2 event-driven на HEAD (ключ hash(node_id+commit_sha) уже есть); H3 TTL-гниение INCONCLUSIVE → STALE. Baseline замера: полный прогон 136 узлов = 431.6ms (fingerprint 371.6ms) — дешевле порога. Контр-риски: false_retraction не выше 0.083%, цена при нагрузке.
**Guard:** новые «проверки» проектной памяти обязаны иметь точку вызова вне ручного чтения (idle/event/ttl) — иначе это снова lazy-by-hand.
**verified_from_clean_state:** ⚠️ не прогонялся (изменения только .md, live-данные из реального сервера PID 10036)

---
## [2026-09-09] — H1: фоновый VOR-проход (IdleScheduler) — память перепроверяется без вызова агента
**Status:** Fixed (6 новых тестов + 1674 полный pytest green; ветка chore/experiments-es1-es2-0909)
**Root Cause:** VOR вызывался ровно из 1 места (intel_get_project_memory, layer.py:1097); idle-задача `_check_index_health` — заглушка → пока агент не дёрнет memory, REFUTED/VERIFIED не копились (Exhibit #23 аудит 2026-09-09; KNOWN_ISSUES 2026-09-07, дедлайн 2026-09-15).
**Fix:** (1) `set_idle_vor_callback()` в task_queue.py + вызов в `_check_index_health` (hook-инъекция: task_queue не импортирует layer → нет cycle-import). (2) `run_background_verify(budget_ms=250)` в layer.py: locked()-guard (Red Team a1 — agent-путь приоритетнее), общий `_write_lock` + `get_verifier`-регистр → idle-VOR и agent-VOR сериализуются в `_persist_transitions` без второй lock/гонки; `_build_symbol_resolver` вынесен из `intel_get_project_memory` (DRY, эквивалентный рефакторинг). (3) Регистрация hook в `server_tools._register_intelligence_tools` после создания `intel_layer` (enable_idle_scheduler вызывается раньше — layer ещё нет). Red Team 3 атаки: lock contention (защищено общим lock+budget), блокировка idle-потока (budget_ms=250 + cooldown 120s), stale hook при перерегистрации (перезапись каждый старт + try/except).
**Guard:** новые точки проверки памяти обязаны использовать существующий lock/verifier-регистр (не создавать второй) — иначе гонка записей project_memory.json.
**verified_from_clean_state:** ⚠️ не проверено — коммит не запушен, clean-state script не прогонялся; полный pytest 1674 passed локально, ruff-ошибка Fix

---
## [2026-09-09] — H2: .h заголовки C включены в AST-индексацию (PARSE_EXTENSIONS + C-парсер)
**Status:** Fixed (commit 0301fa93; KNOWN_ISSUES 2026-09-09 19:35 закрыт)
**Root Cause:** ".h" был в INDEX_EXTENSIONS (вектор-чанкинг шёл), но НЕ в PARSE_EXTENSIONS → CodeParser.parse_file возвращал [], [] (parser.py:438). C-заголовки без AST: нет импортов (#include), вызовов, присваиваний, condition_path. E-S1 live-проба (2026-09-09): curl 65/300 файлов с #include дали 0 рёбер — преимущественно .h; dart-http .c 0/9.
**Fix:** (1) extensions.py PARSE_EXTENSIONS: ".c" → ".c", ".h". (2) parser.py: регистрация `self.parsers[".h"] = <C-парсер>` (tree_sitter_c, не cpp — .h = C). (3) Карты языка по аналогии с ".c": `_EXT_TO_ENV_LANG` {".h": "c"}, IMPORT_NODE_MAP (preproc_include), ASSIGNMENT_NODE_TYPES (init_declarator, assignment_expression), CONDITIONAL_NODE_TYPES (if/for/while/do/switch/case/conditional_expression). (4) +1 тест `test_h_header_preproc_include` (57 passed в файле; full gate-zero через pre-commit). Red Team: прототип-only .h → fallback-line-chunking (не ломается), пустой .h → 0, .hpp остаётся CPP (другая карта не тронута).
**Guard:** интервал "вектор индексируется, AST нет" (INDEX_EXTENSIONS \ PARSE_EXTENSIONS) — проверять BATCH-check'ом при добавлении языка; тест на каждый новый suffix в PARSE_EXTENSIONS.
**verified_from_clean_state:** ⚠️ не проверено — повтор E-S1 live-пробы на curl отложен (требует внешний клон); unit-проверка: CodeParser.parse_file(.h) real tree-sitter → chunks≥1, symbols=[helper]

---
## [2026-09-07] — Cypher-движок: анонимные узлы/рёбра ломали MATCH; ActionReceipt не писался из write-пути
**Status:** Fixed (оба блока закрыты, тесты зелёные)
**Root Cause:** (1) Cypher: `from_node_alias` дефолтил в `n1`, а генератор создавал `n{path_idx*2}` для анонимного узла → `no such column: n0.id`; переменная ребра `[e:]` не регистрировалась → `no such column: e`. (2) Receipts: `_contract_record` (ChangeIntent) вызывался только в rename-fallback и safe_delete; replace/insert/move/workspace_edit писали файл напрямую → ни ChangeIntent, ни ActionReceipt.
**Fix:** (1) cypher_sql.py: alias левого узла резолвится в `n{path_idx*2}`, `edge_vars` + `edge_prop_map` (type/source_id/target_id → колонки, остальное → json_extract), `count(e)` → COUNT(e.id). 10 регресс-тестов + 5 Red Team атак. (2) write_tools.py: новый `_contract_receipt()` (build_receipt + ActionReceiptStore) вызывается из `_contract_record`; сам `_contract_record` добавлен во все write-пути (replace/insert/rename-LSP/move включая refs). Receipt-запись warning-only, не валит write. +1 тест (JSONL создаётся, verdict VERIFIED).
**Guard:** write-операция без ChangeIntent+ActionReceipt = дефект; правило «каждый write пишет оба артефакта». collect() остаётся open (сочтён отдельной записью KNOWN_ISSUES).
**verified_from_clean_state:** ⚠️ не прогонялся (изменения в 2 файлах, pytest tests/ 1629 passed + ruff clean)

---
**Status:** Fixed (branch closed, artifact merged into main)
**Root Cause:** experiment/lab-2026 branch (spike exp-lab-2026-01: NL->LLM->Cypher->parser+schema->PropertyGraph) was orphaned - its artifact experiments/neuro_symbolic_spike.py and EXPERIMENTS_LOG entry never landed on main. Findings C1-C4 were already fixed on main via D1 (CypherExecutor schema layer).
**Fix:** Re-ran spike from clean main (VERDICT: HYPOTHESIS SUPPORTED, parse_ok=8, rejected_by_schema=2 - schema layer correctly rejects hallucinated :SERVICE label and cycle() empty-RETURN). Carried only the useful artifact (spike script + EXPERIMENTS_LOG entry 848fdf33), avoiding a blind merge that would have conflicted in 3 doc files. Deleted orphaned local branch experiment/lab-2026.
**Guard:** When a long-lived experiment branch diverges, carry only the result artifact, never blind-merge doc files that evolved on main.
**verified_from_clean_state:** ✅ yes - spike re-run from clean working tree on main (MockLLM, no network); pre-commit gate-zero green (verify_diary/stale_detector/check_tool_names/negative_controls/check_layer_boundaries).

## [2026-09-02] - PR #20 merged green; issues #21/#22 auto-closed
**Status:** Fixed (merged to main, CI fully green)
**Root Cause:** PR #20 (two-pass symbol resolution) introduced 4 CI failures:
1. git_hooks_installer.py:54 - premature """ closed the PRE_COMMIT_HOOK literal -> 91 invalid-syntax (escaped-quote bug; surrounding escaped quotes are intentional, this one wasn't).
2. graph_resolver.py - 5 F401 unused imports + 1 BLE001 (except Exception).
3. test_graph_adapter_node_selection.py tie-test asserted hardcoded Windows path D:/.../pkg_a/impl.py; adapter normalizes file_path via Path.resolve(), so on Linux CI the value differed -> clean-state job failed.
4. test_modification_guard.py:505 - E731 lambda in class attr (ruff lints src/ AND tests/).
**Fix:** reused escaped quotes; trimmed imports + narrowed except; tie-test asserts chosen.file_path.endswith(pkg_a/impl.py) (platform-stable); lambda->def (4cb1b695, 9659f591).
**Guard:** CI Lint(ruff) runs `ruff check src/ tests/` -> verify BOTH incl. tests, not just src/ (checked src/ only first pass).
**Result:** PR #20 merged; issues #21 (ambiguous writes refuse) & #22 (fail-closed anchors / head-freshness) auto-closed via Fixes footer in commit B (cb88c961).
**verified_from_clean_state:** ✅ yes - CI on head 9659f591: test(ubuntu 3.14) PASS, test(windows 3.14) PASS, clean-state PASS, ruff check src/ tests/ PASS; full pre-commit gate-zero for both fix commits.

## [2026-09-02 20:51] — drift_gate заблокировал коммит: контроль остановил самого автора
**Status:** ? Fixed (коммит A 08281f37 приземлился; B — отдельная незакоммиченная квитанция)
**Root Cause:** предсуществующий BROKEN drift_gate: GitBash bin/ (C:\Program Files\Git\bin) НЕ в PATH процесса > shutil.which("bash") резолвит System32\bash.exe (WSL-шим) > _resolve_bash возвращает None > negative_controls BROKEN. Доказано предсуществование: файлы drift_gate не тронуты в этой сессии (git log), gate был зелёным 2026-08-12 (AGENT_DIARY:723-724) > деградация среды, НЕ вечный UNAVAILABLE.
**Fix:** commit A (08281f37, fixes #21/#22) выполнен процессом с prepend PATH "C:\Program Files\Git\bin;C:\Program Files\Git\usr\bin" > negative_controls все 3 PROVEN, все 5 hook-проверок OK. **--no-verify НЕ использовался** (запрещён): устранена причина (bash в PATH), незаглушена проверка.
**Guard:** паттерн в WISDOM: «hook блокирует > чини среду, не пропуск» (PATH-фикс делает контроль работающим и коммитит ПОД ним; --no-verify оставляет контроль мёртвым).
**Сопутствующее:** пере-стейдж дрейфнувших fail-closed файлов (layer/verify_on_read/test) — стейдж отставал от рабочего дерева после поздних эдитов; пойман повторным git diff --staged (привычка: сверять перед каждым коммитом). Многострочный PS heredoc ломает git commit > использовать -F <файл>.
**verified_from_clean_state:** да (на рабочем дереве = стейдж A): 126 тестов A-зоны passed; hook 5/5 OK; git show --stat 08281f37 = 7 файлов 328+/16-, footer Fixes #21/#22.

---

## [2026-09-02 21:40] — COMMIT B (head-freshness) приземлился: cb88c961; + cp1251 encoding-инцидент
**Status:** ✅ Fixed (коммит B cb88c961; все 5 pre-commit hook'ов OK; рабочее дерево чистое)
**Root Cause 1 (B):** после A (fail-closed symbol, никогда REFUTED) свежесть индекса не проверялась — отсутствие референта не доказывало удаление (stale-индекс). Требование fresh-индекса для честного REFUTED.
**Fix 1 (B):** (1) `evaluate_freshness(build_head,current_head,dirty)` + `resolve_head_dirty(root)` (git rev-parse HEAD + git status --porcelain, Popen+communicate, CREATE_NO_WINDOW, timeout 5s, fail→None) в verify_on_read.py; (2) `index_project` пишет `build_head` в graph meta ТОЛЬКО на успешном completion; (3) freshness-gated `_symbol_resolver` в layer.py — False (REFUTED) только при build_head==HEAD на чистом дереве, иначе None (INCONCLUSIVE); (4) `_classify` снял fail-closed symbol-ветку (резолвер несёт freshness); (5) test_verify_on_read fail-closed-тест → unverifiable-None→INCONCLUSIVE. +8 тестов `tests/test_symbol_freshness.py`.
**Root Cause 2 (encoding):** PowerShell `Set-Content` записал мою русскую запись дневника (эм-даши «—») в cp1251 → AGENT_DIARY.md стал смешанным UTF-8+cp1251 → verify_diary упал (index 0x97). §9 п.9.
**Fix 2 (encoding):** декодировал cp1251-блок (с маркера `## [2026-09-02 20:51]` до EOF) как cp1251, префикс как UTF-8, переписал файл UTF-8 (strict-валиден). Пере-стейджил. verify_diary 5/5 OK. **Урок: никогда не писать русские .md через PS — только edit/write tools (UTF-8) или Python `encoding="utf-8"`.**
**Guard:** WISDOM B-DONE-блок; паттерн §9 «PS cp1251» (запись); чистый-A-прогон (worktree 08281f37): test_verify_on_read 47/47 → A не зависит от B; полный clean-A pytest = 158 среда-fail (embedder/reranker в изолированном worktree), ортогонально B.
**verified_from_clean_state:** ✅ да — полный pytest 1608 passed (hook verify_diary, рабочий B-дерево) / 1602 passed (ручной B-прогон); ruff clean; git show --stat cb88c961 = 10 файлов 343+/42-, создан tests/test_symbol_freshness.py.

## [2026-09-03] — Fake reindex ETA "~8s" + frozen progress in Finalizing (both fixed)
**Status:** ✅ Fixed (commit 32f11662; 5 pre-commit hooks OK; full pytest 1587 passed, 2 pre-existing unrelated env_extractor failures)
**Root Cause 1 (ETA "~8s"):** `_enrich_job_response` had a dead history branch — `job.project_size` is never assigned → always false — and fell into a broken linear extrapolation of the first 2 simulated seconds: `int(2/0.2*0.8)=8` → fake "~8с". History-ETA path (`store.py:249`) was unreachable.
**Fix 1:** single source-of-truth parser `_embed_progress_from_log()` (layer.py) reads the real `[embed] done/total batch=…ch/s` line within the job window → real ETA = `remaining/speed` (verified: 992/1339, inst=16 → ETA 21s, eta_phase="embed"). No data → honest `None` (UI "расчёт…/определяется…") instead of a fabricated number. Reworked `intel_trigger_reindex`/`intel_reset_index` ETA to handle `None` (was a `TypeError` passing None into the stdlib `timedelta` seconds arg).
**Root Cause 2 (frozen Finalizing):** `_safe_ivf_index` (up to ~1min) emitted no progress-callback → bar stuck at 0.8 (embed scale max), chank counter showed stale last-embed line.
**Fix 2:** emit a `finalizing` progress-callback before/after IVF in index_project_runner.py; `_index_progress_callback` maps "finalizing" → 0.8→0.95; `get_job_status` shows honest "⚙️ Finalizing: optimize + IVF index" when done>=total.
**Guard:** 2 new honesty tests in test_job_history.py (ETA None when no data; real rate from mocked `_embed_progress_from_log`). §9: "trust the log speed, never linear-extrapolate simulated early progress".
**verified_from_clean_state:** ⚠️ не проверено — clean-clone verification not run this session; full pytest 1587 passed (2 pre-existing unrelated env_extractor failures), targeted set 51 green.

## [2026-09-03 19:30] — CI RED: circular import layer ↔ tools_reg (architecture_linter)
**Status:** ✅ Fixed (commit f210ed7c; CI all-jobs green on ubuntu+windows)
**Root Cause:** My ETA refactor added `tools_reg → layer` import for `_embed_progress_from_log`, closing an existing `layer → tools_reg` (re-export `register_intelligence_tools`) cycle. `scripts/architecture_linter.py` caught it as `[CIRCULAR]`.
**Fix:** Extracted `_embed_progress_from_log` into neutral `src/core/intelligence/embed_progress.py`. Both layer and tools_reg import from it. Zero cycle, single source of truth preserved.
**Guard:** `architecture_linter.py` is a CI gate — any future circular import will be caught before merge. §9: "before adding a cross-module import, check if the target already imports back."
**verified_from_clean_state:** ✅ да — CI clean-state job (ubuntu clone+venv+install+tests) passed; full pytest 1587 passed (2 pre-existing); ruff clean; architecture_linter all OK.

## [2026-09-04 11:15] — CI RED: ruff lint errors caught only after push (3 commits)
**Status:** ✅ Fixed (commit 986c9be7)
**Root Cause:** Pre-commit hook did not run ruff. CI (`ruff check src/ tests/` in ci.yml) caught F401/W292 only after push, forcing fix-commits. Repeated 3 times (5a771789, b121ab19, 3dd79ba2). Also discovered pre-existing SyntaxError in hook template from bb05d9af (stray `\"\"\"` in PRE_COMMIT_HOOK docstring) — hook never compiled, was installed via MCP after commits pushed so never caught.
**Fix:** Added `scripts/ruff_gate.py` (step 9 in PRE_COMMIT_HOOK, run via `run_script()`). Graceful skip when ruff not installed (advisory). Removed stray `\"\"\"` in template. 3/3 negative control tests passed.
**Guard:** ruff_gate.py now blocks commits locally when ruff finds lint errors. test_ruff_gate.py prevents regression (happy/fail/no-ruff paths). KNOWN_ISSUES.md#2026-09-04-CI-RED-ruff.
**verified_from_clean_state:** ⚠️ не проверено — clean-clone не гонялся; локально подтверждено: ruff clean (3 файла), py_compile hook OK, 3/3 unit tests, hook template .format() verified.

## [2026-09-05 09:15] — Process leak: hung git cat-file leaks git+git.exe+conhost chains (RAM 81%, ~200 procs)
**Status:** ✅ Fixed (code only, не запушено) — verify_diary.py + git_hooks_installer.py
**Root Cause:** `check_commit_exists` (verify_diary.py:361): `proc.communicate(timeout=30)` на таймауте в Python НЕ убивает процесс, `except Exception: pass` глотает TimeoutExpired → Popen утекает навсегда. Git for Windows делает re-exec (git → git.exe), теряя DETACHED_PROCESS → каждый зависший `git cat-file` = 3 вечных процесса (git + git.exe + conhost). Наблюдение: цепочка 9660→24156→24428 жила 6+ часов; триггер — стартовая Contradiction Ledger-проверка (main.py:62, server_factory.py:547) при CPU/Defender contention.
**Fix:** `_kill_git_tree()` — `taskkill /F /T /PID` (снимает re-exec дерево; верифицировано на живой цепочке: исчезли все 3 процесса) + `except subprocess.TimeoutExpired` вокруг communicate в check_commit_exists; тот же kill-tree в run_script (git_hooks_installer.py:93). Новые except — конкретные `(OSError, subprocess.SubprocessError)`, ноль новых ruff-нарушений.
**Guard:** правило §9: communicate(timeout=) на Windows ОБЯЗАН сопровождаться kill на TimeoutExpired (иначе Popen утекает вечно); unit-мок не ловит (мок не бросает TimeoutExpired) — факт подтверждён реальным прогоном (test_contradiction_ledger slow, 2 passed за 10s). Тесты: commit_guard 5 + test_subprocess_windows 2 + ledger slow 2 = 9 passed.
**verified_from_clean_state:** ⚠️ не проверено — clean-clone не гонялся; full local: 9 passed, ruff clean по новым строкам.

## [2026-09-05 12:30] — FIX: stale_detector + predict_change стабильно таймаутили через MCP (-32001): блокирующий sync-код в async-контексте
**Status:** ✅ Fixed (code only, не запушено) — src/mcp/tools/doc_tools.py + predict_tools.py
**Root Cause:** `error_boundary` применяет `asyncio.wait_for(timeout_ms)` вокруг `execute`, но внутри `execute` вызывается **синхронный блокирующий код** (`stale_run` 10-29s, `static_predict`/`ChangePreview` с git-subprocess). На Windows `asyncio.wait_for` НЕ может отменить работающий синхронный блок → event loop заблокирован, клиент (opencode) отваливается по транспортному таймауту `-32001` ДО того, как сервер вернёт ответ.
**Эксперименты (EXPERIMENTS_LOG#2026-09-05):**
1. `stale_run` напрямую: 10.06s (73 файла, 609 дрейфов) — впритык к `timeout_ms=10000`.
2. `asyncio.wait_for(10000ms)` вокруг синхронного `stale_run` → НЕ прервал, вернулся через 24.7s (loop заблокирован).
3. `asyncio.to_thread(stale_run)` + `wait_for` → РЕАЛЬНЫЙ таймаут на 5.0s/10.0s, event loop жив; `wait_for(30000ms)` успевает за 28.96s.
4. `static_predict` из терминала: 0.53s (быстрый!) — таймаут predict_change -32001 из opencode — артефакт транспортной обвязки, не логика.
**Fix:** оба инструмента обернули синхронные блоки в `asyncio.to_thread` (doc_tools.py `_scan_docs`, predict_tools.py `static_predict` + `ChangePreview.run`); таймауты подняты: stale_detector 10s→60s, predict_change 60s→120s. `asyncio.wait_for` теперь реально прерывает операцию при превышении, event loop остаётся живым.
**Guard:** §9: в async-MCP-инструменте синхронные subprocess/filesystem блоки ОБЯЗАНЫ жить в `asyncio.to_thread`, иначе `error_boundary.timeout_ms` иллюзорен. Правило «таймаут без возможности прерывания = фарс».
**verified_from_clean_state:** ⚠️ не проверено — MCP-процесс в Zed не перезапущен (нужен reload окна для применения); прямой вызов `StaleDetectorTool.execute({})` → OK 13.0s (0 дрейфов), `PredictChangeTool.execute({'mode':'static'})` → OK 1.4s (7 files, risk); 62 теста (вкл. subprocess_windows) passed.

## [2026-09-06 21:00] — Починка lock_guard: таймаут 60s ломал весь .locks-протокол

**Status:** ✅ Fixed / **Root Cause:** `scripts/lock_guard.py` `_run` default timeout=60s — любой `git commit` прогоняет pre-commit hook (verify_diary → полный pytest 5-10 мин на Windows), поэтому acquire/release падали с TimeoutExpired, хотя коммит создавался в фоне. Это делало неработоспособным протокол координации параллельных агентов (§10), который мы внедряем (запрос владельца «проверить, что не конфликтуют параллельные агенты»).
**Fix:** timeout 60→900s (+комментарий-обоснование) в `scripts/lock_guard.py`. **Incident:** INC-CD6E. **Guard:** любой новой «быстрой» утилите с git-commit внутри — развязка на время hook'ов; T3-обобщение: `context_tool.py:280`, `git_tools.py:52-99`, `system_tools.py:370/408/446` — кандидаты sync-subprocess в async (не подтверждены замером, KNOWN_ISSUES ⏳). **verified_from_clean_state:** да — полный цикл acquire→status→release on README/lock_guard/probe прошёл под hook'ами; 1608+ tests passed full run; HEAD=origin/main, активных локов нет.

## [2026-09-06 21:30] — sync-subprocess в async-MCP (context_tool, system_tools) — fixed

**Status:** ✅ Fixed (code only) / **Root Cause:** системная проверка после фикса stale/predict: нашлись ещё sync `subprocess.run` внутри async `execute`. `GetContextTool._section_git` (git log через subprocess, 15s) блокировал event loop async `get_context` (timeout_ms=30000); `DualArmHealthCheckTool.execute` держал sync wsl_check + `_run_mutmut_in_wsl` (до 180s WSL) + `_verify_mutmut_can_fail` — wait_for иллюзорен, тот же паттерн P-флага.
**Fix:** `_section_git` → async + `await asyncio.to_thread(subprocess.run, ...)`; вызов в `_collect_sections` → `await`; system_tools: три sync-вызова → `await asyncio.to_thread(...)`. `git_tools._git_run` уже был эталонным async (`create_subprocess_exec` + `wait_for`) — не тронут. **Guard:** §9-правило расширено глобально — любой sync subprocess в async-MCP обязан жить в `asyncio.to_thread` (git_tools — эталон переиспользования). **verified_from_clean_state:** да — test_context_tool 2 passed, ruff clean, imports OK, реальный `_section_git` вернул git-history (2 коммита по config.py). KNOWN_ISSUES синхронизирован (из ⏳ → ✅).

## [2026-09-06 22:00] — P-001 рецидив: cmd-окна при запуске/открытии проекта (powershell/nvidia-smi без CREATE_NO_WINDOW) — FIXED

**Status:** ✅ Fixed / **Root Cause:** повтор инцидента 2026-08-14 (P-001, «чёрные окна CMD»). Фикс 2026-08-14 добавил CREATE_NO_WINDOW для git/netstat/wmic/taskkill в runtime, но ПОЗВОЛИЛ дыру: `resource_monitor.py:303` (powershell Get-CimInstance — RAM-монитор детей) и `:503` (nvidia-smi), `llama_runner.py:1338/1366/1394` (powershell Get-NetTCPConnection, Get-CimInstance CommandLine, taskkill в kill_process_on_port). Под pythonw (no console) каждый такой вызов из фонового сервиса при открытии/запуске проекта создавал видимое окно cmd → «опять появляется cmd и виснет».
**Fix:** CREATE_NO_WINDOW во все 5 сайтов. Guard: `tests/test_subprocess_windows.py` — placeholder (assert True) заменён на реальный статический тест: grep по src/**/*.py за консоль-спавнами (powershell/wsl/wmic/netstat/taskkill/nvidia-smi) без флага → fail; + тест «daemon-потоки без capture_output (pipe-deadlock §5.16)». Оба passed. **verified_from_clean_state:** ✅ да — test_subprocess_windows 2 passed (реальный прогон с диска, не мок): guard находит дыры, ruff clean (все 4 файла), syntax OK.


## [2026-09-08] — B3: grammar-карты parser.py (imports/calls/assigns/conditions) внесены + живые фиксы

**Status:** ✅ Fixed / **Root Cause и итог:** внесены из study 05 карты CALL_NODES/IMPORT_NODE_MAP/ASSIGNMENT_NODE_MAP/CONDITIONAL_NODE_MAP (пер-язычные) в `src/core/indexing/parser.py`. Живые tree-sitter пробы вскрыли недопонимания raw-грамматик, исправлено: CALL_IDENTIFIER_TYPES + simple_identifier (Swift/Kotlin/Dart callee); имя функции + simple_identifier/type_identifier + Dart function_signature и подъём имени из сиблинга function_body (Dart: signature/body — сиблинги, не parent-child); TARGET_NODES + method (Ruby); assignment left + variable_name (PHP $a) и directly_assignable_expression (Swift), right + name-узлы (PHP/Rust); _extract_import_target + regex #include <...>; IMPORT_KEYWORDS + дедуп импортов по (target,line) (Kotlin keyword-дубль, Dart library_import+import_specification); Ruby-imports через call с фильтром require/include.
**Tests:** 94 passed (assignments+calls+imports) > полный прогон 1646 passed. Новые live-тесты: TestMultiLangCalls (7) + TestMultiLangImports (9) в test_symbol_index_call_graph.py, PHP-assign в test_assignments.py. Red Team 5 атак отражены. temp probe-скрипты удалены.
**Guard:** grammar-факты — только через живые tree-sitter пробы (raw grammar_kinds_raw.txt ненадёжен: Go short_var_declaration не перечислен, но существует).
**verified_from_clean_state:** ⚠️ не проверено — чистый clone не гонялся (нет сети в сессии); локально полный pytest 1646 passed / 5 skipped / 91 deselected (Windows).
## [2026-09-08 12:35] — B4: import-экстракция через language_imports (деривация карт + флаг-гейт)

**Status:** ✅ Fixed / **Root Cause:** два источника node-типов импортов (parser.IMPORT_NODE_MAP и литерал LANGUAGE_IMPORT_NODES) расходились (kt/dart/php); ungated fallback-2 в мосте.
**Fix:** LANGUAGE_IMPORT_NODES — производная IMPORT_NODE_MAP (вариант B); fallback-2 только в else-ветке _walk_file (ext без карты) за двойным гейтом MSCODEBASE_LANGUAGE_PACK (else-ветка + is_enabled в iter_import_candidate_nodes); extract_imports_from_file читает флаг через language_pack.is_enabled; дедуп общий. (коммит B4, main)
**Tests:** целевые 103 passed; полный прогон 1651 passed / 5 skipped / 91 deselected (169.2s); ruff clean ×4 файла. Новые: TestMapConsistency (3), TestFallbackImports (4), гейт-тесты флага.
**Guard:** TestMapConsistency структурно ловит любое расхождение карт; ungated-путь закреплён негативными тестами (флаг off → пусто). Lazy-цикл parser⇄language_imports (статика) — осознанный техдолг в _ALLOWED_CORE_CYCLES (KNOWN_ISSUES 2026-09-08), деривация карты переведена на module __getattr__ (PEP 562), на import-time ничего не исполняется.
**verified_from_clean_state:** ⚠️ не проверено — чистый clone требует сети (нет в сессии); локально полный pytest зелёный.

## [2026-09-08 19:40] — collect() в Cypher: json_group_array + типизированный декод (fixed)

**Status:** ✅ Fixed. / **Root Cause:** KNOWN_ISSUES 2026-09-07 ⏳ — `_translate_return_expr` заявлял `collect` как Supported, но SQLite не имеет функции COLLECT («no such function»); ни одного теста на `RETURN collect(...)` не было.
**Fix:** `cypher_sql.py` — COLLECT(expr) → `json_group_array(<sql>) FILTER (WHERE <sql> IS NOT NULL)` (семантика Neo4j: null-игнор, пустой матч → []); `collect(*)` и вложенный obtain → явные ValueError; DISTINCT — SyntaxError из парсера (не наш уровень). Маркер `collect_cols` на трансляторе, в `cypher_executor.py` step5 декодится json.loads ТОЛЬКО помеченных колонок со str-значением (try/except → warning, не роняет весь результат).
**Tests:** 13 новых (SQL/E2E/errors incl. decode-collision `'["not_a_list"]'`); файл 93 passed; полный 1663 passed / 6 skipped / 91 deselected (168.6s). ruff clean, verify_diary 15/0. Эксперименты Г1/Г2 (sqlite 3.50.4, Python 3.14.3) — FILTER и empty→[] подтверждены сырым прогоном, см. .agent_task_state.md.
**Guard:** тест «collect() без алиаса → имя колонки = выражение», decode-collision guard (не-decode не-marked колонок), Red Team 5/5 (empty, null, unicode/quotes, DISTINCT, nested/*).
**verified_from_clean_state:** ⚠️ не проверено — чистый clone требует сети (нет в сессии); локально полный pytest 1663 passed green.

## [2026-09-09] — Аудит «Active MSCodeBase» (Exhibit #23: MCP tool available but never invoked)

**Status:** Open — зафиксирован гэп (исследование + план, код НЕ вносился)
**Root Cause:** фундамент (VOR / DebounceBatch / ConsistencyTracker / IdleScheduler / PropagationEngine) существует, но компоненты изолированы: цепь «файл изменён → STALE → VOR → alert агента» не собрана ни в одном звене. VOR вызывается ровно из 1 места (layer.py:1097, intel_get_project_memory); 2 из 3 idle-задач — пустые заглушки; ConsistencyTracker.mark_stale("memory") never called; system_alerts/precondition contract отсутствуют; FS-event-watcher отсутствует (только heartbeat-Watchdog).
**Fix (план, не внесён):** H1 — подключить VOR в `_check_index_health` (idle-ticker, cooldown 120s уже есть; ~15 строк). Затем optional: mark_stale("memory") в notify_change; system_alerts в ответы MCP-тулов. НЕ добавлять watchdog lib сейчас (notify_change = тот же event).
**Red Team:** (1) lock contention idle-VOR vs agent-VOR — один `_write_lock`, обёрнут asyncio.to_thread, добавить locked()-check; (2) H3 TTL-гниение НЕ применимо к INCONCLUSIVE (42 узла зависнут «навечно») — нужен H1; (3) import cycle — локальный import внутри try/except; (4) alerts токены — низкий риск (одноразовые); (5) concurrent FS при VOR — защищено freshness gate (commit B). 5/5 атак с защитой.
**Guard:** правило §9: перед интеграцией по чужому плану — верифицировать КАЖДЫЙ API через get_symbol_info/search_code (чужой план дал 3 несуществующих API: self.context, vor.run(nodes=), get_active_nodes()).
**verified_from_clean_state:** ⚠️ не прогонялся (изменения только .md; факты из MCP, не из запуска)

## [2026-09-10] — H1 idle-VOR + system_alerts (цепь «файл изменён → STALE → VOR → alert агента» собрана)

**Status:** ✅ Fixed / **Root Cause (Exhibit #23, 2026-09-09):** компоненты цепи существовали по отдельности, но VOR вызывался ровно из 1 места (layer.py:intel_get_project_memory), mark_stale("memory") никогда не вызывался, system_alerts не было.
**Fix (два коммита в ветке chore/experiments-es1-es2-0909):**
- **H1:** `set_idle_vor_callback()` в task_queue.py + вызов из `_check_index_health` (idle-тик, cooldown 120s); `run_background_verify(budget_ms=250)` в layer.py с locked()-guard против agent-VOR (общий `_write_lock`, `get_verifier`-регистр); `_build_symbol_resolver` вынесен из `intel_get_project_memory` (DRY); регистрация hook в `server_tools`.
- **system_alerts:** `AlertStore` (src/core/intelligence/alert_store.py, JSON вне проекта в <data_root>/projects/<hash>/intelligence/, threading.Lock т.к. несколько event-loop'ов, дедуп по kind+payload, атомарный collect_and_clear limit=5). Источники: (a) stale — `mark_stale("memory")` в notify_change ТОЛЬКО при переходе →STALE (не спамим на каждый save; reason меняется и дедуп по payload не спасёт); (b) starved — idle VOR-проход и `intel_get_project_memory` для узлов видимы ≥2 циклов (MATCHED>0, DELIVERED=0). Доставка: `format_system_alerts` prepend в `intel_get_project_memory` (tools_reg) + секция в `intel_explain_project_state` (server_tools, try/except — алерты не роняют диагноз).
**Tests:** 11 в test_alert_store.py (push/collect/clear одноразовость/дедуп/limit/corrupt-json/гонка 2 threading-потоков 20 alerts/per-project изоляция/синглтон по resolved path/orphan) + 3 в test_ui_formatter_memory (empty/alerts render/payload limit 3). Полный pytest 1689 passed / 5 skipped / 91 deselected (180.8s); ruff clean после --fix; architecture_linter «Все инварианты соблюдены».
**Red Team:** (1) дубль-доставка при гонке двух MCP-тулов — collect_and_clear атомарный (первый забрал, второй — пусто); (2) спам на каждый notify_change — alert только при первом переходе →STALE; (3) токен-оверхед — limit=5, payload до 3 ключей; (4) коррапт JSON — graceful reset; (5) multi-window — per-project store. 5/5 с защитой.
**Guard:** дедуп в push + лимиты, single-threaded write под lock. .h-хедеры (H2) — отдельный коммит 0301fa93 (см. KNOWN_ISSUES «`.h` не парсился AST» → Fixed).
**verified_from_clean_state:** ⚠️ не проверено — чистый clone не гонялся (нет сети в сессии); локально полный pytest 1689 passed / 91 deselected (Windows, без e2e/shadow-маркеров — llama недоступен, slow/benchmark отсечены addopts).
