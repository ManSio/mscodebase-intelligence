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

