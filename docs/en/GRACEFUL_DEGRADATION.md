# Graceful Degradation — System Resilience Guide

> **Part of MSCodeBase Intelligence** | v3.2.1

## Overview

MSCodeBase never crashes completely. Instead, it **degrades gracefully** through 6 levels,
maintaining basic functionality even when external services fail.

> **Provider reality (2026-07-12):** The embedding provider runs **in-process** via
> **ONNX INT8 / OpenVINO INT8** (`intfloat/multilingual-e5-base`, 768-dim, ~350 ch/s on
> Windows CPU). This is the **default and primary** path — no external server required for
> semantic search. `LM Studio` is only an **optional fallback** if the local ONNX/OpenVINO
> model is unavailable. The **reranker** runs as a separate `llama-server.exe` process
> serving the `bge-reranker-v2-m3` GGUF model (port `:8081`).

```mermaid
stateDiagram-v2
    [*] --> L1_ONNX: Default startup (in-process)

    state L1_ONNX[Level 1: ONNX/OpenVINO INT8 (in-process)]
        L1_ONNX: E5-base embedder (768-dim)
        L1_ONNX: BM25 + Dense + Reranker (llama.cpp)
        L1_ONNX: ~300ms-3s latency
    end

    L1_ONNX --> L2_GGUF: User has GPU, prefers llama.cpp embed
    L1_ONNX --> L3_LM: ONNX model missing → LM Studio fallback

    state L2_GGUF[Level 2: llama.cpp GGUF (GPU)]
        L2_GGUF: GGUF embed + reranker (Vulkan GPU)
        L2_GGUF: BM25 + Dense + Reranker
        L2_GGUF: ~286ms-3s latency
    end

    L2_GGUF --> L1_ONNX: llama.cpp unavailable

    state L3_LM[Level 3: LM Studio (remote, optional)]
        L3_LM: External API (port 1234)
        L3_LM: BM25 + Dense + Reranker
        L3_LM: ~300ms-5s latency (network)
    end

    L3_LM --> L4_BM25: All external offline

    state L4_BM25[Level 4: BM25 Only]
        L4_BM25: Keyword search only
        L4_BM25: SymbolIndex + FTS5 fallback
        L4_BM25: No vector search
    end

    L4_BM25 --> L5_SYMBOL: BM25 unavailable

    state L5_SYMBOL[Level 5: SymbolIndex Only]
        L5_SYMBOL: Pure AST symbol index
        L5_SYMBOL: Tree-sitter definitions + references
        L5_SYMBOL: No semantic search
    end
```

### Cross-cutting layers (always available)

These are **independent** of the search level above:

```mermaid
stateDiagram-v2
    [*] --> LSP_ACTIVE: basedpyright available

    state LSP_ACTIVE[LSP: basedpyright]
        LSP_ACTIVE: Cross-file rename precision
        LSP_ACTIVE: Full semantic WorkspaceEdit
        LSP_ACTIVE: ~105ms warm latency
    end

    LSP_ACTIVE --> LSP_FALLBACK: Timeout (5s) or unavailable

    state LSP_FALLBACK[LSP: SymbolIndex]
        LSP_FALLBACK: Tree-sitter text-based rename
        LSP_FALLBACK: May miss dynamic imports
        LSP_FALLBACK: Always works, zero infra
    end
```

```mermaid
stateDiagram-v2
    [*] --> DEFAULT_TOOLS: Normal operation

    state DEFAULT_TOOLS[Visible: 12 tools]
        DEFAULT_TOOLS: search_code, get_symbol_info, impact_analysis
        DEFAULT_TOOLS: notify_change, get_index_status
        DEFAULT_TOOLS: intel_get_runtime_status
        DEFAULT_TOOLS: rename_symbol, replace_symbol
    end

    DEFAULT_TOOLS --> ALL_TOOLS: MSCODEBASE_MCP_TOOLS=""
    DEFAULT_TOOLS --> CUSTOM_TOOLS: MSCODEBASE_MCP_TOOLS="a,b,c"

    state ALL_TOOLS[Visible: 33 tools]
        ALL_TOOLS: All 59 MCP tools available (42 core + 14 intel + 3 diag)
    end

    state CUSTOM_TOOLS[Custom selection]
        CUSTOM_TOOLS: User-specified tool subset
    end
```

## Level Details

### Level 1: ONNX/OpenVINO INT8 (Default, in-process)

```python
# Default provider path (EMBEDDING_PROVIDER=e5_onnx)
class RemoteEmbedder:
    def _init_provider_async(self):
        _provider = os.getenv("EMBEDDING_PROVIDER", "e5_onnx")
        if _provider in ("e5_onnx", "auto", ""):
            self._init_onnx()
            # OpenVINO INT8 has priority (~350 ch/s on Windows CPU)
            if getattr(self, "_ov_compiled", None) is not None:
                self.mode = "onnx"
```

| Component | Status |
|-----------|:------:|
| ONNX/OpenVINO E5-base | ✅ In-process (768-dim, INT8) |
| BM25 index | ✅ Built |
| Reranker (llama.cpp) | ✅ Available (`:8081`) |
| mode=ask | ⚠️ Optional (needs LLM profile) |
| **Latency** | **300ms-3s** |
| **Quality** | **Best** (no external dependency) |

**Trigger:** Default startup. No external server required.

### Level 2: llama.cpp GGUF (GPU, optional)

If the user has a Vulkan-capable GPU and prefers GGUF embedding, `llama-server.exe` can
serve the embedder. This is an acceleration path, not the default.

| Component | Status |
|-----------|:------:|
| llama.cpp embed (GPU) | ✅ Available |
| BM25 index | ✅ Built |
| Reranker | ✅ Available |
| mode=ask | ⚠️ Optional |
| **Latency** | **286ms-3s** |
| **Quality** | **Best** |

### Level 3: LM Studio (remote, optional fallback)

```python
# Only reached if the local ONNX/OpenVINO model is unavailable
class RemoteEmbedder:
    def _check_lm_studio(self) -> bool:
        """Routed through CircuitBreaker to prevent cascade failures."""
        if self._breaker is not None:
            return bool(self._breaker.call(self._check_lm_studio_raw, fallback=True))
        return self._check_lm_studio_raw()
```

| Component | Status |
|-----------|:------:|
| LM Studio | ✅ Online (if running) |
| ONNX model | ❌ Missing |
| Reranker | ✅ Available (via LM Studio) |
| mode=ask | ✅ Available |
| **Latency** | **300ms-5s** (network) |
| **Quality** | **Good** |

**Trigger:** `EMBEDDING_PROVIDER=lm_studio` or local ONNX model absent.

### Level 4: BM25 Only (Minimal)

```python
# Graceful degradation in BM25 builder
class Searcher:
    def _build_bm25_index(self) -> None:
        if self.indexer.table is None:
            self._bm25 = {}  # Empty BM25 = degraded mode
            return
        try:
            if self.indexer.table.count_rows() == 0:
                self._bm25 = {}
                return
        except Exception:
            self._bm25 = {}  # Table corrupted → degraded
            return
```

| Component | Status |
|-----------|:------:|
| ONNX model | ❌ Missing |
| LM Studio | ❌ Offline |
| BM25 index | ✅ Available |
| Reranker | ❌ Unavailable |
| mode=ask | ❌ Unavailable |
| **Latency** | **50ms-300ms** |
| **Quality** | **Basic** (keyword only) |

### Level 5: SymbolIndex Only (Last resort)

| Component | Status |
|-----------|:------:|
| ONNX model | ❌ Missing |
| BM25 index | ❌ Unavailable |
| SymbolIndex | ✅ Available |
| Reranker | ❌ Unavailable |
| mode=ask | ❌ Unavailable |
| **Latency** | **<50ms** |
| **Quality** | **AST symbols only** (no semantic search) |

### Level 6: Fallback (First Run)

| Component | Status |
|-----------|:------:|
| ONNX model | ❌ Unavailable |
| BM25 index | ❌ Empty |
| Reranker | ❌ Unavailable |
| mode=ask | ❌ Unavailable |
| **Latency** | N/A |
| **Quality** | **None** (awaiting index) |

## Auto-Recovery

```mermaid
sequenceDiagram
    participant EM as RemoteEmbedder
    participant ONNX as ONNX/OpenVINO (in-process)
    participant LM as LM Studio (optional)
    participant BM25 as BM25 Index

    Note over EM: Level 1 (ONNX, default)
    EM->>ONNX: embed query (in-process)
    ONNX-->>EM: vector (768-dim)

    par Every 30s — scanner loop
        EM->>LM: GET /v1/models (if enabled)
        LM-->>EM: 200 OK
        EM->>EM: switch to LM Studio (optional)
        Note over EM: Level 3 restored (optional)
    end
```
