# Анализ 4 code-intelligence проектов (fallow, code-review-graph, chunkhound, repowise)

> Цель: вскрыть, что реально работает vs бутафория, и что перенять в MSCodeBase.
> Метод: клонирование исходников + глубокое чтение (4 саб-агента) + реальные прогоны CLI на тестовых/реальных репозиториях.
> Дата: 2026-07-19. Песочница: `D:\analysis_sandbox`.

---

## 0. TL;DR — вердикт по каждому

| Проект | Реально работает? | Бутафория | Стоит перенять | Локальный прогон |
|---|---|---|---|---|
| **fallow** (Rust, TS/JS) | ✅ Да, production-grade | Маркетинг «call resolution» (на деле import-graph); Fallow Runtime — закрытый платный слой | Typed JSON contract, exit 0/1/2, SARIF, audit+baseline, suppression markers, SA-IS dup, boundary presets | ✅ `audit`/`health` на самом себе: 66 dead files, score 50/D |
| **code-review-graph** (Py) | ✅ Да, без стабов | «82x token reduction» (whole-corpus upper bound), «recall 1.0» (circular) | Incremental SHA-256, SQL-BFS blast-radius, edge confidence tiers, CRG_TOOLS filter, token-savings panel, custom-languages TOML, multi-repo daemon, hybrid FTS+vector | ✅ `build` на тест-репо: 7 nodes/11 edges, FTS5 |
| **chunkhound** (Py) | ✅ Ядро (parser/DuckDB/research) | «Ollama local» (убран из кода), LanceDB-provider без search, «local-first» = только хранение, не inference | cAST chunking, git-history search, citation engine, elbow detection, map-reduce synthesis, serial executor, watchman bridge | ⚠️ `index` падает без embedding provider (нет regex-only режима) |
| **repowise** (Py+TS) | ✅ Да, ядро живое | ROC AUC 0.74 (только во внешнем bench-репо), «−96% tokens» (метрика загрузки, не счёта при caching), «25 markers» (реально ~60), «10 tools» (реально 17, 10 default) | `_meta` stale_warning, 3-tier call resolution, biomarker registry, git hotspots+ownership, ADR substring-gate, deterministic refactoring, lean MCP-surface, distill | ✅ `init --index-only` без ключа: 3 файла/5.4s, граф 11/13, health считается |

**Главный урок:** во всех четырёх ядро — реальный код, НЕ заглушки. Бутафория — в маркетинговых заголовках (числа завышены/circular), а не в пустых функциях. Исключение: Fallow Runtime (fallow) и LanceDB-provider (chunkhound) — реально неполные/закрытые.

---

## 1. fallow (Rust, TS/JS static analysis)

### Что реально работает (проверено кодом + прогоном)
- **Dead-code detection** — BFS-достижимость от entry points по import/export-рёбрам (`crates/graph/src/graph/reachability.rs`, `crates/core/src/analyze/unused_exports.rs`). На реальном прогоне: 66 dead files, 116 dead exports, 1 circular dep.
- **Duplication (SA-IS suffix array)** — `crates/engine/src/duplication_detector/detect/suffix_array.rs`: полноценный induced-sorting, не заглушка. Пайплайн tokenize→normalize→SA→LCP→ranking собран.
- **Boundary violations** — 4 пресета (`bulletproof`/`layered`/`hexagonal`/`feature-sliced`) в `crates/config/src/config/boundaries.rs`, детектор в `crates/core/src/analyze/boundary.rs`.
- **Audit gate + baseline + suppression** — `crates/cli/src/audit_output.rs` (exit 0/1/2), `crates/engine/src/baseline.rs`, `crates/types/src/suppress.rs`. Прогон `audit` реально работает (0 changed files → pass).
- **MCP server** — ~30 тулов, но как **subprocess-фасад** поверх CLI (`crates/mcp/src/tools/*.rs` шеллит бинарник).
- **Node API** — 7 реальных экспортов через napi (`crates/napi/src/lib.rs`).
- **Typed JSON contract + SARIF** — `crates/api/src/sarif_output.rs`, schema drift-guard.

### Что бутафория / оверпромисинг
- **«Call resolution» — НЕТ.** Граф = import/export-рёбра. `obj.foo()`, динамический dispatch, re-bound callee → `unresolved_callees`, не резолвятся. `trace` честно называет это «import-symbol edges».
- **Fallow Runtime (платный)** — `crates/v8-coverage/src/lib.rs` открыт (парсер V8 coverage), но «cross-reference, combined scoring, hot-path heuristics» — **закрыты** в `fallow-cov` (private). Без лицензии это только парсер дампа.
- **MCP «read-only sandbox без FS/network»** — Code Mode = QuickJS с лимитами ресурсов (`code_mode.rs`), но НЕ доказано, что JS-контекст лишён `fs`/`net`. Sandbox вычислений, не jail ОС.
- Бенчмарки (64ms fastify) подтверждены кодом harness-а, но НЕ прогнаны мной (нет Rust-тулчейна).

### Что стоит перенять в MSCodeBase
1. **Typed JSON output contract + schema drift-guard** (Pydantic→JSON Schema, CI-тест на дрейф).
2. **Exit codes 0/1/2** для PR-гейта (`mscodebase audit --base <commit>`).
3. **SARIF exporter** (сейчас только JSON).
4. **Audit gate с baseline** (только новые проблемы в PR).
5. **Suppression markers** (`// mscodebase-ignore-next-line dead-code` + stale-detection).
6. **SA-IS dup detection** (заменить pairwise-хеш на suffix-array по токенам).
7. **Boundary presets** (layered/hexagonal/feature-sliced) как конфиг + детектор нарушений по графу вызовов.
8. **Plugin system фреймворков** (Django/Flask/FastAPI: правила «эти символы used»).
9. **Impact closure (reverse-BFS)** для PR impact-analysis.

### Риски переноса
- oxc vs tree-sitter: резолвинг импортов в TS точнее, чем у нас будет на tree-sitter.
- SA-IS на Python медленнее (GIL); нужен C-extension или `suffix_array` пакет.
- Точность dead-code = import-granularity; в Python динамика (`__import__`) даст больше false-negative.
- MCP как subprocess — медленно; у нас лучше вызывать Python-API напрямую.

---

## 2. code-review-graph (Python, tree-sitter knowledge graph)

### Что реально работает (проверено кодом + прогоном)
- **Парсер** — `parser.py` (14k строк): реальный generic AST-walker + ручные extract-функции для 32 языков. YAML скипается (честно), редкие языки — regex-фолбэк.
- **Граф в SQLite + NetworkX** — `graph.py::GraphStore`, WAL, FTS5. Прогон: 7 nodes/11 edges, FTS5 rebuilt.
- **Incremental SHA-256** — `incremental.py`: hash per file → re-parse only changed + dependents.
- **SQL-BFS blast-radius** — `graph.py::get_impact_radius_sql` (bounded relaxation в БД, не загрузка всего графа в RAM).
- **Community detection (Leiden)** — `communities.py` через igraph, fallback file-based.
- **Flow detection** — BFS от entry points (`flows.py`).
- **Hybrid search FTS5 + vector RRF** — `search.py` (BM25 + embeddings + Reciprocal Rank Fusion).
- **30 MCP tools** — 0 TODO/NotImplementedError в core/tools (проверено grep).
- **Multi-repo daemon** — `daemon.py` (watchdog + PID-check + respawn детей).
- **Token savings panel + tiktoken verify** — `context_savings.py`.

### Что бутафория / оверпромисинг
- **«82x median token reduction»** — бейзлайн = whole-corpus (весь репо как контекст). README сам признаёт: «upper bound no real agent pays». Реальный `agent_baseline` (grep top-3) гораздо ближе.
- **«impact F1 0.71, recall 1.0»** — recall circular (ground truth из того же графа). Есть честный `co_change` режим с нижним recall.
- **«search MRR 0.35»** — слабый поиск (признан), Express = 0 хитов.
- **«flow detection 33% recall»** — benchmark-derived, не hardcoded.
- `confidence_tier=AMBIGUOUS` задуман, но не заполняется в коде (только EXTRACTED/INFERRED).

### Что стоит перенять в MSCodeBase
1. **Incremental SHA-256 + dependent re-parse** (<2s updates вместо тяжёлой переиндексации).
2. **SQL-BFS blast-radius** (bounded relaxation, меньше RAM).
3. **Edge confidence tiers** (EXTRACTED/INFERRED/AMBIGUOUS + float) — у нас рёбра плоские.
4. **CRG_TOOLS filter** (env-фильтр тулов для token-constrained сред; у нас 39 tools).
5. **Token Savings panel + tiktoken verify** (метрика ценности для владельца).
6. **Custom languages через TOML** (BYO-language без правок кода).
7. **Multi-repo daemon** (health-check + respawn).
8. **Community detection (Leiden)** для architecture overview.
9. **Hybrid FTS+vector search** (BM25 fallback когда embeddings off).
10. **Честный eval-фреймворк** с `co_change`-режимом (избежать circular recall).

### Риски переноса
- `tree_sitter_language_pack` — внешний пакет; наши node-types отличаются.
- SQLite vs LanceDB — BFS надо переписывать под наш graph-store.
- igraph/NetworkX — тяжёлые deps для Windows-расширения Zed.
- Двойной BFS-движок (SQL+NetworkX) — брать сразу SQL-вариант.

---

## 3. chunkhound (Python, local-first RAG + git + web)

### Что реально работает (проверено кодом)
- **cAST chunking** — `parsers/universal_parser.py` (split-then-merge по non-whitespace chars, `max_chunk_size=1200`, greedy-merge, embedded SQL detect).
- **DuckDB** — `providers/database/duckdb_provider.py`: схема files/chunks, embeddings по размерности (`embeddings_<dims>` + HNSW), sidecar `.root.json`, compaction.
- **Embedding providers** — VoyageAI/OpenAI/Azure/OpenAI-compatible (реальные клиенты с batching/rerank).
- **Research (RAG + LLM)** — `services/research/`: unified search → exploration (BFS/wide/parallel) → map-reduce synthesis → citation system. Реальный grounding.
- **MCP server** — `search`/`code_research`/`websearch`/`daemon_status`.
- **Daemon + IPC** — единственный владелец DuckDB, JSON-RPC 2.0 (unix socket / windows pipe).
- **Watchman** — упакованный бинарник + bridge (watchdog PollingObserver).
- **Autodoc** — генерирует Astro-сайт с citation-блоками.
- **`chunkhound_native` (Rust)** — PyO3 cdylib, НО только `scan_files` (file-walker, не парсинг).

### Что бутафория / оверпромисинг
- **«Ollama (local)»** — убран из кода (`llm_config.py`: «use provider='openai' with base_url»). README не уточняет.
- **LanceDB-provider** — `lancedb_provider.py` имеет insert, НО НЕТ `search_semantic`/`search_regex` (write-only, TODO#107). У нас LanceDB — основной и рабочий, не копировать их пример.
- **«Local-first»** — только хранение/индексация локальны. Semantic/research/websearch **требуют API keys** (или локальный LLM-сервер). Regex search — единственный без API.
- **Web research** — требует headless Chrome (`zendriver`), не local-first.
- **Прогон:** `chunkhound index .` **упал** с «No embedding provider configured». Regex-only режим индексации отсутствует.

### Что стоит перенять в MSCodeBase
1. **cAST chunking strategy** (split-then-merge, 1200 non-ws chars, embedded SQL detect).
2. **Git-history search как режим** (`search(commit_range=...)` + безопасная валидация ref).
3. **Citation/grounding engine** (нумерованные цитаты с валидацией файл/строка).
4. **Elbow detection** для фильтрации релевантности (без жёсткого threshold).
5. **Map-reduce synthesis с token-budget**.
6. **Pluggable exploration strategies** (BFS/wide/parallel).
7. **Serial executor для thread-safety** (актуально для нашего §5.13 race с LanceDB).
8. **Watchman bridge** (паттерн «пакуем бинарник + subscription»).
9. **Autodoc как «4-й job»** (docs из тех же чанков).

### Риски переноса
- LanceDB у них сломан — не брать как образец.
- `zendriver`/Chrome для websearch — оверхед; оставить опциональным.
- Docstring-bloat в коде — брать только логику.
- CLI-LLM-провайдеры (claude_code_cli) хрупки (subprocess deadlock по §5.16) — брать только library-SDK.
- Rust `scan_files` не ускоряет парсинг — не переносить.

---

## 4. repowise (Python+TS, 5 intelligence layers)

### Что реально работает (проверено кодом + прогоном)
- **Code Health** — `analysis/health/biomarkers/registry.py`: ~60 детекторов (BrainMethod, GodClass, LCOM4, Rabin-Karp dup, hotspot). Прогон `health`: считает CCN/Nest/NLOC.
- **Graph (3-tier call resolution)** — `ingestion/call_resolver.py`: Tier1 same-file (0.95), Tier2 import-scoped (0.90), Tier3 global-unique (0.50). Leiden communities, PageRank.
- **Git layer** — hotspots (churn×complexity), ownership (blame), co-change, bus factor (`ingestion/git_indexer/`).
- **Refactoring** — детерминированно (Extract Class = LCOM4 components), LLM только опционально для diff.
- **Decisions mining** — 7-8 источников, substring gate перед persistence (`analysis/decisions/`).
- **MCP server** — 17 тулов (10 default), `_meta` envelope (index_age_days, stale_warning).
- **Docs RAG** — FTS5 + vector + RRF.
- **Прогон:** `init --index-only` без ключа: 3 файла/5.4s, граф 11/13, dead code найден, git history проанализирован. Claim «no LLM, no key» ✅.

### Что бутафория / оверпромисинг
- **ROC AUC 0.74** — код `defect_accuracy.py` это precision@K самовалидация, НЕ ROC. Реальный AUC только во внешнем `repowise-bench` (не в репо). Воспроизводимость = «trust our bench-repo».
- **«−96% context tokens»** — сравнение get_context vs raw grep+Read. README сам признаёт: prompt caching мутит cost delta. Метрика загрузки, не счёта.
- **«2.3× CodeScene»** — один benchmark-набор (n=1 dataset).
- **«<30s на 3000 файлов»** — недоказуемо из репо (нет встроенного bench).
- **«25 markers»** — реально ~60 (неточность в меньшую сторону).
- **«10 tools»** — реально 17 (10 default-surface).
- Нет стабов в free-функциональности.

### Что стоит перенять в MSCodeBase
1. **`_meta` stale_warning** (live HEAD vs indexed commit) — добавить `index_age_days` в наши ответы.
2. **3-tier call resolution** (confidence-уровни для резолва вызовов).
3. **Biomarker registry** (явный factory-list, веса defect/maintainability/performance).
4. **Git hotspots = churn×complexity + blame ownership**.
5. **ADR mining с substring gate** (анти-галлюцинационный gate для `intel_auto_collect_adrs`).
6. **Deterministic refactoring plans** (LCOM4 → Extract Class).
7. **Lean MCP-surface** (курируемый набор вместо 39 тулов сразу).
8. **`distill` command** (errors-first с `[repowise#ref]` маркерами).
9. **Agent provenance** (трекинг происхождения ответов).
10. **Counterfactual token savings** (подсчёт экономии vs raw).

### Риски переноса
- graspologic/igraph для Leiden — тяжёлый dep; у нас networkx + Louvain-fallback.
- SQLite/PostgreSQL + alembic (38 миграций) — у нас LanceDB; переносим алгоритмы, не схему.
- ROC AUC недоказуем локально — нужен свой корпус (PROMISE/jEdit).
- Regex-tier resolvers для редких языков — не все tier-1.
- Установка требует Rust (litellm собирается из сырцов) — `--only-binary` обходной путь.

---

## 5. Синтез: что перенять в MSCodeBase (приоритеты)

### Tier 1 — быстрые выигрыши (архитектура/метрики, мало кода)
1. **Token Savings panel + tiktoken verify** (из CRG) — метрика ценности для владельца.
2. **`_meta` stale_warning** (из repowise) — `index_age_days`, сравнение live HEAD vs indexed commit.
3. **CRG_TOOLS / lean MCP-surface** (из CRG/repowise) — фильтр тулов для token-constrained сред.
4. **Exit codes 0/1/2 + SARIF** (из fallow) — для CI-гейта.
5. **Suppression markers** (из fallow) — `// mscodebase-ignore-next-line`.

### Tier 2 — средние усилия (алгоритмы)
6. **Incremental SHA-256 + dependent re-parse** (из CRG) — вместо тяжёлой переиндексации.
7. **Edge confidence tiers** (EXTRACTED/INFERRED/AMBIGUOUS) (из CRG) — у нас рёбра плоские.
8. **3-tier call resolution** (из repowise) — confidence-уровни для резолва.
9. **Hybrid FTS+vector search** (из CRG) — BM25 fallback когда embeddings off.
10. **cAST chunking** (из chunkhound) — split-then-merge по non-ws chars.

### Tier 3 — крупные фичи (исследования)
11. **Code-health biomarkers registry** (из repowise) — 60 детекторов, веса.
12. **Git hotspots + ownership + co-change** (из repowise) — churn×complexity.
13. **Deterministic refactoring plans** (из repowise) — LCOM4 → Extract Class.
14. **ADR mining с substring gate** (из repowise) — для `intel_auto_collect_adrs`.
15. **SA-IS dup detection** (из fallow) — заменить pairwise-хеш.
16. **Multi-repo daemon** (из CRG) — health-check + respawn.
17. **Boundary presets** (из fallow) — layered/hexagonal/feature-sliced.
18. **Citation/grounding engine** (из chunkhound) — для search ответов.

### Антипаттерны (НЕ копировать)
- ❌ «82x / recall 1.0 / −96% tokens» как заголовки — сохранять честные метрики (co_change-режим, context-load vs billable).
- ❌ LanceDB-provider chunkhound (write-only) — у нас рабочий, не портим.
- ❌ Fallow Runtime (закрытый) — не тратим время.
- ❌ MCP как subprocess-фасад (fallow) — у нас прямые Python-API вызовы.
- ❌ Ollama-оверпромисинг (chunkhound) — честно «OpenAI-compatible + base_url».

---

## 6. Экспериментальные данные (реальные прогоны)

| Проект | Команда | Результат |
|---|---|---|
| fallow 3.6.0 | `npx fallow` (на себе) | 66 dead files, 116 dead exports, 1 circular dep, 23 refactoring targets |
| fallow 3.6.0 | `audit --format compact` | 0 changed files → pass (0.33s) |
| fallow 3.6.0 | `health --score` | Score 50/D, deductions: unused deps -20.2, unit size -10.0 |
| CRG 2.3.7 | `build` (тест-репо 2 файла) | 7 nodes, 11 edges, FTS5 rebuilt, schema v9 |
| CRG 2.3.7 | `status` | Nodes 7, Edges 11, Languages python |
| chunkhound 5.2.1 | `index .` | ❌ FAIL: «No embedding provider configured» (regex-only режима нет) |
| repowise 0.27 | `init --index-only -y` (тест-репо) | 3 files/5.4s, graph 11/13, 1 unused export, 0 hotspots |
| repowise 0.27 | `health` | CCN/Nest/NLOC считаются, всё healthy на 8 файлах |

**Окружение:** Windows, Python 3.14, node v24, npm 11. Rust-тулчейн отсутствует (fallow через npx prebuilt; repowise через `--only-binary`).

---

## 7. Рекомендация по действиям

1. **Не копировать код 1-в-1** — брать паттерны/алгоритмы, адаптировать под наш tree-sitter + LanceDB + 39 tools.
2. **Начать с Tier 1** (token-savings panel, stale_warning, lean-surface, SARIF, suppression) — это даст видимость ценности и CI-гейт за пару дней.
3. **Incremental SHA-256** (Tier 2) — критично для производительности (сейчас переиндексация тяжёлая).
4. **Честные бенчмарки** — завести `benchmarks/` с co_change-режимом, чтобы не повторять circular-recall ошибку CRG.
5. **Не тратить время** на Fallow Runtime, LanceDB-chunkhound, Ollama-оверпромисинг.

---

## 8. Источники
- Песочница: `D:\analysis_sandbox\{fallow, code-review-graph, chunkhound, repowise}`
- Саб-агенты: 4 параллельных глубоких анализа (fallow/CRG/chunkhound/repowise)
- Реальные прогоны: см. раздел 6
