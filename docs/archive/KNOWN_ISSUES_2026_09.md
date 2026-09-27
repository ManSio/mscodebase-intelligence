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



---

## Archived 2026-09-26 (auto-synced tail, moved to satisfy <=300-line check)
## 2026-09-22 — Exp E16: переносимость bootstrap trace на чужие проекты (статья CoderLegion)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** Measured (hypothesis CONFIRMED)
**Hypothesis:** динамический трейс (sys.settrace, `src/core/bootstrap_trace_plugin.py`) воспроизводится на чужих Python-репозиториях без правок плагина; lin...
- **Статус:** автоматически синхронизировано


## 2026-09-22 — Exp E14: Embedder A/B — EmbeddingGemma 300M vs e5-small (production)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** Measured (hypothesis CONFIRMED)
**Hypothesis:** gemma 300M (768-dim, ctx 2048) значительно сильнее e5-small (384-dim, ctx 512) на кодовом ретривале при цене 3-4× медленнее на CPU.
**Method...
- **Статус:** автоматически синхронизировано


## 2026-09-20 — Exp E13: текстовый RAG (doc-chunks) vs кодовый baseline (E10/E11)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** Measured (refuted hypothesis)
**Hypothesis:** doc-chunks (README + docs/en/ + docstrings) retrieve as well as code-chunks via search_with_mode quality.
**Method:** 16 EN doc-queries, live ...
- **Статус:** автоматически синхронизировано


## 2026-09-18 — Фаза 1: Incremental Hot-Reload (FreshnessChecker оживлён + hot-reload + KI-109)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** - **Evidence Ladder (2026-08-15, Exp 2-E E1-E3):** форма evidence — переменная; file_content = лучший recall (qwen 0.92), graph = закрытие present-trap ТОЛЬКО у evidence-честных моделей (qwen3.7 FA tr...
- **Статус:** автоматически синхронизировано


## 2026-09-18 — Фаза 1: Incremental Hot-Reload (FreshnessChecker оживлён + hot-reload + KI-109)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (7 тестов свежести включая concurrency-стресс N=16 + 1748 полный pytest green; ветка вне PR — локально)
**Root Cause:** FreshnessChecker (freshness.py) был мёртв (0 вызовов) и СЛОМАН...
- **Статус:** автоматически синхронизировано


## 2026-09-07 — Lazy-only верификация: VOR вызывается только из intel_get_project_memory, нет TTL/фона

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** Open — зафиксировано как проблема + план эксперимента (10-continuous-verification.md)
**Root Cause:** По дизайну (ADR-0003) VOR ленивый, но точки вызова всего одна (layer.py:1097); IdleSch...
- **Статус:** автоматически синхронизировано


## 2026-09-09 — H1: фоновый VOR-проход (IdleScheduler) — память перепроверяется без вызова агента

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (6 новых тестов + 1674 полный pytest green; ветка chore/experiments-es1-es2-0909)
**Root Cause:** VOR вызывался ровно из 1 места (intel_get_project_memory, layer.py:1097); idle-задач...
- **Статус:** автоматически синхронизировано


## 2026-09-09 — H2: .h заголовки C включены в AST-индексацию (PARSE_EXTENSIONS + C-парсер)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (commit 0301fa93; KNOWN_ISSUES 2026-09-09 19:35 закрыт)
**Root Cause:** ".h" был в INDEX_EXTENSIONS (вектор-чанкинг шёл), но НЕ в PARSE_EXTENSIONS → CodeParser.parse_file возвращал [...
- **Статус:** автоматически синхронизировано


## 2026-09-07 — Cypher-движок: анонимные узлы/рёбра ломали MATCH; ActionReceipt не писался из write-пути

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (оба блока закрыты, тесты зелёные)
**Root Cause:** (1) Cypher: `from_node_alias` дефолтил в `n1`, а генератор создавал `n{path_idx*2}` для анонимного узла → `no such column: n0.id`; ...
- **Статус:** автоматически синхронизировано


## 2026-09-03 — Fake reindex ETA "~8s" + frozen progress in Finalizing (both fixed)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (commit 32f11662; 5 pre-commit hooks OK; full pytest 1587 passed, 2 pre-existing unrelated env_extractor failures)
**Root Cause 1 (ETA "~8s"):** `_enrich_job_response` had a dead h...
- **Статус:** автоматически синхронизировано


## 2026-09-03 19:30 — CI RED: circular import layer ↔ tools_reg (architecture_linter)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (commit f210ed7c; CI all-jobs green on ubuntu+windows)
**Root Cause:** My ETA refactor added `tools_reg в†’ layer` import for `_embed_progress_from_log`, closing an existing `layer в†’...
- **Статус:** автоматически синхронизировано


## 2026-09-04 11:15 — CI RED: ruff lint errors caught only after push (3 commits)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (commit 986c9be7)
**Root Cause:** Pre-commit hook did not run ruff. CI (`ruff check src/ tests/` in ci.yml) caught F401/W292 only after push, forcing fix-commits. Repeated 3 times ...
- **Статус:** автоматически синхронизировано


## 2026-09-05 12:30 — FIX: stale_detector + predict_change стабильно таймаутили через MCP (-32001): блокирующий sync-код в async-контексте

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (code only, не запушено) — src/mcp/tools/doc_tools.py + predict_tools.py
**Root Cause:** `error_boundary` применяет `asyncio.wait_for(timeout_ms)` вокруг `execute`, но внутри `exec...
- **Статус:** автоматически синхронизировано


## 2026-09-06 21:00 — Починка lock_guard: таймаут 60s ломал весь .locks-протокол

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed / **Root Cause:** `scripts/lock_guard.py` `_run` default timeout=60s — любой `git commit` прогоняет pre-commit hook (verify_diary → полный pytest 5-10 мин на Windows), поэтому acqu...
- **Статус:** автоматически синхронизировано


## 2026-09-06 21:30 — sync-subprocess в async-MCP (context_tool, system_tools) — fixed

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed (code only) / **Root Cause:** системная проверка после фикса stale/predict: нашлись ещё sync `subprocess.run` внутри async `execute`. `GetContextTool._section_git` (git log через s...
- **Статус:** автоматически синхронизировано


## 2026-09-06 22:00 — P-001 рецидив: cmd-окна при запуске/открытии проекта (powershell/nvidia-smi без CREATE_NO_WINDOW) — FIXED

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** вњ… Fixed / **Root Cause:** РїРѕРІС‚РѕСЂ РёРЅС†РёРґРµРЅС‚Р° 2026-08-14 (P-001, В«С‡С‘СЂРЅС‹Рµ РѕРєРЅР° CMDВ»). Р¤РёРєСЃ 2026-08-14 РґРѕР±Р°РІРёР» CREATE_NO_WINDOW РґР»СЏ git/netstat/wmic/taskkill РІ runtime, РЅРѕ РџРћР—Р’РћР›РР› РґС‹СЂСѓ: `resou...
- **Статус:** автоматически синхронизировано


## 2026-09-08 19:40 — collect() в Cypher: json_group_array + типизированный декод (fixed)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed. / **Root Cause:** KNOWN_ISSUES 2026-09-07 ⏳ — `_translate_return_expr` заявлял `collect` как Supported, но SQLite не имеет функции COLLECT («no such function»); ни одного теста на...
- **Статус:** автоматически синхронизировано


## 2026-09-09 — Аудит «Active MSCodeBase» (Exhibit #23: MCP tool available but never invoked)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** Open — зафиксирован гэп (исследование + план, код НЕ вносился)
**Root Cause:** фундамент (VOR / DebounceBatch / ConsistencyTracker / IdleScheduler / PropagationEngine) существует, но компо...
- **Статус:** автоматически синхронизировано


## 2026-09-10 — H1 idle-VOR + system_alerts (цепь «файл изменён → STALE → VOR → alert агента» собрана)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed / **Root Cause (Exhibit #23, 2026-09-09):** компоненты цепи существовали по отдельности, но VOR вызывался ровно из 1 места (layer.py:intel_get_project_memory), mark_stale("memory")...
- **Статус:** автоматически синхронизировано


## 2026-09-10 — Exp 2 (Agent Behavior) + Exp 4 (Fail-Closed Freshness Gate)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** ✅ Fixed. **Root Cause (Exhibit #23, 2026-09-09):** inform-the-agent approach insufficient — agent can ignore STALE alerts; PlanFence 30/30 failures confirms action-validation unreliable; s...
- **Статус:** автоматически синхронизировано


## 2026-09-11 — H3 TTL-гниение: last_checked для всех проверенных + label stale_ttl (doc 10 closed)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (9 новых тестов + 1725 полный pytest green; doc 10-continuous-verification H1+H2+H3 done)
**Root Cause:** INCONCLUSIVE/непроверенные узлы «висят вечно» без следа проверки: live-срез ...
- **Статус:** автоматически синхронизировано


## 2026-09-13 — H4: agent-memory lifecycle в масштабе dev.to KB — бутылочное горлышко = сетевой capture, не граф

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (эксперимент подтверждён; сопровождение задачи closed)
**Root Cause:** при росте базы 3,989 → 13,519 статей (3.4x), refresh own занял 10м38с на 13.5k статей/82.5k комментов (134 сете...
- **Статус:** автоматически синхронизировано


## 2026-09-20 — Поисковое качество / E13: исследовательские задачи (6 пунктов)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **Описание:** **Status:** Plan (задачи занесены в ISSUE.md KI-R1..R6, код не тронут)
**Контекст:** исследование поиска/RAG — что именно измерять, прежде чем утверждать результат.
**Решение (приоритет):** KI-R1 (пер...
- **Статус:** автоматически синхронизировано

---

## Archived 2026-09-27 (R1 size guard: live file > 300 lines)

Moved 48 closed entries from KNOWN_ISSUES.md verbatim; open/unmarked entries stay live.

## 2026-09-26 — G6 gate blind to paraphrase twins of index phrases (Fixed)
- **Источник/Описание:** F4b (22 runs, `results/f4b/RED_TEAM.md` R1). must-hit `#3` — морф. двойник arrival-фразы каталога; G6 `PASS`, но symptom-условие 3/11. Чекер не видит табличные строки и не стеммит.
- **Fix:** `frozen_overlap_check.py` v2 — numbered-пробы + arrival-фразы каталога + лёгкий стемминг; `--selftest` + `tests/test_frozen_overlap_check.py`. **Статус:** ✅ Fixed.

## 2026-09-25 — Reindex deadlock: `_bounded_link` ran `bulk_write` on a new thread while the caller held the write RLock (Fixed)

- **Источник:** live job `090149f1` (stuck 52% "running", 0 CPU); `py-spy dump 6780` → поток `bounded-bulk_write` idle на `db_writer.py:336` (`with self._table_write_lock:`), поток `asyncio_1` ждёт его в `_bounded_link`; `reindex_ledger.jsonl` записал `RuntimeError: bulk_write exceeded 300s`.
- **Root Cause:** `run()` держит глобальный RLock (`db_manager.begin_write()`) весь reindex на своём потоке; `_bounded_link` (timeout-фикс 2026-09-25) запускал `bulk_write` в НОВОМ daemon-потоке, а `bulk_write` берёт ТОТ ЖЕ RLock → дедлок. Тот же класс для `prune`/`verify` (`recreate_table_physical`).
- **Fix:** `_bounded_link` оборачивает bounded-вызов в `_suspend_write_lock()` (уже применённый для `_safe_ivf_index`) — единая точка, покрывает все звенья.
- **Fix (итог):** разделены два мьютекса — `run()` держит отдельный `begin_run()` (non-reentrant, взаимное исключение запусков), а `_table_write_lock` берётся только на операцию. `_bounded_link` больше не освобождает write-lock. Это закрыло и дедлок, и параллельные индексаторы (auto-index + manual trigger) — они теперь сериализуются.
- **Guard:** `tests/test_bounded_link_deadlock.py` (write-lock на другом потоке не дедлочит + структурный контракт), `tests/test_run_singleflight.py` (begin_run ≠ begin_write; второй run блокируется).
- **LIVE verified (2026-09-25):** full reindex job `c09c2e22` → **completed за 858.5с** (ledger: parsing→embedding→finalizing→complete→end). Индекс: **19653 → 10103**, path-duplication **668 → 0**, dup(file_path,chunk_index) **144 → 0**.
- **Статус:** ✅ Fixed + live-verified.

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

## 2026-09-20 — Exp E13: текстовый RAG (doc-chunks) vs кодовый baseline (E10/E11)

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Measured (refuted hypothesis)
**Hypothesis:** doc-chunks (README + docs/en/ + docstrings) retrieve as well as code-chunks via search_with_mode quality.
**Method:** 16 EN doc-queries, live ...
- **Статус:** автоматически синхронизировано


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


## 2026-09-07 — Cypher-движок: анонимные узлы/рёбра ломали MATCH; ActionReceipt не писался из write-пути

- **Источник:** AGENT_DIARY.md
- **Описание:** **Status:** Fixed (оба блока закрыты, тесты зелёные)
**Root Cause:** (1) Cypher: `from_node_alias` дефолтил в `n1`, а генератор создавал `n{path_idx*2}` для анонимного узла → `no such column: n0.id`; ...
- **Статус:** автоматически синхронизировано


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
