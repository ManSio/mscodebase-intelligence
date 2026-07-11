# 优雅降级 — 系统韧性指南

> **MSCodeBase Intelligence 的一部分** | v2.7.0+

## 概述

MSCodeBase 从不完全崩溃。相反，它通过 5 个级别**优雅降级**，
即使在外部服务故障时也能维持基本功能。

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

## 各级别详情

### 级别 1：完整流水线（生产环境）

| 组件 | 状态 |
|-----------|:------:|
| LM Studio | ✅ 在线 |
| BM25 索引 | ✅ 已构建 |
| Reranker | ✅ 可用 |
| mode=ask (phi-4) | ✅ 可用 |
| **延迟** | **300ms-5s** |
| **质量** | **最佳** |

**触发条件：** LM Studio 在 `127.0.0.1:1234/v1/models` 响应

### 级别 2：ONNX Runtime（回退）

```python
# 当 LM Studio 不可达时自动回退
class RemoteEmbedder:
    def _check_lm_studio(self) -> bool:
        """通过 CircuitBreaker 路由以防止级联故障。"""
        if self._breaker is not None:
            return bool(self._breaker.call(self._check_lm_studio_raw, fallback=True))
        return self._check_lm_studio_raw()
    
    def _init_onnx(self):
        """从 .codebase_models/onnx/bge-m3/ 加载 ONNX 模型"""
        if not self.local_model_dir.exists():
            raise FileNotFoundError("运行：python scripts/download_model.py")
        self._onnx_session = ort.InferenceSession(str(self.local_model_dir / "model.onnx"))
```

| 组件 | 状态 |
|-----------|:------:|
| LM Studio | ❌ 离线 |
| ONNX 模型 | ✅ 可用（438 MB） |
| Reranker | ❌ 不可用 |
| mode=ask | ❌ 不可用 |
| **延迟** | **1-6s** |
| **质量** | **良好**（仅 embedding，无 reranker） |

### 级别 3：仅 BM25（最低限度）

```python
# BM25 构建器中的优雅降级
class Searcher:
    def _build_bm25_index(self) -> None:
        if self.indexer.table is None:
            self._bm25 = {}  # 空 BM25 = 降级模式
            return
        try:
            if self.indexer.table.count_rows() == 0:
                self._bm25 = {}
                return
        except Exception:
            self._bm25 = {}  # 表损坏 → 降级
            return
```

| 组件 | 状态 |
|-----------|:------:|
| LM Studio | ❌ 离线 |
| ONNX 模型 | ❌ 缺失 |
| BM25 索引 | ✅ 可用 |
| Reranker | ❌ 不可用 |
| mode=ask | ❌ 不可用 |
| **延迟** | **50ms-300ms** |
| **质量** | **基础**（仅关键词） |

### 级别 4：回退（首次运行）

```python
# 表重建后的首次运行
class Indexer:
    def _warmup_status(self) -> None:
        count = self.table.count_rows()
        self._cached_total_chunks = count
        if count == 0:
            logger.debug("🔥 冷启动 — 空数据库")
```

| 组件 | 状态 |
|-----------|:------:|
| LM Studio | ❌ 离线 |
| ONNX 模型 | ❌ 不可用 |
| BM25 索引 | ❌ 为空 |
| Reranker | ❌ 不可用 |
| mode=ask | ❌ 不可用 |
| **延迟** | 不适用 |
| **质量** | **无**（等待索引） |

## 自动恢复

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

**关键特性：**
- 扫描器每 30 秒在后台线程中运行
- 当更高级别变为可用时 → **自动切换**
- 无需重启
- CircuitBreaker 防止快速开关循环

## 保护机制

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

| 保护机制 | 原理 | 恢复 |
|-----------|-----------|----------|
| **CircuitBreaker** | 5 次失败 → OPEN（30 秒）→ HALF_OPEN → CLOSED | 冷却后自动恢复 |
| **DebounceBatch** | 500ms 窗口，最多 100 个文件 | 触发一次 BM25 重建 |
| **RateLimiter** | 滑动窗口，每个工具 10 次调用/秒 | 超出时以 RateLimitError 丢弃 |
| **IndexGuard** | 计数检查 + 模式验证 | 表损坏时重建 |
