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
## 2026-09-22 вЂ” Exp E16: РїРµСЂРµРЅРѕСЃРёРјРѕСЃС‚СЊ bootstrap trace РЅР° С‡СѓР¶РёРµ РїСЂРѕРµРєС‚С‹ (СЃС‚Р°С‚СЊСЏ CoderLegion)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** Measured (hypothesis CONFIRMED)
**Hypothesis:** РґРёРЅР°РјРёС‡РµСЃРєРёР№ С‚СЂРµР№СЃ (sys.settrace, `src/core/bootstrap_trace_plugin.py`) РІРѕСЃРїСЂРѕРёР·РІРѕРґРёС‚СЃСЏ РЅР° С‡СѓР¶РёС… Python-СЂРµРїРѕР·РёС‚РѕСЂРёСЏС… Р±РµР· РїСЂР°РІРѕРє РїР»Р°РіРёРЅР°; lin...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-22 вЂ” Exp E14: Embedder A/B вЂ” EmbeddingGemma 300M vs e5-small (production)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** Measured (hypothesis CONFIRMED)
**Hypothesis:** gemma 300M (768-dim, ctx 2048) Р·РЅР°С‡РёС‚РµР»СЊРЅРѕ СЃРёР»СЊРЅРµРµ e5-small (384-dim, ctx 512) РЅР° РєРѕРґРѕРІРѕРј СЂРµС‚СЂРёРІР°Р»Рµ РїСЂРё С†РµРЅРµ 3-4Г— РјРµРґР»РµРЅРЅРµРµ РЅР° CPU.
**Method...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-20 вЂ” Exp E13: С‚РµРєСЃС‚РѕРІС‹Р№ RAG (doc-chunks) vs РєРѕРґРѕРІС‹Р№ baseline (E10/E11)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** Measured (refuted hypothesis)
**Hypothesis:** doc-chunks (README + docs/en/ + docstrings) retrieve as well as code-chunks via search_with_mode quality.
**Method:** 16 EN doc-queries, live ...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-18 вЂ” Р¤Р°Р·Р° 1: Incremental Hot-Reload (FreshnessChecker РѕР¶РёРІР»С‘РЅ + hot-reload + KI-109)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** - **Evidence Ladder (2026-08-15, Exp 2-E E1-E3):** С„РѕСЂРјР° evidence вЂ” РїРµСЂРµРјРµРЅРЅР°СЏ; file_content = Р»СѓС‡С€РёР№ recall (qwen 0.92), graph = Р·Р°РєСЂС‹С‚РёРµ present-trap РўРћР›Р¬РљРћ Сѓ evidence-С‡РµСЃС‚РЅС‹С… РјРѕРґРµР»РµР№ (qwen3.7 FA tr...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-18 вЂ” Р¤Р°Р·Р° 1: Incremental Hot-Reload (FreshnessChecker РѕР¶РёРІР»С‘РЅ + hot-reload + KI-109)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** Fixed (7 С‚РµСЃС‚РѕРІ СЃРІРµР¶РµСЃС‚Рё РІРєР»СЋС‡Р°СЏ concurrency-СЃС‚СЂРµСЃСЃ N=16 + 1748 РїРѕР»РЅС‹Р№ pytest green; РІРµС‚РєР° РІРЅРµ PR вЂ” Р»РѕРєР°Р»СЊРЅРѕ)
**Root Cause:** FreshnessChecker (freshness.py) Р±С‹Р» РјС‘СЂС‚РІ (0 РІС‹Р·РѕРІРѕРІ) Рё РЎР›РћРњРђРќ...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-07 вЂ” Lazy-only РІРµСЂРёС„РёРєР°С†РёСЏ: VOR РІС‹Р·С‹РІР°РµС‚СЃСЏ С‚РѕР»СЊРєРѕ РёР· intel_get_project_memory, РЅРµС‚ TTL/С„РѕРЅР°

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** Open вЂ” Р·Р°С„РёРєСЃРёСЂРѕРІР°РЅРѕ РєР°Рє РїСЂРѕР±Р»РµРјР° + РїР»Р°РЅ СЌРєСЃРїРµСЂРёРјРµРЅС‚Р° (10-continuous-verification.md)
**Root Cause:** РџРѕ РґРёР·Р°Р№РЅСѓ (ADR-0003) VOR Р»РµРЅРёРІС‹Р№, РЅРѕ С‚РѕС‡РєРё РІС‹Р·РѕРІР° РІСЃРµРіРѕ РѕРґРЅР° (layer.py:1097); IdleSch...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-09 вЂ” H1: С„РѕРЅРѕРІС‹Р№ VOR-РїСЂРѕС…РѕРґ (IdleScheduler) вЂ” РїР°РјСЏС‚СЊ РїРµСЂРµРїСЂРѕРІРµСЂСЏРµС‚СЃСЏ Р±РµР· РІС‹Р·РѕРІР° Р°РіРµРЅС‚Р°

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** Fixed (6 РЅРѕРІС‹С… С‚РµСЃС‚РѕРІ + 1674 РїРѕР»РЅС‹Р№ pytest green; РІРµС‚РєР° chore/experiments-es1-es2-0909)
**Root Cause:** VOR РІС‹Р·С‹РІР°Р»СЃСЏ СЂРѕРІРЅРѕ РёР· 1 РјРµСЃС‚Р° (intel_get_project_memory, layer.py:1097); idle-Р·Р°РґР°С‡...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-09 вЂ” H2: .h Р·Р°РіРѕР»РѕРІРєРё C РІРєР»СЋС‡РµРЅС‹ РІ AST-РёРЅРґРµРєСЃР°С†РёСЋ (PARSE_EXTENSIONS + C-РїР°СЂСЃРµСЂ)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** Fixed (commit 0301fa93; KNOWN_ISSUES 2026-09-09 19:35 Р·Р°РєСЂС‹С‚)
**Root Cause:** ".h" Р±С‹Р» РІ INDEX_EXTENSIONS (РІРµРєС‚РѕСЂ-С‡Р°РЅРєРёРЅРі С€С‘Р»), РЅРѕ РќР• РІ PARSE_EXTENSIONS в†’ CodeParser.parse_file РІРѕР·РІСЂР°С‰Р°Р» [...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-07 вЂ” Cypher-РґРІРёР¶РѕРє: Р°РЅРѕРЅРёРјРЅС‹Рµ СѓР·Р»С‹/СЂС‘Р±СЂР° Р»РѕРјР°Р»Рё MATCH; ActionReceipt РЅРµ РїРёСЃР°Р»СЃСЏ РёР· write-РїСѓС‚Рё

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** Fixed (РѕР±Р° Р±Р»РѕРєР° Р·Р°РєСЂС‹С‚С‹, С‚РµСЃС‚С‹ Р·РµР»С‘РЅС‹Рµ)
**Root Cause:** (1) Cypher: `from_node_alias` РґРµС„РѕР»С‚РёР» РІ `n1`, Р° РіРµРЅРµСЂР°С‚РѕСЂ СЃРѕР·РґР°РІР°Р» `n{path_idx*2}` РґР»СЏ Р°РЅРѕРЅРёРјРЅРѕРіРѕ СѓР·Р»Р° в†’ `no such column: n0.id`; ...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-03 вЂ” Fake reindex ETA "~8s" + frozen progress in Finalizing (both fixed)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** вњ… Fixed (commit 32f11662; 5 pre-commit hooks OK; full pytest 1587 passed, 2 pre-existing unrelated env_extractor failures)
**Root Cause 1 (ETA "~8s"):** `_enrich_job_response` had a dead h...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-03 19:30 вЂ” CI RED: circular import layer в†” tools_reg (architecture_linter)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** вњ… Fixed (commit f210ed7c; CI all-jobs green on ubuntu+windows)
**Root Cause:** My ETA refactor added `tools_reg в†’ layer` import for `_embed_progress_from_log`, closing an existing `layer в†’...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-04 11:15 вЂ” CI RED: ruff lint errors caught only after push (3 commits)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** вњ… Fixed (commit 986c9be7)
**Root Cause:** Pre-commit hook did not run ruff. CI (`ruff check src/ tests/` in ci.yml) caught F401/W292 only after push, forcing fix-commits. Repeated 3 times ...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-05 12:30 вЂ” FIX: stale_detector + predict_change СЃС‚Р°Р±РёР»СЊРЅРѕ С‚Р°Р№РјР°СѓС‚РёР»Рё С‡РµСЂРµР· MCP (-32001): Р±Р»РѕРєРёСЂСѓСЋС‰РёР№ sync-РєРѕРґ РІ async-РєРѕРЅС‚РµРєСЃС‚Рµ

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** вњ… Fixed (code only, РЅРµ Р·Р°РїСѓС€РµРЅРѕ) вЂ” src/mcp/tools/doc_tools.py + predict_tools.py
**Root Cause:** `error_boundary` РїСЂРёРјРµРЅСЏРµС‚ `asyncio.wait_for(timeout_ms)` РІРѕРєСЂСѓРі `execute`, РЅРѕ РІРЅСѓС‚СЂРё `exec...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-06 21:00 вЂ” РџРѕС‡РёРЅРєР° lock_guard: С‚Р°Р№РјР°СѓС‚ 60s Р»РѕРјР°Р» РІРµСЃСЊ .locks-РїСЂРѕС‚РѕРєРѕР»

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** вњ… Fixed / **Root Cause:** `scripts/lock_guard.py` `_run` default timeout=60s вЂ” Р»СЋР±РѕР№ `git commit` РїСЂРѕРіРѕРЅСЏРµС‚ pre-commit hook (verify_diary в†’ РїРѕР»РЅС‹Р№ pytest 5-10 РјРёРЅ РЅР° Windows), РїРѕСЌС‚РѕРјСѓ acqu...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-06 21:30 вЂ” sync-subprocess РІ async-MCP (context_tool, system_tools) вЂ” fixed

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** вњ… Fixed (code only) / **Root Cause:** СЃРёСЃС‚РµРјРЅР°СЏ РїСЂРѕРІРµСЂРєР° РїРѕСЃР»Рµ С„РёРєСЃР° stale/predict: РЅР°С€Р»РёСЃСЊ РµС‰С‘ sync `subprocess.run` РІРЅСѓС‚СЂРё async `execute`. `GetContextTool._section_git` (git log С‡РµСЂРµР· s...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-06 22:00 вЂ” P-001 СЂРµС†РёРґРёРІ: cmd-РѕРєРЅР° РїСЂРё Р·Р°РїСѓСЃРєРµ/РѕС‚РєСЂС‹С‚РёРё РїСЂРѕРµРєС‚Р° (powershell/nvidia-smi Р±РµР· CREATE_NO_WINDOW) вЂ” FIXED

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** вњ… Fixed / **Root Cause:** РїРѕРІС‚РѕСЂ РёРЅС†РёРґРµРЅС‚Р° 2026-08-14 (P-001, В«С‡С‘СЂРЅС‹Рµ РѕРєРЅР° CMDВ»). Р¤РёРєСЃ 2026-08-14 РґРѕР±Р°РІРёР» CREATE_NO_WINDOW РґР»СЏ git/netstat/wmic/taskkill РІ runtime, РЅРѕ РџРћР—Р’РћР›РР› РґС‹СЂСѓ: `resou...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-08 19:40 вЂ” collect() РІ Cypher: json_group_array + С‚РёРїРёР·РёСЂРѕРІР°РЅРЅС‹Р№ РґРµРєРѕРґ (fixed)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** вњ… Fixed. / **Root Cause:** KNOWN_ISSUES 2026-09-07 вЏі вЂ” `_translate_return_expr` Р·Р°СЏРІР»СЏР» `collect` РєР°Рє Supported, РЅРѕ SQLite РЅРµ РёРјРµРµС‚ С„СѓРЅРєС†РёРё COLLECT (В«no such functionВ»); РЅРё РѕРґРЅРѕРіРѕ С‚РµСЃС‚Р° РЅР°...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-09 вЂ” РђСѓРґРёС‚ В«Active MSCodeBaseВ» (Exhibit #23: MCP tool available but never invoked)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** Open вЂ” Р·Р°С„РёРєСЃРёСЂРѕРІР°РЅ РіСЌРї (РёСЃСЃР»РµРґРѕРІР°РЅРёРµ + РїР»Р°РЅ, РєРѕРґ РќР• РІРЅРѕСЃРёР»СЃСЏ)
**Root Cause:** С„СѓРЅРґР°РјРµРЅС‚ (VOR / DebounceBatch / ConsistencyTracker / IdleScheduler / PropagationEngine) СЃСѓС‰РµСЃС‚РІСѓРµС‚, РЅРѕ РєРѕРјРїРѕ...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-10 вЂ” H1 idle-VOR + system_alerts (С†РµРїСЊ В«С„Р°Р№Р» РёР·РјРµРЅС‘РЅ в†’ STALE в†’ VOR в†’ alert Р°РіРµРЅС‚Р°В» СЃРѕР±СЂР°РЅР°)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** вњ… Fixed / **Root Cause (Exhibit #23, 2026-09-09):** РєРѕРјРїРѕРЅРµРЅС‚С‹ С†РµРїРё СЃСѓС‰РµСЃС‚РІРѕРІР°Р»Рё РїРѕ РѕС‚РґРµР»СЊРЅРѕСЃС‚Рё, РЅРѕ VOR РІС‹Р·С‹РІР°Р»СЃСЏ СЂРѕРІРЅРѕ РёР· 1 РјРµСЃС‚Р° (layer.py:intel_get_project_memory), mark_stale("memory")...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-10 вЂ” Exp 2 (Agent Behavior) + Exp 4 (Fail-Closed Freshness Gate)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** вњ… Fixed. **Root Cause (Exhibit #23, 2026-09-09):** inform-the-agent approach insufficient вЂ” agent can ignore STALE alerts; PlanFence 30/30 failures confirms action-validation unreliable; s...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-11 вЂ” H3 TTL-РіРЅРёРµРЅРёРµ: last_checked РґР»СЏ РІСЃРµС… РїСЂРѕРІРµСЂРµРЅРЅС‹С… + label stale_ttl (doc 10 closed)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** Fixed (9 РЅРѕРІС‹С… С‚РµСЃС‚РѕРІ + 1725 РїРѕР»РЅС‹Р№ pytest green; doc 10-continuous-verification H1+H2+H3 done)
**Root Cause:** INCONCLUSIVE/РЅРµРїСЂРѕРІРµСЂРµРЅРЅС‹Рµ СѓР·Р»С‹ В«РІРёСЃСЏС‚ РІРµС‡РЅРѕВ» Р±РµР· СЃР»РµРґР° РїСЂРѕРІРµСЂРєРё: live-СЃСЂРµР· ...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-13 вЂ” H4: agent-memory lifecycle РІ РјР°СЃС€С‚Р°Р±Рµ dev.to KB вЂ” Р±СѓС‚С‹Р»РѕС‡РЅРѕРµ РіРѕСЂР»С‹С€РєРѕ = СЃРµС‚РµРІРѕР№ capture, РЅРµ РіСЂР°С„

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** Fixed (СЌРєСЃРїРµСЂРёРјРµРЅС‚ РїРѕРґС‚РІРµСЂР¶РґС‘РЅ; СЃРѕРїСЂРѕРІРѕР¶РґРµРЅРёРµ Р·Р°РґР°С‡Рё closed)
**Root Cause:** РїСЂРё СЂРѕСЃС‚Рµ Р±Р°Р·С‹ 3,989 в†’ 13,519 СЃС‚Р°С‚РµР№ (3.4x), refresh own Р·Р°РЅСЏР» 10Рј38СЃ РЅР° 13.5k СЃС‚Р°С‚РµР№/82.5k РєРѕРјРјРµРЅС‚РѕРІ (134 СЃРµС‚Рµ...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ


## 2026-09-20 вЂ” РџРѕРёСЃРєРѕРІРѕРµ РєР°С‡РµСЃС‚РІРѕ / E13: РёСЃСЃР»РµРґРѕРІР°С‚РµР»СЊСЃРєРёРµ Р·Р°РґР°С‡Рё (6 РїСѓРЅРєС‚РѕРІ)

- **РСЃС‚РѕС‡РЅРёРє:** AGENT_DIARY.md
- **РћРїРёСЃР°РЅРёРµ:** **Status:** Plan (Р·Р°РґР°С‡Рё Р·Р°РЅРµСЃРµРЅС‹ РІ ISSUE.md KI-R1..R6, РєРѕРґ РЅРµ С‚СЂРѕРЅСѓС‚)
**РљРѕРЅС‚РµРєСЃС‚:** РёСЃСЃР»РµРґРѕРІР°РЅРёРµ РїРѕРёСЃРєР°/RAG вЂ” С‡С‚Рѕ РёРјРµРЅРЅРѕ РёР·РјРµСЂСЏС‚СЊ, РїСЂРµР¶РґРµ С‡РµРј СѓС‚РІРµСЂР¶РґР°С‚СЊ СЂРµР·СѓР»СЊС‚Р°С‚.
**Р РµС€РµРЅРёРµ (РїСЂРёРѕСЂРёС‚РµС‚):** KI-R1 (РїРµСЂ...
- **РЎС‚Р°С‚СѓСЃ:** Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРёРЅС…СЂРѕРЅРёР·РёСЂРѕРІР°РЅРѕ

