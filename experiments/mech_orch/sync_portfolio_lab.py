"""One-off lab -> portfolio sync (M1..E4.2, exp-24..exp-31).

Writes src/data/lab/experiments.json + experiments.ru.json in D:\\Project\\MSPortfolio
preserving their byte conventions: CRLF, indent=2, trailing-newline absent,
ensure_ascii per-file (EN ascii if no literal non-ascii, RU literal utf-8).
Field parity contract: id/date/verdict congruent EN<->RU (guard tests in
MSPortfolio tests/lab.test.ts).
"""
import json
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PORTFOLIO = Path(r"D:\Project\MSPortfolio\src\data\lab")

EN = [
    {
        "id": "exp-24",
        "date": "2026-08-25",
        "project": "mscodebase-intelligence",
        "title": "M1: real tool telemetry — 5/62 MCP tools ever used; the working-set boundary is single-digit",
        "hypothesis": "Of ~62 registered MCP tools most are dead weight in real sessions; the boundary of the effective working set is a single- or double-digit number.",
        "command": "python experiments/mech_orch/tool_metrics_analysis.py (historical tool_metrics.json) + grep error_handler lines of 2MB mscodebase-intelligence.log + debug_runtime_passport/intel_get_runtime_status",
        "result": "Registered 32 core + 14 intel + 12 inline + 4 dev = 62; server masks 16/32 by default. tool_metrics.json (entire recorded span): 8 calls across 5 tools — lsp_get_diagnostics 2c/0e, lsp_document_symbols 2c/0e, lsp_get_type_info 2c/2e (15s timeout), lsp_find_definition 1c/0e, lsp_find_references 1c/1e; LSP toolkit 37.5% error rate; search_code has 10 historical timeouts 15-31s.",
        "verdict": "partial",
        "finding": "Only 5 of 62 tools ever recorded a metric; dead-tool metrics are NOT measurable with current telemetry — a per-call counter in the error_handler path is required. The LSP toolkit (8 calls, 3 errors) is the top latency risk.",
        "chart": None,
        "conclusion": "How many tools are actually used cannot be measured retroactively — telemetry must log every call (or at least per-tool counters), otherwise the set boundary is intuition, not a metric.",
        "links": ["exp-25", "exp-26"],
    },
    {
        "id": "exp-25",
        "date": "2026-08-25",
        "project": "mscodebase-intelligence",
        "title": "M2: sub-agent in a fresh project — natural 0/5 MCP calls vs MCP-first 9 (4 wasted on unindexed files)",
        "hypothesis": "A fresh agent without MCP instructions won't touch MCP tools (goes to grep/read); with instructions it uses them, but on unindexed files semantics is useless.",
        "command": "Fixture experiments/mech_orch/lab/ (calc.py/rpn.py/tests, 1 planted bug: reverse-pop in RPN); two sub-agents in parallel: A 'MCP-first, diagnostics only', B 'natural, fix'; baseline 1 failed/4 passed.",
        "result": "Agent A (MCP-first): MCP_CALLS=9 IDE_CALLS=5 — passport OK (sub-agents see the same MCP), search_code x2 on lab -> 0 relevant (lab NOT indexed), get_symbol_info('evaluate...') -> not found, read_live_file x3 -> OK, bug found rpn.py:11 (reverse pop). Agent B (natural): MCP_CALLS=0 IDE_CALLS=5 -> 5 passed in 0.04s; baseline after fix 5 passed 0.03s, 1 file changed.",
        "verdict": "confirmed",
        "finding": "Natural agent: 0/5 MCP; MCP-first: 9 calls, ~4 idle (2 search + get_symbol_info + find_path on unindexed lab), only read_live_file (disk) productive. New files are invisible until reindex -> semantic layer on fresh code = zero. Correctness control: A found the root with exact file:line, B fixed all 4 branches not just '-', tests green.",
        "chart": None,
        "conclusion": "MCP value lives on INDEXED code; for fresh/foreign dirs meta-tools need a disk-read + ripgrep fallback instead of silent empty answers. The prompt (MCP instruction) is the strongest predictor of tool usage — stronger than tool design.",
        "links": ["exp-24", "exp-26"],
    },
    {
        "id": "exp-26",
        "date": "2026-08-25",
        "project": "mscodebase-intelligence",
        "title": "M3: latency matrix — search fast 75ms HIT vs quality 3666ms MISS; get_symbol_info misses a real symbol",
        "hypothesis": "quality semantics gives better context at a comparable cost; get_symbol_info works as an exact tool by symbol name.",
        "command": "Live session, same 9003-chunk index: search_code(fast='def get_stale_warning search_tools') -> search_code(quality='how stale warning triggers during reindex blocking') -> get_symbol_info('_get_stale_warning search_tools.py') -> grep -c on disk.",
        "result": "search_code(fast) 75ms exact hit search_tools.py:1 (_get_stale_warning); search_code(quality) 3666ms MISS (results_tasks_v3.json + CHANGELOG.md); get_symbol_info('_get_stale_warning search_tools.py') -> 'not found' (real symbol, 2nd miss per session); grep -c 28ms control.",
        "verdict": "refuted",
        "finding": "quality was 49x slower than fast (3666 vs 75ms) and semantically worse; get_symbol_info misses exact names carrying a trailing hint. On short queries fast search + grep + read_live_file beat quality search + symbol info on time AND accuracy.",
        "chart": None,
        "conclusion": "Tool smartness does not correlate with usefulness: the cheap exact signal (fast/ripgrep) beats expensive semantics (BGE-M3/BM25 rerank); a QoS threshold for quality (<1.5s) and a fast->grep fallback chain belong inside meta-tools.",
        "links": ["exp-24", "exp-27"],
    },
    {
        "id": "exp-27",
        "date": "2026-08-26",
        "project": "mscodebase-intelligence",
        "title": "E2: category pilot on the live index — fast 5/6 HIT (83%) vs quality 2/3 + leak to docs/JSON; index self-pollution discovered",
        "hypothesis": "(H2.1) the leak between categories (docs/JSON instead of code) is the main quality defect; (H2.2) fast wins on identifiers, quality on prose.",
        "command": "6 real queries with ground truth from the session x fast (5) + quality (3), limit=3 (details experiments/mech_orch/E2_category_pilot.md); GT verified earlier by grep/read; after window reload + MCP restart + reindex (9089 chunks).",
        "result": "Q1 fast 75ms HIT(top1) vs quality 3666ms MISS->JSON/CHANGELOG; Q2 fast 3779ms HIT cold / 161ms warm; Q3 fast 161ms HIT(domain); Q4 fast 190ms MISS (top1 = own E2 doc: self-pollution) vs quality 6638ms HIT(domain) indexer.py; Q5 fast 172ms HIT vs quality 284ms HIT; Q6 fast 166ms HIT vs quality 2638ms HIT(top1=incident_dataset). fast 5/6=83%; quality 2/3 + 1 domain-hit; warm latency fast 75-190ms, quality 284-6638ms (median ~2.6s).",
        "verdict": "partial",
        "finding": "fast is 83% and an order of magnitude cheaper; quality saved the only fast-MISS (Q4) at ~35x cost. The leak is confirmed (Q1 quality -> JSON/CHANGELOG; Q4/Q6 quality top-1 incident datasets) but is NOT junk — semantically relevant docs; a category-priority filter is needed, not a prohibition. NEW: the index self-pollutes with its own experiment docs (experiments/mech_orch/* captures code queries). Binary fast/quality routing is suboptimal — cascade fast-hit->stop / MISS->quality+filter+budget.",
        "chart": None,
        "conclusion": "Query-form->mode is underdetermined without a category filter; adding experiment docs to the index changes ranking (the index is sensitive to its own composition — experiments need ranking control).",
        "links": ["exp-26", "exp-28"],
    },
    {
        "id": "exp-28",
        "date": "2026-08-26",
        "project": "mscodebase-intelligence",
        "title": "E3: category router on tasks_v3.json (30 tasks) — cascade 0.233 > fast 0.167 > quality 0.133; 4 graph classes 0.00 across all arms",
        "hypothesis": "(1) the fast->quality cascade pays off; (2) different klass need different arms (a class router beats a single arm).",
        "command": "EXT venv python experiments/mech_orch/E3_category_router_eval.py (limit=8, topk=5; real DB 9089 rows; embedder force llama_cpp — auto-detect in standalone falls into ONNX-fallback, environment artifact). Arms: fast / quality / cascade.",
        "result": "fast recall@5 0.167 facts_cov 0.517 lat_med 148ms; quality 0.133 facts_cov 0.861 lat_med 2145ms; cascade 0.233 facts_cov 0.753 lat_med 564ms. BY KLASS (fast/quality/cascade): find_bug_cause 0.20/0.00/0.20 | find_caller_callee 0.00/0.50/0.50 | find_impact 0/0/0 | find_test 0/0/0 | git_history 0.50/0.25/0.50 | modify_function 0/0/0 | prepare_change 0.25/0.00/0.25 | understand_architecture 0.25/0.50/0.50 | verify_change 0/0/0.",
        "verdict": "confirmed",
        "finding": "Cascade is the winner; the winner depends on klass (git_history/bug/prepare -> fast with quality 0.00 at bug; caller_callee/architecture -> quality); find_test/find_impact/modify/verify_change = 0.00 across ALL arms — search does not replace graph/AST/impact stages.",
        "chart": {"type": "bar", "title": "recall@5 by search arm", "data": [{"label": "fast", "value": 0.167}, {"label": "quality", "value": 0.133}, {"label": "cascade", "value": 0.233}]},
        "conclusion": "Search-only gives recall@5 <= 0.23 on real code tasks; klass is a real predictor of the winning arm; a single sweeper is capped on test/impact classes without a graph stage. The 'code passport' must include call graph + impact + test-mapping, not search-only.",
        "links": ["exp-27", "exp-29"],
    },
    {
        "id": "exp-29",
        "date": "2026-08-26",
        "project": "mscodebase-intelligence",
        "title": "E4: deterministic per-class keyword router (PoC) — 0.200 < cascade 0.233, klass_acc 0.40 (NEGATIVE)",
        "hypothesis": "A per-class router (fast/bug+git+prepare, quality/caller+arch, union/test+impact+modify+verify) gives recall >= cascade (0.233) at median < 600ms.",
        "command": "EXT venv python experiments/mech_orch/E4_router_poc.py — classifier: 9 keyword rules (order matters), arms per E3; same metrics.",
        "result": "router: recall=0.200 facts_cov=0.533 lat_med=298ms p95=10745ms klass_acc=0.40; baselines (E3): fast 0.167 / quality 0.133 / cascade 0.233; BY KLASS: find_bug_cause 0.20 | git_history 0.50 | caller_callee 0.50 | arch 0.25 | prepare 0.25 | modify/test/impact/verify 0.00 ALL (even union fast+quality).",
        "verdict": "refuted",
        "finding": "klass_acc=0.40 — keyword rules are noisy (bug tasks contain 'callers', git tasks 'why'); the union arm does not save the 4 graph classes — search cannot find what is not textually in the index (callers/callees/impact must come from the graph). The search-only ceiling on this dataset is ~0.23 at ANY routing.",
        "chart": {"type": "bar", "title": "recall: keyword router vs cascade", "data": [{"label": "router", "value": 0.2}, {"label": "cascade", "value": 0.233}]},
        "conclusion": "Keyword routing by prompt does not pay off; improvement is query features (symbol tokens, intent verbs, priorities), BUT the ceiling without a graph stage remains. The 'code passport' = search(fast+cascade) + a SEPARATE graph stage (symbol index in memory), otherwise 4/9 classes = 0.00 always.",
        "links": ["exp-28", "exp-30"],
    },
    {
        "id": "exp-30",
        "date": "2026-08-26",
        "project": "mscodebase-intelligence",
        "title": "E4.1: the graph stage breaks the search-only ceiling — recall 0.433 (cascade 0.267), med 177ms (Track 1)",
        "hypothesis": "A graph stage (SymbolIndexAdapter over graph.db, cold-start) lifts the 4 failing classes (find_test/find_impact/modify/verify) above the search-only ceiling; target recall>=0.40 med<600ms.",
        "command": "EXT venv python experiments/mech_orch/E4_1_graph_arm.py (same-run: cascade AND cascade+graph in one process; real graph.db 10748 nodes / 33538 edges).",
        "result": "same-run: cascade alone 0.267 | +graph arm 0.433 | med=177ms p95=4220ms. BY KLASS (graph vs cascade): find_impact 1.00 vs 0.00 | find_test 0.50 vs 0.00 | modify_function 0.25 vs 0.00 | verify_change 0.00 vs 0.00 | other classes equal. Example graph-arm hits (10-15ms, facts instead of 4-7s quality): T2 modify intel_code_topology -> layer.py | T3 impact _expand_graph_context -> engine.py | T5 test trigger_reindex | T18 impact notify_change -> server_tools.py | T27 impact intel_code_topology.",
        "verdict": "confirmed",
        "finding": "The graph stage added +0.166 recall on three of the four failing classes at ~15ms latency and lost nowhere (fallback to cascade by construction). Lessons: (1) has_symbol is an exact node-name — search_symbols(LIKE) + strict suffix is required; (2) graph navigation must go through SymbolIndexAdapter(graph.db), not a disk-only SymbolIndex (empty JSON); (3) an empty symbol_index.json did not block the graph — it blocked choosing the wrong instance.",
        "chart": {"type": "bar", "title": "recall: cascade vs cascade+graph", "data": [{"label": "cascade", "value": 0.267}, {"label": "cascade+graph", "value": 0.433}]},
        "conclusion": "The graph stage breaks the search-only ceiling. Honest remainder: verify_change stays 0 (T9 'engine' resolves to the wrong node; T29 prompt has no identifiers); facts-coverage for graph rows was not counted (graph returns file paths, not snippets); same-run methodology is mandatory (run-to-run fast/quality variance is high).",
        "links": ["exp-28", "exp-29", "exp-31"],
    },
    {
        "id": "exp-31",
        "date": "2026-08-26",
        "project": "mscodebase-intelligence",
        "title": "E4.2: deterministic concept resolver (no LLM) — verify_change T9/T29 HIT on real graph.db, facts 4/4 & 3/4 (Track 2)",
        "hypothesis": "The two E4.1 remainders — verify_change=0 (T9 wrong-anchor 'engine', T29 no-anchor) and 'graph returns files, not text' (facts=0) — are closed NOT by an LLM classifier but by a mechanical concept-phrase registry (fail-open, klass-gated) BEFORE the lexical extract_symbol (resolution, not classification — RESEARCH.md rec #3). Regression on other classes is structurally excluded: recipes are klass-gated to verify_change, other classes fall back to the old extract_symbol.",
        "command": "Layer proof without embedder: python experiments/mech_orch/probe_e42_verify.py (real graph.db, read-only) + python -m pytest tests/test_mech_resolver.py tests/test_symbol_index_persistence.py -q.",
        "result": "probe: T9 verify_change sym=notify_change files=[.../src/mcp/server_tools.py] -> HIT gt=src/mcp/server_tools.py facts=4/4 | T29 verify_change sym=_extract_symbol_name files=[..., .../src/core/search/utils.py] -> HIT gt=src/core/search/utils.py facts=3/4 | ALL HIT. Full live same-run (30 tasks, real embedder): cascade 0.267 -> cascade+graph 0.50, med 196.8ms, p95 4514ms; verify_change graph=1.00 (T9 arm=graph:notify_change, T29 arm=graph:_extract_symbol_name) vs cascade 0.00; 9/9 classes >= cascade (no regression). pytest: 14 passed in 2.48s (resolver 10 + persistence 4).",
        "verdict": "confirmed",
        "finding": "Both verify_change misses resolve to the correct file on the real graph.db (10748 nodes); graph rows now carry facts (graph_fact_text), not 0; regression is excluded by construction (klass-gating). A 'wordless' prompt is an anchor-resolution problem, not classification — lexical extract_symbol survives neither consequence-instead-of-name (T9) nor concept-instead-of-name (T29).",
        "chart": None,
        "conclusion": "A mechanical concept registry with klass-gating is deterministic and non-regressing; recipe seeding from the 3300-call corpus (RESEARCH.md rec #3). Live same-run confirmed: verify_change 0->1.0, overall recall 0.433->0.50 at med 196.8ms (target >=0.40/<600ms).",
        "links": ["exp-30"],
    },
]

RU = [
    {
        "id": "exp-24",
        "date": "2026-08-25",
        "project": "mscodebase-intelligence",
        "title": "M1: реальная телеметрия — 5/62 MCP-инструмента хоть раз вызывались; граница рабочего набора — однозначное число",
        "hypothesis": "Из ~62 зарегистрированных MCP-инструментов большинство — мёртвый груз в реальных сессиях; граница эффективного рабочего набора — одно-двузначное число.",
        "command": "python experiments/mech_orch/tool_metrics_analysis.py (историч. tool_metrics.json) + grep error_handler-строк 2MB лога mscodebase-intelligence.log + debug_runtime_passport/intel_get_runtime_status",
        "result": "Зарегистрировано 32 core + 14 intel + 12 inline + 4 dev = 62; сервер по умолчанию маскирует 16/32. tool_metrics.json (весь записанный период): 8 вызовов на 5 инструментах — lsp_get_diagnostics 2c/0e, lsp_document_symbols 2c/0e, lsp_get_type_info 2c/2e (timeout 15s), lsp_find_definition 1c/0e, lsp_find_references 1c/1e; LSP-тулкит 37.5% ошибок; у search_code 10 исторических таймаутов 15-31s.",
        "verdict": "partial",
        "finding": "Лишь 5 из 62 инструментов хоть раз записали метрику; мёртвый груз НЕ измеряется текущей телеметрией — нужен счётчик на каждый вызов в error_handler-пути. LSP-тулкит (8 вызовов, 3 ошибки) — главный латентность-риск.",
        "chart": None,
        "conclusion": "Сколько инструментов реально используется нельзя измерить постфактум — телеметрия обязана писать каждый вызов (или хотя бы per-tool счётчик), иначе граница набора — интуиция, а не метрика.",
        "links": ["exp-25", "exp-26"],
    },
    {
        "id": "exp-25",
        "date": "2026-08-25",
        "project": "mscodebase-intelligence",
        "title": "M2: субагент в свежем проекте — natural 0/5 MCP-вызовов vs MCP-first 9 (4 холостых на неиндексированных файлах)",
        "hypothesis": "Свежий агент без инструкции про MCP не тронет MCP-инструменты (уйдёт в grep/read); с инструкцией — использует, но на неиндексированных файлах семантика бесполезна.",
        "command": "Фикстура experiments/mech_orch/lab/ (calc.py/rpn.py/tests, 1 подсаженный баг: reverse-pop в RPN); два субагента параллельно: A 'MCP-first, только диагностика', B 'natural, исправить'; baseline 1 failed/4 passed.",
        "result": "Agent A (MCP-first): MCP_CALLS=9 IDE_CALLS=5 — passport OK (субагенты видят тот же MCP), search_code x2 по lab -> 0 релевантных (lab НЕ в индексе), get_symbol_info('evaluate...') -> not found, read_live_file x3 -> OK, баг найден rpn.py:11 (reverse pop). Agent B (natural): MCP_CALLS=0 IDE_CALLS=5 -> 5 passed в 0.04s; baseline после фикса 5 passed 0.03s, 1 файл изменён.",
        "verdict": "confirmed",
        "finding": "Natural-агент: 0/5 MCP; MCP-first: 9 вызовов, ~4 холостых (2 search + get_symbol_info + find_path по неиндексированному lab), продуктивен только read_live_file (диск). Новые файлы невидимы до reindex -> семантический слой на свежем коде = нуль. Контроль правильности: A нашёл корень с точным file:line, B починил все 4 ветки (не только '-'), тесты зелёные.",
        "chart": None,
        "conclusion": "Ценность MCP-слоя — на ИНДЕКСИРОВАННОМ коде; для свежих/чужих директорий мета-инструментам нужен fallback «read из диска + ripgrep» вместо молчаливого пустого ответа. Промпт (инструкция про MCP) — сильнейший предиктор использования инструментов, сильнее самого дизайна.",
        "links": ["exp-24", "exp-26"],
    },
    {
        "id": "exp-26",
        "date": "2026-08-25",
        "project": "mscodebase-intelligence",
        "title": "M3: матрица латентности — search fast 75ms HIT vs quality 3666ms MISS; get_symbol_info промахивается по реальному символу",
        "hypothesis": "«Quality-семантика» даёт лучший контекст за сопоставимое время; get_symbol_info работает как «точный» инструмент по имени символа.",
        "command": "Живая сессия, тот же индекс 9003 chunks: search_code(fast='def get_stale_warning search_tools') -> search_code(quality='how stale warning triggers during reindex blocking') -> get_symbol_info('_get_stale_warning search_tools.py') -> grep -c на диске.",
        "result": "search_code(fast) 75ms точное попадание search_tools.py:1 (_get_stale_warning); search_code(quality) 3666ms ПРОМАХ (results_tasks_v3.json + CHANGELOG.md); get_symbol_info('_get_stale_warning search_tools.py') -> 'not found' (реальный символ, 2-й miss за сессию); grep -c 28ms контроль.",
        "verdict": "refuted",
        "finding": "quality в 49× медленнее fast (3666 vs 75ms) и при этом семантически хуже; get_symbol_info промахивается по точным именам с хвостом-подсказкой. На коротких запросах fast search + grep + read_live_file выигрывают у quality search + symbol info по времени И точности.",
        "chart": None,
        "conclusion": "Степень «умности» инструмента не коррелирует с пользой: дешёвый точный сигнал (fast/ripgrep) бьёт дорогую семантику (BGE-M3/BM25 rerank); QoS-порог для quality (<1.5s) и fallback-цепочка fast->grep обязаны быть в мета-инструментах.",
        "links": ["exp-24", "exp-27"],
    },
    {
        "id": "exp-27",
        "date": "2026-08-26",
        "project": "mscodebase-intelligence",
        "title": "E2: категорийный пилот на живом индексе — fast 5/6 HIT (83%) vs quality 2/3 + утечка в docs/JSON; обнаружено само-загрязнение индекса",
        "hypothesis": "(H2.1) утечка между категориями (docs/JSON вместо кода) — главный дефект quality; (H2.2) fast выигрывает на идентификаторах, quality — на прозе.",
        "command": "6 реальных запросов с ground truth из сессии × fast (5) + quality (3), limit=3 (детали experiments/mech_orch/E2_category_pilot.md); GT верифицированы ранее grep/read; после релоада окна + рестарта MCP + реиндекса (9089 chunks).",
        "result": "Q1 fast 75ms HIT(top1) vs quality 3666ms MISS->JSON/CHANGELOG; Q2 fast 3779ms HIT холод / 161ms тёплый; Q3 fast 161ms HIT(домен); Q4 fast 190ms MISS (top1 = свой E2-док: само-загрязнение) vs quality 6638ms HIT(домен) indexer.py; Q5 fast 172ms HIT vs quality 284ms HIT; Q6 fast 166ms HIT vs quality 2638ms HIT(top1=incident_dataset). fast 5/6=83%; quality 2/3 + 1 домен-hit; тёплая латентность fast 75-190ms, quality 284-6638ms (медиана ~2.6s).",
        "verdict": "partial",
        "finding": "fast — 83% и на порядок дешевле; quality спас единственный fast-MISS (Q4) ценой ~35× времени. Утечка подтверждена (Q1 quality -> JSON/CHANGELOG; Q4/Q6 quality top-1 incident-датасеты), но это НЕ мусор — семантически релевантные документы; нужен фильтр по приоритету категорий, не запрет. НОВОЕ: индекс само-загрязняется собственными эксперимент-доками (experiments/mech_orch/* перехватывает кодовые запросы). Бинарный роут fast/quality неоптимален — каскад fast-hit->стоп / MISS->quality+фильтр+бюджет.",
        "chart": None,
        "conclusion": "«Форма запроса -> режим» недоопределена без категорийного фильтра; добавление эксперимент-доков в индекс меняет ранжирование (индекс чувствителен к своему составу — нужен контроль экспериментов в ранжировании).",
        "links": ["exp-26", "exp-28"],
    },
    {
        "id": "exp-28",
        "date": "2026-08-26",
        "project": "mscodebase-intelligence",
        "title": "E3: категорийный роутер на tasks_v3.json (30 задач) — каскад 0.233 > fast 0.167 > quality 0.133; 4 граф-класса 0.00 у ВСЕХ рук",
        "hypothesis": "(1) каскад fast->quality окупается; (2) разные klass требуют разных рук (роутер по классам > единой руки).",
        "command": "EXT venv python experiments/mech_orch/E3_category_router_eval.py (limit=8, topk=5; реальная БД 9089 rows; embedder force llama_cpp — авто-детект в standalone ломается в ONNX-fallback, артефакт среды). Руки: fast / quality / cascade.",
        "result": "fast recall@5 0.167 facts_cov 0.517 lat_med 148ms; quality 0.133 facts_cov 0.861 lat_med 2145ms; cascade 0.233 facts_cov 0.753 lat_med 564ms. BY KLASS (fast/quality/cascade): find_bug_cause 0.20/0.00/0.20 | find_caller_callee 0.00/0.50/0.50 | find_impact 0/0/0 | find_test 0/0/0 | git_history 0.50/0.25/0.50 | modify_function 0/0/0 | prepare_change 0.25/0.00/0.25 | understand_architecture 0.25/0.50/0.50 | verify_change 0/0/0.",
        "verdict": "confirmed",
        "finding": "Каскад — победитель; победитель зависит от klass (git_history/bug/prepare -> fast при quality 0.00 у bug; caller_callee/architecture -> quality); find_test/find_impact/modify/verify_change = 0.00 у ВСЕХ рук — поиск не заменяет граф/AST/impact-стадии.",
        "chart": {"type": "bar", "title": "recall@5 по поисковым рукам", "data": [{"label": "fast", "value": 0.167}, {"label": "quality", "value": 0.133}, {"label": "cascade", "value": 0.233}]},
        "conclusion": "Поиск-только даёт recall@5 <= 0.23 на реальных кодовых задачах; klass — реальный предиктор победившей руки; «single sweeper» ограничен на test/impact классах без граф-стадии. «Паспорт кода» обязан включать call graph + impact + test-mapping, а не быть search-only.",
        "links": ["exp-27", "exp-29"],
    },
    {
        "id": "exp-29",
        "date": "2026-08-26",
        "project": "mscodebase-intelligence",
        "title": "E4: детерминированный keyword-роутер по классам (PoC) — 0.200 < каскад 0.233, klass_acc 0.40 (ОТРИЦАТЕЛЬНЫЙ)",
        "hypothesis": "Пер-классный роутер (fast/bug+git+prepare, quality/caller+arch, union/test+impact+modify+verify) даст recall >= каскада (0.233) при медиане < 600ms.",
        "command": "EXT venv python experiments/mech_orch/E4_router_poc.py — классификатор: 9 keyword-правил (порядок важен), руки по E3; те же метрики.",
        "result": "router: recall=0.200 facts_cov=0.533 lat_med=298ms p95=10745ms klass_acc=0.40; baseline (E3): fast 0.167 / quality 0.133 / cascade 0.233; BY KLASS: find_bug_cause 0.20 | git_history 0.50 | caller_callee 0.50 | arch 0.25 | prepare 0.25 | modify/test/impact/verify 0.00 ВСЕ (даже union fast+quality).",
        "verdict": "refuted",
        "finding": "klass_acc=0.40 — keyword-правила шумные (bug-задачи содержат «callers», гиты — «почему»); union-рука не спасает 4 граф-класса — поиск не может найти того, чего нет в индексе текстово (callers/callees/impact обязаны прийти из графа). Потолок search-only на этом датасете ~0.23 при ЛЮБОЙ маршрутизации.",
        "chart": {"type": "bar", "title": "recall: keyword-роутер vs каскад", "data": [{"label": "router", "value": 0.2}, {"label": "cascade", "value": 0.233}]},
        "conclusion": "Keyword-роутинг по промпту не окупается; улучшение — фичи запроса (symbol-токены, интенты-глаголы, приоритеты), НО потолок без граф-стадии остаётся. «Паспорт кода» = search(fast+cascade) + ОТДЕЛЬНАЯ граф-стадия (symbol index в памяти), иначе 4/9 классов = 0.00 всегда.",
        "links": ["exp-28", "exp-30"],
    },
    {
        "id": "exp-30",
        "date": "2026-08-26",
        "project": "mscodebase-intelligence",
        "title": "E4.1: граф-стадия пробивает потолок search-only — recall 0.433 (каскад 0.267), med 177ms (Дорожка 1)",
        "hypothesis": "Граф-стадия (SymbolIndexAdapter над graph.db, cold-start) поднимает 4 провальных класса (find_test/find_impact/modify/verify) выше потолка search-only; цель recall>=0.40 med<600ms.",
        "command": "EXT venv python experiments/mech_orch/E4_1_graph_arm.py (same-run: каскад И каскад+граф в одном процессе; реальный graph.db 10748 узлов / 33538 рёбер).",
        "result": "same-run: cascade alone 0.267 | +graph arm 0.433 | med=177ms p95=4220ms. BY KLASS (graph vs cascade): find_impact 1.00 vs 0.00 | find_test 0.50 vs 0.00 | modify_function 0.25 vs 0.00 | verify_change 0.00 vs 0.00 | остальные — equal. Примеры попаданий граф-руки (10-15ms, факты вместо 4-7s quality): T2 modify intel_code_topology -> layer.py | T3 impact _expand_graph_context -> engine.py | T5 test trigger_reindex | T18 impact notify_change -> server_tools.py | T27 impact intel_code_topology.",
        "verdict": "confirmed",
        "finding": "Граф-стадия добавила +0.166 recall на трёх из четырёх провальных классов при латентности ~15ms и не проиграла нигде (fallback на каскад по построению). Уроки: (1) has_symbol — точное имя узла, нужен search_symbols(LIKE) + strict-суффикс; (2) граф-навигация обязана идти через SymbolIndexAdapter(graph.db), а не обычный SymbolIndex с диска (пустой JSON); (3) пустой symbol_index.json не блокировал граф — блокировал выбор неправильного инстанса.",
        "chart": {"type": "bar", "title": "recall: каскад vs каскад+граф", "data": [{"label": "cascade", "value": 0.267}, {"label": "cascade+graph", "value": 0.433}]},
        "conclusion": "Граф-стадия пробивает потолок search-only. Остаток честно: verify_change остаётся 0 (T9 'engine' резолвится не туда; T29 — промпт без идентификаторов); facts-покрытие граф-строк не считалось (граф отдаёт пути файлов, не сниппеты); same-run методология обязательна (run-to-run дисперсия fast/quality высока).",
        "links": ["exp-28", "exp-29", "exp-31"],
    },
    {
        "id": "exp-31",
        "date": "2026-08-26",
        "project": "mscodebase-intelligence",
        "title": "E4.2: детерминированный concept-резолвер (без LLM) — verify_change 0→1.0, recall 0.433→0.50 (Дорожка 2)",
        "hypothesis": "Два остатка E4.1 — verify_change=0 (T9 wrong-anchor 'engine', T29 no-anchor) и «граф отдаёт файлы, не текст» (facts=0) — закрываются НЕ LLM-классификатором, а механическим concept-phrase-реестром (fail-open, klass-gated) ПЕРЕД лексическим extract_symbol (резолв, не классификация — RESEARCH.md rec #3). Регресс на других классах структурно исключён: рецепты klass-gated на verify_change, остальные классы fallback на старый extract_symbol.",
        "command": "Подтверждение слоя без эмбеддера: python experiments/mech_orch/probe_e42_verify.py (реальный graph.db, read-only) + python -m pytest tests/test_mech_resolver.py tests/test_symbol_index_persistence.py -q; полный live: EXT venv python experiments/mech_orch/E4_1_graph_arm.py",
        "result": "probe: T9 verify_change sym=notify_change files=[.../src/mcp/server_tools.py] -> HIT gt=src/mcp/server_tools.py facts=4/4 | T29 verify_change sym=_extract_symbol_name files=[..., .../src/core/search/utils.py] -> HIT gt=src/core/search/utils.py facts=3/4 | ALL HIT. Полный live same-run (30 задач, реальный эмбеддер): cascade 0.267 -> cascade+graph 0.50, med 196.8ms, p95 4514ms; verify_change graph=1.00 (T9 arm=graph:notify_change, T29 arm=graph:_extract_symbol_name) vs cascade 0.00; 9/9 классов >= каскада (без регресса). pytest: 14 passed в 2.48s (resolver 10 + persistence 4).",
        "verdict": "confirmed",
        "finding": "Оба verify_change-промаха резолвятся в правильный файл на реальном graph.db (10748 узлов); граф-строки теперь несут факты (graph_fact_text), а не 0; регресс исключён по построению (klass-gating) и подтверждён прогоном (9/9 классов >= каскада). «Бессловесный» промпт — задача резолва якоря, а не классификации: лексический extract_symbol не переживает ни «следствие вместо имени» (T9), ни «концепт вместо имени» (T29). Полный live same-run выполнен: recall 0.433→0.50 при med 196.8ms (цель ≥0.40/<600ms).",
        "chart": None,
        "conclusion": "Механический concept-реестр с klass-gating детерминирован и не регрессит; наполнение рецептов — из 3300-call корпуса (RESEARCH.md rec #3). Live same-run подтвердил: verify_change 0→1.0, recall 0.433→0.50 при med 196.8ms.",
        "links": ["exp-30"],
    },
]

NEGATIVE_RESULTS_EN = [
    {
        "attempt": "Per-class deterministic keyword router (fast/bug+git+prepare, quality/caller+arch, union/test+impact+modify+verify) as the orchestration layer replacing a single search arm",
        "whyFailed": "klass_acc 0.40 — keyword rules are noisy (bug tasks contain 'callers', git tasks 'why'); the union fast+quality arm did not lift the 4 graph classes (0.00). The search-only ceiling on this dataset is ~0.23 at ANY routing — search cannot find what is not textually in the index.",
        "date": "2026-08-26",
        "ref": "exp-29",
    }
]

NEGATIVE_RESULTS_RU = [
    {
        "attempt": "Пер-классный детерминированный keyword-роутер (fast/bug+git+prepare, quality/caller+arch, union/test+impact+modify+verify) как слой оркестрации вместо единой поисковой руки",
        "whyFailed": "klass_acc 0.40 — keyword-правила шумные (bug-задачи содержат «callers», гиты — «почему»); union-рука fast+quality не подняла 4 граф-класса (0.00). Потолок search-only на этом датасете ~0.23 при ЛЮБОЙ маршрутизации — поиск не может найти того, чего нет в индексе текстово.",
        "date": "2026-08-26",
        "ref": "exp-29",
    }
]


def _has_literal_non_ascii(path: Path) -> bool:
    return any(ord(c) > 127 for c in path.read_text(encoding="utf-8"))


def sync() -> None:
    en_path = PORTFOLIO / "experiments.json"
    ru_path = PORTFOLIO / "experiments.ru.json"
    en = json.loads(en_path.read_text(encoding="utf-8"))
    ru = json.loads(ru_path.read_text(encoding="utf-8"))

    existing = {e["id"] for e in en["experiments"]}
    for e in EN:
        if e["id"] in existing:
            idx = next(i for i, x in enumerate(en["experiments"]) if x["id"] == e["id"])
            en["experiments"][idx] = e
            print(f"[updt] {e['id']}")
            continue
        en["experiments"].append(e)
        print(f"[add ] {e['id']} -> {e['title'][:60]}...")
    en["negativeResults"].extend(NEGATIVE_RESULTS_EN)

    existing_ru = {e["id"] for e in ru["experiments"]}
    for e in RU:
        if e["id"] in existing_ru:
            idx = next(i for i, x in enumerate(ru["experiments"]) if x["id"] == e["id"])
            ru["experiments"][idx] = e
            continue
        ru["experiments"].append(e)
    ru["negativeResults"].extend(NEGATIVE_RESULTS_RU)

    # preserve per-file writing conventions: CRLF via default newline translation,
    # indent=2, no trailing newline, ensure_ascii matching current literal style.
    for path, data in ((en_path, en), (ru_path, ru)):
        ensure_ascii = not _has_literal_non_ascii(path)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=ensure_ascii, indent=2)

    print(f"EN experiments: {len(en['experiments'])} | RU: {len(ru['experiments'])}")


if __name__ == "__main__":
    try:
        sync()
    except Exception:
        import traceback

        traceback.print_exc()
        sys.exit(1)