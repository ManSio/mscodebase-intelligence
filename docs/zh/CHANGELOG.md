<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](../en/CHANGELOG.md) • [🇷🇺 Русский](../ru/CHANGELOG.md) • [🇨🇳 中文](CHANGELOG.md)

# 更新日志

本项目所有值得注意的变更都会记录在此文件中。

## [3.2.0] — 2026-07-11 — Graph-Native Engine (PropertyGraph + Cypher)

### 新增
- 🕸️ **PropertyGraph**: 基于 SQLite 的持久化知识图谱 (WAL + mmap)。15 种节点类型，**28 种边类型** (+`ASSIGNED_FROM`)。
- 🔍 **Cypher Query Engine**: `query_graph` MCP 工具 — `MATCH (f:Function)-[:CALLS]->(g)` 语法。
- 🚦 **HTTP Route Extraction**: Flask/FastAPI/Django/Express/Next.js 路由自动检测 → Route 节点。
- 📊 **Multi-Signal Scorer**: 4 个额外排名信号 (api_signature, graph_diffusion, module_proximity, cochange_boost)。
- 💀 **Dead Code Detection**: 检测没有入站 CALLS 边的函数。
- 🔄 **PURE mode**: SymbolIndexAdapter 不再在内存中复制数据。
- 🔗 **Data Flow Tracking**: `ASSIGNED_FROM` 边类型 — 函数内变量赋值追踪。`CodeParser.extract_assignments()` 遍历 Tree-sitter AST (支持嵌套函数的 scope stack)，检测 `x = y` / `x += y` 模式。创建 `Variable` 节点 + `ASSIGNED_FROM` 边。[基准测试: 3,235 条边, 66.6/KLOC, 91.8% 的 MSCodeBase 文件 — 覆盖度是 stdlib `ast` 的 5.4 倍.]

### 变更
- 56 → 57 个 MCP 工具 (+ `query_graph`)
- 24 → 29 个 `src/core/` 文件
- 全部 479 个测试通过，无需修改

---

## [3.1.0] — 2026-07-11 — 基于 CodeGraph 的改进

### 新增
- 📊 **自适应搜索预算**: `search_code` 根据项目规模自动调整 limit (<500 文件→4, <5K→6, <15K→8, ≥15K→10)。显式指定的 `limit` 参数仍然有效。
- 🕐 **过期警告**: 当上次索引超过1小时前时，显示 "Index may be stale" 警告。一次轻量级 LanceDB 查询，无需磁盘扫描。
- 🧩 **搜索结果中的图上下文**: `_expand_graph_context` 现在对所有搜索模式运行（之前仅 `deep`）。每个结果都显示谁调用它 — 内联显示，无需额外工具调用。
- 🔇 **DEFAULT_TOOLS 过滤器**: 默认仅显示 12 个核心工具。其余 44 个仍在代码中，通过 `MSCODEBASE_MCP_TOOLS` 环境变量重新启用。`MSCODEBASE_MCP_TOOLS=""` 显示全部 56 个。
- 🏷️ **ToolAnnotations** (`readOnlyHint`): 所有只读工具现在带有 `readOnlyHint: true` — Cursor Ask 模式需要此标志。
- 📁 **统一扩展名管理**: 新的 `src/core/extensions.py` 取代了 3 个不同的 `SUPPORTED_EXTENSIONS` 列表。三个列表的并集 + 按用途拆分。
- 🛡️ **Zed SQLite 模式保护**: 启动时验证 `scoped_kv_store` 表是否存在。日志中显示警告，不会崩溃。
- 📋 **MCP 协议版本日志**: 启动时记录协议版本，用于跨版本故障排除。
- 🔧 **LSP 超时可配置**: `LSP_REQUEST_TIMEOUT` 和 `LSP_START_TIMEOUT` 移至 `.env.example`。`get_event_loop()` → `get_running_loop()`。
- 📈 **BENCHMARK.md**: 真实基准测试 — 289ms 快速模式, 8-18 倍 token 节省, 各模式的延迟分布。

### 变更
- `search_code`: 图上下文扩展现在适用于所有模式（之前仅 deep）
- 工具可见性: 默认 12/56 个工具（之前全部 56 个）
- LSP 优先级: basedpyright > pyright 在 `_find_server()` 中
- 超时: 健康报告的 git 检查从 30 秒减少到 15 秒

### 修复
- DEFAULT_TOOLS 过滤器中的 `_show_all`: `MSCODEBASE_MCP_TOOLS=""` 现在正确显示所有工具
- LspClient 中废弃的 `asyncio.get_event_loop()` → `get_running_loop()`

---

## [3.0.0] — 2026-07-11 — Write Tools + LSP 客户端 + 元数据补丁

### 新增
- ✏️ **6 个写入工具**: `rename_symbol`, `move_symbol`, `safe_delete`, `replace_symbol`, `insert_before_symbol`, `insert_after_symbol` — 全部支持预览/应用 + `@modification_guard` 装饰器 (PageRank + 影响范围 + ack TTL)
- 🧠 **LspClient**: 轻量级 pyright LSP 客户端 (JSON-RPC 2.0 over stdio, 懒启动, 自动重启, 优雅降级)
- ⚡ **P0 元数据补丁**: `move_chunks_metadata` — 无需重新嵌入即可更新 LanceDB 中的 file_path (30-80ms vs 2000-5000ms, 0MB RAM vs 700MB)
- 🛡 **Modification Guard**: `@modification_guard(pagerank_min, blast_min, ack_ttl)` — 防止在未明确确认的情况下写入关键文件
- 🔄 **SymbolIndex 扩展**: `find_all_references()`, `rename_symbol()`, `has_symbol()`, `remap_file()`
- ⚡ **BM25 快速失效**: `_reset_bm25()` — 丢弃缓存而非完全重建

### 修复
- `intelligence_layer.py` — `_resolve_symbol_count` 在列 0 处吞没了所有类方法 (Intel 工具不可见)。已移至类定义之前
- `intel_get_runtime_status`, `intel_log_incident` 及所有 Intel 工具现在正常工作 (ProjectIntelligenceLayer 上的 11 个方法)

---

## [2.7.1] — 2026-07-11 — SQLite缓存，索引状态，docs同步

### 新增
- 🔧 Windows Insider（build >= 26000）的CRT API Set修补器 — 修补PE导入api-ms-win-crt → ucrtbase
- 🖥️ Vulkan GPU支持 — 自动检测 + `LLAMA_BACKEND=vulkan` + `-ngl 99`
- 🔄 `verify_index_freshness()` — 检查SHA256哈希（2-5秒，替代完整重新索引的5分钟）
- 💾 SQLite连接缓存 — `_get_sqlite_connection()` 带TTL 2秒（替代每次调用2个新连接）
- 📝 `../../docs/KNOWN_ISSUES.md` — P0-P3问题和技术债务的统一注册表

### 修复
- `server.py:329-331` — 在 `scoped_kv_store` 中添加SQL ORDER BY（多窗口竞争）
- `indexer.py:get_status()` — `_cached_unique_files` 回退：如果缓存为空但块存在 — 扫描LanceDB
- `ui_formatter.py:193` — `symbols` 从 `total_files` 而非 `symbol_index_count` 读取
- `intelligence_layer.py` — 在index_telemetry中添加 `symbol_index_count`
- `llama_runner.py` — `-ngl` 三元表达式修复：`else "-ngl","0"` → `else "0"`
- `llama_runner.py` — GGUF_MODELS中'bge-m3'键重复（恢复'qwen3-embedding'）
- `health_report.py` — 只读检查（不再从索引中删除孤立项）
- `install.py` — `llama_msvc`、`llama_vulkan`、`models` 添加到跳过列表
- SEARCH_PIPELINE.md中的RRF伪代码 — 修复 `enumerate(bm25 + dense)` 为分别枚举

### 文档
- 同步28个文件（12个en + 6个ru + 9个zh + 1个代码）
- AI_INSTALLATION_PROMPT.md — 根据实际工作流重写（install.py → 测试MCP → 重新加载）
- README.md（en/ru/zh）— 清理虚构内容：43→50个工具，LM Studio→llama.cpp为主要
- CHANGELOG.md — 修复指向LSP_WONTFIX.md的损坏链接
- HANDFOFF.md — 34→33个核心工具

---

## [2.7.0] — 2026-07-09
### 新增
- 🦙 llama.cpp作为主要提供者（通过install.py自动安装）
- LlamaRunner — llama-server.exe的生命周期管理器（下载、启动、停止）
- GGUF模型：bge-m3 Q4_K_M（417 MB）+ bge-reranker-v2-m3 Q4_K_M（418 MB）
- 平台检测：Windows/macOS/Linux，x64/ARM64
- ../../docs/research/2026-07-09-provider-benchmark.md — 完整基准测试

### 变更
- 安装程序：10→12个步骤（+llama.cpp，+GGUF模型）
- patch_zed_settings：保留 // 注释，no-op保护
- 提供者优先级：LM Studio → llama.cpp → ONNX server → local ONNX
- MCP：227 MB RAM（原为1200 MB）— 减少5.3倍
- ONNX server：Tokenizer.from_file() 替代 AutoTokenizer — 不再卡死

### 修复
- AutoTokenizer.from_pretrained() 在Windows上卡死（HTTP请求huggingface.co）
- patch_zed_settings 删除了 // 注释 → 恢复按钮
- _detect_model_dir() 创建544 MB的InferenceSession仅用于读取维度
- 所有HTTP客户端：httpx.Limits(keepalive_expiry=30.0) 适配Zed 1.10.0

---

## [v2.5.3] — 2026-07-07 — mode=ask：通过phi-4进行RAG生成回答

### 🚀 mode=ask
- **`src/core/searcher.py`**: 新方法 `Searcher.ask_async()` — 混合搜索 →
  上下文 → phi-4（chat completion）→ 带引用的结构化回答。
- **`src/mcp/tools/search_tools.py`**: 新增 `mode="ask"` 模式带保护：
  在 `light` 配置文件中 — 自动回退到 `quality` 并给出警告。
- **`src/core/config.py`**: `ASK_TIMEOUT`（60秒）、`ASK_MODEL`（phi-4-mini-instruct）。

### 📦 版本
- `extension.toml`: 2.5.2 → 2.5.3
- `src/__init__.py`: 2.5.2 → 2.5.3

---

## [v2.5.2] — 2026-07-07 — phi-4-mini-instruct 验证 + 实时测试

### 🔬 LM Studio
- `phi-4-mini-instruct Q4_K_M` 通过 `/v1/chat/completions` 测试：
  成功响应（75个token，`finish_reason=stop`）。
- 模型按需加载（状态：not-loaded → auto-load）。
- 确认已准备好 `mode=ask`（v2.7.0）。

### 📦 版本
- `extension.toml`: 2.5.1 → 2.5.2
- `src/__init__.py`: 2.5.1 → 2.5.2

---

## [v2.5.1] — 2026-07-07 — 多桶RAG + 上下文检索 + 配置文件

### 🚀 多桶RAG（第一阶段）
- **`src/core/searcher.py`**: 过度获取（`raw_limit = min(limit * factor, MAX)`）、
  按 CODE_EXTENSIONS/DOCS_EXTENSIONS 的桶分布、
  在reranker之前的软加权、截断至limit。
- **`src/core/config.py`**: `CODE_EXTENSIONS`、`DOCS_EXTENSIONS`、
  `MAX_RERANKER_INPUT=30`、`overfetch_factor`、`code_bucket_weight`、
  `docs_bucket_weight` — 全部通过 `.env`。

### 🧩 上下文检索（第二阶段）
- **`src/core/parser.py`**: 新的代码前缀格式：
  `// File: {path} | Context: {class}.{func}`，对于.md：
  `From {path}, section '{heading}':`。需要重新索引。

### ⚖️ 软评分 + intent_hint（第三阶段）
- **`src/mcp/tools/search_tools.py`**: 新参数 `intent_hint`
 （`"auto"` / `"code"` / `"docs"`）。
- **`src/core/searcher.py`**: `_apply_bucket_weights()` — 动态权重：
  code=1.2/docs=0.8 对应 `"code"`、code=0.8/docs=1.2 对应 `"docs"`、
  1.0/1.0 对应 `"auto"`。

### ⚙️ SYSTEM_PROFILE（第四阶段）
- **`src/core/config.py`**: `SYSTEM_PROFILE=light|server` 带验证
  和属性 `is_light_profile`/`is_server_profile`。
  `light` — 同步模式（默认），`server` — 保留。

### 📦 版本
- `extension.toml`: 2.4.4 → 2.5.1
- `src/__init__.py`: 1.0.0 → 2.5.1

---

## [v2.4.7] — 2026-07-05 — LM Studio 连接池 + 预热

### ⚡ 性能
- **`src/core/remote_embedder.py`**: 添加 `httpx.AsyncClient` 带**连接池**
  （5个keepalive连接，60秒过期）— 消除每次嵌入请求的TCP/TLS开销。
- **`src/core/remote_embedder.py`**: 新方法 `embed_batch_async()` — 通过统一HTTP客户端
  进行异步嵌入。`searcher.py` 自动使用它。
- **`src/mcp/server.py`**: 服务器启动时的 `_warmup_embedder()` — 用测试请求预热bge-m3，
  消除首次 search_code 约3秒的冷启动延迟。

---

## [v2.4.6] — 2026-07-05 — UI格式化器 + 死锁修复 + 日志集中化

### 🐛 死锁修复
- **`src/core/rate_limiter.py`**: `DebounceBatch._debounce_wait()` 不再
  在 `threading.Lock` 内部调用 `await` — 移到单独变量
  `should_flush`。`threading.Lock` 不可重入 — 批量 `notify_change` 时100%死锁。
  修复代码质量：删除 `field`，添加 `Any`。

### 🎨 UI格式化器（新模块）
- **`src/utils/ui_formatter.py`**: 8个基本格式化函数：
  `header()`、`table()`、`key_value()`、`code_block()`、`empty_result()`、
  `error_result()`、`ok_result()`、`format_search_code()`、`format_repo_rank()`、
  `format_health_report()`、`format_telemetry()`、`format_eta()`。
- 所有数据放在 `<details>` 折叠面板下，使用Markdown表格替代JSON。

### 🔄 日志集中化
- **`src/core/log_manager.py`**: `get_log_dir()` 现在**始终**指向
  `ext_root/.codebase_indices/logs/`，而非按项目分配。添加
  `_cleanup_stale_project_logs()` — 清理项目中的旧日志。
- 清理导入：删除 `datetime`、`timedelta`、`timezone`、重复 `import os`。

### 🧩 UI格式化器集成
- **`src/mcp/tools/search_tools.py`**: `_format_results()` 迁移到
  `format_search_code()`。输出 — 带#、文件、行、片段、层列的表。
- **`src/mcp/tools/system_tools.py`**: `GetIndexStatusTool.execute()` — 输出
  通过 `header() + key_value() + code_block()`。
- **`src/mcp/tools/analysis_tools.py`**: `GetRepoRankTool.execute()` — 输出
  通过 `format_repo_rank()` 带表格和折叠面板下的原始JSON。

### 🧠 项目记忆
- `known_issues`: Zed 1.9.0 Windows上的LSP WONTFIX（NODE-567a10）
- `incidents`: INC-2CE4, INC-8817

---

### 📄 文档
- **新的调查报告**：[LSP_WONTFIX.md](investigations/LSP_WONTFIX.md)。
  对Zed 1.9.0源码的完整审计（`crates/project/src/lsp_store.rs`、
  `crates/extension/src/extension_manifest.rs`、`crates/settings_content/src/language.rs`）
  包含代码引用和指向原始GitHub的链接。结论：**Zed 1.9.0上的WONTFIX** —
  无法仅通过 `settings.json` 注册自定义LSP，
  需要Rust+WASM封装。

### 🧹 死代码清理
- **`install.py`**: 删除LSP配置生成（`lsp_config`）。不再在 `settings.json`
  中创建LSP部分 — 它不起作用（WONTFIX）。
- **`src/utils/zed_config.py`**: 从 `patch_zed_settings()` 中删除 `lsp.mscodebase-lsp`
  注册块。该函数不再接收LSP配置。
- **`scripts/check_lsp_health.py`**: 新的诊断脚本。检查
  settings.json、进程、桥接文件、SQLite数据库。输出清晰的结论
  和推荐操作。

### 📚 文档
- **`ZED_WINDOWS_QUIRKS.md`**（1.0 → 1.1）：新章节「LSP在Zed 1.9.0上不启动（WONTFIX）」，
  包含真实根因。
- **更新** `AGENT_DIARY.md`：新增15:55条目，包含正确的根因
  和调查报告链接。旧条目15:30标记为DEPRECATED。

### 🧠 项目记忆
- 在 `known_issues` 中添加关于LSP-WONTFIX的节点，包含调查报告链接
  和三种解决方案（MCP、SQLite回退、替换pyright）。

### ℹ️ 这意味着什么
- **MCP仍然是所有代码助手场景的主要传输方式**。
- **Zed 1.9.0 Windows上的编辑器内LSP功能（inlay-hints、code-actions、自动补全）**
  在没有Rust封装的情况下不可行 — 这是设计使然，不是我们的bug。
- **v3.0** 计划走路径A（通过 `impl zed::Extension::language_server_command`
  的Rust+WASM封装）。

---

## [v2.4.4] — 2026-07-05 — 元数据增强：语义指南针 + 扁平树

### 🧭 语义指南针（MCompassRAG风格，src/core/parser.py + src/core/indexer.py）
- 每个块现在包含 `layer`（架构层：core/mcp/utils/tests/...）。
- 根据文件路径自动检测层，无需手动标记。
- 字段 `module_name` — 模块逻辑名称（core.parser、mcp.server）。
- 字段 `is_public` — 公开/私有符号（根据 `_` 前缀）。
- 字段 `symbol_type` — AST节点类型（function_definition、method_definition、...）。

### 🌳 扁平树（SproutRAG风格，src/core/parser.py + src/core/indexer.py）
- `hierarchy_level`: function | method | class | impl | lines | function_part | section。
- `parent_id`: 父元素的确定性md5哈希。
  - 对于方法：哈希 `file_path::ClassName`。
  - 对于函数：哈希 `file_path`（模块）。
  - 无需图数据库的多粒度检索。

### 🗃 LanceDB模式
- 6个新字段：`layer`、`module_name`、`hierarchy_level`、`is_public`、`symbol_type`、`parent_id`。
- 通过 `_migrate_add_metadata_columns()` 自动迁移 — 无需drop_table。
- 旧块获得空值；重新索引后填充。

### 🔧 代码
- `src/core/parser.py`: +`_build_chunk_metadata()` — 4个创建块的点。
- `src/core/indexer.py`: +`_migrate_add_metadata_columns()`，+`chunk_metadatas`。
- 全部103个测试通过，没有中断。

### 🎯 按层过滤搜索（MCompassRAG — 搜索）
- `search_code` 获得参数 `filter_layer`（core/mcp/utils/tests/...）。
- LanceDB `.where()` 带 `prefilter=True` — 在索引级别的过滤，无需加载所有块。
- BM25 按metadata中的layer进行后过滤。
- 在所有模式下工作：fast（仅向量）、quality（混合）、deep。

### 🌳 多粒度检索（SproutRAG — 搜索）
- 新方法 `Searcher.get_chunks_by_parent_id()` — 按parent_id查找所有子块。
- 允许沿层次结构上溯：模块 → 类 → 函数。
- E2E：core过滤器仅返回core，tests过滤器仅返回tests，0交叉。

---

## [v2.4.3] — 2026-07-05 — RuntimeCoordinator + intel_get_project_context

### 🎯 RuntimeCoordinator（新，src/core/runtime_coordinator.py）
- 决定「是否可以执行MCP请求？」的单一决策点。
- 使用Registry（状态）、SystemArtifacts（系统路径）、
  Runtime Passport（就绪状态）。
- `can_execute(path) → ExecutionVerdict(ok, reason, state, detail)`。
- MCPTool中的 `require_ready_project()` 委托给Coordinator。
- 工具名称：`intel_get_project_context`（Intel Layer统一风格）。

### 🧪 代码
- ProjectContext、RuntimeCoordinator、server.py、base.py — 语法正常。
- 架构：Tool → Coordinator → Snapshot，无重复代码。

---

## [v2.4.2] — 2026-07-05 — ProjectContext — 统一项目状态模型

### 🏗 ProjectContext（新，src/core/project_context.py）
- 统一的项目快照对象：state + index + bridge + health + memory + jobs。
- 替代5个不同调用 — 一个 `await ctx.capture()`。
- 所有字段可选：如果组件不可用 → None，不会崩溃。
- `get_project_context` MCP工具 — 一次性返回包含项目完整状况的JSON。
- 不破坏任何东西 — 在现有架构之上的新层。

### 🔧 SystemArtifacts（src/core/system_artifacts.py）
- 识别系统文件的统一模块（4级保护）。
- file_guard.py 迁移到 SystemArtifacts — 所有列表集中在一处。

---

## [v2.4.1] — 2026-07-05 — 扩展Passport + 反馈循环防护 + 两阶段就绪

### 🆔 Passport扩展（BUILD_ID + Bridge/Registry/ProjectState）
- **`src/mcp/server.py`**: 添加 `_BUILD_ID`（git commit哈希）— 即时
  验证代码版本。
- `_log_run_passport()` 现在在启动时记录Bridge状态和Registry状态。
- `debug_runtime_passport` 返回：`build_id`、`project_state`（枚举）、
  `bridge`、`bridge_error`、`registry.paths`、`registry.cached_projects`、
  `registry.cache_hits/misses`。

### 🛡 反馈循环防护（防止索引污染）
- **`src/core/file_guard.py`**: 在 `_load_gitignore()` 中添加显式模式
  排除索引服务文件：
  - `chunk_summaries.json`、`summaries_cache/**` — 块描述
  - `incidents.json`、`project_memory.json`、`commits.json` — 内存元数据
  - `.index_guard.json`、`symbol_index/**` — 索引
- 双层保护：SKIP_DIRS（目录）+ .gitignore（文件）。
- 没有这些排除项，可能出现反馈循环：块描述 → 摘要 →
  索引摘要 → 基于前一个摘要的新摘要。

### ⏱ 两阶段 wait_until_ready
- **`src/mcp/tools/base.py`**: `require_ready_project()` 现在分两阶段：
  1. 快速检查bridge（1秒）— 如果LSP尚未写入project_root，
     立即记录警告，而不是等待5秒。
  2. 完全等待READY（剩余秒数）。

### 🧪 测试
- 所有文件通过 py_compile。
- 索引：1362个块，106个文件，1080个Tree-sitter符号，status=active。

---

## [v2.4.0] — 2026-07-05 — 自索引修复 + 进程Passport + 项目状态机

### 🛡 自索引防护：开发仓库修复
- **`src/mcp/server.py`**: 删除错误的 `_SELF_INDEX_MARKER`
  （`(path / "src/lsp_main.py").exists()`），替换为
  `_reject_self_index_target(p, source=)`。
  - 拒绝：`p == _ext_root` + `is_zed_install_dir(p)`。
  - 不再阻止开发仓库（`D:\Project\MSCodeBase`），如果
    用户将扩展源码作为Zed中的项目打开。
- **`src/mcp/tools/base.py`**: 添加环境变量覆盖 `MSCODEBASE_ALLOW_SELF_INDEX=1`
  用于开发场景。
- **`src/utils/zed_config.py`**: `patch_zed_settings()` 写入
  `MSCODEBASE_ALLOW_SELF_INDEX=1` 到 MCP/LSP 环境。

### 🆔 进程Passport（debug_runtime_passport）
- **`src/mcp/server.py`**: MCP启动时记录「护照」 —
  `RUN_ID`、`PID`、`_ext_root`、`PROJECT_PATH`、`ZED_WORKTREE_ROOT`、
  `MSCODEBASE_ALLOW_SELF_INDEX`、`PYTHONPATH`。
- 注册MCP工具 `debug_runtime_passport` — 返回JSON
  包含RUN_ID、PID、运行时间、源文件、ext_root、环境变量、防护结果。
  一次调用即可确认：「执行我代码的是正确的进程吗？」

### 🏗 项目状态机（无竞争的多窗口）
- **`src/core/project_indexer_registry.py`**:
  - 添加 `enum ProjectState`：`UNINITIALIZED → STARTING → INDEXING → READY → FAILED`。
  - 按项目的 `asyncio.Event` 用于就绪信号通知。
  - `get_indexer()` 在创建时自动将项目转为STARTING，
    然后转为READY/INDEXING。
  - `wait_until_ready(path, timeout=5.0)` — 等待READY（解决切换窗口时的
    竞争条件：新项目的LSP尚未写入bridge，但MCP已收到工具调用）。
  - 修复重复的 `with self._create_lock`（删除无效副本）。
- **`src/mcp/tools/base.py`**: 在 `MCPTool` 中添加 `async require_ready_project()`。
  工具现在等待就绪状态，而非使用「最后一个活动项目」。

### 🛠 工具
- **`scripts/sync_src.py`**（新）— 快速同步 `src/` 从
  开发仓库到扩展的安装目录。
- **`scripts/patch_zed_settings.py`**（新）— 修补Zed的全局
  `settings.json` 以添加 `MSCODEBASE_ALLOW_SELF_INDEX=1`。

### 🧪 测试
- 直接运行：`_is_self_index_path(D:\Project\MSCodeBase) = False`。
- `resolve_project_root()` 正确返回 `D:\Project\MSCodeBase`，无错误。
- MCP服务器启动并注册43个工具（33+10）。
- 索引：1362个块，106个文件，1080个Tree-sitter符号，status active。

---

## [v2.3.3] — 2026-07-05 — 可见项目路径 + 自索引防护

### 🎯 项目路径可见性（INC-6BCB-v3）
用户不再需要猜测「MCP在哪里搜索？」。现在：

- **`search_code`** 输出以 `📂 Project: <path>` 开头。
- **`index_project_dir`** 输出末尾包含 `📂 Project: <path>`。
- **`notify_change`** 输出在更新后包含 `📂 Project: <path>`。
- **`get_index_status`** 输出以 `📂 Project: <path>` 开头。
- **`index_health`** 输出在JSON响应中包含 `project_path`、`db_path`、
  `total_chunks`。

### 🛡 严格自索引防护（ToolError，非静默）
- **`resolve_indexer_for_request()`**（在 `src/mcp/tools/base.py` 中）在解析的project_path为以下情况时抛出
  `ToolError`：
  - `_ext_root`（扩展自身的源码）
  - Zed安装目录（`is_zed_install_dir()`）
  - `None`（未定义的项目根目录）
- **`IndexProjectDirTool`** 在创建Indexer**之前**进行**额外**检查，
  并给出清晰消息：「拒绝索引Zed安装目录：...」。
- **错误详情**包含修复指南（显式打开项目、传递显式project_root，或设置PROJECT_PATH环境变量）。

### 🐛 Bug修复
- **`is_zed_install_dir()`** 没有找到 `D:\AI\Zed`（安装根目录）
  因为标记需要尾部路径分隔符。添加了
  安装根目录的标记 + 反斜杠/正斜杠规范化
  以支持跨平台比较。

### 🧪 测试
- **`tests/test_project_header.py`（新，16个测试）**：
  - `_is_self_index_path()`：7个用例（None、Zed安装目录、ext_root、用户项目）。
  - `resolve_indexer_for_request()`：4个用例（用户OK、Zed安装目录被阻止、
    None被阻止、ext_root被阻止）。
  - `_project_header()` / `_project_metadata()`：5个用例（成功、错误、
    字典内容）。
- **全部测试通过：323 / 323**（307个之前的 + 16个新的）。

### 📊 冒烟测试
- `create_mcp_server()` 在8.61秒内启动，33个工具 + 4个处理器。
- `indexer.bm25_batch` 按项目（v2.3.1）+ 项目头部（v2.3.3）
  协同工作。

---

## [v2.3.2] — 2026-07-05 — 多根目录感知 + 自索引防护

### 🐛 严重Bug：自索引Zed安装目录
- **症状：** MCP索引 `D:\AI\Zed\`（Zed本身的安装目录）而非
  用户项目。在 `intel_get_runtime_status` 中显示为 `db_isolated_path:
  D:\AI\Zed\.codebase_indices\...`。
- **根因：** LSP从Zed接收 `params.root_uri`（或 `workspaceFolders`）。
  如果Zed以 `D:\AI\Zed` 作为工作树根目录打开（最后一个打开的工作区，
  或Zed IDE在没有显式项目的情况下启动），LSP将该路径写入bridge，
  然后MCP索引整个Zed目录（exe、dll、配置文件）。
- **解决方案：**
  1. `lsp_project_bridge.is_zed_install_dir(path)` — 通过路径中的标记（Zed.exe、%LOCALAPPDATA%\Zed等）和目录旁是否存在Zed.exe来检测Zed安装目录。
  2. `lsp_main.on_initialize` — 读取 `params.workspaceFolders`（LSP 3.6+），
     过滤Zed安装目录，为每个剩余工作区初始化DI。
  3. `lsp_project_bridge.write_active_project` — 接受 `all_workspaces`
     所有工作区URI的列表。
  4. `lsp_project_bridge.read_active_project` — 从 `all_workspaces` 中选择第一个非Zed安装的
     工作区，回退到 `project_root`。
  5. LSP服务器现在声明 `workspace.workspaceFolders` 能力
    （supported: True，changeNotifications: True）— Zed将在打开/关闭项目时发送
     `workspace/didChangeWorkspaceFolders`。

### 🔧 多根目录LSP
- `ls._all_workspaces` — 所有打开的工作区URI列表（用于监视器）。
- 按工作区DI：为 `workspaceFolders` 中的每个文件夹创建
  自己的 `_services_per_workspace[uri]`。如果Zed打开3个项目 —
  将有3个DI容器、3个ProjectIndexerRegistry、3个.codebase_indices/。

### 🧪 测试：306通过 + 1个预先存在的失败
- 所有先前测试无需更改通过。
- `test_expected_message_mismatch` — 预先存在，与v2.3.2无关。

### 📚 迁移
- 更新后：`sync_to_installed.bat --full` + 重启Zed。
- 如果 `D:\AI\Zed\.codebase_indices/` 包含自索引产生的垃圾 —
  可以手动删除：`rm -rf /d/AI/Zed/.codebase_indices`。
- 确保Zed正确打开项目：`cmd+shift+p` → 「Open Project」 →
  选择 `D:\Project\MSCodeBase`（将创建 `.zed/` 工作区标记）。

---

## [v2.3.1] — 2026-07-05 — 启动挂起修复 + 按项目的DebounceBatch

### 🐛 严重Bug修复
- **`lsp_main.py:did_change_watched_files`** — `if _services is None` 抛出 `NameError`（全局 `_services` 在按工作区架构中不存在）。替换为在 `_services_per_workspace[uri]` 中查找，回退到第一个可用项。没有此修复，观察者事件在首次触发时就因NameError崩溃。
- **`lsp_main.py:did_change`/`did_close`/`did_save`** — workspace_uri和project_root**未**传递给 `_execute_file_indexing`（只有 `did_open` 传递了）。在多窗口中，这意味着所有被索引的文件都进入默认的Indexer。**已修复** — 所有四个钩子现在传递 `getattr(ls, "_workspace_uri", "")` 和 `getattr(ls, "_project_root", None)`。
- **`lsp_main.py:_execute_file_indexing`** — `services.resolve(type("_IndexerFactory", (), {})) if False else ...`（带匿名type的死代码）替换为直接调用 `_get_factory(services)`。类似地 `services.resolve(type("ProjectRootKey", (), {}))` → `services.resolve(ProjectRootKey)`。
- **`search_tools.py:_agentic_search`** — `self.searcher` 和 `self.symbol_index` 在基础 `MCPTool` 中**不存在**（Indexer/Searcher按项目通过registry获取）。替换为 `self.resolve_searcher()` / `self.resolve_symbol_index()`。没有此修复，agentic_search会因AttributeError崩溃。
- **`graph_tools.py:GraphQueryTool`** — `__init__` 中的 `services.resolve(SymbolIndex)` + `services.resolve(Indexer)`（Indexer不再是单例）替换为每次调用使用 `self.resolve_symbol_index()` / `self.resolve_indexer()`。删除 project_root 的 `Path.cwd()` 回退。
- **`mcp/server.py:IntelligenceLayer`** — `services.resolve(Indexer/Searcher/SymbolIndex)`（三个都未注册）替换为 `resolve_indexer_for_request(services)`。没有此修复，10个intel_*工具无法注册（警告「Intel layer not registered」）。
- **`mcp/server.py:33+13` → `33+10`** — 纠正计数（10个intel工具，而非13个）。

### 🔧 按项目的DebounceBatch（多窗口）
- **之前：** `DebounceBatch` 作为单例在DI中注册，捕获默认 `ProjectRootKey` — 对于非默认项目，BM25重新索引使用**错误的** project_root（所有按项目的文件都由默认Searcher重新索引）。
- **现在：** `bm25_batch` 在 `_create_indexer_for_path()` 内部按项目创建（在闭包中捕获具体的 `Indexer`），并存储为 `indexer.bm25_batch`。所有消费者（`lsp_main.py:_execute_file_indexing`、`lsp_main.py:_process_watched_changes`、`mcp/tools/indexing_tools.py:NotifyChangeTool`）通过 `getattr(indexer, "bm25_batch", None)` 从 `indexer.bm25_batch` 获取batch，回退到同步 `searcher.reindex()`。
- **`di_container.py`** — 删除 `_batch_reindex_bm25_factory` 和 `services._factories[DebounceBatch]`。`_create_indexer_for_path` 现在显式创建 `p_indexer.bm25_batch = DebounceBatch(callback=..., config=...)`。
- **延迟绑定修复：** `_create_indexer_for_path` 在 `notification_broker` **之后**声明（之前通过globals使用延迟绑定 — 脆弱）。通过默认参数（`_embedder=embedder, _notification_broker=notification_broker`）捕获变量使行为确定性。

### 🚀 自索引防护 + Bridge重检查
- **`_trigger_auto_index_if_empty`** — 添加检查 `indexer.project_path == _ext_root`。如果 resolve_project_root 回退到fallback（与LSP的竞争），auto-index**不启动**（之前会索引扩展本身约500MB的源码）。
- **延迟bridge重检查** — MCP启动后1.5秒的后台任务重新读取 `read_project_from_bridge(max_wait=2.0)`。如果LSP已经写入project_root — `reset_project_root_cache()` 清除缓存，后续 `resolve_project_root` 调用将选择bridge。**解决了冷启动时的LSP↔MCP竞争**。

### 🧹 维护
- **`mcp/tools/base.py`** — 删除死代码 `_indexer_factory_from_services` 和 `_IndexerFactoryKey`（自v2.3.0起未使用）。
- **`mcp/tools/indexing_tools.py`** — 删除未使用的导入 `DebounceBatch`。
- **`mcp/tools/graph_tools.py`** — 删除未使用的导入 `SymbolIndex`。

### 🧪 测试：307通过
- `tests/test_di_container.py::test_creates_all_services` — 从列表中删除 `DebounceBatch`（不再是单例）。
- `tests/test_di_container.py::test_debounce_batch_uses_searcher` — 重写：batch从 `indexer.bm25_batch` 获取，而非通过 `services.resolve(DebounceBatch)`。
- 其余305个测试无需更改通过。

### 📚 迁移说明
- 更新后：`sync_to_installed.bat --full` + 重启Zed。
- 无需手动修改 `settings.json`（全部通过 `patch_zed_settings`）。

---

## [v2.3.0] — 2026-07-05 — 多窗口支持与加固

### 🏗️ 架构：多窗口
- **`ProjectIndexerRegistry`**（新，`src/core/project_indexer_registry.py`）：
  按项目的 `Indexer`，带懒加载创建和LRU淘汰（5个槽位）。
  每个打开的Zed窗口获得隔离的 `Indexer`/
  `FileGuard`/`SymbolIndex`/`db_path` — 切换窗口不再破坏状态。
- **`ResourceMonitor`**（新，`src/core/resource_monitor.py`）：
  仅使用stdlib的RAM/CPU监控（`resource.getrusage` + Windows上的 `ctypes/psapi`，
  无 `psutil`）。软/硬阈值用于自适应节流。
- **LSP按工作区DI**：`_services_per_workspace[uri]` 替代单个
  全局 `_services`。`init_components(project_root, workspace_uri=...)`。
- **MCP `resolve_indexer_for_request`**：从registry获取按项目的indexer，
  优先级：显式参数 → `resolve_project_root()` → DI默认。

### 🔧 加固
- **`_safe_close()`**：清空LanceDB连接 + 缓存 + `gc.collect()` —
  立即释放Windows上的 `.lance` mmap句柄。
- **自适应节流**：`Indexer.index_project` 在软压力下减速（0.1秒），
  在硬压力下停止（最多2秒）。
- **HealthReport `_check_resources`**：rss_mb、cpu_percent、线程数、
  registry统计（cached/evictions/hits/misses）在 `metrics` 中。
- **`async indexer` 可重入性**：LSP中的 `_indexing_serial_lock` 序列化
  在 `did_open`/`did_change`/`did_save` 之间的LanceDB写入。

### 🐛 Bug修复（审计INC-53EC，19个问题）
- `di_container.py:177` — `CircuitBreaker.on_state_change` 中的 `notification_broker` NameError
- `lsp_main.py:372` — `did_change_watched_files` 中未定义的全局 `_indexer`
- `did_change` 防抖350ms（非每次按键）
- `asyncio.Lock` → `threading.Lock`（跨循环安全：LSP pygls循环 + MCP asyncio.run循环）
- Sentinel DI键（`ProjectRootKey`/`DbPathKey`/`IndexerFactoryKey`）替代 `str`/`type("…")`
- `indexer.set_searcher(searcher)` 替代 `indexer.searcher = …`（封装）
- 通过 `atexit` + `weakref.finalize` 的 `SafePathManager.cleanup`
- `add_columns` 迁移LanceDB替代 `drop+create` 竞争
- `O(N) to_pandas()` 替换为 `table.search().where(...).limit(1)`
- LSP观察者glob `**/*.{ext1,ext2,…}`（按扩展名过滤）
- `git log` 在HealthReport中使用 `cwd=project_path`
- `HeartbeatService` 类（DI友好）替代模块全局变量
- `IndexGuard` 协调（之前的 `needs_reindex` 不会卡住）
- `nul` 文件已删除（Windows保留名称）

### 🔧 Zed设置
- 从 `patch_zed_settings` 中删除 `current_dir`（Zed不在 `current_dir` 中替换
  `$ZED_WORKTREE_ROOT` — bug #36019）。`resolve_project_root`
  自行处理优先级：PROJECT_PATH env → bridge → CWD → ext_root。
- `fix_zed_settings.bat`（新）— 修补用户现有的 `settings.json`
  （删除带备份的 `current_dir`）。
- 自索引防护：PROJECT_PATH指向MSCodeBase → 日志中的警告。

### 🧪 测试：325 → 307通过（+ 11个新 = 318；11个弃用，减后 = 307）
- `test_resource_monitor.py`（新，11个测试）：
  - `ResourceMonitor`：采样、节流、压力阈值、摘要、单例
  - `ProjectIndexerRegistry`：按路径单例、LRU淘汰、压力淘汰、
    显式淘汰、统计（命中/未命中/淘汰）
- `test_health_report.py`：降级状态、total_symbols/embedder_mode别名、
  孤立文件检测、git log cwd、回退嵌入器警告
- `test_integration.py`：`isolated_indexer` 使用 `temp_project` 作为
  `project_path`（曾有bug — FileGuard拒绝文件为「不在项目中」）
- `test_di_container.py`：`Indexer`/`Searcher` 现在通过registry按项目管理

### 📚 文档
- README：测试徽章325 → 307，在功能中添加多窗口
- `ARCHITECTURE.md`：章节「多窗口注册表」+ ResourceMonitor
- CHANGELOG：此文件
- `pyproject.toml`：升级到v2.3.0
- AGENT_DIARY.md：3条记录（审计 + 多窗口 + 资源监控器）

### ⚠️ 迁移说明
- 更新后运行 `fix_zed_settings.bat` 以删除
  `current_dir` 从 `~/.config/Zed/settings.json`（或 `%APPDATA%\Zed\settings.json`）。
- `sync_to_installed.bat --full` 同步到已安装的副本。
- 重启Zed以加载新版本。

---

## [v2.2.0] — 2026-07-04 — 架构现代化

### 🏗 架构重写
- **DI容器：** 带构造函数注入的ServiceCollection（15个服务）
- **server.py：** 3,100 → **220行**（-93%）。消除了上帝对象。
- **37个工具**解耦到 `src/mcp/tools/` 中的10个领域特定文件
- **error_boundary** 装饰器：统一JSON响应，真实的 `asyncio.wait_for` 超时
- **DebounceBatch：** 通过500ms防抖的BM25重新索引（非每次文件变更）
- **SlidingWindowRateLimiter：** 防止VFS循环（最多10 req/sec）
- **CircuitBreaker：** LM Studio的CLOSED/OPEN/HALF_OPEN（5次失败 → 30秒恢复）
- **hybrid_server.py：** DEPRECATED（所有逻辑在DI容器 + lsp_main.py中）

### 🔧 改进
- `lsp_main.py` — 4个全局变量 → DI容器（_services）
- `notify_change` — 速率限制器 + DebounceBatch 替代立即BM25
- `get_index_progress` — 作为模块级导出的进度追踪
- `read_live_file` — 新工具（从LSP VFS读取，带磁盘回退）
- `_resolve_project_path` → 独立的 `resolve_project_root()`
- `GIT_ASKPASS=echo` + `CREATE_NO_WINDOW` — 防止Windows上的Git挂起
- `_is_complex_query` — 修复：俄语语法 → 基于token + 英语W-words

### 🧪 测试
- 52个新的单元测试，用于：
  - `error_handler.py` — ToolError、error_boundary（异步+同步）、超时、重试
  - `rate_limiter.py` — SlidingWindow、DebounceBatch、CircuitBreaker（所有状态）
  - `di_container.py` — ServiceCollection、15个DI服务、Searcher↔Indexer循环
- 总计：**325个测试**

### 📚 文档
- README完全重写：37个工具，带DI的整洁架构
- `ARCHITECTURE.md` — 带DI容器和工具文件的新图表
- CONTRIBUTING.md — 根据新架构风格更新
- AGENT_DIARY.md — 5条记录（重构的所有阶段）
- pyproject.toml：升级到v2.2.0

---

## [v2.1.0] — 2026-07-03

### 🚀 主要
- **搜索整合：** `search_code(query, mode)` — 带5种模式的统一工具（auto/fast/quality/deep/context）
- **智能层：** 10个高级 `intel_*` 工具（自诊断、拓扑、项目记忆）
- **放弃双重写入：** `patch_zed_settings()` 现在单次通过（MCP + LSP + Languages一次调用）
- **项目记忆：** ADR、known_issues、tech_debt、failed_attempts — 在会话之间自动保存

### 🔧 改进
- `get_health_report`/`index_health` — `project_root` 可选（回退到 `$PROJECT_PATH`）
- `notify_change` — 正确从项目根目录解析路径（非CWD）
- `_resolve_project_path()` — 集中式helper用于解析项目根目录
- 通过 `PROJECT_PATH` 环境变量集中处理路径（由Zed设置）
- `install.py` — 清理：删除重复的LSP代码（现在在 `patch_zed_settings` 中）

### 📚 文档
- README完全重写：26个工具，带mode的search_code，Intel Layer
- `ARCHITECTURE.md` — 更新工具列表（14→26 + 10个intel_*）
- `WINDOWS_SETUP.md` — 根据新格式更新
- `CONTRIBUTING.md` — 删除弃用工具的提及
- 创建 `sync_to_installed.bat` 用于快速同步 source→installed

### 🧹 维护
- 删除 `run_tests.py`、`run_tests.bat`（`pytest` 的重复）
- 更新 `.gitignore`（添加开发工件）
- 项目根目录清理测试垃圾

### ⚠️ 弃用
- `smart_search`、`deep_search`、`context_search` → 使用 `search_code(query, mode=...)`
- 旧函数仍然作为包装器工作（向后兼容）

## [v2.0.0] — 2026-06-28

### 🚀 主要
- LSP + MCP混合架构：带共享内存的统一进程替代独立服务器
- 完全放弃进程间通信 — 降低延迟并简化部署

### ⚠️ 破坏性变更
- 需要从先前架构迁移到统一的LSP+MCP进程
- 与编辑器的集成点已更改（不再有独立的MCP服务器）
- 配置格式已更新

## [v1.4.2] — 2026-06-28

### 🔧 改进
- 从ThreadPoolExecutor迁移到asyncio.gather用于异步操作
- 改进了并行请求提供者的性能

## [v1.4.1] — 2026-06-28

### 🔧 改进
- 为LM Studio添加基于嵌入的重排序器
- 提高了搜索结果排序的准确性

## [v1.4.0] — 2026-06-28

### 🚀 主要
- 深度调用图，遍历深度2+级别
- 扩展符号依赖分析（调用者/被调用者）

## [v1.3.0] — 2026-06-28

### 🔧 改进
- 多提供者重排序：Ollama → LM Studio → RRF回退
- 提供者不可用时自动切换

## [v1.2.0] — 2026-06-28

### 🚀 主要
- 生产就绪版本
- 改进语义的Agentic search v4
- 索引进度跟踪系统

## [v1.1.0] — 2026-06-22

### 🚀 主要
- 用于远程嵌入生成的RemoteEmbedder
- 用于快速部署的即用安装程序

## [v1.0.0] — 2026-06-21

### 🚀 主要
- 项目的第一个版本
- 基于代码库的基本语义搜索
- 与LanceDB集成用于向量存储
