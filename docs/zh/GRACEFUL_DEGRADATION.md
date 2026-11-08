# 优雅降级

[English](../en/GRACEFUL_DEGRADATION.md) · [Русский](../ru/GRACEFUL_DEGRADATION.md) · [中文](GRACEFUL_DEGRADATION.md)

> 翻译：2026-11-08，来源 docs/en/GRACEFUL_DEGRADATION.md。英文版为准。

> 版本 3.5.0。当某个组件缺失时，代码如何行为。本代码库中没有编号的"降级等级"
> 模型——只有下面这些回退。

## 1. 三种结果

| 结果 | 你如何看到它 |
|---|---|
| **完整回答** | 正常结果 |
| **带洞的回答** | 结果加上 `degraded: [...]` 列表（在 `investigate` 中）或一行警告 |
| **失败** | JSON 错误封套：`{"ok": false, "error": {"code", "message", "next_action", "details"}}`。`details` 保留原有字段：`status`（`error`/`warning`/`timeout`）、`detail`、`latency_ms`、`tool`、`recoverable` |

规则：*次要*通道可以静默失败（它不得把回答搞垮）；*主要*能力要大声失败，并给出
调用方可据以分支的状态。

## 2. 检索阶梯（默认的文本优先配置）

`MSCODEBASE_DENSE_OFF=true` 与 `MSCODEBASE_SQLITE_CHUNKS=true` 是默认值：

```
SQLite FTS5 / BM25 → optional graph bucket → on-demand cosine rerank (top-N)
                   → exact-name boost → dedupe
```

| 缺失的组件 | 行为 | 位置 |
|---|---|---|
| Embedder | 候选仍来自 FTS5 + 图；按需 rerank 抛异常、被捕获，融合结果池原样返回 | `engine.py::_apply_ondemand_reranker_async` |
| Reranker（BGE / 多 provider） | 按 RRF 顺序原样返回；`is_available == False` 在任何调用之前就短路 | `engine.py::_apply_multi_reranker_async` |
| 图数据库 | 图桶不产出任何内容；文本结果不受影响 | `_sqlite_hybrid_search_async`（图阶段被 try/except 包裹） |
| SQLite 块存储（初始化失败） | 记录警告，`_chunk_store = None`；跳过 FTS5 层，调用落到图 / BM25（以及启用时的稠密层） | `Searcher.__init__`、`hybrid_search_async` |
| 正在重建索引 | 同步路径**立即返回空结果**，而不是在数据库锁上阻塞；异步路径抛出"几秒后重试" | `_reindex_fast_fail()`、`hybrid_search_async` |

重建索引期间的空回答是有意为之，但看起来像"无匹配"，所以在断定查询很差之前先检查
`codebase(action="index", path="progress")`。

## 3. 遗留的稠密路径（`dense_off=false`）

`fast` 会对查询做 embedding；若 embedder 抛错，`query_vector` 变为 `None`，调用
继续走 FTS5 + 图（E24：未加守卫的 embed 过去会 10/10 失败，而 `quality` 则降级）。
`quality` 增加了 reranker 阶段，在没有 provider 应答时跳过。稠密检索是增强，永远
不是前提条件。

## 4. `investigate` —— 按通道降级

两轮共七条通道，按通道超时（12 s，grep 为 15 s；整个工具 30 s）。第一轮：`search`、
`symbols`、`grep`。第二轮：`impact`、`graph`、`tests`、`memory`。超时追加
`name:timeout`；异常追加 `name:<ExceptionType>`。合并后的回答仍会返回，并按
`(channel count, rank)` 排序，但你总能看到哪些通道是沉默的：

```
🧭 investigate: `who calls ack_impact`
   identifiers: ack_impact
   results: 6 | degraded: tests:TimeoutError
```

### 证据，而不是自信

`grep` 是唯一能说“这个标识符出现在这个文件里”的通道。其它通道永远返回邻近结果，
因此标题里会给出每个标识符的精确命中数——当主体本身在代码中不存在时也会明说：

```
🧭 investigate: `where is build_call_graph defined`
   identifiers: build_call_graph, defined
   results: 8
   exact: build_call_graph=30, defined=20
```

```
🧭 investigate: `where is missing_widget implemented`
   identifiers: missing_widget, implemented
   results: 8
   ⚠️ exact: missing_widget=0, implemented=5 — the first identifier does not occur
   in the indexed code; the results below are neighbours, not matches.
```

必须始终成立的四条规则（守卫：`tests/test_no_silent_success.py`）：

1. 空总体是拒绝（`exit 2`，原因写入 stderr），而不是一行“0 %”；
2. 失败的通道会出现在 `degraded` 里，它的沉默永远不会变成“0 次命中”——沉默不是测量；
3. `latency_ms` 来自时钟：60 ms 的调用至少报 50，两种不同开销给出两个不同数字；
4. 两个非精确通道指向同一位置只是相关性，不是证明：`exact:` 行不会因“一致”而改变。

当第一个标识符在代码中**完全不存在**、且图也不知道该符号时，回答是拒绝，而不是邻居列表：

```
🧭 investigate: `where is missing_widget defined`
   identifiers: missing_widget
   results: 0
   exact: missing_widget=0
   ℹ️ Ничего не найдено. Запрос не подтверждён ни одним каналом.
   Neighbours withheld: 8. Pass include_neighbours=true to see them anyway.
```

`include_neighbours=true` 会把它们返回。两种情况不会拒绝：未完成的通道（它的沉默是
“未知”，不是“没有”），以及图里已知的符号（名字是真实的，即使精确通道漏掉了它）。

## 5. 工具级失败与超时

`@error_boundary(name, timeout_ms=...)` 是唯一的包装器：

- 超时是真正的 `asyncio.wait_for`——挂起的协程会被取消；
- **只有超时才重试**（间隔 1 s）。`ToolError` 是确定性的，立即返回；意外异常会带
  回溯记录到日志，并作为 `INTERNAL_ERROR` 返回，消息经过净化（绝对路径被替换，
  上限 200 字符）；
- 预算：`write` 与 `investigate` 为 30 s，`get_health_report` 为 45 s，
  `dual_arm_health_check` 为 300 s；
- 每次调用都为 `intel_tool_health` / `get_tool_metrics_summary` 记录，包括失败，
  因此总是失败的通道会以统计数字的形式可见。

### 错误契约（破坏性变更，2026-11-08）

任何失败都返回 JSON 文本，而不是 Markdown 块：

```json
{"ok": false,
 "error": {"code": "INDEX_NOT_READY",
           "message": "Index is not ready",
           "next_action": "Index is empty or building. Call intel_trigger_reindex(mode='incremental') …",
           "details": {"status": "warning", "tool": "search_code",
                       "detail": "Run index_project_dir() to initialize",
                       "latency_ms": 12, "recoverable": true}}}
```

`code` 取自 `VALIDATION_FAILED`、`NOT_FOUND`、`AUTH_REQUIRED`、`TIMEOUT`、
`RATE_LIMIT`、`INDEX_NOT_READY`、`REINDEX_IN_PROGRESS`、`DEPENDENCY_DOWN`、
`CONFLICT`、`INTERNAL_ERROR`（`src/core/error_envelope.py`）。按 `code` 分支；
读取 `next_action`，不要自创重试策略。带错误 `status`（`error`、`warning`、
`denied`、`too_large`、`not_installed`）的字典结果会转换成同一封套——它不再可能
显示成成功的「✅ Completed」。

这类 payload 的 `isError` 为 `true`：`src/mcp/error_results.py` 在
`create_mcp_server` 中一次性包装底层 CallTool 处理器，当结果文本正是封套时置位该
标志，文本本身不变——`json.loads(content[0].text)` 仍然可用。若未来 `mcp` 版本
改变这层私有接口，`tests/test_mcp_is_error.py` 会失败，标志降级为 `false` 并写日志，
而不会破坏 payload。

Inline 与 dev 工具（`generate_docs`、`bump_version`、`auto_update_docs`、
`install_git_hooks`、`refresh_db_connection`）也返回同一封套，取代手写的
`Error: …` / `❌ …` 字符串，因此同样带该标志。

## 6. 索引

- **纯文本（默认）** —— `index_project()` 路由到
  `_index_text_only_project()`：解析、切块、写入 SQLite、更新图。不接触任何
  embedder。
- **稠密（`dense_off=false`）** —— embedder 是必需的。`is_ready()` 为假时以
  "Embedder not ready. Indexing aborted." 中止；provider 返回的向量数量不对时
  中止整批，而不是写一个半成品索引。

缺失某个 Tree-sitter 语法只降级一种语言，而不是整次运行：`parser.py` 在自己的
`try/except ImportError` 中导入每个语法。

## 7. Providers

`RemoteEmbedder.mode` ∈ `onnx`、`onnx_server`、`lm_studio`、`ollama`、
`llama_cpp`、`fallback`、`unknown`。启动时若无任何东西应答则设为 `fallback`
（"safe default — don't pretend ONNX works"）；一个扫描器以退避重试（基准 30 s，
上限 300 s）。llama.cpp embed 做 3 次批量重试（带退避），然后是逐块重试，之后抛错
——它不会捏造零向量。Reranker（LM Studio、Ollama、llama.cpp、HTTP ONNX）在初始化
时探测；全部不可达意味着 `is_available == False` 与 RRF 顺序。可选的 ONNX server
是 `127.0.0.1:1235` 上的子进程（`DISABLE_ONNX_FALLBACK=true` 会移除它）。

## 8. LSP 与网络

`lsp_*` 工具需要 `PATH` 中有 `basedpyright-langserver`。没有它时每个调用都返回
"LSP недоступен (basedpyright не найден). …" 并指向符号索引；启动失败会带 TTL 缓存
并重新探测，因此之后安装 basedpyright 不需要永久重启。LSP→MCP 桥本身已于
2026-07-20 移除，没有工具依赖它。

默认路径中没有任何东西使用网络。例外是可选的：`install.py` 中的下载（总会提示）与
可选的 `tree-sitter-language-pack`，其额外解析器在首次使用时下载。

## 9. 哪些**不**降级

这里的"优雅"会意味着"静默地错误"：

| 情形 | 响应 |
|---|---|
| 空索引（`total_chunks == 0`） | `IndexNotReadyError` → `🟡 Warning: Index is not ready`，不是"无结果" |
| 未确认就写入承重文件 | 来自 `modification_guard` 的 `denied`，附带影响令牌 |
| 写入时符号有歧义 | `denied`、候选列表，不静默挑选 |
| 可信根之外的破坏性操作 | 按 `trust_boundary` 策略拒绝 |
| 未启用时的 `execute_script` | 工具根本未被注册 |
| `execute_script` 中的沙箱违规 | 执行前的 `SandboxViolation` |

## 10. 如何观察降级

1. `get_health_report()` —— 索引、provider、资源、内存警告。
2. `codebase(action="index", path="status")` —— `total_chunks`、文件数。
3. `get_runtime_counters()` —— `verdict_blocked_*` 原因；`blocked > 5%` 的检查数
   是文档中给出的"该看看架构了"的信号。
4. `intel_tool_health()`（完整 profile）—— 成功率、P50/P95、重复率。
5. `investigate` 的 `degraded[]` —— 每次调用的通道失败。
6. `get_logs()` —— 近期 warnings/errors；载荷留在日志里，不进入响应。

---

**Verified against:** `src/core/search/engine.py` (tier order, rerank fallbacks,
`_reindex_fast_fail`), `src/core/error_handler.py` (`error_boundary`, retry
policy, `_format_error_response`, `IndexNotReadyError`, message sanitising),
`src/mcp/tools/base.py` (`require_index` → `IndexNotReadyError`),
`src/mcp/tools/investigate_tool.py` (7 channels, timeouts, `degraded`),
`src/core/indexing/indexer.py` (`index_project` → text-only),
`src/core/indexing/index_project_runner.py` (abort on embedder failure),
`src/core/indexing/index_pipeline.py`, `src/core/indexing/parser.py`,
`src/providers/embedder/remote_embedder.py`,
`src/providers/reranker/multi_provider.py`,
`src/providers/reranker/llama_runner.py`, `src/mcp/tools/lsp_tools.py`,
`src/core/lsp_client.py`, `src/mcp/tools/system_tools.py`,
`src/core/runtime_coordinator.py`, `src/config/settings.py`,
`src/core/error_envelope.py`.
