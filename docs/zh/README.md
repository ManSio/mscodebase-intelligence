# MSCodebase Intelligence

**Zed IDE 的语义代码搜索 MCP 服务器。**

[🇬🇧 English](../../README.md) • [🇷🇺 Русский](../ru/README.md) • [🇨🇳 中文](README.md)

[功能特性](#功能特性) • [快速开始](#快速开始) • [工具列表](#mcp-工具共50个) • [文档地图](#文档地图)

*最后更新：2026-07-11*

---

## 功能特性

| 功能 | 描述 |
|------|------|
| **代码搜索** | `search_code()` — BM25 + 向量 + RRF + 重排序。5种模式 |
| **调用图** | `get_symbol_info()` + `impact_analysis()` — 调用者/被调用者/影响分析 |
| **项目记忆** | ADR、已知问题、技术债务 — 跨会话保存 |
| **诊断** | `intel_get_runtime_status()` — 嵌入器、索引、资源状态 |
| **跨仓库搜索** | `cross_repo_search()` — 多项目搜索 |

**50 个 MCP 工具：** 33 core + 14 intel + 3 diagnostic。

---

## 快速开始

在 Zed 中安装 `mscodebase-intelligence` 扩展，然后：

```bash
cd D:\Project\MSCodeBase
python install.py

# 重启 Zed (File → Quit → reopen)
# 验证：intel_get_runtime_status()
```

**install.py 完成：**
1. 复制 39+ 个源文件到扩展目录
2. 安装 Python 依赖
3. 下载 llama-server.exe + GGUF 模型
4. 配置 Zed 的 MCP 设置

---

## 文档地图

| 文档 | 说明 |
|------|------|
| [INSTALL.md](INSTALL.md) | 安装指南 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 架构说明 |
| [FAQ.md](FAQ.md) | 常见问题 |
| [ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md) | Windows 特性 |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史 |
| [KNOWN_ISSUES.md](../../docs/KNOWN_ISSUES.md) | 已知问题 |

---

## MCP 工具（共 50 个）

### 核心搜索（6）
`search_code(mode=auto/fast/quality/deep/context/ask, intent_hint=code/docs/auto)`,
`get_symbol_info()`, `impact_analysis()`, `structural_search()`,
`cross_repo_search()`, `cross_project_deps()`

### 索引管理（8）
`get_index_status()`, `index_project_dir()`, `notify_change()`,
`get_index_progress()`, `get_index_timeline()`, `index_health()`,
`generate_chunk_summaries()`, `scan_changes()`

### 系统与诊断（5）
`get_health_report()`, `watcher_status()`, `get_logs()`,
`get_repo_map()`, `read_live_file()`

### 分析（6）
`get_hotspots()`, `get_repo_rank()`, `get_bug_correlation()`,
`get_related_files()`, `graph_query()`, `find_similar_bugs()`

### Git 与历史（3）
`get_commit_history()`, `get_file_history()`, `get_branch_info()`

### 生命周期（3）
`submit_background_task()`, `get_task_status()`, `verify_action()`

### 智能层 — 14 个 intel_* 工具
`intel_get_runtime_status()`, `intel_trigger_reindex()`,
`intel_get_job_status()`, `intel_code_topology()`,
`intel_get_project_memory()`, `intel_log_incident()`,
`intel_analyze_incident()`, `intel_add_memory_node()`,
`intel_get_hotspots()`, `intel_predict_root_cause()`,
`intel_get_telemetry()`, `intel_tool_health()`,
`intel_execution_timeline()`, `intel_explain_project_state()`

### 诊断（3）
`debug_runtime_passport()`, `get_runtime_counters()`,
`intel_execution_timeline()`

---

## 项目结构

```
mscodebase-intelligence/
├── src/              # MCP 源代码
│   ├── main.py       # 入口点
│   ├── mcp/          # 服务器 + 33 个 core 工具
│   ├── core/         # 业务逻辑 + 14 个 intel 工具
│   └── utils/
├── docs/             # 61 个 .md 文件 (en/ru/zh)
├── tests/            # 396 个测试
└── install.py        # 安装程序
```
