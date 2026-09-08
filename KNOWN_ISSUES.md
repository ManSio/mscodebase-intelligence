# KNOWN ISSUES — MSCodeBase Intelligence

> Синхронизируется из `AGENT_DIARY.md` при каждом [🏁 ИТОГ].
> Формат: дата | что было | статус | fix

---


**11 entries** — compressed per §4.8 R3 (conclusion-first)

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
- **Статус:** 🟢 Cypher-часть fixed; 🟢 receipts fixed; ⏳ collect() open


## 2026-09-07 — Lazy-only верификация: память не проверяется без вызова агента; нет TTL/фона (open, эксперимент нужен)

- **Источник:** live-срез project_memory.json текущего проекта (136 узлов) + grep точек вызова VOR/idle-планировщика
- **Симптомы (все Verified):**
  - VOR вызывается ровно из 1 места — `intel_get_project_memory` (layer.py:1097). Таймеров/старт-хуков/idle-подписок нет.
  - У 42 узлов ACTIVE нет ни одного поля TTL/last_checked/next_check — висят без статуса с 2026-08-11 (1 месяц).
  - Узлы без якорей (`file:/import:/env:/pkg:`) → INCONCLUSIVE → VOR **не пишет ничего** (ни статуса, ни verified_at) — их нельзя ни подтвердить, ни отозвать автоматически. Пример: ADRs с commit_hash в data, но без шпилей.
  - IdleScheduler (`enable_idle_scheduler`, task_queue.py:345) включается только из `record_tool_call()` — после вызова инструмента; VOR туда не подключён; из 3 idle-задач 2 — заглушки (`_improve_summaries_batch`, `_check_index_health` — пустые тела, только debug-лог).
  - Со стороны агента: вызвал `intel_get_project_memory` → 110/110 узлов проверено (47 VERIFIED, 63 не-refuted) — работает, но только «по руке».
- **Дизайн-решение для эксперимента (следующий шаг):** непрерывная проверка «без вызова» — (a) idle-тикер VOR в фоне по расписанию с cooldown; (b) react на git/файловые события (HEAD сменился → перепроверка затронутых узлов); (c) TTL/`verified_at` для INCONCLUSIVE → по возрастанию падать в REFUTED label «не подтверждён за N дней». Контр-риск: цена (CPU/disk) непрерывной проверки vs польза свежести — мерить, не угадывать (см. docs/research/universal-engine-study/10-continuous-verification.md).
- **Статус:** ⏳ Open — нужен эксперимент (гипотеза → замер → выбор)


## 2026-09-08 — B4: статический цикл parser ⇄ language_imports (осознанный техдолг, lazy, allowed)

- **Источник:** `architecture_linter` (Invariant 3) после деривации `LANGUAGE_IMPORT_NODES` из `CodeParser.IMPORT_NODE_MAP` (B4).
- **Описание:** `src.core.language_imports` импортирует `src.core.indexing.parser` (для деривации карты), а `parser._extract_fallback_imports` импортирует `language_imports` (fallback-режим 2). Статически — цикл; в рантайме ни один импорт при загрузке модулей не выполняется: parser импортирует language_imports только локально в функции; language_imports импортирует parser только лениво (module `__getattr__` → `_derive_language_import_nodes`, PEP 562) при первом обращении к `LANGUAGE_IMPORT_NODES`.
- **Fix:** пара добавлена в `_ALLOWED_CORE_CYCLES` (scripts/architecture_linter.py) с комментарием; `LANGUAGE_IMPORT_NODES` переведён на ленивую деривацию (кэш `_LANGUAGE_IMPORT_NODES_CACHE`, `__getattr__`), прямое обращение к карте внутри модуля заменено на `_get_language_import_nodes()`. Удалить из allowlist после выноса `IMPORT_NODE_MAP` в нейтральный модуль (не историю карт в parser) — тогда language_imports сможет импортировать parser односторонне.
- **Статус:** ✅ Fixed (allowed tech debt, deferred refactor; целевые 68 passed, architecture_linter 4/4 OK)

