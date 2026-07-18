<div align="center">

<img src="../../logo/baner.png" alt="MSCodeBase Banner" width="100%"/>

[🇬🇧 English](../../README.md) • [🇷🇺 Русский](../ru/README.md) • [🇨🇳 中文](README.md)

# MSCodebase Intelligence

**Zed IDE 的 AI 驱动语义代码搜索 MCP 服务器 — 深度代码分析 MCP 服务器**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![Zed](https://img.shields.io/badge/Zed-extension-orange.svg)](https://zed.dev/)
[![Tests](https://img.shields.io/badge/tests-605%20passing-brightgreen)](../../tests/)

[功能特性](#-功能特性) • [快速开始](#-快速开始) • [工具列表](#-mcp-工具共38个) • [文档地图](#-文档地图) • [安装指南](INSTALL.md) • [架构说明](ARCHITECTURE.md) • [贡献指南](../../CONTRIBUTING.md) • [安全策略](../../SECURITY.md)

*最后更新：2026-07-18*

</div>

---

## 🎯 定位

**MSCodeBase Intelligence** 是一个面向 **Zed IDE** 的 MCP 服务器，为 AI 助手提供 **对整个代码库的深度理解**：语义搜索、调用图、项目记忆、诊断。

这**不是** LSP 服务器，也不是编辑器内置自动补全的替代品。它是编辑器之上的"代码智能"层：

```
┌─────────────────────────────────────────────────────┐
│                      Zed IDE                         │
│  ┌───────────────────────────────────────────────┐  │
│  │        LSP（内置自动补全、                      │  │
│  │        内联提示、诊断）                         │  │
│  └───────────────────────────────────────────────┘  │
│                        │                              │
│                        ▼                              │
│  ┌───────────────────────────────────────────────┐  │
│  │  MSCodeBase（MCP 服务器）                     │  │
│  │  · 代码库语义搜索                              │  │
│  │  · 调用图与影响分析                            │  │
│  │  · 项目记忆（ADR、技术债务）                   │  │
│  │  · 自诊断与自愈                                │  │
│  │  · 为 AI 助手提供 38 个工具                    │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 能力对比

| 功能 | MSCodeBase | 标准 LSP（pyright/pylsp） |
|---------|:----------:|:---------------------------:|
| 🔍 **语义搜索**（BM25 + 向量 + 重排序） | ✅ | ❌ |
| 🧠 **调用图 + 影响分析** | ✅ | ❌ |
| 🗃️ **项目记忆**（ADR、已知问题） | ✅ | ❌ |
| 🏥 **自诊断 + 自愈** | ✅ | ❌ |
| 🔎 **跨仓库搜索** | ✅ | ❌ |
| 🤖 **RAG 答案生成**（mode=ask） | ✅ | ❌ |
| 🔬 **搜索透明度**（per-stage 评分分解） | ✅ | ❌ |
| 🏛️ **架构漂移检测**（chain/hub/circular） | ✅ | ❌ |
| ✅ **声明验证**（AI 代理事实核查） | ✅ | ❌ |
| ✏️ **内联自动补全** | ❌ | ✅ |
| 🏷️ **内联提示** | ❌ | ✅ |

### LSP：仅用于重命名（混合模式）

MSCodeBase **仅在 `rename_symbol` 中使用 LSP** — LSP 客户端（`src/core/lsp_client.py`）启动 **pyright-langserver** 以实现精确的跨文件重命名，超时时自动回退到 SymbolIndex（Tree-sitter）。所有其他功能通过 **38 个 MCP 工具** 实现。

独立的 LSP 服务器（`src/lsp_main.py`）是实验性组件，**在 Zed 中无法工作** — 参见 [LSP_WONTFIX.md](investigations/LSP_WONTFIX.md)。

### 支持平台

在 **Windows** 上设计和测试。macOS 和 Linux 应可工作，但尚未经过官方验证。

### 支持语言

| 语言 | 解析 | 调用图 | Data Flow (ASSIGNED_FROM) |
|---|---|---|---|
| **Python** | ✅ | ✅ | ✅ |
| **TypeScript** | ✅ | ✅ | ✅ |
| **TSX** | ✅ | ✅ | ✅ |
| **Rust** | ✅ | ✅ | ✅ |
| **Go** | ✅ | ✅ | ✅ |
| **JavaScript** | ✅ | ✅ | ✅ |
| **Java** | ✅ | ✅ | ✅ |
| **C#** | ✅ | ✅ | ✅ |
| **Ruby** | ✅ | ✅ | ✅ |
| **PHP** | ✅ | ✅ | ✅ |
| **Kotlin** | ✅ | ✅ | ✅ |
| **Swift** | ✅ | ✅ | ✅ |
| **C** | ✅ | ✅ | ✅ |
| **C++** | ✅ | ✅ | ✅ |
| **Scala** | ✅ | ✅ | ✅ |
| **Dart** | ✅ | ✅ | ✅ |
| **Shell** | ✅ | ⚪ | ⚪ |
| **Bash** | ✅ | ⚪ | ⚪ |

## ✨ 功能特性

| 功能 | 描述 |
|---------|-------------|
| 🔍 **统一搜索** | `search_code(query, mode, intent_hint)` — 单一工具：fast/quality/deep/context/ask/auto |
| 🧠 **智能层** | 13 个高级 `intel_*` 工具：自诊断、拓扑、记忆、错误预测 |
| 🗃️ **项目记忆** | ADR、已知问题、技术债务 — 跨会话自动持久化 |
| 🌐 **跨仓库搜索** | 使用 `@mention` 语法跨多个项目搜索 |
| 🌳 **调用图** | 完整调用图：定义 + 调用方 + 被调用方 + 影响分析 |
| 🏗 **结构搜索** | 13 种 AST 模式（class_inheritance、async_function、decorator 等） |
| 🔎 **上下文搜索** | 查找相似代码 — 粘贴片段，获取语义重复 |
| 🪣 **多桶 RAG** | 代码/文档桶，软权重，intent_hint（code/docs/auto） |
| 🤖 **mode=ask** | 通过 phi-4 生成 RAG 答案（server 配置） |
| 💾 **LanceDB v2** | 向量数据库，支持项目隔离（增量 BM25 重索引） |
| 🛡 **限流** | DebounceBatch + CircuitBreaker — 防止 VFS 循环 |
| 🏥 **自诊断** | `get_health_report` + `index_health` — 完整检查与恢复 |
🧪 **整洁架构** | DI 容器（18 个服务），38 个工具（18 core + 13 intel + 6 inline + 1 optional），605+ 测试 |
| 🪟 **多窗口** | `ProjectIndexerRegistry` — 每个项目独立 Indexer，LRU 5，ResourceMonitor 限流 |
| ✏️ **Write Tools** | `codebase(action=...)` — 统一枢纽：rename、move、delete、replace、insert、ack |
| ⚡ **Meta-Patching** | LanceDB `move_chunks_metadata` — 无需重新嵌入即可重命名 file_path（50ms vs 5s） |
| ⚙️ **SYSTEM_PROFILE** | `light`（同步）/ `server`（异步，带 phi-4） |
| 🔗 **数据流图** | `ASSIGNED_FROM` 边追踪变量赋值。Unified Walker + Conditional Flow（if/for/while/try）。MSCodeBase 上 42 种边类型。 |

---

## 🚀 快速开始

在 Zed 中安装 `mscodebase-intelligence` 扩展，然后：

```bash
cd D:\Project\MSCodeBase
python install.py

# 重启 Zed（File → Quit → 重新打开）
# 验证：intel_get_runtime_status()
```

**install.py 完成以下操作：**
1. 将 39+ 个源文件复制到扩展目录
2. 安装 Python 依赖
3. 下载 llama-server.exe + GGUF 重排序模型（bge-reranker-v2-m3）。嵌入器（multilingual-e5-small INT8）为单独的 ONNX 模型
4. 在 Zed 的 settings.json 中配置 MCP

另见：[AI_INSTALLATION_PROMPT.md](../../AI_INSTALLATION_PROMPT.md)、[INSTALL.md](INSTALL.md)

### 提供者

MCP 自动选择最佳可用提供者：

```
ONNX/OpenVINO INT8（进程内）→ llama.cpp GGUF（GPU）→ LM Studio（如果运行中）→ 仅 BM25
   ~0.5 GB RAM                ~1.7 GB RAM (2× llama-server)   ~6 GB RAM             无嵌入
   e5-small 嵌入器（384dim）     重排序器（bge-reranker-v2-m3）   外部 API
```

基准测试：[docs/research/2026-07-10-final-benchmark.md](../research/2026-07-10-final-benchmark.md)

---

## 📚 文档地图

| 文档 | 描述 | 受众 | 语言 |
|----------|-------------|----------|-----------|
| **[INSTALL.md](INSTALL.md)** | 安装、设置、卸载 | 用户 | 🇬🇧 🇷🇺 🇨🇳 |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | 整洁架构、层次、DI | 开发者 | 🇬🇧 🇷🇺 🇨🇳 |
| **[ARCHITECTURE_DEEP.md](ARCHITECTURE_DEEP.md)** | 深度架构：流水线、生命周期、对比 | 架构师 | 🇬🇧 🇷🇺 🇨🇳 |
| **[SEARCH_PIPELINE.md](SEARCH_PIPELINE.md)** | 搜索流水线：BM25 → RRF → 重排序 | 开发者 | 🇬🇧 |
| **[GRACEFUL_DEGRADATION.md](GRACEFUL_DEGRADATION.md)** | 5 级优雅降级（llama.cpp → ONNX → BM25） | DevOps | 🇬🇧 |
| **[ARCHITECTURE_LAYERS.md](ARCHITECTURE_LAYERS.md)** | 10 个运行时层次 | 架构师 | 🇬🇧 🇷🇺 🇨🇳 |
| **[FAQ.md](FAQ.md)** | 常见问题 | 全部 | 🇬🇧 🇷🇺 🇨🇳 |
| **[TELEMETRY.md](TELEMETRY.md)** | 指标、ETA、数据收集 | DevOps | 🇬🇧 🇷🇺 🇨🇳 |
| **[investigations/ONNX_SESSION_REPORT.md](investigations/ONNX_SESSION_REPORT.md)** | 完整 ONNX 迁移、7 个修复、基准测试 | 支持 | 🇬🇧 |
| **[investigations/LSP_WONTFIX.md](investigations/LSP_WONTFIX.md)** | Windows 上 LSP 调研（WONTFIX） | 支持 | 🇬🇧 🇨🇳 |
| **[ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md)** | Windows 特性、受限模式 | Windows 用户 | 🇬🇧 🇷🇺 🇨🇳 |
| **[CHANGELOG.md](CHANGELOG.md)** | 版本历史 | 全部 | 🇬🇧 🇷🇺 🇨🇳 |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | 如何贡献、PR | 贡献者 | 🇬🇧 🇷🇺 🇨🇳 |
| **[SECURITY.md](SECURITY.md)** | 安全策略、漏洞 | 安全人员 | 🇬🇧 🇷🇺 🇨🇳 |
| **[../../AGENTS.md](../../AGENTS.md)** | AI 代理系统规则 | AI 代理 | 🇬🇧 |
| **[../../SECURITY.md](../../SECURITY.md)** | 安全策略、报告漏洞 | 安全人员 | 🇬🇧 |
| **[../../CODE_OF_CONDUCT.md](../../CODE_OF_CONDUCT.md)** | 社区准则 | 贡献者 | 🇬🇧 |

| **[../../docs/KNOWN_ISSUES.md](../../docs/KNOWN_ISSUES.md)** | 已知问题与技术债务注册表 | 全部 | 🇬🇧 |

所有文档相互引用。提供 3 种语言：English、Русский、中文。

---

## 🔧 MCP 工具（共 38 个）

### 核心搜索

| 工具 | 使用场景 |
|------|-------------|
| `search_code(query, mode, filter_layer, intent_hint)` | **主搜索工具。** `mode="auto"` / `"fast"` / `"quality"` / `"deep"` / `"context"` / `"ask"`。`intent_hint="code"` / `"docs"` / `"auto"` — 软桶权重。`filter_layer="core"` — 在特定架构层内搜索 |
| `structural_search(pattern)` | AST 搜索：`class_inheritance`、`async_function`、`function_with_decorator` 等 |
| `cross_repo_search(query @repo)` | 跨多项目搜索（单体仓库） |
| `cross_project_deps(action)` | 跨项目依赖图：`graph` / `deps` / `cycles` / `impact` |
| `get_symbol_info(query)` | 调用图：调用方、被调用方、影响文件 |
| `impact_analysis(symbol)` | 符号变更影响分析（风险分数、深度） |

### 索引管理

| 工具 | 使用场景 |
|------|-------------|
| `get_index_status()` | 索引状态：块数、文件数、符号数 |
| `get_index_progress()` | 索引进度（阶段、百分比） |
| `index_project_dir(path)` | 开始完整项目索引 |
| `get_index_timeline()` | 按日期查看索引历史 |
| `index_health(project_root)` | 索引诊断与自我恢复 |
| `notify_change(file_path)` | 强制更新某个文件的索引（通过 DebounceBatch） |
| `generate_chunk_summaries(root)` | 代码块的 LLM 生成描述 |
| `scan_changes(project_root)` | 架构差异 — 分析自上次基线以来的变更 |

### 系统与诊断

| 工具 | 使用场景 |
|------|-------------|
| `get_health_report()` | **完整自诊断：** 索引、嵌入器、日志、同步 |
| `watcher_status()` | 组件状态：嵌入器模式、索引、健康 |
| `get_logs(project_root)` | 项目日志中的最新错误和警告 |
| `get_repo_map(project_root)` | 项目地图：文件树 + 关键符号 |
| `read_live_file(path)` | 从 LSP 内存读取文件（含未保存的更改） |
| `predict_eta(operation)` | 基于历史预测操作耗时 |
| `run_health_check()` | 完整项目健康检查（测试 + git + 索引） |

### 分析

| 工具 | 使用场景 |
|------|-------------|
| `get_hotspots(project_root)` | 热点 — 高缺陷率的文件 |
| `get_repo_rank(project_root, top_k)` | 符号重要性排名（调用图上的 PageRank） |
| `get_bug_correlation(project_root)` | 缺陷-变更关联分析 |
| `get_related_files(project_root, path)` | 通过共同变更/缺陷关联相关的文件 |
| `graph_query(query_type, target)` | 知识图谱查询：`impact` / `feature` / `deps` / `tests` |
| `find_similar_bugs(error)` | 通过错误文本从历史中查找类似缺陷 |

### Git 与历史

| 工具 | 使用场景 |
|------|-------------|
| `get_commit_history(root, limit)` | 语义化提交历史 |
| `get_file_history(root, path)` | 特定文件的变更历史 |
| `get_branch_info(project_root)` | 分支信息 + 索引状态 |

### 生命周期与验证

| 工具 | 使用场景 |
|------|-------------|
| `submit_background_task(type, root)` | 运行长任务：`bug_correlation` / `build_knowledge_graph` / `full_analysis` |
| `get_task_status(task_id)` | 后台任务状态 |
| `verify_action(action_type)` | 验证：`file_write` / `git_commit` / `git_push` / `index_sync` |

### Write Tools — `codebase(action=...)`

| 操作 | 使用场景 |
|------|-------------|
| `codebase(action="rename", old, new, apply)` | 在所有文件中重命名符号（预览/应用，冲突检查） |
| `codebase(action="move", symbol, to_file, apply)` | 将符号移动到另一个文件（预览/应用，导入更新） |
| `codebase(action="safe_delete", symbol, force, apply)` | 安全删除并检查引用（强制模式） |
| `codebase(action="replace", symbol, new_code, apply)` | 替换函数/类主体（预览/应用） |
| `codebase(action="insert_before", anchor, new_code, apply)` | 在锚点符号前插入代码（预览/应用） |
| `codebase(action="insert_after", anchor, new_code, apply)` | 在锚点主体后插入代码（预览/应用） |
| `codebase(action="ack_impact", file_path)` | 确认影响以解除 modification guard |

### 智能层（intel_*）— 13 个高级工具

| 工具 | 功能 |
|------|-------------|
| `intel_get_runtime_status()` | 聚合健康状态：嵌入器、索引、资源使用 |
| `intel_trigger_reindex()` | 即发即弃的重索引（不阻塞 Zed） |
| `intel_get_job_status(job_id)` | 后台任务进度 |
| `intel_code_topology(symbol)` | 调用图 + 模块拓扑（< 2 秒） |
| `intel_get_project_memory()` | 项目记忆地图：ADR、known_issues、tech_debt |
| `intel_log_incident(...)` | 记录事件到项目历史 |
| `intel_analyze_incident(error)` | 查找类似事件 + 现成解决方案 |
| `intel_add_memory_node(section, data)` | 添加记录到项目记忆 |
| `intel_get_hotspots()` | 缺陷负载最高的 Top-5 文件 |
| `intel_predict_root_cause(error)` | 从日志 + 历史预测根本原因 |
| `intel_get_telemetry(days)` | 按工具统计的遥测、资源使用、LLM 统计 |

> `intel_tool_health()`、`intel_explain_project_state()`、`intel_get_project_context()` — 见下方诊断工具。

### 诊断工具（6 个）

| 工具 | 功能 |
|------|-------------|
| `debug_runtime_passport()` | 进程护照：RUN_ID、PID、构建信息 |
| `get_runtime_counters()` | 运行时计数器：调用次数、阻塞次数、警告次数 |
| `intel_execution_timeline(limit)` | 最近操作时间线及耗时 |
| `intel_get_project_context(root)` | 单一快照：状态、索引、健康、记忆 |
| `intel_explain_project_state(root)` | 人类可读的项目状态诊断 |
| `intel_tool_health()` | 工具成功率、延迟、置信度 |

---

## 🏗️ 架构

### 基于 DI 容器的整洁架构

```
┌──────────────────────────────────────────────────────────────────┐
│                   MCP 服务器（约 600 行）                         │
│            src/mcp/server.py + server_tools.py + server_factory.py │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              DI 容器（18 个服务）                          │   │
│  │  src/core/di_container.py — ServiceCollection             │   │
│  │                                                           │   │
│  │  ┌──────────┐  ┌────────────┐  ┌──────────────────────┐  │   │
│  │  │ Indexer  │  │  Searcher  │  │  DebounceBatch       │  │   │
│  │  │ Embedder │  │  SymbolIdx │  │  CircuitBreaker      │  │   │
│  │  │ Parser   │  │  FileGuard │  │  RateLimiter         │  │   │
│  │  └──────────┘  └────────────┘  └──────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                       │
│              ┌────────────┴────────────┐                         │
│              ▼                          ▼                         │
│  ┌────────────────────┐  ┌────────────────────────────────────┐  │
│  │  18 个工具类      │  │  13 intel_* + 6 inline 工具      │  │
│  │  src/mcp/tools/*.py│  │  intelligence/layer.py +         │  │
│  │  + codebase hub     │  │  server_tools.py (inline)       │  │
│  │  构造函数注入      │  │  error_boundary 装饰器            │  │
│  │  1 execute_script   │  │  asyncio.wait_for(timeout)       │  │
│  └────────────────────┘  └────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐     ┌───────────────────┐
│  RemoteEmbedder  │     │  LanceDB v2       │
│  (LM Studio /    │     │  (向量数据库)      │
│   Ollama / ONNX) │     │  BM25 + 向量      │
└─────────────────┘     └───────────────────┘
```

---

## ⚡ 性能

| 模式 | 延迟 | 最佳用途 |
|:-----|:--------|:---------|
| `search_code(query, mode="fast")` | ~80-500ms | 简单关键词/精确名称 |
| `search_code(query, mode="quality")` | ~250-2000ms | 带重排序的语义搜索 |
| `search_code(query, mode="deep")` | ~2-5s | 跨模块复杂调研 |
| `search_code(query, mode="context")` | ~200-800ms | 通过片段查找相似代码 |
| `get_symbol_info(query)` | ~200-1500ms | 符号定义 + 调用图 |
| `impact_analysis(symbol)` | ~1-5s | 变更影响分析 |

### 环境变量

| 变量 | 默认值 | 描述 |
|----------|---------|-------------|
| `LM_STUDIO_URL` | `http://localhost:1234/v1` | LM Studio API 端点 |
| `LM_STUDIO_PORT` | `1234` | LM Studio 端口 |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API 端点 |
| `LOG_LEVEL` | `INFO` | 日志详细级别 |
| `ZED_WINDOWS_QUIRKS.md` | *（见文件）* | Windows 特定说明 |

---

## 🔧 故障排除

### MCP 服务器无响应

**症状：** 工具超时，无响应。

**检查清单：**
1. **File → Quit** → 重新打开项目
2. 运行 `python install.py` 重新配置
3. 检查日志：`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`

### 索引为空（0 个块）

在代理面板中运行：
```
intel_trigger_reindex()
```

然后验证：`get_index_status()`

### LM Studio 连接问题

```bash
# 验证服务器是否响应：
python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:1234/v1/health').read())"
```

预期输出：`{"status":"ok"}`。

---

## 📁 项目结构

```
mscodebase-intelligence/
├── src/
│   ├── main.py                   # MCP 服务器入口点（约 194 行）
│   ├── lsp_main.py               # LSP 服务器（基于 DI，用于 didSave 索引）
│   ├── mcp/
│   │   ├── server.py             # MCP 服务器创建（约 597 行）
│   │   ├── server_factory.py     # DI 设置 + 服务器生命周期
│   │   ├── server_tools.py       # 工具注册（18 core + 13 intel + 6 inline）
│   │   └── tools/                # 12 个文件，18 个基于类的工具
│   │       ├── search_tools.py   # search_code、get_symbol_info、impact_analysis
│   │       ├── indexing_tools.py # notify_change、index_project_dir、index_health
│   │       ├── git_tools.py      # get_branch_info、get_commit_history
│   │       ├── system_tools.py   # get_index_status、watcher_status、read_live_file
│   │       ├── analysis_tools.py # structural_search、get_repo_map、scan_changes
│   │       ├── graph_tools.py    # cross_repo_search、graph_query、get_related_files
│   │       ├── investigation_tools.py  # get_bug_correlation、get_hotspots
│   │       └── lifecycle_tools.py      # submit_background_task、verify_action
│   ├── core/
│   │   ├── di_container.py       # ★ DI 容器（18 个服务，ServiceCollection）
│   │   ├── error_handler.py      # ★ error_boundary + ToolError
│   │   ├── rate_limiter.py       # ★ SlidingWindowRateLimiter + DebounceBatch + CircuitBreaker
│   │   ├── indexer.py            # LanceDB 向量存储
│   │   ├── searcher.py           # 混合搜索（BM25 + 密集向量 + RRF）
│   │   ├── symbol_index.py       # 调用图（BFS、影响分析）
│   │   ├── intelligence_layer.py # intel_* 工具（13 个高级）
│   │   ├── llama_runner.py       # llama.cpp 生命周期管理器 ★
│   ├── remote_embedder.py    # ONNX/OpenVINO multilingual-e5-small INT8（进程内）+ LM Studio / Ollama fallback
│   │   ├── reranker.py           # 多提供者重排序（HTTP 到提供者）
│   │   ├── parser.py             # Tree-sitter AST
│   │   ├── health_report.py      # 自诊断引擎
│   │   └── ...
│   └── utils/
│       ├── paths.py              # SafePathManager、to_win_long_path
│       └── zed_config.py         # 自动配置 Zed 设置
├── docs/
│   ├── en/               # 英文文档
│   ├── ru/               # 俄文文档
│   └── zh/               # 中文文档
├── tests/                        # 605 个测试（pytest）
├── .agents/skills/               # AI 代理技能
├── install.py                    # 安装程序
└── README.md
```

---

## 🛠️ 开发

参见 [CONTRIBUTING.md](CONTRIBUTING.md) 了解：
- 如何添加新的 MCP 工具
- 测试结构与 CI 流水线
- 提交信息约定

### 开发者快速开始

```bash
# 设置
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 直接运行 MCP 服务器（测试）
python -m src.main

# 运行测试
pytest tests/ -m "not integration and not benchmark"
```

---

## 📄 许可证

MIT 许可证 — 详见 [LICENSE](../../LICENSE)。

---

## 🙏 致谢

- [Zed IDE](https://zed.dev/) — 代码编辑器
- [LM Studio](https://lmstudio.ai/) — 本地 LLM 推理
- [LanceDB](https://lancedb.github.io/) — 向量数据库
- [Model Context Protocol](https://modelcontextprotocol.io/) — MCP 标准
