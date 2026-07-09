<img src="../../logo/logo.svg" width="64" height="64" align="left" style="margin-right: 16px;">

[🇬🇧 English](../en/CHANGELOG.md) • [🇷🇺 Русский](../ru/CHANGELOG.md) • [🇨🇳 中文](CHANGELOG.md)

# 更新日志

本文件中记录了所有重要的项目变更。

## [2.7.0] — 2026-07-09
### Added
- 🦙 llama.cpp 作为主要提供商（通过 install.py 自动安装）
- LlamaRunner — llama-server.exe 生命周期管理器（下载、启动、停止）
- GGUF 模型：bge-m3 Q4_K_M (417 MB) + bge-reranker-v2-m3 Q4_K_M (418 MB)
- 平台检测：Windows/macOS/Linux、x64/ARM64
- docs/research/2026-07-09-provider-benchmark.md — 完整基准测试

### Changed
- 安装程序：10→12 步骤（+llama.cpp、+GGUF 模型）
- patch_zed_settings：保留 // 注释，no-op guard
- 提供商优先级：LM Studio → llama.cpp → ONNX server → local ONNX
- MCP：227 MB RAM（原为 1200 MB）— 减少 5.3 倍
- ONNX server：使用 Tokenizer.from_file() 替代 AutoTokenizer — 无挂起

### Fixed
- AutoTokenizer.from_pretrained() 在 Windows 上挂起（HTTP 连接到 huggingface.co）
- patch_zed_settings 删除了 // 注释 → "恢复"按钮
- _detect_model_dir() 仅为了读取维度创建了 544 MB 的 InferenceSession
- 所有 HTTP 客户端：httpx.Limits(keepalive_expiry=30.0) 以兼容 Zed 1.10.0

---

## [v2.5.3] — 2026-07-07 — mode=ask：通过 phi-4 的 RAG 回答生成

### 🚀 mode=ask
- **`src/core/searcher.py`**: 新方法 `Searcher.ask_async()` — 混合搜索 →
  上下文 → phi-4 (chat completion) → 带引用的结构化回答。
- **`src/mcp/tools/search_tools.py`**: 新增 `mode="ask"` 模式并带保护：
  在 `light` 配置下自动回退到 `quality` 并发出警告。
- **`src/core/config.py`**: `ASK_TIMEOUT` (60秒), `ASK_MODEL` (phi-4-mini-instruct)。

### 📦 版本
- `extension.toml`: 2.5.2 → 2.5.3
- `src/__init__.py`: 2.5.2 → 2.5.3

---

## [v2.5.2] — 2026-07-07 — phi-4-mini-instruct 验证 + 实时测试

### 🔬 LM Studio
- 通过 `/v1/chat/completions` 测试了 `phi-4-mini-instruct Q4_K_M`：
  成功响应（75 个 token，`finish_reason=stop`）。
- 模型按需加载（state: not-loaded → auto-load）。
- 确认已为 `mode=ask` (v2.7.0) 做好准备。

### 📦 版本
- `extension.toml`: 2.5.1 → 2.5.2
- `src/__init__.py`: 2.5.1 → 2.5.2

---

## [v2.5.1] — 2026-07-07 — Multi-Bucket RAG + 上下文检索 + 配置文件

### 🚀 Multi-Bucket RAG (第一阶段)
- **`src/core/searcher.py`**: Overfetch (`raw_limit = min(limit * factor, MAX)`),
  按 CODE_EXTENSIONS/DOCS_EXTENSIONS 分发存储桶,
  reranker 之前的 soft weighting, cut-to-limit。
- **`src/core/config.py`**: `CODE_EXTENSIONS`, `DOCS_EXTENSIONS`,
  `MAX_RERANKER_INPUT=30`, `overfetch_factor`, `code_bucket_weight`,
  `docs_bucket_weight` — 全部通过 `.env` 配置。

### 🧩 上下文检索 (第二阶段)
- **`src/core/parser.py`**: 代码的新前缀格式：
  `// File: {path} | Context: {class}.{func}`, 对于 .md：
  `From {path}, section '{heading}':`。需要重新索引。

### ⚖️ 软评分 + intent_hint (第三阶段)
- **`src/mcp/tools/search_tools.py`**: 新增参数 `intent_hint`
  (`"auto"` / `"code"` / `"docs"`)。
- **`src/core/searcher.py`**: `_apply_bucket_weights()` — 动态权重：
  code=1.2/docs=0.8 用于 `"code"`, code=0.8/docs=1.2 用于 `"docs"`,
  1.0/1.0 用于 `"auto"`。

### ⚙️ SYSTEM_PROFILE (第四阶段)
- **`src/core/config.py`**: `SYSTEM_PROFILE=light|server` 带验证
  和属性 `is_light_profile`/`is_server_profile`。
  `light` — 同步模式（默认），`server` — 保留。

### 📦 版本
- `extension.toml`: 2.4.4 → 2.5.1
- `src/__init__.py`: 1.0.0 → 2.5.1

---

## [v2.4.7] — 2026-07-05 — LM Studio 连接池 + 预热

### ⚡ 性能
- **`src/core/remote_embedder.py`**: 添加 `httpx.AsyncClient` 与 **连接池**
  （5 个保持活动连接，60 秒过期）— 消除每个嵌入请求的 TCP/TLS 开销。
- **`src/core/remote_embedder.py`**: 新方法 `embed_batch_async()` — 通过
  单一 HTTP 客户端进行异步嵌入。`searcher.py` 自动检测并使用它。
- **`src/mcp/server.py`**: `_warmup_embedder()` 在服务器启动时预热 bge-m3
  模型，消除首次 search_code 的 ~3s 冷启动延迟。

---

## [v2.4.6] — 2026-07-05 — UI 格式化器 + 死锁修复 + 日志集中化

### 🐛 死锁修复
- **`src/core/rate_limiter.py`**：`DebounceBatch._debounce_wait()` 不再在
  `threading.Lock` 内部调用 `await` — 已提取到独立变量 `should_flush`。
  `threading.Lock` 不可重入 — 批量 `notify_change` 必现 100% 死锁。
  修复代码质量：删除 `field`，添加 `Any`。

### 🎨 UI 格式化器（新模块）
- **`src/utils/ui_formatter.py`**：8 个基础格式化函数：
  `header()`、`table()`、`key_value()`、`code_block()`、`empty_result()`、
  `error_result()`、`ok_result()`、`format_search_code()`、`format_repo_rank()`、
  `format_health_report()`、`format_telemetry()`、`format_eta()`。
- 所有数据放在 `<details>` 折叠标签下，使用 Markdown 表格替代 JSON。

### 🔄 日志集中化
- **`src/core/log_manager.py`**：`get_log_dir()` 现在**始终**指向
  `ext_root/.codebase_indices/logs/`，而非按项目分开。新增
  `_cleanup_stale_project_logs()` — 清理项目中的旧日志。
- 清理导入：删除 `datetime`、`timedelta`、`timezone`、重复的 `import os`。

### 🧩 UI 格式化器集成
- **`src/mcp/tools/search_tools.py`**：`_format_results()` 迁移到
  `format_search_code()`。输出表格包含列：#、文件、行、片段、层。
- **`src/mcp/tools/system_tools.py`**：`GetIndexStatusTool.execute()` — 输出
  使用 `header() + key_value() + code_block()`。
- **`src/mcp/tools/analysis_tools.py`**：`GetRepoRankTool.execute()` — 输出
  使用 `format_repo_rank()`，表格和原始 JSON 放在折叠标签下。

### 🧠 项目记忆
- `known_issues`：LSP WONTFIX 在 Zed 1.9.0 Windows 上（NODE-567a10）
- `incidents`：INC-2CE4、INC-8817

---

### 📄 文档
- **新调查报告**：`docs/investigations/2026-07-05-lsp-zed-1.9.0.md`。
  对 Zed 1.9.0 源码的全面审计（`crates/project/src/lsp_store.rs`、
  `crates/extension/src/extension_manifest.rs`、`crates/settings_content/src/language.rs`）
  包含代码引用和 GitHub 原始链接。结论：**Zed 1.9.0 上 WONTFIX** —
  无法仅通过 `settings.json` 注册自定义 LSP，需要 Rust+WASM 包装。

### 🧹 清理死代码
- **`install.py`**：删除 LSP 配置生成（`lsp_config`）。`settings.json` 中的 LSP 部分
  不再创建 — 它不起作用（WONTFIX）。
- **`src/utils/zed_config.py`**：从 `patch_zed_settings()` 中删除 `lsp.mscodebase-lsp`
  注册块。函数不再接受 LSP 配置。
- **`scripts/check_lsp_health.py`**：新增诊断脚本。检查
  settings.json、进程、桥接文件、SQLite 数据库。输出带有建议的明确结论。

### 📚 文档
- **`ZED_WINDOWS_QUIRKS.md`**（1.0 → 1.1）：新增章节「LSP 在 Zed 1.9.0 上无法启动（WONTFIX）」包含真实根本原因。
- **更新** `AGENT_DIARY.md`：15:55 新条目包含正确的根本原因
  和调查报告链接。旧条目 15:30 标记为 DEPRECATED。

### 🧠 项目记忆
- 在 `known_issues` 中添加 LSP-WONTFIX 节点，包含报告链接
  和三种解决方法（MCP、SQLite 回退、替换 pyright）。

### ℹ️ 这意味着什么
- **MCP 仍是所有代码辅助场景的主要传输方式。**
- **编辑器中的 LSP 功能（嵌入提示、代码操作、自动补全）**在 Zed 1.9.0
  Windows 上无法实现，除非使用 Rust 包装 — 这是设计如此，不是我们的缺陷。
- **v3.0 计划**采用路径 A（通过 `impl zed::Extension::language_server_command` 的 Rust+WASM 包装）。

---

## [v2.4.4] — 2026-07-05 — 元数据丰富：语义指南针 + 扁平树

### 🧭 语义指南针（MCompassRAG 风格，src/core/parser.py + src/core/indexer.py）
- 每个块现在包含 `layer`（架构层：core/mcp/utils/tests/...）。
- 通过文件路径自动检测层，无需手动标记。
- `module_name` 字段 — 模块的逻辑名称（core.parser、mcp.server）。
- `is_public` 字段 — 公开/私有符号（按 `_` 前缀判断）。
- `symbol_type` 字段 — AST 节点类型（function_definition、method_definition、...）。

### 🌳 扁平树（SproutRAG 风格，src/core/parser.py + src/core/indexer.py）
- `hierarchy_level`：function | method | class | impl | lines | function_part | section。
- `parent_id`：父元素的确定性 md5 哈希。
  - 对于方法：哈希 `file_path::ClassName`。
  - 对于函数：哈希 `file_path`（模块）。
  - 无需图数据库即可实现多粒度检索。

### 🗃 LanceDB 模式
- 6 个新字段：`layer`、`module_name`、`hierarchy_level`、`is_public`、`symbol_type`、`parent_id`。
- 通过 `_migrate_add_metadata_columns()` 自动迁移 — 无需删除表。
- 旧块获得空值；重新索引后将填充。

### 🔧 代码
- `src/core/parser.py`：+`_build_chunk_metadata()` — 4 个块创建点。
- `src/core/indexer.py`：+`_migrate_add_metadata_columns()`、+`chunk_metadatas`。
- 全部 103 个测试通过，无任何损坏。

### 🎯 按层过滤搜索（MCompassRAG — 搜索）
- `search_code` 新增参数 `filter_layer`（core/mcp/utils/tests/...）。
- LanceDB `.where()` 使用 `prefilter=True` — 在索引级别过滤，无需加载所有块。
- BM25 根据元数据中的 layer 进行后过滤。
- 在所有模式下工作：fast（仅向量）、quality（混合）、deep。

### 🌳 多粒度检索（SproutRAG — 搜索）
- 新方法 `Searcher.get_chunks_by_parent_id()` — 根据 parent_id 查找所有子块。
- 允许沿层级向上导航：模块 → 类 → 函数。
- 端到端：core 过滤器只输出 core，tests 过滤器只输出 tests，零交叉。

---

## [v2.4.3] — 2026-07-05 — RuntimeCoordinator + intel_get_project_context

### 🎯 RuntimeCoordinator（新，src/core/runtime_coordinator.py）
- 统一决策点"是否可以执行 MCP 请求？"。
- 使用 Registry（状态）、SystemArtifacts（系统路径）、
  Runtime Passport（就绪状态）。
- `can_execute(path) → ExecutionVerdict(ok, reason, state, detail)`。
- MCPTool 中的 `require_ready_project()` 委托给 Coordinator。
- 工具名称：`intel_get_project_context`（统一的 Intel Layer 风格）。

### 🧪 代码
- ProjectContext、RuntimeCoordinator、server.py、base.py — 语法 OK。
- 架构：Tool → Coordinator → Snapshot，无复制粘贴。

---

## [v2.4.2] — 2026-07-05 — ProjectContext — 统一项目状态模型

### 🏗 ProjectContext（新，src/core/project_context.py）
- 统一项目快照对象：state + index + bridge + health + memory + jobs。
- 替代 5 个不同的调用 — 一次 `await ctx.capture()`。
- 所有字段均为可选：如果组件不可用 → None，不会崩溃。
- `get_project_context` MCP 工具 — 一次性返回包含项目全貌的 JSON。
- 不破坏任何东西 — 在现有架构之上的新层。

### 🔧 SystemArtifacts（src/core/system_artifacts.py）
- 用于识别系统文件的统一模块（4 级保护）。
- file_guard.py 已迁移到 SystemArtifacts — 所有列表集中在一处。

---

## [v2.4.1] — 2026-07-05 — 扩展护照 + 反馈循环防护 + 两阶段就绪

### 🆔 扩展护照（BUILD_ID + Bridge/Registry/ProjectState）
- **`src/mcp/server.py`**：添加 `_BUILD_ID`（git 提交哈希）— 即时
  代码版本验证。
- `_log_run_passport()` 现在在启动时记录 Bridge 状态和 Registry 状态。
- `debug_runtime_passport` 返回：`build_id`、`project_state`（枚举）、
  `bridge`、`bridge_error`、`registry.paths`、`registry.cached_projects`、
  `registry.cache_hits/misses`。

### 🛡 反馈循环防护（防止索引污染）
- **`src/core/file_guard.py`**：在 `_load_gitignore()` 中添加显式模式
  以排除索引服务的文件：
  - `chunk_summaries.json`、`summaries_cache/**` — 块的描述
  - `incidents.json`、`project_memory.json`、`commits.json` — 记忆元数据
  - `.index_guard.json`、`symbol_index/**` — 索引
- 双层保护：SKIP_DIRS（目录）+ .gitignore（文件）。
- 没有这些排除，可能存在反馈循环：块描述 → 摘要 →
  摘要被索引 → 基于前一个摘要的新摘要。

### ⏱ 两阶段 wait_until_ready
- **`src/mcp/tools/base.py`**：`require_ready_project()` 现在分两个阶段：
  1. 快速检查桥接（1s）— 如果 LSP 尚未写入 project_root，
     立即记录警告，而不是等待 5 秒。
  2. 完全等待 READY（剩余秒数）。

### 🧪 测试
- 所有文件通过 py_compile。
- 索引：1362 个块、106 个文件、1080 个 Tree-sitter 符号、status=active。

---

## [v2.4.0] — 2026-07-05 — 自索引修复 + 进程护照 + 项目状态机

### 🛡 自索引防护：开发仓库修复
- **`src/mcp/server.py`**：删除错误的 `_SELF_INDEX_MARKER`
  （`(path / "src/lsp_main.py").exists()`），替换为
  `_reject_self_index_target(p, source=)`。
  - 拒绝：`p == _ext_root` + `is_zed_install_dir(p)`。
  - 如果用户在 Zed 中以项目形式打开了扩展源代码，
    **不再**阻塞开发仓库（`D:\Project\MSCodeBase`）。
- **`src/mcp/tools/base.py`**：添加环境变量覆盖 `MSCODEBASE_ALLOW_SELF_INDEX=1`
  用于开发场景。
- **`src/utils/zed_config.py`**：`patch_zed_settings()` 将
  `MSCODEBASE_ALLOW_SELF_INDEX=1` 写入 MCP/LSP 环境变量。

### 🆔 进程护照（debug_runtime_passport）
- **`src/mcp/server.py`**：MCP 启动时记录"护照" —
  `RUN_ID`、`PID`、`_ext_root`、`PROJECT_PATH`、`ZED_WORKTREE_ROOT`、
  `MSCODEBASE_ALLOW_SELF_INDEX`、`PYTHONPATH`。
- 注册 MCP 工具 `debug_runtime_passport` — 返回 JSON
  包含 RUN_ID、PID、运行时间、source_file、ext_root、env、防护结果。
  一次调用即可确认："我代码正在被哪个进程执行？"。

### 🏗 项目状态机（无竞态多窗口）
- **`src/core/project_indexer_registry.py`**：
  - 添加 `enum ProjectState`：`UNINITIALIZED → STARTING → INDEXING → READY → FAILED`。
  - 每个项目的 `asyncio.Event` 用于就绪信号。
  - `get_indexer()` 在创建时自动将项目转为 STARTING，
    然后转为 READY/INDEXING。
  - `wait_until_ready(path, timeout=5.0)` — 等待 READY（解决窗口切换时的
    竞态条件：新项目的 LSP 尚未写入桥接，
    但 MCP 已经收到工具调用）。
  - 修复重复的 `with self._create_lock`（删除死副本）。
- **`src/mcp/tools/base.py`**：在 `MCPTool` 中添加 `async require_ready_project()`。
  工具等待就绪状态，而非使用"最后活跃项目"。

### 🛠 实用工具
- **`scripts/sync_src.py`**（新）— 从开发仓库到扩展安装目录的快速 `src/` 同步。
- **`scripts/patch_zed_settings.py`**（新）— 修补 Zed 全局
  `settings.json` 以添加 `MSCODEBASE_ALLOW_SELF_INDEX=1`。

### 🧪 测试
- 直接运行：`_is_self_index_path(D:\Project\MSCodeBase) = False`。
- `resolve_project_root()` 返回 `D:\Project\MSCodeBase` 无错误。
- MCP 服务器启动并注册 43 个工具（33+10）。
- 索引：1362 个块、106 个文件、1080 个 Tree-sitter 符号、状态 active。

---

## [v2.3.3] — 2026-07-05 — 可见项目路径 + 自索引防护

### 🎯 项目路径可见性（INC-6BCB-v3）
用户不再需要猜测"MCP 在哪里搜索？"。现在：

- **`search_code`** 输出以 `📂 Project: <path>` 开头。
- **`index_project_dir`** 输出末尾包含 `📂 Project: <path>`。
- **`notify_change`** 输出更新后包含 `📂 Project: <path>`。
- **`get_index_status`** 输出以 `📂 Project: <path>` 开头。
- **`index_health`** 输出在 JSON 响应中包含 `project_path`、`db_path`、
  `total_chunks`。

### 🛡 硬性自索引防护（ToolError，非静默）
- **`resolve_indexer_for_request()`**（在 `src/mcp/tools/base.py` 中）抛出
  `ToolError`，如果解析出的 project_path 是：
  - `_ext_root`（扩展自身的源代码）
  - Zed 安装目录（`is_zed_install_dir()`）
  - `None`（未定义的 project_root）
- **`IndexProjectDirTool`** 在创建 Indexer **之前**执行**额外**检查，
  附带明确的消息："拒绝索引 Zed 安装目录：..."。
- **错误详情**包含修复说明（明确打开项目、
  传递显式 project_root、或设置 PROJECT_PATH 环境变量）。

### 🐛 缺陷修复
- **`is_zed_install_dir()`** 未找到 `D:\AI\Zed`（安装根目录），
  因为标记要求尾部路径分隔符。已为安装根目录添加标记，
  并添加反斜杠/正斜杠规范化以进行跨平台比较。

### 🧪 测试
- **`tests/test_project_header.py`**（新，16 个测试）：
  - `_is_self_index_path()`：7 种情况（None、Zed 安装、ext_root、用户项目）。
  - `resolve_indexer_for_request()`：4 种情况（用户 OK、Zed 安装被阻止、
    None 被阻止、ext_root 被阻止）。
  - `_project_header()` / `_project_metadata()`：5 种情况（成功、错误、
    dict 内容）。
- **所有测试通过：323 / 323**（之前 307 个 + 新 16 个）。

### 📊 冒烟测试
- `create_mcp_server()` 在 8.61 秒内启动，33 个工具 + 4 个处理器。
- `indexer.bm25_batch` 每个项目（v2.3.1）+ 项目标头（v2.3.3）
  协同工作。

---

## [v2.3.2] — 2026-07-05 — 多根识别 + 自索引防护

### 🐛 严重缺陷：自索引 Zed 安装目录
- **症状：** MCP 索引 `D:\AI\Zed\`（Zed 自身安装目录）而不是
  用户项目。可见为 `db_isolated_path: D:\AI\Zed\.codebase_indices\...`
  在 `intel_get_runtime_status` 中。
- **根因：** LSP 从 Zed 接收 `params.root_uri`（或 `workspaceFolders`）。
  如果 Zed 以 `D:\AI\Zed` 作为工作区根目录打开（最后打开的工作区，
  或 Zed IDE 在没有明确项目的情况下启动），LSP 向桥接写入该路径，
  MCP 索引整个 Zed 目录（exe、dll、配置）。
- **解决方案：**
  1. `lsp_project_bridge.is_zed_install_dir(path)` — 通过路径中的标记
     （Zed.exe、%LOCALAPPDATA%\Zed 等）以及目录旁是否存在
     Zed.exe 来检测 Zed 安装目录。
  2. `lsp_main.on_initialize` — 读取 `params.workspaceFolders`（LSP 3.6+），
     过滤 Zed 安装目录，为每个剩余项目初始化 DI。
  3. `lsp_project_bridge.write_active_project` — 接受 `all_workspaces`
     所有工作区 URI 的列表。
  4. `lsp_project_bridge.read_active_project` — 从 `all_workspaces` 中选择
     第一个非 Zed 安装的工作区，回退到 `project_root`。
  5. LSP 服务器现在声明 `workspace.workspaceFolders` 能力
     （supported: True, changeNotifications: True）— Zed 将在打开/关闭项目时
     发送 `workspace/didChangeWorkspaceFolders`。

### 🔧 多根 LSP
- `ls._all_workspaces` — 所有打开工作区的 URI 列表（用于观察者）。
- 每个工作区 DI：为 `workspaceFolders` 中的每个文件夹创建
  自己的 `_services_per_workspace[uri]`。如果 Zed 打开 3 个项目 —
  将有 3 个 DI 容器、3 个 ProjectIndexerRegistry、3 个 .codebase_indices/。

### 🧪 测试：306 通过 + 1 个预先存在的失败
- 所有之前的测试通过，无需更改。
- `test_expected_message_mismatch` — 预先存在，与 v2.3.2 无关。

### 📚 迁移
- 更新后：`sync_to_installed.bat --full` + 重启 Zed。
- 如果 `D:\AI\Zed\.codebase_indices/` 包含自索引的垃圾 —
  可手动删除：`rm -rf /d/AI/Zed/.codebase_indices`。
- 确保 Zed 正确打开项目：`cmd+shift+p` → "Open Project" →
  选择 `D:\Project\MSCodeBase`（将创建 `.zed/` 工作区标记）。

---

## [v2.3.1] — 2026-07-05 — 启动挂起修复 + 每个项目的 DebounceBatch

### 🐛 严重缺陷修复
- **`lsp_main.py:did_change_watched_files`** — `if _services is None` 抛出 `NameError`（全局 `_services` 在按工作区架构中不存在）。替换为在 `_services_per_workspace[uri]` 中查找，回退到第一个可用项。否则观察者事件在首次触发时就以 NameError 崩溃。
- **`lsp_main.py:did_change`/`did_close`/`did_save`** — workspace_uri 和 project_root **未**传递给 `_execute_file_indexing`（只有 `did_open` 传递了）。在多窗口模式下这意味着所有索引文件都进入默认 Indexer。**已修复** — 所有四个钩子现在传递 `getattr(ls, "_workspace_uri", "")` 和 `getattr(ls, "_project_root", None)`。
- **`lsp_main.py:_execute_file_indexing`** — `services.resolve(type("_IndexerFactory", (), {})) if False else ...`（带有匿名 type 的死代码）替换为直接 `_get_factory(services)`。类似地 `services.resolve(type("ProjectRootKey", (), {}))` → `services.resolve(ProjectRootKey)`。
- **`search_tools.py:_agentic_search`** — `self.searcher` 和 `self.symbol_index` 在基本 `MCPTool` 中**不存在**（Indexer/Searcher 通过 registry 按项目分配）。替换为 `self.resolve_searcher()` / `self.resolve_symbol_index()`。否则 agentic_search 以 AttributeError 崩溃。
- **`graph_tools.py:GraphQueryTool`** — `__init__` 中的 `services.resolve(SymbolIndex)` + `services.resolve(Indexer)`（Indexer 不再是单例）替换为每次调用的 `self.resolve_symbol_index()` / `self.resolve_indexer()`。删除了 project_root 的 `Path.cwd()` 回退。
- **`mcp/server.py:IntelligenceLayer`** — `services.resolve(Indexer/Searcher/SymbolIndex)`（三个都未注册）替换为 `resolve_indexer_for_request(services)`。未修复前 10 个 intel_* 工具未注册（警告"Intel layer not registered"）。
- **`mcp/server.py:33+13` → `33+10`** — 正确的计数（10 个 intel 工具，不是 13 个）。

### 🔧 每个项目的 DebounceBatch（多窗口）
- **之前：** `DebounceBatch` 在 DI 中注册为单例，捕获默认 `ProjectRootKey` — 对于非默认项目，BM25 重新索引使用**错误**的 project_root（所有按项目的文件由默认 Searcher 重新索引）。
- **现在：** `bm25_batch` 在 `_create_indexer_for_path()` 内部按项目创建（在闭包中捕获特定 `Indexer`）并存储为 `indexer.bm25_batch`。所有消费者（`lsp_main.py:_execute_file_indexing`、`lsp_main.py:_process_watched_changes`、`mcp/tools/indexing_tools.py:NotifyChangeTool`）通过 `getattr(indexer, "bm25_batch", None)` 获取 batch，回退到同步 `searcher.reindex()`。
- **`di_container.py`** — `_batch_reindex_bm25_factory` 和 `services._factories[DebounceBatch]` 已删除。`_create_indexer_for_path` 现在显式创建 `p_indexer.bm25_batch = DebounceBatch(callback=..., config=...)`。
- **晚绑定修复：** `_create_indexer_for_path` 在 `notification_broker`**之后**声明（之前使用通过全局变量的晚绑定 — 脆弱）。通过默认参数捕获变量（`_embedder=embedder, _notification_broker=notification_broker`）使行为确定性。

### 🚀 自索引防护 + 桥接重新检查
- **`_trigger_auto_index_if_empty`** — 添加检查 `indexer.project_path == _ext_root`。如果 resolve_project_root 回退（与 LSP 竞态），自动索引**不启动**（之前索引约 500MB 的扩展自身源代码）。
- **延迟桥接重新检查** — MCP 启动后 1.5 秒的后台任务重新读取 `read_project_from_bridge(max_wait=2.0)`。如果 LSP 成功写入 project_root — `reset_project_root_cache()` 清除缓存，后续 `resolve_project_root` 调用将选择桥接。**解决冷启动时的 LSP↔MCP 竞态**。

### 🧹 内务管理
- **`mcp/tools/base.py`** — 删除死代码 `_indexer_factory_from_services` 和 `_IndexerFactoryKey`（自 v2.3.0 起未使用）。
- **`mcp/tools/indexing_tools.py`** — 删除未使用的导入 `DebounceBatch`。
- **`mcp/tools/graph_tools.py`** — 删除未使用的导入 `SymbolIndex`。

### 🧪 测试：307 通过
- `tests/test_di_container.py::test_creates_all_services` — 从列表中移除 `DebounceBatch`（不再是单例）。
- `tests/test_di_container.py::test_debounce_batch_uses_searcher` — 重写：batch 从 `indexer.bm25_batch` 获取，而非通过 `services.resolve(DebounceBatch)`。
- 所有其他 305 个测试通过，无需更改。

### 📚 迁移说明
- 更新后：`sync_to_installed.bat --full` + 重启 Zed。
- 无需手动修改 `settings.json`（全部通过 `patch_zed_settings`）。

---

## [v2.3.0] — 2026-07-05 — 多窗口支持与加固

### 🏗️ 架构：多窗口
- **`ProjectIndexerRegistry`**（新，`src/core/project_indexer_registry.py`）：
  按项目 `Indexer` 具有惰性创建和 LRU 淘汰（5 个槽位）。
  每个打开的 Zed 窗口获得隔离的 `Indexer`/`FileGuard`/`SymbolIndex`/`db_path` — 窗口切换不再破坏状态。
- **`ResourceMonitor`**（新，`src/core/resource_monitor.py`）：
  仅 stdlib 的 RAM/CPU 监控（`resource.getrusage` + Windows 上的 `ctypes/psapi`，
  无需 `psutil`）。软/硬阈值用于自适应节流。
- **LSP 每个工作区 DI**：`_services_per_workspace[uri]` 替代单个
  全局 `_services`。`init_components(project_root, workspace_uri=...)`。
- **MCP `resolve_indexer_for_request`**：按项目从 registry 获取 indexer
  优先级：显式 kwarg → `resolve_project_root()` → DI 默认。

### 🔧 加固
- **`_safe_close()`**：清空 LanceDB 连接 + 缓存 + `gc.collect()` —
  立即释放 Windows 上的 `.lance` mmap 句柄。
- **自适应节流**：`Indexer.index_project` 在软压力下减慢（0.1 秒），
  在硬压力下停止（最多 2 秒）。
- **HealthReport `_check_resources`**：rss_mb、cpu_percent、线程数、
  registry 统计（缓存/淘汰/命中/未命中）在 `metrics` 中。
- **`async indexer` 可重入**：LSP 中的 `_indexing_serial_lock` 序列化
  `did_open`/`did_change`/`did_save` 之间的 LanceDB 写入。

### 🐛 缺陷修复（审计 INC-53EC，19 个问题）
- `di_container.py:177` — `CircuitBreaker.on_state_change` 中的 `notification_broker` NameError
- `lsp_main.py:372` — `did_change_watched_files` 中未定义的 `_indexer` 全局变量
- `did_change` 去抖 350ms（不每次击键都触发）
- `asyncio.Lock` → `threading.Lock`（跨循环安全：LSP pygls 循环 + MCP asyncio.run 循环）
- Sentinel DI 键（`ProjectRootKey`/`DbPathKey`/`IndexerFactoryKey`）替代 `str`/`type("…")`
- `indexer.set_searcher(searcher)` 替代 `indexer.searcher = …`（封装）
- 通过 `atexit` + `weakref.finalize` 的 `SafePathManager.cleanup`
- `add_columns` LanceDB 迁移替代 `drop+create` 竞态
- `O(N) to_pandas()` 替换为 `table.search().where(...).limit(1)`
- LSP 观察者 glob `**/*.{ext1,ext2,…}`（按扩展名过滤）
- HealthReport 中使用 `cwd=project_path` 的 `git log`
- `HeartbeatService` 类（DI 友好）替代模块全局变量
- `IndexGuard` 协调（之前的 `needs_reindex` 不会卡住）
- `nul` 文件已删除（Windows 保留名称）

### 🔧 Zed 设置
- 从 `patch_zed_settings` 中移除 `current_dir`（Zed 不会在 `current_dir` 中替换 `$ZED_WORKTREE_ROOT` — bug #36019）。`resolve_project_root` 自行处理优先级：PROJECT_PATH env → 桥接 → CWD → ext_root。
- `fix_zed_settings.bat`（新）— 修补用户现有的 `settings.json`（删除带备份的 `current_dir`）。
- 自索引防护：PROJECT_PATH 指向 MSCodeBase → 日志中的警告。

### 🧪 测试：325 → 307 通过（+ 11 新 = 318；11 弃用，减去 = 307）
- `test_resource_monitor.py`（新，11 个测试）：
  - `ResourceMonitor`：采样、节流、压力阈值、摘要、单例模式
  - `ProjectIndexerRegistry`：每个路径单例、LRU 淘汰、压力淘汰、
    显式淘汰、统计（命中/未命中/淘汰次数）
- `test_health_report.py`：降级状态、total_symbols/embedder_mode 别名、
  孤儿文件检测、git log cwd、回退嵌入器警告
- `test_integration.py`：`isolated_indexer` 使用 `temp_project` 作为
  `project_path`（之前有缺陷 — FileGuard 将文件拒绝为"不在项目中"）
- `test_di_container.py`：`Indexer`/`Searcher` 现在通过 registry 按项目分配

### 📚 文档
- README：测试徽章 325 → 307，在功能特性中添加多窗口
- `docs/architecture.md`："多窗口注册表"部分 + ResourceMonitor
- CHANGELOG：本文件
- `pyproject.toml`：升级到 v2.3.0
- AGENT_DIARY.md：3 条记录（审计 + 多窗口 + 资源监控）

### ⚠️ 迁移说明
- 更新后运行 `fix_zed_settings.bat` 以从 `~/.config/Zed/settings.json`（或 `%APPDATA%\Zed\settings.json`）删除 `current_dir`。
- `sync_to_installed.bat --full` 用于与已安装副本同步。
- 重启 Zed 以加载新版本。

---

## [v2.2.0] — 2026-07-04 — 架构现代化

### 🏗 架构重写
- **DI 容器：** 带构造函数注入的 ServiceCollection（15 个服务）
- **server.py：** 3,100 → **220 行**（-93%）。消除了上帝对象。
- **37 个工具**解耦到 `src/mcp/tools/` 中的 10 个领域特定文件
- **error_boundary** 装饰器：统一的 JSON 响应、真正的 `asyncio.wait_for` 超时
- **DebounceBatch：** 500ms 去抖的 BM25 重新索引（不是每个文件都触发）
- **SlidingWindowRateLimiter：** 防止 VFS 循环（最多 10 请求/秒）
- **CircuitBreaker：** 用于 LM Studio 的 CLOSED/OPEN/HALF_OPEN（5 次失败 → 30 秒恢复）
- **hybrid_server.py：** DEPRECATED（所有逻辑在 DI 容器 + lsp_main.py 中）

### 🔧 改进
- `lsp_main.py` — 4 个全局变量 → DI 容器（_services）
- `notify_change` — 立即 BM25 替换为 Rate Limiter + DebounceBatch
- `get_index_progress` — 进度跟踪作为模块级导出
- `read_live_file` — 新工具（从 LSP VFS 读取，带磁盘回退）
- `_resolve_project_path` → 独立的 `resolve_project_root()`
- `GIT_ASKPASS=echo` + `CREATE_NO_WINDOW` — 防止 Windows 上的 Git 挂起
- `_is_complex_query` — 已修复：俄语语法 → 基于标记 + 英语 W-词

### 🧪 测试
- 52 个新单元测试用于：
  - `error_handler.py` — ToolError、error_boundary（异步 + 同步）、超时、重试
  - `rate_limiter.py` — SlidingWindow、DebounceBatch、CircuitBreaker（所有状态）
  - `di_container.py` — ServiceCollection、15 个 DI 服务、Searcher↔Indexer 循环
- 总计：**325 个测试**

### 📚 文档
- README 完全重写：37 个工具、带 DI 的整洁架构
- `docs/ARCHITECTURE.md` — 带 DI 容器 + 工具文件的新架构图
- CONTRIBUTING.md — 更新为新的架构风格
- AGENT_DIARY.md — 5 条记录（所有重构阶段）
- pyproject.toml：升级到 v2.2.0

---

## [v2.1.0] — 2026-07-03

### 🚀 重大变更
- **搜索整合：** `search_code(query, mode)` — 具有 5 种模式的统一工具（auto/fast/quality/deep/context）
- **智能层：** 10 个高级 `intel_*` 工具（自我诊断、拓扑、项目记忆）
- **放弃双写：** `patch_zed_settings()` 现在是单次通过（MCP + LSP + 语言一次调用）
- **项目记忆：** ADR、已知问题、技术债务、失败的尝试 — 跨会话自动保存

### 🔧 改进
- `get_health_report`/`index_health` — `project_root` 可选（回退到 `$PROJECT_PATH`）
- `notify_change` — 从项目根目录（非 CWD）正确解析路径
- `_resolve_project_path()` — 用于解析项目根目录的集中式辅助函数
- 通过 `PROJECT_PATH` 环境变量集中处理路径（由 Zed 设置）
- `install.py` — 清理：删除重复的 LSP 代码（现在在 `patch_zed_settings` 中）

### 📚 文档
- README 完全重写：26 个工具、带 mode 的 search_code、Intel 层
- `docs/architecture.md` — 更新工具列表（14→26 + 10 个 intel_*）
- `docs/windows-setup.md` — 更新为新格式
- `CONTRIBUTING.md` — 删除对已弃用工具的引用
- 为快速源→已安装同步创建 `sync_to_installed.bat`

### 🧹 内务管理
- 删除 `run_tests.py`、`run_tests.bat`（`pytest` 的副本）
- 更新 `.gitignore`（添加开发工件）
- 项目根目录清理了测试垃圾

### ⚠️ 弃用说明
- `smart_search`、`deep_search`、`context_search` → 使用 `search_code(query, mode=...)`
- 旧函数暂时作为包装器工作（向后兼容）

## [v2.0.0] - 2026-06-28

### 🚀 重大变更
- LSP + MCP 混合架构：单一进程共享内存，替代独立服务器
- 完全消除进程间通信 — 降低延迟并简化部署

### ⚠️ 破坏性变更
- 需要从以前的架构迁移到统一的 LSP+MCP 进程
- 编辑器集成点已更改（不再有独立的 MCP 服务器）
- 配置格式已更新

## [v1.4.2] - 2026-06-28

### 🔧 改进
- 从 ThreadPoolExecutor 迁移到 asyncio.gather 用于异步操作
- 改进了对提供程序的并发查询性能

## [v1.4.1] - 2026-06-28

### 🔧 改进
- 为 LM Studio 添加基于嵌入的重排序器
- 提高了搜索结果排名的准确性

## [v1.4.0] - 2026-06-28

### 🚀 重大变更
- 深度调用图，遍历深度 2+ 层
- 扩展了符号依赖分析（调用方/被调方）

## [v1.3.0] - 2026-06-28

### 🔧 改进
- 多提供商重排序：Ollama → LM Studio → RRF 回退
- 提供商不可用时自动切换

## [v1.2.0] - 2026-06-28

### 🚀 重大变更
- 生产就绪版本
- 具有改进语义的 Agentic search v4
- 索引进度跟踪系统

## [v1.1.0] - 2026-06-22

### 🚀 重大变更
- 用于远程嵌入生成的 RemoteEmbedder
- 用于快速部署的完整安装程序

## [v1.0.0] - 2026-06-21

### 🚀 重大变更
- 项目的首次发布
- 基于代码库的基本语义搜索
- 与 LanceDB 集成以实现向量存储
