# ADR-0004: Typed Dependency Edges + Propagation Engine

## Status
✅ Accepted — 2026-08-12

## Context
Memory nodes in MSCodeBase Intelligence live in isolation from the code graph. When a memory node is retracted (e.g., code changed, fact wrong), there is no mechanism to propagate this retraction to downstream memory nodes that depend on it. This causes contamination: agents continue to use stale VERIFIED facts.

Related ADRs: ADR-0002 (RetractionReceipt), ADR-0003 (Verify-On-Read)

## Decision
Implement typed dependency edges between memory nodes and code, plus a Propagation Engine for two-phase retraction.

### 1. DependencyType Enum (src/core/graph.py)
Add to EdgeType class:
```python
class EdgeType:
    # ... existing 29 types ...
    
    # NEW: Memory relationship edges
    MEMORY_DERIVED_FROM = "MEMORY_DERIVED_FROM"       # Memory ← code (file/import)
    MEMORY_VERIFIES = "MEMORY_VERIFIES"               # Test ← memory
    MEMORY_SUPERSEDES = "MEMORY_SUPERSEDES"           # New memory ← old memory
    MEMORY_DEPENDS_ON = "MEMORY_DEPENDS_ON"           # Memory ← memory
    MEMORY_SAME_PREDICATE = "MEMORY_SAME_PREDICATE"   # Похожие утверждения
```

### 2. Memory Dependency Edges
When a memory node is written (intel_add_memory_node), automatically create edges:
- `MEMORY_DERIVED_FROM` → from code anchors (file:/import: env:)
- `MEMORY_VERIFIES` → from test references
- `MEMORY_SUPERSEDES` → from explicit supersedes links

### 3. Propagation Engine (src/core/intelligence/propagation_engine.py)
Two-phase propagation on retract:
```python
class PropagationEngine:
    def retract(self, memory_id: str, cause: str):
        # Phase 1: Mark as RETRACTED
        node = self.store.get(memory_id)
        node["status"] = REFUTED
        node["retract_reason"] = cause
        node["retracted_at"] = now()
        self.store.update(node)
        
        # Phase 2: Graph traversal with typed edges
        downstream = self.find_downstream_edges(memory_id)
        
        for edge in downstream:
            if edge.edge_type in [DERIVED_FROM, DEPENDS_ON]:
                target = self.store.get(edge.target_memory_id)
                target["status"] = STALE_PENDING_REVALIDATION
                self.store.update(target)
                
                # Trigger revalidation
                self.revalidate(target["node_id"], edge.derivation_method)
    
    def revalidate(self, memory_id: str, method: str):
        node = self.store.get(memory_id)
        
        if method == "ast":
            verified = self.verify_ast_anchors(node["anchors"])
        elif method == "import_graph":
            verified = self.verify_import_graph(node["imports"])
        else:
            verified = self.llm_revalidate(node["content"])
        
        node["status"] = VERIFIED if verified else REFUTED
        self.store.update(node)
```

### 4. Integration with Verify-On-Read
VerifyOnRead.run() should check propagation status:
- If node has downstream edges marked STALE_PENDING_REVALIDATION → filter out
- If node itself is REFUTED → filter out
- If node is VERIFIED but downstream is STALE → mark as INCONCLUSIVE

## Alternatives Considered
1. **No propagation** (current state): Contamination risk, agents read stale facts
2. **Full LLM revalidation**: Too slow, non-deterministic
3. **Simple status propagation**: Doesn't account for typed dependencies, too brittle

Chosen approach provides typed, deterministic propagation with fallbacks.

## Consequences
- ✅ Downstream memory nodes automatically retracted when upstream retracts
- ✅ Agents don't read contaminated context
- ✅ New complexity: must maintain dependency edges when writing memory
- ✅ Performance: graph traversal O(depth) per retract, acceptable for typical depths (< 10)
- ✅ Requires write-time anchor capture (already in ADR-0003 follow-up)

## Migration
- Existing memory nodes: no edges → assume DERIVED_FROM code anchors on first read
- New memory nodes: edges auto-created via intel_add_memory_node hook
- No breaking changes to public API

## Open Questions
1. TTL for STALE_PENDING_REVALIDATION status? (suggested: 24h, then auto-REFUTED)
2. LLM vs AST revalidation threshold? (suggested: AST first, LLM only if AST returns ambiguous)
3. How to handle circular dependencies? (suggested: detect and mark as INCONCLUSIVE)

## Implementation Notes (2026-08-12)

Реализация выполнена на уровне JSON-хранилища памяти (`project_memory.json`), а не
через PropertyGraph-рёбра:

- `src/core/intelligence/propagation_engine.py` — `PropagationEngine.retract_cascade`:
  транзитивный BFS по явным зависимостям (`data.depends_on: [node_id]`, указываются
  агентом при записи узла) и `superseded_by`-связям; циклы безопасны (visited-set).
- Хук: `intel_retract_memory_node` применяет каскад в том же RMW под `_write_lock`
  (TOCTOU-инвариант ADR-0002 сохраняется; два одновременных отзыва не теряют каскад).
- Зависимые узлы получают `status=REFUTED`, `retract_source="propagation"`,
  `retract_reason="PROPAGATED_FROM:<root> | <root_reason>"` — трассируемость.
  Уже REFUTED зависимые не перезаписываются (история не переписывается, ADR-0002).
- PropertyGraph-рёбра (MEMORY_DERIVED_FROM и др.) и статус STALE_PENDING_REVALIDATION
  НЕ введены: хранилище памяти — JSON (десятки узлов), обход O(n) на отзыв дёшев;
  граф-рёбра добавили бы связность без практической выгоды. Если память мигрирует
  в PropertyGraph — рёбра вводятся по спецификации выше.
- Open Question 3 закрыт: циклы безопасны по построению (visited-set), отдельный
  детектор не требуется.
- Границы v1: каскад только на ручном отзыве (MCP-тул); restore и авто-отзывы
  verify-on-read не каскадят (downstream-якоря проверяются независимо;
  восстановление downstream — ручное решение агента).