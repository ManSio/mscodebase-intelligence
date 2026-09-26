# E17 Research: Comparative Analysis

## Сравнительная таблица: Test-to-Code Traceability → LLM Context

| Работа | Год | Язык | Механика | Данные | Доказательство | Хранение | Применение | Измерение |
|--------|-----|------|----------|--------|----------------|----------|------------|-----------|
| **TCTracer** | 2022 | Java | Dynamic trace + static ensemble | Call traces, naming, TF-IDF | MAP 85% (method), 92% (class) | Links file | Maintenance, refactoring | Precision/Recall/MAP |
| **PyTCTracer** | 2022 | Python | sys.settrace + pytest plugin | CSV trace log | Same techniques as TCTracer | JSON links | Traceability recovery | Precision/Recall/F1/MAP |
| **Chen et al.** | 2025 | Python | 15 техник (dynamic + static) | 7 projects, 3198 tests | Cross-level info | N/A | Traceability techniques | Recall/Precision trade-offs |
| **TDAD** | 2026 | Python | Static AST → code-test graph | Dependency map | Regressions -70% (6.08%→1.82%) | Agent skill (text file) | Pre-change impact analysis | Regression rate, resolution rate |
| **RepoGraph** | 2026 | Py/JS/TS | Static-first + runtime overlay | Graph DB (Kuzu) | Pathway scoring | Graph DB | Repository intelligence | Qualitative (pathways, dead code) |
| **TICoder** | 2026 | Multi | Tests as behavioral specs | Test cases | +11.52% on benchmarks | N/A | Code generation planning | Pass@k on benchmarks |
| **ARB** | 2026 | Multi | Benchmark: code2test, trace2code | 427 samples, 25 repos | MRR/Recall/BCY@8k | Dataset | Retrieval evaluation | MRR, Recall@20, BCY@8k |
| **Syncause** | 2026 | Python | Runtime tracing → context injection | Call traces | +6% on SWE-bench (77.4%→83.4%) | Runtime facts | LLM context injection | SWE-bench score |
| **Shiplight** | 2026 | Multi | Agent-first testing | Browser traces | Qualitative | YAML tests | Agent verification | Qualitative (agent workflow) |
| **CKG** | 2026 | Multi | Code Knowledge Graph | AST, imports, calls | Graph queries | SQLite + Rust | MCP retrieval | Qualitative |
| **ABCoder** | 2026 | TS | Graph-based indexing | UniAST | Function-level retrieval | Graph index | Code agent context | Retrieval accuracy |
| **DeepDiscovery** | 2026 | Multi | Task-level context recovery | Multi-relational graph | Implementation path recovery | Structured context | Downstream reasoning | SWE performance |
| **E17 (наш)** | 2026 | Python | Runtime trace → TESTS edges → search | sys.settrace, PropertyGraph | 97.1% queries get tests, retrieval unchanged | PropertyGraph (SQLite) | Search context | hit@1/MRR (unchanged) |

## Ключевые различия

### TCTracer / PyTCTracer / Chen et al.
**Задача:** Восстановить test-to-code traceability links
**Цель:** Maintenance, refactoring, impact analysis
**Результат:** Links (test → code)
**НЕ делают:** Не используют links для LLM context

### TDAD
**Задача:** Уменьшить regressions от AI coding agents
**Механика:** Static AST → dependency map → agent skill
**Результат:** -70% regressions
**Отличие от нас:** Static (не runtime), не persistent graph

### RepoGraph
**Задача:** Repository intelligence
**Механика:** Static-first + runtime overlay
**Результат:** Pathways, dead code, variable flows
**Отличие от нас:** Не специализируется на test-to-code, runtime = overlay (не evidence)

### TICoder
**Задача:** Repository-level code generation
**Механика:** Tests as behavioral specs → planning
**Результат:** +11.52% on benchmarks
**Отличие от нас:** Tests как specs (не execution evidence), не persistent graph

### ARB
**Задача:** Benchmark для retrieval
**Механика:** code2test, trace2code задачи
**Результат:** Leaderboard (MRR, Recall)
**Отличие от нас:** Benchmark (не система), не использует runtime trace

### Syncause ⚠️ КРИТИЧЕСКИЙ КОНКУРЕНТ
**Задача:** Inject runtime context в LLM
**Механика:** Runtime tracing → facts → LLM context
**Результат:** +6% на SWE-bench (77.4% → 83.4%)
**Отличие от нас:** 
- Не persistent graph (runtime facts per query)
- Не test-to-code specifically (general runtime tracing)
- Не PropertyGraph с TESTS edges

### Наш E17
**Задача:** Execution-backed test evidence для LLM
**Механика:** Runtime trace → TESTS edges → persistent graph → search context
**Результат:** 97.1% queries get tests, retrieval unchanged
**Уникальность:**
1. Persistent TESTS edges в PropertyGraph (не per-query)
2. TESTS-signal в search (не injection)
3. Execution-backed (не static, не behavioral specs)

**НО:**
- Retrieval не улучшился (hit@1 unchanged)
- LLM impact НЕ измерен
- Syncause показал +6% на SWE-bench с runtime tracing

## Выводы

### Что НЕ ново:
- test-to-code traceability (TCTracer 2022)
- Dynamic execution traces для linking (PyTCTracer)
- Tests как context для LLM (TICoder, Shiplight)
- Runtime tracing для LLM context (Syncause)
- Graph-based code indexing (ABCoder, CKG, RepoGraph)

### Что может быть ново:
1. **Persistent TESTS edges в PropertyGraph** — не per-query runtime facts, а permanent graph structure
2. **TESTS-signal в search** — не injection, а часть retrieval pipeline
3. **Полная цепочка:** runtime trace → persistent graph → search → LLM context

### Но:
- **Syncause** делает похожее (runtime → LLM) и показывает +6%
- **Мы не измерили LLM impact** — retrieval unchanged, но LLM?
- **Наша уникальность не в результате, а в архитектуре** (persistent vs per-query)

### Следующий эксперимент (критический):
Измерить LLM-level impact:
- 30 вопросов к кодовой базе
- A/B: без TESTS vs с TESTS
- Метрики: behavior understanding, edge case detection, change planning

Если LLM impact = 0 → инфраструктура работает, но ценность не доказана
Если LLM impact > 0 → уникальная архитектура (persistent TESTS edges) имеет значение

## Дополнительные находки

### Reddit r/AI_Agents (2026-03-04):
"We added runtime tracing to an SWE-bench agent and pushed Gemini 3 Pro from 77.4% to 83.4%"
- Syncause: runtime facts → LLM context → +6%
- Подтверждает гипотезу: runtime evidence помогает LLM

### Reddit r/LLMDevs (2026-06-07):
"What if agent traces became a behavior graph?"
- Trajectory failures ≠ answer-quality issues
- Behavior graph для agent traces
- Похожая идея: traces → graph structure

### DEV.to (2026-04-10):
"Agent-First Testing: Build Quality Into Every AI Coding Session"
- Shiplight: agent writes tests during development
- Tests как verification, не как evidence
- Другое применение (не retrieval)

### DEV.to (2026-08-01):
"Keeping Specs, Tests, And Code In Sync In AI Development"
- Traceability model: requirement → design → test → code
- Spec-to-test mapping (не execution-backed)
- Static traceability (не runtime)
