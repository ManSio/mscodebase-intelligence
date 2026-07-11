# Graceful Degradation — System Resilience Guide

> **Part of MSCodeBase Intelligence** | v2.7.0+

## Overview

MSCodeBase never crashes completely. Instead, it **degrades gracefully** through 5 levels,
maintaining basic functionality even when external services fail.

```mermaid
stateDiagram-v2
    [*] --> L1_LLAMA: All services available
    
    state L1_LLAMA[Level 1: llama.cpp GGUF (GPU)]
        L1_LLAMA: llama.cpp embed + reranker (Vulkan GPU)
        L1_LLAMA: BM25 + Dense + Reranker + Co-change
        L1_LLAMA: ~280ms-3s latency
    end
    
    L1_LLAMA --> L2_ONNX: llama.cpp unavailable
    
    state L2_ONNX[Level 2: ONNX Runtime (CPU)]
        L2_ONNX: ONNX embeddings only
        L2_ONNX: BM25 + Dense (CPU)
        L2_ONNX: No reranker (BM25 ranking only)
        L2_ONNX: ~1-6s latency
    end
    
    L2_ONNX --> L3_LM: llama.cpp offline → LM Studio fallback
    
    state L3_LM[Level 3: LM Studio (remote)]
        L3_LM: External API (port 1234)
        L3_LM: BM25 + Dense + Reranker
        L3_LM: ~300ms-5s latency (network)
    end
    
    L3_LM --> L4_BM25: All external offline
    
    state L4_BM25[Level 4: BM25 Only]
        L4_BM25: Keyword search only
        L4_BM25: No semantic understanding
        L4_BM25: ~50ms-300ms latency
    end
    
    L4_BM25 --> L5_Fallback: BM25 index empty
    
    state L5_Fallback[Level 5: Fallback]
        L5_Fallback: Creating index
        L5_Fallback: First run / after table drop
        L5_Fallback: Empty results (index building)
    end
    
    L5_Fallback --> L4_BM25: Index ready
    L4_BM25 --> L3_LM: LM Studio detected
    L3_LM --> L2_ONNX: ONNX reloaded
    L2_ONNX --> L1_LLAMA: llama.cpp GGUF available
    
    L1_LLAMA --> L2_ONNX: llama crash
    L2_ONNX --> L3_LM: ONNX error → LM Studio scan
    L3_LM --> L4_BM25: LM Studio crash
    L3_BM25 --> [*]: Catastrophic failure
```

## Level Details

### Level 1: Full Pipeline (Production)

| Component | Status |
|-----------|:------:|
| LM Studio | ✅ Online |
| BM25 index | ✅ Built |
| Reranker | ✅ Available |
| mode=ask (phi-4) | ✅ Available |
| **Latency** | **300ms-5s** |
| **Quality** | **Best** |

**Trigger:** LM Studio responds on `127.0.0.1:1234/v1/models`

### Level 2: ONNX Runtime (Fallback)

```python
# Automatic fallback when LM Studio is unreachable
class RemoteEmbedder:
    def _check_lm_studio(self) -> bool:
        """Routes through CircuitBreaker to prevent cascade failures."""
        if self._breaker is not None:
            return bool(self._breaker.call(self._check_lm_studio_raw, fallback=True))
        return self._check_lm_studio_raw()
    
    def _init_onnx(self):
        """Loads ONNX model from .codebase_models/onnx/bge-m3/"""
        if not self.local_model_dir.exists():
            raise FileNotFoundError("Run: python scripts/download_model.py")
        self._onnx_session = ort.InferenceSession(str(self.local_model_dir / "model.onnx"))
```

| Component | Status |
|-----------|:------:|
| LM Studio | ❌ Offline |
| ONNX model | ✅ Available (438 MB) |
| Reranker | ❌ Unavailable |
| mode=ask | ❌ Unavailable |
| **Latency** | **1-6s** |
| **Quality** | **Good** (embedding only, no reranker) |

### Level 3: BM25 Only (Minimal)

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
| LM Studio | ❌ Offline |
| ONNX model | ❌ Missing |
| BM25 index | ✅ Available |
| Reranker | ❌ Unavailable |
| mode=ask | ❌ Unavailable |
| **Latency** | **50ms-300ms** |
| **Quality** | **Basic** (keyword only) |

### Level 4: Fallback (First Run)

```python
# First run after table recreation
class Indexer:
    def _warmup_status(self) -> None:
        count = self.table.count_rows()
        self._cached_total_chunks = count
        if count == 0:
            logger.debug("🔥 Cold start — empty database")
```

| Component | Status |
|-----------|:------:|
| LM Studio | ❌ Offline |
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
    participant LM as LM Studio
    participant ONNX as ONNX Runtime
    participant BM25 as BM25 Index
    
    Note over EM: Level 2 (ONNX)
    EM->>ONNX: embed query
    ONNX-->>EM: vector (1024-dim)
    
    par Every 30s — scanner loop
        EM->>LM: GET /v1/models
        LM-->>EM: 200 OK (bge-m3, phi-4)
        EM->>EM: switch to LM Studio
        Note over EM: Level 1 restored!
    end
    
    EM->>LM: embed query (async)
    LM-->>EM: vector (faster, GPU)
```

**Key properties:**
- Scanner runs every 30s in background thread
- When higher level becomes available → **automatic switch**
- No restart needed
- CircuitBreaker prevents rapid on/off cycling

## Protection Mechanisms

```mermaid
flowchart LR
    subgraph "Protection Layer"
        CB[CircuitBreaker\n5 failures → 30s cooldown]
        DB[DebounceBatch\n500ms batch window]
        RL[RateLimiter\n10 calls/sec per tool]
        IG[IndexGuard\nself-recovery on corruption]
    end
    
    CB --> |open| FALLBACK[Fallback to level 2/3]
    DB --> |batched| BM25[Incremental reindex]
    RL --> |throttled| REQ[MCP requests]
    IG --> |repaired| TABLE[LanceDB table]
```

| Protection | Mechanism | Recovery |
|-----------|-----------|----------|
| **CircuitBreaker** | 5 failures → OPEN (30s) → HALF_OPEN → CLOSED | Auto-recovery after cooldown |
| **DebounceBatch** | 500ms window, max 100 files | Triggers BM25 rebuild once |
| **RateLimiter** | Sliding window, 10 calls/s per tool | Drops excess with RateLimitError |
| **IndexGuard** | Count check + schema validation | Recreates table on corruption |
