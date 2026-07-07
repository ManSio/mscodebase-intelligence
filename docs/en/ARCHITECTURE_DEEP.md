# MSCodeBase Intelligence — Deep Architecture Guide

> **Version:** v2.7.0+ | **Last updated:** 2026-07-07

```mermaid
flowchart TD
    User[User / AI Agent] --> MCP[MCP Server\n43 tools]
    MCP --> DI[DI Container\n15 services]
    DI --> Search[Search Pipeline]
    DI --> Index[Indexing Pipeline]
    DI --> Intel[Intelligence Layer]
    DI --> Health[Health & Diagnostics]
    
    Search --> BM25[BM25 Sparse\nkeyword search]
    Search --> Dense[LanceDB Dense\nvector search]
    Search --> RRF[RRF Fusion\nreciprocal rank fusion]
    Search --> Rerank[Cross-encoder\nbge-reranker-v2-m3]
    Search --> Bucket[Multi-Bucket RAG\ncode/docs weighting]
    Search --> CoChange[Co-change boost\ngit coupling]
    
    Intel --> Topology[Code Topology\ncall graph]
    Intel --> Memory[Project Memory\nADR / debt / issues]
    Intel --> RCA[Root Cause Analysis\nerror prediction]
    
    Health --> Report[Health Report\nfull diagnostics]
    Health --> Guard[Index Guard\nself-recovery]
```

---

## 1. Architecture Layers

The system is divided into 10 runtime layers, from lowest (infrastructure) to highest (user-facing tools).

```mermaid
flowchart LR
    subgraph "Layer 10 — MCP Tools"
        T1[search_code]
        T2[get_symbol_info]
        T3[impact_analysis]
        T4[intel_*]
    end
    subgraph "Layer 9 — Error Boundary"
        EB[@error_boundary\ntimeout + retry]
    end
    subgraph "Layer 8 — Intelligence"
        IL[intel_predict_root_cause\nintel_code_topology\nintel_get_project_memory]
    end
    subgraph "Layer 7 — Search"
        SH[hybrid_search_async\nRRF + reranker + buckets]
    end
    subgraph "Layer 6 — Index"
        IX[Indexer\nLanceDB + BM25 + SymbolIndex]
    end
    subgraph "Layer 5 — Embeddings"
        EM[RemoteEmbedder\nLM Studio / Ollama / ONNX]
    end
    subgraph "Layer 4 — Parsing"
        PS[Tree-sitter AST\nParser + SymbolIndex]
    end
    subgraph "Layer 3 — Storage"
        ST[LanceDB v2\nper-project isolation]
    end
    subgraph "Layer 2 — Rate Limiting"
        RL[CircuitBreaker\nDebounceBatch\nSlidingWindow]
    end
    subgraph "Layer 1 — DI Container"
        DI[ServiceCollection\n15 singletons + factories]
    end
    T1 --> EB --> IL --> SH --> IX --> EM --> PS --> ST --> RL --> DI
```

---

## 2. Search Pipeline — Complete Flow

```mermaid
sequenceDiagram
    participant User as AI Agent
    participant MCP as MCP Server
    participant EB as error_boundary
    participant ST as SearchTool
    participant S as Searcher
    participant I as Indexer
    participant E as Embedder
    participant DB as LanceDB
    participant R as Reranker

    User->>MCP: search_code(query="auth", mode="quality")
    MCP->>EB: @error_boundary(timeout=10000)
    EB->>ST: execute(query, mode, intent_hint)
    
    par BM25 Search
        ST->>S: bm25_search_async(query)
        S->>I: table.search().where(...)
        I-->>S: BM25 results (sparse)
    and Dense Search
        ST->>S: embed query vector
        S->>E: embed_batch_async([query])
        E-->>S: query vector (1024-dim)
        S->>DB: search(vector, limit=raw_limit)
        DB-->>S: dense results
    end
    
    S->>S: RRF Fusion (k=60)
    S->>S: Bucket Weighting (code/docs)
    S->>S: Co-change Boost (git coupling)
    
    opt reranker available
        S->>R: rerank(query, candidates, top_n=5)
        R-->>S: reranked scores
    end
    
    S-->>EB: sorted results
    EB-->>MCP: formatted response
    MCP-->>User: search results with file paths
```

### Mode Performance

| Mode | Pipeline | Latency | Use Case |
|------|----------|---------|----------|
| `fast` | BM25 only | ~300ms | Exact symbol lookup |
| `quality` | BM25 + Dense + RRF + Reranker | ~1200ms | Architecture questions |
| `deep` | Recursive graph expansion | 2-5s | Complex investigations |
| `context` | Code fragment similarity | ~500ms | Find similar code |
| `ask` | Search → phi-4 generation | 5-15s | RAG question answering |

---

## 3. Tool Lifecycle

```mermaid
flowchart TD
    Start[Agent calls tool] --> Resolve[DI Container resolves service]
    Resolve --> Guard{RuntimeCoordinator\ncan_execute?}
    Guard -->|blocked| Error[Return error\nwith recovery hint]
    Guard -->|ready| Boundary[error_boundary wraps call\nwith timeout + retry]
    
    Boundary --> Execute[Tool.execute params]
    Execute --> LMEnd{LM Studio\navailable?}
    
    LMEnd -->|yes| LM[RemoteEmbedder\nembeddings via LM Studio]
    LMEnd -->|no| ONNX[RemoteEmbedder\nembeddings via ONNX Runtime]
    
    LM --> Result[Return structured result]
    ONNX --> Result
    
    Result --> Telemetry[record_tool_call\nmetrics + latency]
    Telemetry --> Done[Response to agent]
    
    Boundary -->|timeout| Retry{Retries\nleft?}
    Retry -->|yes| Execute
    Retry -->|no| Timeout[Timeout error]
```

---

## 4. Component Interaction — Startup Flow

```mermaid
sequenceDiagram
    participant Zed as Zed IDE
    participant MCP as MCP Server
    participant DI as DI Container
    participant IX as Indexer
    participant EM as Embedder
    participant LM as LM Studio
    participant DB as LanceDB

    Zed->>MCP: Start context server
    MCP->>DI: create_service_collection()
    DI->>DI: Register 15 services
    
    par Startup sequence
        DI->>IX: Create Indexer
        IX->>DB: open_table / create_table
        DB-->>IX: table handle
        IX->>IX: _warmup_status()
        IX-->>DI: Indexer ready
    and
        DI->>EM: Create RemoteEmbedder
        EM->>EM: _init_provider_async() [background]
        EM->>LM: check /v1/models
        LM-->>EM: available (bge-m3, phi-4)
        EM-->>DI: Embedder ready
    end
    
    DI-->>MCP: Container ready
    MCP->>MCP: Register 43 tools
    MCP-->>Zed: Server ready (PID announced)
    
    Note over Zed,DB: Total startup: ~2-5s (async embedder init)
```

---

## 5. Intelligence Layer Architecture

```mermaid
flowchart LR
    subgraph "Intel Tools"
        RTS[intel_get_runtime_status]
        CT[intel_code_topology]
        PM[intel_get_project_memory]
        RCA[intel_predict_root_cause]
        AI[intel_analyze_incident]
        TL[intel_get_telemetry]
        HOT[intel_get_hotspots]
    end
    
    subgraph "Backing Services"
        SI[SymbolIndex]
        IDX[Indexer status]
        ERR[Error history]
        TEL[Telemetry metrics]
    end
    
    RTS --> IDX
    CT --> SI
    PM --> PMDB[(Project Memory\nJSON store)]
    RCA --> ERR
    RCA --> SI
    AI --> ERR
    TL --> TEL
    HOT --> SI
    HOT --> IDX
```

---

## 6. Data Model

```mermaid
erDiagram
    CHUNK ||--o{ METADATA : contains
    CHUNK {
        string id PK
        vector vector "1024-dim float"
        string text "compact chunk"
        string text_full "full function text"
        string file_path "relative path"
        string file_hash "MD5 for incremental"
        int chunk_index
        string source "lsp_vfs | filesystem"
        string indexed_at ISO8601
        string summary "LLM-generated"
        string callees "JSON array of callee names"
        float health_score "1-10"
        string health_band "healthy|warning|alert"
    }
    METADATA {
        string layer "core | mcp | tests"
        string module_name "core.searcher"
        string hierarchy_level "function | class | module"
        bool is_public
        string symbol_type "function_definition"
        string parent_id "hash for multi-granularity"
    }
    SYMBOL {
        string name
        string file_path
        int line
        string kind
        bool is_definition
    }
    SYMBOL ||--o{ SYMBOL : calls
```

---

## 7. Comparison: MSCodeBase vs Ecosystem

| Criterion | **MSCodeBase** | Qartez MCP | CodeGraph | SymDex |
|-----------|:--------------:|:----------:|:---------:|:------:|
| **Language** | Python + LanceDB (Rust-core) | Rust | TypeScript | - |
| **Search** | BM25 + Dense + RRF + Reranker | Static analysis | Knowledge Graph | Symbol lookup |
| **Tools** | **43** | 30+ | - | - |
| **Tests** | **396** | - | - | - |
| **Windows** | **Native** (UNC, MAX_PATH) | - | - | - |
| **Incremental index** | MD5 + DebounceBatch | - | - | - |
| **Self-recovery** | IndexGuard | - | - | - |
| **Project Memory** | ADR / debt / issues | - | - | - |
| **Reranker** | bge-reranker-v2-m3 | - | - | - |
| **Co-change** | Git coupling matrix | - | - | - |
| **Health** | Full diagnostics | - | - | - |
| **Docs** | **3 languages** | 1 | 1 | 1 |
| **License** | MIT | Dual | MIT | - |

---

## 8. System Profile Comparison

| Feature | `light` profile | `server` profile |
|---------|:---------------:|:----------------:|
| `mode=ask` (phi-4) | ❌ Blocked | ✅ Available |
| Async search | ✅ | ✅ |
| Reranker | ✅ | ✅ |
| RAM usage | ~150 MB | ~300 MB (with phi-4) |
| Startup time | ~1s | ~3s |
| Use case | Daily coding | Deep analysis |

---

## 9. Graceful Degradation Levels

```mermaid
flowchart LR
    L1["Level 1: LM Studio\nFull pipeline\n300ms-5s"] -->|offline| L2
    L2["Level 2: ONNX Runtime\nEmbeddings only\nCPU, slower"] -->|missing| L3
    L3["Level 3: BM25 only\nKeyword search\nNo semantic"] -->|index missing| L4
    L4["Level 4: Fallback\nCreate index\nFirst run"]
```

**Auto-recovery:** The system continuously scans for LM Studio/Ollama availability.
When the higher level becomes available, it switches automatically — no restart needed.

---

## 10. Key Metrics

| Metric | Value |
|--------|-------|
| **Search modes** | 6 (fast, quality, deep, context, ask, auto) |
| **MCP tools** | 43 (33 core + 10 intel) |
| **Services in DI** | 15 |
| **Tests** | 396 |
| **Languages** | 3 (EN, RU, ZH) |
| **Schema fields** | 19 (chunk: 9 + metadata: 6 + v3.0: 4) |
| **Embedding dim** | 1024 (bge-m3) |
| **Reranker** | bge-reranker-v2-m3 |
| **LLM** | phi-4-mini-instruct |
| **Vector DB** | LanceDB v2 |
| **Parser** | Tree-sitter |
