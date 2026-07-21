# 优雅降级（Graceful Degradation）— 系统弹性指南

> **MSCodeBase Intelligence 的一部分** | v3.2.1

## 概述

MSCodeBase 永远不会完全崩溃。相反，它通过 **6 个级别优雅降级**，
即使外部服务失败也能保持基本功能。

> **提供者（provider）现状（2026-07-12）：** 嵌入提供者（provider）通过 **ONNX INT8 / OpenVINO INT8**
> **进程内** 运行（`multilingual-e5-small-int8`，384 维，Windows CPU 上 ~37 ch/s）。
> 这是 **默认且主要** 的路径 — 语义搜索不需要外部服务器。`LM Studio` 仅是
> **可选的回退（fallback）**，当本地 ONNX/OpenVINO 模型不可用时。**重排序器（reranker）** 作为独立
> `llama-server.exe` 进程运行，提供 `bge-reranker-v2-m3` GGUF 模型（端口 `:8081`）。

```mermaid
stateDiagram-v2
    [*] --> L1_ONNX: 默认启动（进程内）

    state L1_ONNX[级别 1: ONNX/OpenVINO INT8（进程内）]
        L1_ONNX: E5-small 嵌入器（384 维）
        L1_ONNX: BM25 + Dense + Reranker（llama.cpp）
        L1_ONNX: ~300ms-3s 延迟
    end

    L1_ONNX --> L2_GGUF: 有 GPU，偏好 llama.cpp 嵌入
    L1_ONNX --> L3_LM: ONNX 模型缺失 → LM Studio 回退（fallback）

    state L2_GGUF[级别 2: llama.cpp GGUF（GPU）]
        L2_GGUF: GGUF 嵌入 + 重排序（Vulkan GPU）
        L2_GGUF: BM25 + Dense + Reranker
        L2_GGUF: ~286ms-3s 延迟
    end

    L2_GGUF --> L1_ONNX: llama.cpp 不可用

    state L3_LM[级别 3: LM Studio（远程，可选）]
        L3_LM: 外部 API（端口 1234）
        L3_LM: BM25 + Dense + Reranker
        L3_LM: ~300ms-5s 延迟（网络）
    end

    L3_LM --> L4_BM25: 所有外部离线

    state L4_BM25[级别 4: 仅 BM25]
        L4_BM25: 仅关键词搜索
        L4_BM25: SymbolIndex + FTS5 回退（fallback）
        L4_BM25: 无向量搜索
    end

    L4_BM25 --> L5_SYMBOL: BM25 不可用

    state L5_SYMBOL[级别 5: 仅 SymbolIndex]
        L5_SYMBOL: 纯 AST 符号索引
        L5_SYMBOL: Tree-sitter 定义 + 引用
        L5_SYMBOL: 无语义搜索
    end
```

### 横切层（始终可用）

以下各层 **独立于** 上述搜索级别：

```mermaid
stateDiagram-v2
    [*] --> LSP_ACTIVE: basedpyright 可用

    state LSP_ACTIVE[LSP: basedpyright]
        LSP_ACTIVE: 跨文件重命名精度
        LSP_ACTIVE: 完整语义 WorkspaceEdit
        LSP_ACTIVE: ~105ms warm 延迟
    end

    LSP_ACTIVE --> LSP_FALLBACK: 超时（5s）或不可用

    state LSP_FALLBACK[LSP: SymbolIndex]
        LSP_FALLBACK: Tree-sitter 基于文本的重命名
        LSP_FALLBACK: 可能遗漏动态导入
        LSP_FALLBACK: 始终工作，零基础设施
    end
```

```mermaid
stateDiagram-v2
    [*] --> DEFAULT_TOOLS: 正常操作

    state DEFAULT_TOOLS[可见: 12 个工具]
        DEFAULT_TOOLS: search_code, get_symbol_info, impact_analysis
        DEFAULT_TOOLS: notify_change, get_index_status
        DEFAULT_TOOLS: intel_get_runtime_status
        DEFAULT_TOOLS: rename_symbol, replace_symbol
    end

    DEFAULT_TOOLS --> ALL_TOOLS: MSCODEBASE_MCP_TOOLS=""
    DEFAULT_TOOLS --> CUSTOM_TOOLS: MSCODEBASE_MCP_TOOLS="a,b,c"

    state ALL_TOOLS[可见: 37 个工具]
        ALL_TOOLS: 全部 37 个 MCP 工具可用（19 core + 12 intel + 6 diag）
    end

    state CUSTOM_TOOLS[自定义选择]
        CUSTOM_TOOLS: 用户指定的工具子集
    end
```

## 级别详情

### 级别 1: ONNX/OpenVINO INT8（默认，进程内）

```python
# 默认提供者路径（EMBEDDING_PROVIDER=e5_onnx）
class RemoteEmbedder:
    def _init_provider_async(self):
        _provider = os.getenv("EMBEDDING_PROVIDER", "e5_onnx")
        if _provider in ("e5_onnx", "auto", ""):
            self._init_onnx()
            # OpenVINO INT8 优先（Windows CPU 上 ~37 ch/s）
            if getattr(self, "_ov_compiled", None) is not None:
                self.mode = "onnx"
```

| 组件 | 状态 |
|-----------|:------:|
| ONNX/OpenVINO E5-small | ✅ 进程内（384 维，INT8） |
| BM25 索引 | ✅ 已构建 |
| 重排序器（reranker）（llama.cpp） | ✅ 可用（`:8081`） |
| mode=ask | ⚠️ 可选（需要 LLM profile） |
| **延迟** | **300ms-3s** |
| **质量** | **最佳**（无外部依赖） |

**触发：** 默认启动。不需要外部服务器。

### 级别 2: llama.cpp GGUF（GPU，可选）

如果用户有 Vulkan GPU 并偏好 GGUF 嵌入，`llama-server.exe` 可提供嵌入器（embedder）。这是加速路径，非默认。

| 组件 | 状态 |
|-----------|:------:|
| llama.cpp 嵌入（GPU） | ✅ 可用 |
| BM25 索引 | ✅ 已构建 |
| 重排序器（reranker） | ✅ 可用 |
| mode=ask | ⚠️ 可选 |
| **延迟** | **286ms-3s** |
| **质量** | **最佳** |

### 级别 3: LM Studio（远程，可选回退 fallback）

```python
# 仅当本地 ONNX/OpenVINO 模型不可用时到达
class RemoteEmbedder:
    def _check_lm_studio(self) -> bool:
        """通过 CircuitBreaker 路由，防止级联失败。"""
        if self._breaker is not None:
            return bool(self._breaker.call(self._check_lm_studio_raw, fallback=True))
        return self._check_lm_studio_raw()
```

| 组件 | 状态 |
|-----------|:------:|
| LM Studio | ✅ 在线（若运行） |
| ONNX 模型 | ❌ 缺失 |
| 重排序器（reranker） | ✅ 可用（通过 LM Studio） |
| mode=ask | ✅ 可用 |
| **延迟** | **300ms-5s**（网络） |
| **质量** | **良好** |

**触发：** `EMBEDDING_PROVIDER=lm_studio` 或本地 ONNX 模型缺失。

### 级别 4: 仅 BM25（最小）

```python
# BM25 builder 中的优雅降级
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
| ONNX 模型 | ❌ 缺失 |
| LM Studio | ❌ 离线 |
| BM25 索引 | ✅ 可用 |
| 重排序器（reranker） | ❌ 不可用 |
| mode=ask | ❌ 不可用 |
| **延迟** | **50ms-300ms** |
| **质量** | **基础**（仅关键词） |

### 级别 5: 仅 SymbolIndex（最后手段）

| 组件 | 状态 |
|-----------|:------:|
| ONNX 模型 | ❌ 缺失 |
| BM25 索引 | ❌ 不可用 |
| SymbolIndex | ✅ 可用 |
| 重排序器（reranker） | ❌ 不可用 |
| mode=ask | ❌ 不可用 |
| **延迟** | **<50ms** |
| **质量** | **仅 AST 符号**（无语义搜索） |

### 级别 6: 回退（Fallback）（首次运行）

| 组件 | 状态 |
|-----------|:------:|
| ONNX 模型 | ❌ 不可用 |
| BM25 索引 | ❌ 空 |
| 重排序器（reranker） | ❌ 不可用 |
| mode=ask | ❌ 不可用 |
| **延迟** | N/A |
| **质量** | **无**（等待索引） |

## 自动恢复

```mermaid
sequenceDiagram
    participant EM as RemoteEmbedder
    participant ONNX as ONNX/OpenVINO（进程内）
    participant LM as LM Studio（可选）
    participant BM25 as BM25 Index

    Note over EM: 级别 1（ONNX，默认）
    EM->>ONNX: embed query（进程内）
    ONNX-->>EM: vector（768 维）

    par 每 30s — scanner loop
        EM->>LM: GET /v1/models（若启用）
        LM-->>EM: 200 OK
        EM->>EM: 切换到 LM Studio（可选）
        Note over EM: 级别 3 恢复（可选）
    end
```
