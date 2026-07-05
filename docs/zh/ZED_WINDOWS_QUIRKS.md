# Zed 在 Windows 上：注意事项和架构决策

> 版本：1.1（2026-07-05）— 更新了「LSP 无法启动」部分
> 适用于：MSCodeBase Intelligence v2.4.4+
> 详细报告：`../en/investigations/LSP_WONTFIX.md`

[🇬🇧 English](../en/ZED_WINDOWS_QUIRKS.md) • [🇷🇺 Русский](../ru/ZED_WINDOWS_QUIRKS.md) • [🇨🇳 中文](ZED_WINDOWS_QUIRKS.md)

## ⚠️ 至关重要：受限模式（安全模式）

在 Zed 中打开**新的**项目（之前未打开过的）时，编辑器会显示**"受限模式"**安全对话框。这**不是**缺陷 — 这是 Zed 的内置保护。

### 受限模式阻止了什么

| 机制 | 状态 | 后果 |
|----------|--------|-------------|
| 语言服务器（LSP） | 🔴 完全被阻止 | `lsp_main.py` 无法启动 → 桥接无法写入桥接文件 |
| 本地 `settings.json`（`.zed/settings.json`） | 🔴 被忽略 | 设置中的 `current_dir` 和 `env` 不生效 |
| MCP 服务器 | 🔴 无法建立 | 上下文服务器无法注册 |

### 如何解决

1. **点击"Trust and Continue"**（或按 `Enter`）
2. **勾选"Trust all projects in D:\Project"** — 这样就不再为整个工作目录显示此对话框
3. **不勾选此选项**则来自 `D:\Project` 的每个新项目都会再次显示对话框

### 为什么 MSCodeBase 需要知道这一点

如果项目处于受限模式：
- `LSP 桥接`不写入 JSON 文件 → `resolve_project_root()` 无法从 LSP 获取项目
- `SQLite 数据库回退`**仍然**正常工作（从 Zed 数据库读取 `workspaces`）
- 但 `settings.json` 被忽略 → `current_dir` 不变 → CWD 始终指向 Zed 安装目录（例如 `D:\AI\Zed` 或 `C:\Program Files\Zed\`）

---

## 🪟 Windows 特性：ZED_WORKTREE_ROOT

**状态：** ⚠️ 在 Windows 上始终为 `<unset>`（Zed bug #36019）

环境变量 `ZED_WORKTREE_ROOT` 在 Windows 上**未设置**。这是已知的 Zed 缺陷，已关闭但未修复。

### 这意味着什么

- 在 `settings.json` 中为 `context_servers` 不能在 `current_dir` 或 `env` 中使用 `$ZED_WORKTREE_ROOT`
- 任何依赖此变量的尝试都会导致 `None`
- 在 Linux/macOS 上，此变量设置正确

### MSCodeBase 中的解决方案

使用无需 `ZED_WORKTREE_ROOT` 的回退链（见下文）：

1. ~~`LSP 桥接` — LSP 通过 LSP 协议接收 `root_uri`~~
   **在 Windows 上不起作用** — LSP 服务器无法启动（参见
   `docs/investigations/2026-07-05-lsp-zed-1.9.0.md`）。
2. `SQLite 数据库` — 从 Zed 数据库读取 `workspaces`（主要工作路径）
3. `PROJECT_PATH` 来自 `.env` — 手动指定项目

---

## 🔧 resolve_project_root 链（优先级）

MCP 服务器按以下顺序确定当前项目：

```
[来自工具请求]
    │
    ▼
1. 传入了显式 project_root？──（是）──> 使用它
    │ （否）
    ▼
2. LSP 桥接文件存在？──（在 Windows 上为否 — LSP 不启动）──> 步骤 3
3. Zed SQLite 数据库可访问？──（是）──> 读取 workspaces，
    │                                 过滤自索引，
    │                                 按 .git + 时间戳排序
    │ （否 / 数据库被锁定）
    ▼
4. 来自 .env 的 PROJECT_PATH？──（是）──> 使用它
    │ （否）
    ▼
5. CWD（始终为 Zed 安装目录，例如 `D:\AI\Zed`）──> 自索引防护
    │                       ──> 回退到 ext_root
    ▼
                ⚠️ 自我诊断模式
```

### 多窗口：MCP 不区分窗口

**问题：** 所有 MCP 工具（除了 `intel_*`）都处理**一个项目** — 即 `resolve_project_root()` 选择的默认项目。如果您打开多个包含不同项目的窗口，`get_index_status()` 将显示默认项目的索引，而不是当前窗口所在的索引。

**为什么：** MCP 服务器是所有 Zed 窗口的一个进程。它不知道请求来自哪个窗口。在 macOS/Linux 上，`ZED_WORKTREE_ROOT` 解决了这个问题，在 Windows 上它始终为 `<unset>`。

**如何规避：**
- 对于 `intel_*` 工具：它们自行查找第一个非自索引项目
- 对于 `get_index_status`：关闭多余窗口，只保留所需项目
- 对于 `search_code`：传递显式的 `project_root`（如果工具支持）

---

### 步骤 3：SQLite 数据库（Zed 数据库）— 工作原理

**这不是我们的数据库。** 这是 Zed 自身的数据库，存储已打开的项目（workspaces）。我们只读取它（只读）。
```
%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite
```

读取 `workspaces` 表：
```sql
SELECT paths, timestamp FROM workspaces ORDER BY timestamp DESC
```

**重要：** 列名为 `paths`，而不是 `absolute_path`。选择最新的 workspace（按 `timestamp`），该 workspace 不是自索引的（如果路径与扩展目录或 Zed 目录匹配则拒绝）。

**我们的数据库（LanceDB）** — 代码的向量索引，存储在项目**内部**：

| 项目 | 索引路径 |
|--------|---------------|
| `MSCodeBase` | `D:\Project\MSCodeBase\.codebase_indices\lancedb_v2\` |
| `gemma_agent` | `D:\Project\gemma_agent\.codebase_indices\lancedb_v2\` |

每个项目都有**自己的隔离索引**。删除扩展时，索引保留在项目中。删除项目时，索引丢失。

**`.codebase_indices/` 中还存储什么：**（在项目内部）

| 目录 | 用途 |
|-----------|-----------|
| `lancedb_v2/` | LanceDB 向量数据库（代码索引：块 + 嵌入） |
| `branches/` | Git 分支：按分支隔离的索引 |
| `commit_memory/` | 提交历史和语义分析 |
| `intelligence/` | 项目记忆（ADR、已知问题、技术债务） |

**日志**（v2.4.6 之后）：集中在扩展目录中，**不在**项目中：
```
%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\
```

**Zed 自身的数据库**（我们只读取）：
```
%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite
```

**自索引过滤：** 匹配 `ext_root`、`Zed 安装目录`或系统目录的路径被丢弃。

**多窗口：** 当多个窗口打开时，选择得分最高的项目（2 = 有 `.git`，1 = 无 `.git`），然后按 `updated_at` 的时间新鲜度排序。

### 步骤 2：LSP 桥接 — 为什么可能为空

```
🌉 桥接：无 JSON 文件 — LSP 未写入 project_root！
  原因：
  1. 受限模式（未点击"Trust and Continue"）
  2. LSP 启动时崩溃（检查：intel_get_runtime_status）
  3. Python 文件未打开 — LSP 仅在打开 .py/.rs/... 文件时启动
```

---

## 📁 CWD = Zed 启动位置

**重要：** MCP 进程的 CWD（工作目录）继承自 Zed 自身。在 Windows 上，`settings.json` 中的 `current_dir` 不会解析 `$ZED_WORKTREE_ROOT`，因此 MCP 服务器的 CWD = Zed 进程的 CWD。

如果 Zed 从以下位置启动：
- `cmd` 或 `powershell` → CWD 将是启动时的文件夹
- 快捷方式 / 开始菜单 → CWD 通常为 `zed.exe` 所在目录
- `D:\AI\Zed`（就像您的情况）→ CWD = `D:\AI\Zed`

---

## 🔒 Zed 的附加机制

### 动态沙箱

Zed 使用受限的 Windows 权限运行 MCP 服务器。如果进程需要提升的权限（Win32 API、受保护的系统文件夹），系统会返回 `Access Denied`。

**解决方案：** 所有索引存储在项目根目录的 `.codebase_indices/` 内 — 进程在那里始终有写权限。

### LSP 初始化超时（约 10-15 秒）

如果 `lsp_main.py` 未能在 10-15 秒内响应 `initialize`，Zed 会终止 LSP 进程，并且在窗口重新加载前**不再尝试重启它**。

**解决方案：** LSP 必须立即（< 2 秒）返回 `READY`。繁重工作放入后台线程。

### 文件观察器敏感性

Zed 使用独占锁锁定打开的文件。如果第三方进程（索引器、遥测收集器）过于频繁地修改工作区根目录中的文件，Zed 可能暂时冻结观察器。

**解决方案：** 缓存连接。索引文件严格放在 `.codebase_indices/` 中。

### Windows UNC 路径规范化

Windows 上的路径可能有 `\\?\` 前缀（UNC）。比较路径时 `D:\Project` 和 `\\?\D:\Project` 被视为**不同**的字符串，但指向同一目录。

**解决方案：** 比较路径时始终使用 `Path(p).resolve()`。这会去除 UNC 前缀。

---

## 📋 在新电脑上安装时的检查清单

1. ✅ 通过 `install.py` 安装扩展
2. ✅ 在项目中打开任意 `.py` 文件
3. ✅ 对话框出现时点击"Trust and Continue"
4. ✅ 勾选"Trust all projects in ..."
5. ✅ 检查 `intel_get_runtime_status` — project_path 应为项目路径，**而非** `ext_root`
6. 如果 `project_path` 显示 ext_root — 打开文件并检查步骤 3
7. ✅ 运行 `intel_get_telemetry` — 检查数据是否正在收集

---

## 📊 问题诊断

| 症状 | 查看 | 命令 |
|---------|----------|---------|
| MCP 不知道项目 | 日志：`resolve_project_root: fallback to ext_root` | `intel_get_runtime_status` |
| LSP 无法启动 | 日志：`桥接：无 JSON 文件` | 见下方「LSP 在 Zed 1.9.0 上无法启动」部分 |
| 索引为空 | 状态：0 个块 | `get_index_status` |
| 工具未就绪 | 状态：UNINITIALIZED | 在项目中打开文件 |
| 数据库被锁定 | 日志：`database is locked` | 关闭其他包含项目的窗口 |

---

## 🚫 LSP 在 Zed 1.9.0 上无法启动（WONTFIX）

**状态：** ⚠️ Zed 1.9.0 在 Windows 上的已知限制。包含源代码引用和链接的详细报告：`docs/investigations/2026-07-05-lsp-zed-1.9.0.md`。

### 什么不起作用

LSP 服务器 `mscodebase-lsp`（Python，`src/lsp_main.py`，基于 pygls）**无法**通过 `settings.json` 注册。无论我们在 `lsp.<id>.binary.path` 或 `languages.<lang>.language_servers` 中写什么，Zed 都找不到名为 `mscodebase-lsp` 的适配器在其 `LanguageRegistry` 中，并在 `lsp_store.rs:start_language_server` 中以 `expect("To find LSP adapter")` 崩溃。

### 真实原因（来自 Zed 源代码）

来自 `crates/project/src/lsp_store.rs`：

```rust
let adapter = self.languages
    .lsp_adapters(language_name)
    .into_iter()
    .find(|adapter| adapter.name() == disposition.server_name)
    .expect("To find LSP adapter");
```

`lsp_adapters(name)` 仅从以下来源返回适配器：
1. **内置语言** — `crates/languages/src/*.rs`（Python、Rust、Go），带有硬编码的 LSP 适配器。
2. **已加载的 WASM 扩展** — `extension.toml` + 编译后的 `extension.wasm`，带有 `impl zed::Extension::language_server_command`。

`settings.json` 中的 `lsp.<id>.binary.path` — 这是对已注册适配器**路径的覆盖**，而不是注册新适配器。**这是设计如此，不是缺陷。**

### 这对 MSCodeBase 意味着什么

- **编辑器中的 LSP 功能（mscodebase-lsp 的嵌入提示、代码操作、自动补全）在 Zed 1.9.0 Windows 上不可用。**
- **所有语义和搜索通过 MCP 继续工作** — 43 个工具、按 `layer` 过滤、通过 `get_chunks_by_parent_id()` 的多粒度检索、遥测、ETAPredictor。这足以覆盖 95% 的代码辅助场景。
- **LSP 桥接（来自 LSP 的 project_root）** 保持为空，但 `resolve_project_root()` 通过 SQLite 回退弥补了这一点。

### 为什么 settings.json 中出现 Serde 错误

来自 `crates/settings_content/src/language.rs`：

```rust
#[schemars(range(min = 1, max = 128))]
pub tab_size: Option<NonZeroU32>,
```

错误 `expected a nonzero u32` — 这是**关于 `language_servers` 的错误**，而是关于同一结构体中的 `tab_size`（或其他带有 `NonZeroU32` 的字段）。使用 `with_fallible_options` 的解析器将此字段重置为 `None` 并在 UI 中显示 `Invalid user settings file` 横幅。**LSP 不会因此崩溃 — 它根本不会尝试启动，因为适配器名称不在注册表中。**

### 该怎么做

#### 现在（v2.4.4+ 版本）

1. **不要在 `settings.json` 中注册 `mscodebase-lsp`** — 这会在 UI 中产生虚假错误，且不提供任何有用的功能。
2. **对所有操作使用 MCP** — 它不依赖 LSP。
3. **通过 `scripts/check_lsp_health.py` 检查 LSP 状态** — 脚本将输出清晰的报告「LSP 未注册 / 无法启动」，而不是无信息的 Serde 错误。

#### 长远来看（v3.0+）

- **编写 Rust 包装**（通过 `wasm32-wasip2` 的 WASM），带有 `impl zed::Extension::language_server_command`，它调用 `python -m src.lsp_main`。通过 `zed: install dev extension` 安装。这是在 Zed 中运行 LSP 的唯一途径。
- **或者替换 `pyright`** 通过 `lsp.pyright.binary.path` — 工作量最小，但我们的 LSP 会伪装成其他人的。适用于重视编辑器内高亮而非适配器唯一性的场景。
