# KNOWN_ISSUES archive — 2026-09 auto-synced experiment entries

> Archived 2026-09-22 per §4.8 R4 (KNOWN_ISSUES.md exceeded 300 lines).
> These entries were auto-synced from AGENT_DIARY.md (experiment results);
> canonical source = AGENT_DIARY.md / EXPERIMENTS_LOG.md.

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


## 2026-09-20 — Exp E13: текстовый RAG (doc-chunks) vs кодовый baseline (E10/E11)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Measured (refuted hypothesis)
**Hypothesis:** doc-chunks (README + docs/en/ + docstrings) retrieve as well as code-chunks via search_with_mode quality.
**Method:** 16 EN doc-queries, live ...
- **Статус:** автоматически синхронизировано


## 2026-09-18 — Фаза 1: Incremental Hot-Reload (FreshnessChecker оживлён + hot-reload + KI-109)

- **Источник:** AGENT_DIARY.md
- **Описание:** - **Evidence Ladder (2026-08-15, Exp 2-E E1-E3):** форма evidence — переменная; file_content = лучший recall (qwen 0.92), graph = закрытие present-trap ТОЛЬКО у evidence-честных моделей (qwen3.7 FA tr...
- **Статус:** автоматически синхронизировано


## 2026-09-18 — Фаза 1: Incremental Hot-Reload (FreshnessChecker оживлён + hot-reload + KI-109)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (7 тестов свежести включая concurrency-стресс N=16 + 1748 полный pytest green; ветка вне PR — локально)
**Root Cause:** FreshnessChecker (freshness.py) был мёртв (0 вызовов) и СЛОМАН...
- **Статус:** автоматически синхронизировано


## 2026-09-07 — Lazy-only верификация: VOR вызывается только из intel_get_project_memory, нет TTL/фона

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Open — зафиксировано как проблема + план эксперимента (10-continuous-verification.md)
**Root Cause:** По дизайну (ADR-0003) VOR ленивый, но точки вызова всего одна (layer.py:1097); IdleSch...
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


## 2026-09-08 19:40 — collect() в Cypher: json_group_array + типизированный декод (fixed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed. / **Root Cause:** KNOWN_ISSUES 2026-09-07 ⏳ — `_translate_return_expr` заявлял `collect` как Supported, но SQLite не имеет функции COLLECT («no such function»); ни одного теста на...
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


## 2026-09-11 — H3 TTL-гниение: last_checked для всех проверенных + label stale_ttl (doc 10 closed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (9 новых тестов + 1725 полный pytest green; doc 10-continuous-verification H1+H2+H3 done)
**Root Cause:** INCONCLUSIVE/непроверенные узлы «висят вечно» без следа проверки: live-срез ...
- **Статус:** автоматически синхронизировано


## 2026-09-20 — Поисковое качество / E13: исследовательские задачи (6 пунктов)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Plan (задачи занесены в ISSUE.md KI-R1..R6, код не тронут)
**Контекст:** исследование поиска/RAG — что именно измерять, прежде чем утверждать результат.
**Решение (приоритет):** KI-R1 (пер...
- **Статус:** автоматически синхронизировано


## 2026-09-10 — Exp 2 (Agent Behavior) + Exp 4 (Fail-Closed Freshness Gate)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed. **Root Cause (Exhibit #23, 2026-09-09):** inform-the-agent approach insufficient — agent can ignore STALE alerts; PlanFence 30/30 failures confirms action-validation unreliable; s...
- **Статус:** автоматически синхронизировано

## 2026-09-13 — H4: agent-memory lifecycle в масштабе dev.to KB — бутылочное горлышко = сетевой capture, не граф

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (эксперимент подтверждён; сопровождение задачи closed)
**Root Cause:** при росте базы 3,989 → 13,519 статей (3.4x), refresh own занял 10м38с на 13.5k статей/82.5k комментов (134 сете...
- **Статус:** автоматически синхронизировано

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


## 2026-09-20 — Exp E13: текстовый RAG (doc-chunks) vs кодовый baseline (E10/E11)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Measured (refuted hypothesis)
**Hypothesis:** doc-chunks (README + docs/en/ + docstrings) retrieve as well as code-chunks via search_with_mode quality.
**Method:** 16 EN doc-queries, live ...
- **Статус:** автоматически синхронизировано


## 2026-09-18 — Фаза 1: Incremental Hot-Reload (FreshnessChecker оживлён + hot-reload + KI-109)

- **Источник:** AGENT_DIARY.md
- **Описание:** - **Evidence Ladder (2026-08-15, Exp 2-E E1-E3):** форма evidence — переменная; file_content = лучший recall (qwen 0.92), graph = закрытие present-trap ТОЛЬКО у evidence-честных моделей (qwen3.7 FA tr...
- **Статус:** автоматически синхронизировано


## 2026-09-18 — Фаза 1: Incremental Hot-Reload (FreshnessChecker оживлён + hot-reload + KI-109)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (7 тестов свежести включая concurrency-стресс N=16 + 1748 полный pytest green; ветка вне PR — локально)
**Root Cause:** FreshnessChecker (freshness.py) был мёртв (0 вызовов) и СЛОМАН...
- **Статус:** автоматически синхронизировано


## 2026-09-07 — Lazy-only верификация: VOR вызывается только из intel_get_project_memory, нет TTL/фона

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Open — зафиксировано как проблема + план эксперимента (10-continuous-verification.md)
**Root Cause:** По дизайну (ADR-0003) VOR ленивый, но точки вызова всего одна (layer.py:1097); IdleSch...
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


## 2026-09-08 19:40 — collect() в Cypher: json_group_array + типизированный декод (fixed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed. / **Root Cause:** KNOWN_ISSUES 2026-09-07 ⏳ — `_translate_return_expr` заявлял `collect` как Supported, но SQLite не имеет функции COLLECT («no such function»); ни одного теста на...
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


## 2026-09-11 — H3 TTL-гниение: last_checked для всех проверенных + label stale_ttl (doc 10 closed)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (9 новых тестов + 1725 полный pytest green; doc 10-continuous-verification H1+H2+H3 done)
**Root Cause:** INCONCLUSIVE/непроверенные узлы «висят вечно» без следа проверки: live-срез ...
- **Статус:** автоматически синхронизировано


## 2026-09-20 — Поисковое качество / E13: исследовательские задачи (6 пунктов)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Plan (задачи занесены в ISSUE.md KI-R1..R6, код не тронут)
**Контекст:** исследование поиска/RAG — что именно измерять, прежде чем утверждать результат.
**Решение (приоритет):** KI-R1 (пер...
- **Статус:** автоматически синхронизировано

