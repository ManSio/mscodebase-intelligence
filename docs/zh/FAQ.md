# 常见问题 — MSCodeBase Intelligence

[English](../en/FAQ.md) · [Русский](../ru/FAQ.md) · [中文](FAQ.md)

> 翻译：2026-11-08，来源 docs/en/FAQ.md。英文版为准。

以下答案读自本仓库的代码（版本 3.5.0），而不是更早的博客文章。可引用的数字
位于 `docs/FACTS.md`。

---

## 搜索需要 embedding 吗？

不需要，默认情况下不用。默认运行时是 **文本优先**：

| 设置项 | 默认值 | 作用 |
|---|---|---|
| `MSCODEBASE_DENSE_OFF` | `true` | 没有稠密层：查询永远不会被 embedding 用于向量检索 |
| `MSCODEBASE_SQLITE_CHUNKS` | `true` | 块以文本形式存放在 SQLite FTS5 中，不存储向量 |
| `MSCODEBASE_ONDEMAND_RERANK` | `false` | 启用时在查询时对 top-N 候选实时做 embedding，**前提是**有 embedder 应答；单次调用：`investigate(rerank=true)` |

候选来自 SQLite FTS5（BM25 排序）加上 PropertyGraph。索引过程同样跳过
embedding：当 `dense_off` 为 true 时，`Indexer.index_project()` 会路由到
`_index_text_only_project()`。

如果没有可达的 embedder，按需 rerank 会抛出异常，被捕获后返回 RRF 顺序的融合
结果池（`engine.py::_apply_ondemand_reranker_async`，"Fallback к RRF-порядку"）。
搜索仍然可用——只是不再按余弦相似度重排。

## 为什么结果看起来很"词法"？

因为它们确实就是词法的。在 `dense_off=true` 下，候选列表是 FTS5 上的 BM25 加上
图命中；排序由词项驱动，所以精确的标识符胜过同义改写。有两个升级项，但默认关闭，
必须先在你自己的查询上做实测：`MSCODEBASE_CODE_BM25=true`（标识符切分、字段加权）
与 `MSCODEBASE_RERANKER_*` 系列 provider。各模式的质量数字在 `docs/FACTS.md` §5
——那是快照，不是保证。

## 数据存放在哪里？

两处位置，刻意分开：

| 内容 | 路径 |
|---|---|
| 块文本 + FTS5 索引 | `<project>/.mscodebase/chunks.db`（可用 `MSCODEBASE_CHUNKS_DB` 覆盖） |
| 图、项目记忆、遥测、LanceDB（仅在用到时） | `<data_root>/projects/<hash8>/` |

`<data_root>` 在 Windows 上是 `%LOCALAPPDATA%\mscodebase`，在 macOS 上是
`~/Library/Caches/mscodebase`，在 Linux 上是 `~/.cache/mscodebase`。可用
`MSCODEBASE_DATA_DIR` 覆盖（`BASE_INDEX_DIR` 是旧别名）；一个项目目录中包含
`graph.db`、`intelligence/project_memory.json`、`metrics/job_history.json`、
`commit_memory/`、`telemetry/YYYY-MM-DD.json`。

产物被刻意移出被索引的项目：索引别人的仓库时，不得往它里面写东西。`chunks.db`
是例外，可通过 `MSCODEBASE_CHUNKS_DB` 选择退出。

## 怎么看到其它工具？

注册与可见性是两回事。**69** 个工具始终注册（36 core + 16 intel + 13 inline +
4 dev）。对外呈现的表面按 profile 过滤：

```bash
# default: 17 tools, one entry per intent
MSCODEBASE_MCP_PROFILE=core

# everything
MSCODEBASE_MCP_PROFILE=full
```

改动之后要重启宿主——过滤器只在 `create_mcp_server()` 期间运行一次。
`tool_help()` 会列出当前 profile、可见工具与隐藏工具；它在 core profile 下始终可见。
`MSCODEBASE_MCP_TOOLS=a,b,c` 是显式允许列表，会覆盖 profile。`execute_script`
是独立的第 70 个可选工具，由 `MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true` 打开。

## 如何重置索引？

完整 profile：`intel_reset_index()`——关闭数据库句柄、释放 PID 锁、删除索引目录
与遗留的项目内目录，然后启动后台重建索引（用 `intel_get_job_status(job_id)` 轮询）。

core profile（没有 `intel_reset_index`）：删除产物并强制重建。

```powershell
Remove-Item .mscodebase\chunks.db* -Force
Remove-Item "$env:LOCALAPPDATA\mscodebase\projects\<hash8>" -Recurse -Force
```

然后用 `codebase(action="index", path="project_dir", project_root=".")` 重建索引
（完整 profile 用 `intel_trigger_reindex()`），或在 shell 中执行：
`python scripts/reindex_text_only.py --project .`（文本 + 图，无 embedding）；
`python scripts/rebuild_graph.py` 只重建图。

## "什么都没找到" 与 "索引为空"

这是两种不同的状态，工具的回答也不一样。

- **索引为空** —— `codebase(action="index", path="status")` 报告
  `total_chunks = 0`。这不是"无匹配"；而是什么都还没被索引。检查就绪状态的工具
  会抛出 `IndexNotReadyError`，渲染为 `🟡 Warning: Index is not ready`，详情为
  `Index is empty for project: … Run index_project_dir() first.`
- **正在重建索引** —— 同步搜索路径（`hybrid_search` / `search_with_mode`）立即
  返回空结果，而不是在数据库锁上等待；异步路径会抛出
  "⏳ Индекс перестраивается … повторите поисковый запрос через несколько секунд"。
- **确实没有匹配** —— `total_chunks > 0`，只是查询没有词法命中。改用源码中出现的
  标识符重述，或改成 `docs/` 意图的查询；静态检索不是同义改写引擎。

`investigate` 展示同样的区分：只有当七条通道全部返回空时，它才打印
"Ничего не найдено. Запрос не подтверждён ни одним каналом"；如果某条通道超时，
则改为追加 `degraded: ...`。

## 没有 GPU 或没有网络能运行吗？

能。默认路径中没有任何东西需要 GPU、云 API 或互联网：FTS5、AST 图与 tree-sitter
解析都在本地。唯一的网络用途是下载可选模型（通过 `install.py` 获取 GGUF/ONNX）
以及可选的 `tree-sitter-language-pack`，其解析器在首次使用时抓取
（`MSCODEBASE_LANGUAGE_PACK=true`）。关掉该开关后，所有语法都来自固定版本的
wheel，不会发生任何下载。

可选加速器，全部默认关闭：LM Studio（`127.0.0.1:1234`）、Ollama
（`127.0.0.1:11434`）、llama.cpp（`127.0.0.1:8080` embedder / `8081` reranker）、
ONNX server（`127.0.0.1:1235`）。参见 `LM_STUDIO_SETUP.md` 与 `INSTALL_MODELS.md`。

## 宿主、日志，以及修改服务端之后

**OpenCode 是主要宿主**：它启动
`…\Zed\extensions\mscodebase-intelligence\venv\Scripts\mscodebase-mcp.exe -u -m src.main`，
并把 `PYTHONPATH` 指向该扩展目录。Zed 扩展仍受支持（`extension.toml`，
`capabilities = ["context_servers"]`）。两者运行的都是被复制过去的代码，因此修改
`src/` 之后要执行 `python install.py --sync-only` 并重启宿主——只重载不够，进程仍
持有旧模块。

日志：`<data_root>/logs/`（崩溃 + 轮转）、`get_logs()`（本项目近期的
warnings/errors）、`debug_runtime_passport()`（完整 profile：RUN_ID、BUILD_ID、PID、
uptime、解析出的项目——用它判断是否真的重启过）。

回答变慢或某条通道总是失败：先看 `get_health_report()`，再看
`codebase(action="index", path="status")`，然后看 `intel_get_runtime_status()`
（完整 profile）。单条通道变慢只会让 `investigate` 降级，而不是失败；哪些降级、
哪些失败见 `GRACEFUL_DEGRADATION.md`。

另见 `INSTALL.md`、`ARCHITECTURE.md`、`SEARCH_PIPELINE.md`、`TELEMETRY.md`，
以及 `docs/FACTS.md`——所有可引用数字都在那里。

**Verified against:** `pyproject.toml`, `src/config/settings.py`,
`src/core/search/engine.py`, `src/core/indexing/indexer.py`,
`src/core/indexing/chunk_store.py`, `src/core/artifact_paths.py`,
`src/core/intelligence/tools_reg.py`, `src/core/error_handler.py`,
`src/mcp/server_tools.py`, `src/mcp/tools/investigate_tool.py`,
`src/mcp/tools/codebase_tool.py`, `install.py`, `extension.toml`,
`scripts/reindex_text_only.py`, `%USERPROFILE%\.config\opencode\opencode.jsonc`.
