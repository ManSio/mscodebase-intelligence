# 架构

> 翻译：2026-11-08，来源 docs/en/ARCHITECTURE.md。英文版为准。

> 2026-11-08 重写。描述默认的 Phase 3 运行时（文本优先：SQLite FTS5/BM25 +
> PropertyGraph）。Vector/LanceDB、embedding、reranker 和 LSP rename 属于可选层，
> 文中会明确标注。
> 数字位于 [FACTS.md](../FACTS.md)；本页解释结构，不解释计数。
> 客户端配置：[CLIENTS.md](CLIENTS.md)。配置说明：[CONFIGURATION.md](CONFIGURATION.md)。
> 提交门禁：[HOOKS_AND_GATES.md](HOOKS_AND_GATES.md)。

## 1. 分层

```text
┌──────────────────────────────────────────────────────────────┐
│ Client: MCP host — OpenCode (primary) or Zed (stdio, JSON-RPC)│
├──────────────────────────────────────────────────────────────┤
│ Tool layer        src/mcp/tools/*                             │
│   investigate · search_code · grep_code · get_symbol_info     │
│   impact_analysis · graph_query · codebase hub · lifecycle    │
│   every tool is wrapped by @error_boundary (timeout + envelope)│
├──────────────────────────────────────────────────────────────┤
│ Intelligence      src/core/intelligence/*                     │
│   project memory · incidents · health · jobs · telemetry      │
├──────────────────────────────────────────────────────────────┤
│ Core services     src/core/search, src/core/indexing, graph   │
│   Searcher · SQLiteChunkStore · Indexer · PropertyGraph       │
├──────────────────────────────────────────────────────────────┤
│ Providers         src/providers/*   (optional)                │
│   llama.cpp/ONNX/LM Studio/Ollama embedders · BGE-M3 reranker │
└──────────────────────────────────────────────────────────────┘
```

以下规则由架构 linter（`scripts/architecture_linter.py`）和层边界门禁强制执行：

- `core` 永不导入 `mcp`；工具依赖 core，而不是反过来。
- `RuntimeCoordinator` 决定就绪状态；工具不得自行二次判断。
- 每个工具是一个文件（或一个类），只承担一项职责；`codebase` 中枢按 `action`
  分发，而不是继续增加顶层工具。

## 2. 组装与生命周期

`src/main.py` → `create_mcp_server()`（`src/mcp/server_factory.py`）：

1. 构建 DI 容器（`src/core/di_container.py`），数据路径来自
   `src/core/artifact_paths.py`。
2. 注册 core 工具，然后注册 intel、inline diagnostics 和 dev 工具
   （`register_all_tools`）。
3. 应用**工具 profile**（`_apply_tool_profile`）：完整注册表会被构建（全部 69 个
   工具），随后所有不在 `CORE_PROFILE` 中的工具都从客户端接口中移除。注册本身
   不依赖 profile —— 在 2026-11-08 之前这句话是错的，当时一个硬编码的默认
   allowlist 仍会把注册裁到 56 个名称，而且 `_apply_tool_profile` 会在 dev 工具
   注册之前运行。该不变量现在由 `tests/test_tool_profile.py`
   （`test_core_profile_registers_full_registry_then_hides`）固定。
4. 启动 stdio transport；provider 和矛盾台账（contradiction ledger）在后台启动，
   因此握手永远不会被阻塞。

单次请求的生命周期：`require_ready_project()` → 工具主体 → `error_boundary`
包装结果（超时、遥测、结构化错误）。搜索类工具在查询前还会触发受节流限制的
新鲜度检查（hot-reload）。

## 3. 存储

| 内容 | 位置 | 格式 |
|---|---|---|
| 文本 chunk + FTS5 索引 | `<project>/.mscodebase/chunks.db` | SQLite |
| 图（符号、边、meta） | `<data_root>/projects/<hash>/graph.db` | SQLite (PropertyGraph) |
| 项目记忆、incident、job | `<data_root>/projects/<hash>/intelligence/` | JSON |
| 提交记忆 | `<data_root>/projects/<hash>/commit_memory/` | JSON |
| 日志、遥测 | `<data_root>/logs/`、`<data_root>/projects/<hash>/telemetry/` | 文件 |
| 向量表（可选） | `<data_root>/projects/<hash>/lancedb_v2/` | LanceDB |

`<data_root>` 取自 `MSCODEBASE_DATA_DIR`，否则为 `%LOCALAPPDATA%/mscodebase`
（Windows）或 `~/.cache/mscodebase`。项目内部只存在 `chunks.db` 和 `.mscodebase/`，
两者都已被 gitignore。

## 4. 索引

两个入口，一条流水线：

- **全量文本索引** —— `scripts/reindex_text_only.py`：遍历（`FileGuard` 排除项）、
  用 Tree-sitter 解析、把 chunk 写入 SQLite、把符号/边写入图。不做 embedding。
- **增量索引** —— `FreshnessChecker` 将磁盘文件的 `(mtime, size, hash)` 与 SQLite
  存储比对，重建变更/新增文件并删除已删除项。搜索后按节流运行（默认 30 s），
  启动时若存储为空则通过 auto-index 任务运行。

`experiments/**` 被 `SystemArtifacts`（`src/core/indexing/file_guard.py`）排除在
索引之外：冻结面板不得泄漏进检索结果。

## 5. 搜索栈

`Searcher`（`src/core/search/engine.py`）负责检索：

- **Phase 3 路径** —— SQLite FTS5 候选（limit × 4，有上限），对 top 池可选的
  按需 rerank；不访问 LanceDB。
- **标识符短路** —— 形如标识符的查询直接进入图阶段，取得精确位置。
- **文档路由** —— 对 `docs/**` 额外执行一次 FTS 查询；若最佳 docs 分数超过最佳
  code 分数 `MSCODEBASE_DOCS_MARGIN`（4.0），则文档胜出。
- **legacy dense 路径** —— 仅在 `MSCODEBASE_DENSE_OFF=false` 且 provider 可用时。

细节与各阶段预算见 [SEARCH_PIPELINE.md](SEARCH_PIPELINE.md)。

## 6. 工具层

**已注册 69 个**工具（36 core + 16 intel + 13 inline + 4 dev）；默认的 `core`
profile 暴露 **17** 个。`execute_script` 是第 70 个可选工具，需
`MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`。

可见集合按意图各一项：`investigate`、`search_code`、`grep_code`、
`get_symbol_info`、`impact_analysis`、`graph_query`、`codebase`、
`read_live_file`、`notify_change`、`get_health_report`、
`intel_get_project_memory`、`predict_change`、`tool_help`，外加四个 dev 工具。
`MSCODEBASE_MCP_PROFILE=full` 暴露全部；`MSCODEBASE_MCP_TOOLS` 仍是显式 allowlist。

`investigate` 是两轮扇出：第 1 轮并行运行 search、symbols 和 grep；第 2 轮针对
第 1 轮的发现运行 impact、callers、tests 和项目记忆。结果按 `(file, line)` 合并，
并携带找到该项的通道集合；超时的通道出现在 `degraded[]` 中。

`codebase(action=…)` 是中枢：`index`（status/progress/health/timeline）、
`git`（log/history/branch），以及写操作（rename/move/safe_delete/
replace/insert），带 preview 与 impact guard。

## 7. 安全与失败行为

- 每个工具都有超时；provider 卡死只会让答案降级，不会冻结服务器。
- 搜索/写工具在索引为空时拒绝执行，而不是返回“没有结果”（空与坏必须看起来不同）。
- 写操作会先预览；破坏性操作需要 impact 确认令牌。
- 子进程以 `Popen(stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL) + communicate`
  启动；当服务器 stdout 就是 JSON-RPC 管道时，`capture_output=True` 会死锁
  （AGENTS.md §5.16）。
- 矛盾台账（启动时运行，缓存 6 h）用代码核对 `AGENT_DIARY.md` 中的 `✅` 声明；
  它自身的失败会被报告，绝不静默忽略。

## 8. 可选层

- **Embedding/reranker：** llama.cpp GGUF、ONNX、LM Studio 或 Ollama；供按需
  rerank 和 legacy dense 路径使用。
- **LSP：** 基于 basedpyright 的 references/definition/diagnostics，带硬性启动
  预算和 30 s 失败缓存。
- **向量存储：** LanceDB，仅在启用 dense 检索时使用。

默认的文本优先路径不需要其中任何一项。
