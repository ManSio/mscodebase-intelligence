<div align="center">

<img src="logo/baner.svg" width="800" alt="MSCodeBase Intelligence">

[🇬🇧 English](README.md) • [🇷🇺 Русский](README.ru.md) • [🇨🇳 中文](README.zh.md)

# MSCodebase Intelligence

**AI 驱动的语义代码搜索 — 专为 Zed IDE 打造**
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![Zed](https://img.shields.io/badge/Zed-extension-orange.svg)](https://zed.dev/)
[![Tests](https://img.shields.io/badge/tests-391%20passing-brightgreen)](tests/)

[功能特性](#-功能特性) • [快速开始](#-快速开始) • [工具列表](#-mcp-工具共-43-个) • [文档地图](#-文档地图) • [安装指南](docs/INSTALL.md) • [架构说明](docs/architecture.md) • [开发指南](CONTRIBUTING.md)

*最后更新：2026-07-05*

</div>

---

## ✨ 功能特性

| 特性 | 描述 |
|---------|-------------|
| 🔍 **统一搜索** | `search_code(query, mode)` — 一个工具覆盖所有搜索类型（快速/高质量/深度/上下文/自动） |
| 🧠 **智能层** | 10 个高级 `intel_*` 工具：自我诊断、拓扑分析、错误预测 |
| 🗃️ **项目记忆** | ADR、已知问题、技术债务 — 跨会话自动保存 |
| 🌐 **跨仓库搜索** | 使用 `@mention` 语法跨多个项目搜索 |
| 🌳 **调用图** | 完整的调用图：定义 + 调用方 + 被调方 + 影响分析 |
| 🏗 **结构搜索** | 13 种 AST 模式（类继承、异步函数、装饰器等） |
| 🔎 **上下文搜索** | 查找相似代码 — 粘贴片段，获取语义重复项 |
| 💾 **LanceDB v2** | 按项目隔离的向量数据库（增量 BM25 重新索引） |
| 🛡 **速率限制** | DebounceBatch + CircuitBreaker — 防止 VFS 循环和过载 |
| 🏥 **自我诊断** | `get_health_report` + `index_health` — 全面检查和恢复 |
| 🧪 **整洁架构** | DI 容器（15 个服务）、43 个工具（33 个基于类 + 10 个 intel）、391+ 个测试 |
| 🪟 **多窗口** | `ProjectIndexerRegistry` — 每个项目隔离的 Indexer，LRU 5，ResourceMonitor 节流 |

---

## 🚀 快速开始

> 完整安装说明：**[docs/INSTALL.md](docs/INSTALL.md)**

```bash
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence
python install.py
```

**安装后：** File → Quit → 打开项目 → 等待索引完成。

**验证：** 在 Agent 面板（`Ctrl+Shift+P` → `Agent Panel: Toggle`）中执行：
```
get_index_status()
```

> **Windows：** Windows 上有一些特殊情况（受限模式、项目路径通过 SQLite 解析）。
> 安装前请务必阅读 **[ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md)**。
>
> **LM Studio：** 推荐用于向量搜索。安装后运行在 1234 端口 — MCP 会自动连接。

---

## 📚 文档地图

| 文档 | 内容 | 面向读者 |
|----------|-------|----------|
| **[docs/INSTALL.md](docs/INSTALL.md)** | 安装、配置、卸载 | 用户 |
| **[docs/architecture.md](docs/architecture.md)** | 整洁架构、分层、DI 容器 | 开发者 |
| **[docs/architecture-layers.md](docs/architecture-layers.md)** | 10 层架构（文件系统 → AI 代理） | 架构师 |
| **[docs/telemetry.md](docs/telemetry.md)** | 指标、ETA、数据收集 | DevOps |
| **[docs/investigations/2026-07-05-lsp-zed-1.9.0.md](docs/investigations/2026-07-05-lsp-zed-1.9.0.md)** | 调查报告：Windows 上的 LSP（WONTFIX） | 支持 |
| **[ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md)** | Windows 特性、受限模式、CWD | 所有 Windows 用户 |
| **[CHANGELOG.md](CHANGELOG.md)** | 版本历史 | 所有人 |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | 如何开发、测试、提交 PR | 贡献者 |
| **[AGENTS.md](AGENTS.md)** | AI 代理的系统规则（上下文） | AI 代理 |
| **[SECURITY.md](SECURITY.md)** | 安全策略、漏洞报告 | 安全 |

所有文档之间都有交叉引用。如果发现不一致，请提 issue。

---

## 🔧 MCP 工具（共 43 个）

### 核心搜索

| 工具 | 使用场景 |
|------|-------------|
| `search_code(query, mode, filter_layer)` | **主要搜索工具。** `mode="auto"` / `"fast"` / `"quality"` / `"deep"` / `"context"`。`filter_layer="core"` — 仅在指定架构层中搜索 |
| `structural_search(pattern)` | 按 AST 搜索：`class_inheritance`、`async_function`、`function_with_decorator` 等 |
| `cross_repo_search(query @repo)` | 跨多个项目搜索（单体仓库） |
| `cross_project_deps(action)` | 项目间依赖图：`graph` / `deps` / `cycles` / `impact` |
| `get_symbol_info(query)` | 调用图：谁调用我、我调用谁、影响文件 |
| `impact_analysis(symbol)` | 符号变更影响分析（风险评分、深度） |

### 索引管理

| 工具 | 使用场景 |
|------|-------------|
| `get_index_status()` | 索引状态：块数、文件数、符号数 |
| `get_index_progress()` | 索引进度（阶段、百分比） |
| `index_project_dir(path)` | 启动项目完整索引 |
| `get_index_timeline()` | 按日期查看索引历史 |
| `index_health(project_root)` | 索引诊断和自修复 |
| `notify_change(file_path)` | 强制更新文件索引（通过 DebounceBatch） |
| `generate_chunk_summaries(root)` | 代码块的 LLM 描述 |
| `scan_changes(project_root)` | 架构差异 — 分析相对于上次基线的变更 |

### 系统与诊断

| 工具 | 使用场景 |
|------|-------------|
| `get_health_report()` | **全面自我诊断：** 索引、嵌入器、日志、同步 |
| `watcher_status()` | 组件状态：嵌入器模式（LM Studio / Ollama / ONNX） |
| `get_logs(project_root)` | 项目日志中的最新错误和警告 |
| `get_repo_map(project_root)` | 项目地图：文件树 + 关键符号 |
| `read_live_file(path)` | 从 LSP 内存读取文件（包括未保存的更改） |

### 分析

| 工具 | 使用场景 |
|------|-------------|
| `get_hotspots(project_root)` | "热点" — 缺陷率高的文件 |
| `get_repo_rank(project_root, top_k)` | 符号重要性排名（调用图上的 PageRank） |
| `get_bug_correlation(project_root)` | 分析缺陷与代码变更的关联 |
| `get_related_files(project_root, path)` | 通过共同变更/缺陷关联相关的文件 |
| `graph_query(query_type, target)` | 知识图谱查询：`impact` / `feature` / `deps` / `tests` |
| `find_similar_bugs(error)` | 根据错误文本从历史中查找相似缺陷 |

### Git 与历史

| 工具 | 使用场景 |
|------|-------------|
| `get_commit_history(root, limit)` | 语义化提交历史 |
| `get_file_history(root, path)` | 特定文件的变更历史 |
| `get_branch_info(project_root)` | 分支信息 + 索引状态 |

### 生命周期与验证

| 工具 | 使用场景 |
|------|-------------|
| `submit_background_task(type, root)` | 启动长时间任务：`bug_correlation` / `build_knowledge_graph` / `full_analysis` |
| `get_task_status(task_id)` | 后台任务状态 |
| `verify_action(action_type)` | 验证：`file_write` / `git_commit` / `git_push` / `index_sync` |
| `predict_eta(operation)` | 预测操作执行时间 |
| `run_health_check()` | 项目全面健康检查（测试 + git） |

### 智能层 (intel_*) — 10 个高级工具

| 工具 | 功能 |
|------|-------------|
| `intel_get_runtime_status()` | 聚合健康状态：嵌入器、索引、资源使用率 |
| `intel_trigger_reindex()` | 即发即弃式重新索引（不阻塞 Zed） |
| `intel_get_job_status(job_id)` | 后台任务进度 |
| `intel_code_topology(symbol)` | 调用图 + 模块拓扑（< 2 秒） |
| `intel_get_project_memory()` | 项目记忆地图：ADR、已知问题、技术债务 |
| `intel_log_incident(...)` | 将事件记录到项目历史 |
| `intel_analyze_incident(error)` | 查找类似事件 + 现成解决方案 |
| `intel_add_memory_node(section, data)` | 向项目记忆添加记录 |
| `intel_get_hotspots()` | 缺陷负载最高的前 5 个文件 |
| `intel_predict_root_cause(error)` | 根据日志 + 历史预测故障根本原因 |

---

## 🏗️ 架构

### 使用 DI 容器的整洁架构

```
┌──────────────────────────────────────────────────────────────────┐
│                   MCP 服务器（约 220 行）                           │
│            src/mcp/server.py — 仅注册                              │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              DI 容器（15 个服务）                           │   │
│  │  src/core/di_container.py — ServiceCollection              │   │
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
│  │  33 个工具类        │  │  10 个 intel_* 工具                 │  │
│  │  src/mcp/tools/*.py │  │  src/core/intelligence_layer.py    │  │
│  │  每个工具一个类      │  │  error_boundary 装饰器              │  │
│  │  构造函数注入        │  │  JSON status/message/detail        │  │
│  └────────────────────┘  │  asyncio.wait_for(timeout)        │  │
│                          └────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────┐     ┌───────────────────┐
│  RemoteEmbedder  │     │  LanceDB v2       │
│  (LM Studio /    │     │  (向量数据库)      │
│   Ollama / ONNX) │     │  BM25 + Vector    │
└─────────────────┘     └───────────────────┘
```

---

## ⚡ 性能

| 模式 | 延迟 | 最佳用途 |
|:-----|:--------|:---------|
| `search_code(query, mode="fast")` | ~300ms | 简单关键词 / 精确名称 |
| `search_code(query, mode="quality")` | ~1200ms | 带重排序的语义搜索 |
| `search_code(query, mode="deep")` | ~2-5s | 跨模块复杂研究 |
| `search_code(query, mode="context")` | ~500ms | 通过片段查找相似代码 |
| `cross_repo_search(query @repo)` | ~500ms-2s | 跨项目搜索 |

### 环境变量

| 变量 | 默认值 | 描述 |
|----------|---------|-------------|
| `LM_STUDIO_URL` | `http://localhost:1234/v1` | LM Studio API 端点 |
| `LM_STUDIO_PORT` | `1234` | LM Studio 端口 |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API 端点 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `ZED_WINDOWS_QUIRKS.md` | *(见文件)* | Windows 说明 |

---

## 🔧 故障排除

### MCP 服务器无响应

**症状：** 工具无响应、超时。

**检查清单：**
1. **File → Quit** → 重新打开项目
2. 运行 `python install.py` 重新配置
3. 检查日志：`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\`

### 索引为空（0 块）

在 Agent 面板中执行：
```
intel_trigger_reindex()
```

然后检查：`get_index_status()`

### LM Studio 连接问题

```bash
# 检查服务器是否响应：
python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:1234/v1/health').read())"
```

应返回 `{"status":"ok"}`。

---

## 📁 项目结构

```
mscodebase-intelligence/
├── src/
│   ├── main.py                   # MCP 服务器入口点（约 220 行）
│   ├── lsp_main.py               # LSP 服务器（基于 DI，用于 didSave 索引）
│   ├── mcp/
│   │   ├── server.py             # DI 路由 — 仅导入 + 注册
│   │   └── tools/                 # 10 个文件，33 个基于类 + 10 个 intel = 共 43 个
│   │       ├── search_tools.py   # search_code, get_symbol_info, impact_analysis
│   │       ├── indexing_tools.py # notify_change, index_project_dir, index_health
│   │       ├── git_tools.py      # get_branch_info, get_commit_history
│   │       ├── system_tools.py   # get_index_status, watcher_status, read_live_file
│   │       ├── analysis_tools.py # structural_search, get_repo_map, scan_changes
│   │       ├── graph_tools.py    # cross_repo_search, graph_query, get_related_files
│   │       ├── investigation_tools.py  # get_bug_correlation, get_hotspots
│   │       └── lifecycle_tools.py      # submit_background_task, verify_action
│   ├── core/
│   │   ├── di_container.py       # ★ DI 容器（15 个服务，ServiceCollection）
│   │   ├── error_handler.py      # ★ error_boundary + ToolError
│   │   ├── rate_limiter.py       # ★ SlidingWindowRateLimiter + DebounceBatch + CircuitBreaker
│   │   ├── indexer.py            # LanceDB 向量存储
│   │   ├── searcher.py           # 混合搜索（BM25 + Dense + RRF）
│   │   ├── symbol_index.py       # 调用图（BFS，影响分析）
│   │   ├── intelligence_layer.py # intel_* 工具（10 个高级工具）
│   │   ├── remote_embedder.py    # LM Studio / Ollama 客户端
│   │   ├── reranker.py           # 多提供商重排序器
│   │   ├── parser.py             # Tree-sitter AST
│   │   ├── health_report.py      # 自我诊断引擎
│   │   └── ...
│   └── utils/
│       ├── paths.py              # SafePathManager, to_win_long_path
│       └── zed_config.py         # 自动配置 Zed 设置
├── docs/
│   ├── architecture.md
│   └── INSTALL.md
├── tests/                        # 391 个测试（pytest）
├── .agents/skills/               # AI 代理的技能
├── install.py                    # 安装程序
└── README.md
```

---

## 🛠️ 开发

参见 [CONTRIBUTING.md](CONTRIBUTING.md) 了解：
- 如何添加新的 MCP 工具
- 测试结构和 CI 流水线
- 提交消息约定

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

MIT 许可证 — 详见 [LICENSE](LICENSE)。

---

## 🙏 致谢

- [Zed IDE](https://zed.dev/) — 代码编辑器
- [LM Studio](https://lmstudio.ai/) — 本地 LLM 推理
- [LanceDB](https://lancedb.github.io/) — 向量数据库
- [Model Context Protocol](https://modelcontextprotocol.io/) — MCP 标准
