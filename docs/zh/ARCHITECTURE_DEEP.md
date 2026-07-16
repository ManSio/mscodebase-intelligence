# MSCodeBase Intelligence — 深入架构指南

[🇬🇧 English](../en/ARCHITECTURE_DEEP.md) • [🇷🇺 Русский](../ru/ARCHITECTURE_DEEP.md) • [🇨🇳 中文](ARCHITECTURE_DEEP.md)

> **版本:** v3.0.0 | **最后更新:** 2026-07-11

> **注意:** 架构图的完整翻译需要更新 mermaid 图。请参阅英文版本获取最新图表。

```mermaid
flowchart TD
    User[User / AI Agent] --> MCP[MCP Server\n33 tools]
    MCP --> DI[DI Container\n18 services]
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

## 1. 架构层

系统分为10个运行时层，从最低级（基础设施）到最高级（面向用户的工具）。

```mermaid
flowchart LR
    subgraph "第10层 — MCP工具"
        T1[search_code]
        T2[get_symbol_info]
        T3[impact_analysis]
        T4[intel_*]
    end
    subgraph "第9层 — 错误边界"
        EB[@error_boundary\ntimeout + retry]
    end
    subgraph "第8层 — 智能层"
        IL[intel_predict_root_cause\nintel_code_topology\nintel_get_project_memory]
    end
    subgraph "第7层 — 搜索"
        SH[hybrid_search_async\nRRF + reranker + buckets]
    end
    subgraph "第6层 — 索引"
        IX[Indexer\nLanceDB + BM25 + SymbolIndex]
    end
    subgraph "第5层 — 嵌入"
        EM[RemoteEmbedder\nllama.cpp GGUF / LM Studio / ONNX]
    end
    subgraph "第4层 — 解析"
        PS[Tree-sitter AST\nParser + SymbolIndex]
    end
    subgraph "第3层 — 存储"
        ST[LanceDB v2\nper-project isolation]
    end
    subgraph "第2层 — 速率限制"
        RL[CircuitBreaker\nDebounceBatch\nSlidingWindow]
    end
    subgraph "第1层 — DI容器"
        DI[ServiceCollection\n15 singletons + factories]
    end
    T1 --> EB --> IL --> SH --> IX --> EM --> PS --> ST --> RL --> DI
```

---

## 2. 搜索管道 — 完整流程

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
    
    par BM25搜索
        ST->>S: bm25_search_async(query)
        S->>I: table.search().where(...)
        I-->>S: BM25结果（稀疏）
    and 稠密搜索
        ST->>S: 嵌入查询向量
        S->>E: embed_batch_async([query])
        E-->>S: 查询向量（768维）
        S->>DB: search(vector, limit=raw_limit)
        DB-->>S: 稠密结果
    end
    
    S->>S: RRF融合（k=60）
    S->>S: 桶加权（code/docs）
    S->>S: 共变更增强（git耦合）
    
    opt reranker可用
        S->>R: rerank(query, candidates, top_n=5)
        R-->>S: 重排序分数
    end
    
    S-->>EB: 排序结果
    EB-->>MCP: 格式化响应
    MCP-->>User: 带文件路径的搜索结果
```

### 模式性能

| 模式 | 管道 | 延迟 | 用例 |
|------|----------|---------|----------|
| `fast` | 仅BM25 | ~300ms | 精确符号查找 |
| `quality` | BM25 + Dense + RRF + Reranker | ~1200ms | 架构问题 |
| `deep` | 递归图扩展 | 2-5s | 复杂调查 |
| `context` | 代码片段相似度 | ~500ms | 查找相似代码 |
| `ask` | 搜索 → phi-4生成 | 5-15s | RAG问答 |

---

## 3. 工具生命周期

```mermaid
flowchart TD
    Start[Agent调用工具] --> Resolve[DI容器解析服务]
    Resolve --> Guard{RuntimeCoordinator\ncan_execute?}
    Guard -->|blocked| Error[返回错误\n带恢复提示]
    Guard -->|ready| Boundary[error_boundary包裹调用\n带超时 + 重试]
    
    Boundary --> Execute[Tool.execute 参数]
    Execute --> LMEnd{llama.cpp / LM Studio\navailable?}
    
    LMEnd -->|yes| LLAMA[RemoteEmbedder\nllama.cpp GGUF (GPU)]
    LMEnd -->|no| LM[RemoteEmbedder\nembeddings via LM Studio]
    LMEnd -->|no| ONNX[RemoteEmbedder\nembeddings via ONNX Runtime]
    
    LM --> Result[返回结构化结果]
    ONNX --> Result
    
    Result --> Telemetry[record_tool_call\nmetrics + latency]
    Telemetry --> Done[响应给Agent]
    
    Boundary -->|timeout| Retry{还有\n重试次数?}
    Retry -->|yes| Execute
    Retry -->|no| Timeout[超时错误]
```

---

## 4. 组件交互 — 启动流程

```mermaid
sequenceDiagram
    participant Zed as Zed IDE
    participant MCP as MCP Server
    participant DI as DI Container
    participant IX as Indexer
    participant EM as Embedder
    participant LM as LM Studio
    participant DB as LanceDB

    Zed->>MCP: 启动上下文服务器
    MCP->>DI: create_service_collection()
    DI->>DI: 注册15个服务
    
    par 启动序列
        DI->>IX: 创建Indexer
        IX->>DB: open_table / create_table
        DB-->>IX: 表句柄
        IX->>IX: _warmup_status()
        IX-->>DI: Indexer就绪
    and
        DI->>EM: 创建RemoteEmbedder
        EM->>EM: _init_provider_async() [后台]
        EM->>LM: check /v1/models
        LM-->>EM: available (bge-m3, phi-4)
        EM-->>DI: Embedder就绪
    end
    
    DI-->>MCP: 容器就绪
    MCP->>MCP: 注册50个工具
    MCP-->>Zed: 服务器就绪（已宣布PID）
    
    Note over Zed,DB: 总启动时间：~2-5秒（异步嵌入器初始化）
```

---

## 5. 智能层架构

```mermaid
flowchart LR
    subgraph "Intel工具"
        RTS[intel_get_runtime_status]
        CT[intel_code_topology]
        PM[intel_get_project_memory]
        RCA[intel_predict_root_cause]
        AI[intel_analyze_incident]
        TL[intel_get_telemetry]
        HOT[intel_get_hotspots]
    end
    
    subgraph "支持服务"
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

## 6. 数据模型

```mermaid
erDiagram
    CHUNK ||--o{ METADATA : contains
    CHUNK {
        string id PK
        vector vector "768-dim float"
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

## 7. MSCodeBase vs 生态系统对比

| 标准 | **MSCodeBase** | Qartez MCP | CodeGraph | SymDex |
|-----------|:--------------:|:----------:|:---------:|:------:|
| **语言** | Python + LanceDB (Rust-core) | Rust | TypeScript | - |
| **搜索** | BM25 + Dense + RRF + Reranker | 静态分析 | 知识图谱 | 符号查找 |
| **工具** | **43** | 30+ | - | - |
| **测试** | **396** | - | - | - |
| **Windows** | **原生**（UNC, MAX_PATH） | - | - | - |
| **增量索引** | MD5 + DebounceBatch | - | - | - |
| **自恢复** | IndexGuard | - | - | - |
| **项目记忆** | ADR / debt / issues | - | - | - |
| **重排序器** | bge-reranker-v2-m3 | - | - | - |
| **共变更** | Git耦合矩阵 | - | - | - |
| **健康检查** | 完整诊断 | - | - | - |
| **文档** | **3种语言** | 1 | 1 | 1 |
| **许可证** | MIT | Dual | MIT | - |

---

## 8. 系统配置对比

| 特性 | `light` 配置 | `server` 配置 |
|---------|:---------------:|:----------------:|
| `mode=ask` (phi-4) | ❌ 阻止 | ✅ 可用 |
| 异步搜索 | ✅ | ✅ |
| 重排序器 | ✅ | ✅ |
| RAM使用 | ~150 MB | ~300 MB（含phi-4） |
| 启动时间 | ~1秒 | ~3秒 |
| 使用场景 | 日常编码 | 深入分析 |

---

## 9. 优雅降级级别

```mermaid
flowchart LR
    L1["级别 1: llama.cpp GGUF\nGPU embeddings + reranker\n280ms-3s"] -->|offline| L2
    L2["级别 2: ONNX Runtime\nCPU embeddings only\nSlower"] -->|missing| L3
    L3["级别 3: LM Studio\nExternal API\n300ms-5s"] -->|offline| L4
    L4["级别 4: BM25 only\nKeyword search\nNo semantic"] -->|index missing| L5
    L5["级别 5: Fallback\nCreate index\nFirst run"]
```

**自动恢复：** 系统默认运行 ONNX/OpenVINO E5-base（进程内），并持续扫描可选的 llama.cpp GGUF GPU 嵌入器，然后是 LM Studio/Ollama 作为 fallback。当更高级别变为可用时，自动切换 — 无需重启。

---

## 10. 关键指标

| 指标 | 值 |
|--------|-------|
| **搜索模式** | 6（fast, quality, deep, context, ask, auto） |
| **MCP工具** | 33（16个核心 + 14个intel + 3个诊断） |
| **DI中的服务** | 15 |
| **测试** | 501 |
| **语言** | 3（EN, RU, ZH） |
| **模式字段** | 19（chunk: 9 + metadata: 6 + v3.0: 4） |
| **嵌入维度** | 768（E5-base INT8，进程内） |
| **重排序器** | bge-reranker-v2-m3 |
| **LLM** | phi-4-mini-instruct（可选，仅 mode=ask） |
| **向量数据库** | LanceDB v2 |
| **解析器** | Tree-sitter |
