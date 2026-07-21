# Windows 上的 Zed：陷阱与架构决策

[🇬🇧 English](../en/ZED_WINDOWS_QUIRKS.md) • [🇷🇺 Русский](../ru/ZED_WINDOWS_QUIRKS.md) • [🇨🇳 中文](ZED_WINDOWS_QUIRKS.md)

> 版本：1.2（2026-07-11）— 已更新为 llama.cpp + Vulkan
> 适用于：MSCodeBase Intelligence v2.7.0+
> 详细报告：`investigations/LSP_WONTFIX.md`

## ⚠️ 关键：受限模式（Restricted Mode）

在 Zed 中打开**新**项目（之前未打开过的）时，编辑器会显示**"受限模式（Restricted Mode）"**安全对话框。这不是 bug — 它是 Zed 内置的保护机制。

### 受限模式阻止的内容

| 机制 | 状态 | 后果 |
|-----------|--------|-------------|
| 语言服务器 (LSP) | 🔴 完全阻塞 | `lsp_main.py` 不启动 → 桥接器（bridge）不写入 bridge 文件 |
| 本地 `settings.json` (`.zed/settings.json`) | 🔴 被忽略 | `current_dir` 和 `env` 中的设置不会生效 |
| MCP 服务器 | 🔴 未安装 | 上下文服务器未注册 |

### 如何修复

1. **点击"Trust and Continue"**（或按 `Enter`）
2. **勾选"Trust all projects in D:\Project"** — 这样整个工作区目录都不会再看到此对话框
3. **如果不勾选此复选框**，来自 `D:\Project` 的每个新项目都会再次显示该对话框

### 为什么 MSCodeBase 需要知道这一点

如果项目处于受限模式：
- `LSP Bridge` 不写入 JSON 文件 → `resolve_project_root()` 无法从 LSP 获取项目
- `SQLite DB 回退（fallback）` 仍然有效（从 Zed 的数据库读取 `workspaces`）
- 但 `settings.json` 被忽略 → `current_dir` 不会改变 → CWD 始终指向 Zed 安装目录（例如 `D:\AI\Zed` 或 `C:\Program Files\Zed\`）

---

## 🪟 Windows 特定问题：ZED_WORKTREE_ROOT

**状态：** ⚠️ 在 Windows 上始终为 `<unset>`（Zed bug #36019）

`ZED_WORKTREE_ROOT` 环境变量在 Windows 上未设置。这是一个已知的 Zed bug，已关闭未修复。

### 这意味着什么

- 在 `settings.json` 的 `context_servers` 中，你不能在 `current_dir` 或 `env` 中使用 `$ZED_WORKTREE_ROOT`
- 任何依赖此变量的尝试都会导致 `None`
- 在 Linux/macOS 上此变量设置正确

### MSCodeBase 的解决方案

使用无需 `ZED_WORKTREE_ROOT` 即可工作的回退（fallback）链（见下文）：

1. ~~`LSP Bridge` — LSP 通过 LSP 协议获取 `root_uri`~~
   **在 Windows 上不起作用** — LSP 服务器未启动（参见
   [`LSP_WONTFIX.md`](investigations/LSP_WONTFIX.md)）。
2. `SQLite DB` — 从 Zed 的数据库读取 `workspaces`（主要工作路径）
3. `.env` 中的 `PROJECT_PATH` — 手动指定项目

---

## 🔧 resolve_project_root 链（优先级）

MCP 服务器按以下顺序确定当前项目：

```
[来自工具的请求]
    │
    ▼
1. 显式传递了 project_root？ ──(是)──> 使用它
    │ (否)
    ▼
2. LSP Bridge 文件存在？ ──(Windows 上为 NO — LSP 未启动)──> 步骤 3
3. SQLite Zed DB 可访问？ ──(是)──> 读取 workspaces，
    │                                 过滤自索引，
    │                                 按 .git + 时间戳排序
    │ (否 / 数据库锁定)
    ▼
4. .env 中的 PROJECT_PATH？ ──(是)──> 使用它
    │ (否)
    ▼
5. CWD（始终为 Zed 安装目录，例如 `D:\AI\Zed`）──> 自索引保护
    │                       ──> 回退到 ext_root
    ▼
                ⚠️ 自诊断模式
```

### 多窗口：MCP 不区分窗口

**问题：** 所有 MCP 工具（除 `intel_*` 外）都作用于**单个项目** — `resolve_project_root()` 选择的默认项目。如果你打开了多个不同项目的窗口，`intel_get_runtime_status()` 将显示默认项目的索引，而不是你当前所在的窗口。

**原因：** MCP 服务器是所有 Zed 窗口的单一进程。它不知道请求来自哪个窗口。在 macOS/Linux 上，`ZED_WORKTREE_ROOT` 解决了这个问题，在 Windows 上它始终为 `<unset>`。

**解决方法：**
- 对于 `intel_*` 工具：它们会自动找到第一个非自索引项目
- 对于 `intel_get_runtime_status`：关闭其他窗口，只保留目标项目
- 对于 `search_code`：传递显式的 `project_root`（如果工具支持）

---

### 步骤 3：SQLite DB（Zed 的数据库）— 工作原理

**这不是我们的数据库。** 这是 Zed 自己的数据库，存储打开的项目（工作区）。我们只读取它（只读）。
```
%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite
```

它读取 `workspaces` 表：
```sql
SELECT paths, timestamp FROM workspaces ORDER BY timestamp DESC
```

**重要：** 列名是 `paths`，不是 `absolute_path`。选择最近（按 `timestamp`）的非自索引工作区（如果路径匹配扩展或 Zed 目录则拒绝）。

**我们的数据库 (LanceDB)** — 向量代码索引，存储在项目内部：

| 项目 | 索引路径 |
|---------|---------------|
| `MSCodeBase` | `D:\Project\MSCodeBase\.codebase_indices\lancedb_v2\` |
| `gemma_agent` | `D:\Project\gemma_agent\.codebase_indices\lancedb_v2\` |

每个项目都有**自己独立的索引**。当扩展被删除时，索引保留在项目中。当项目被删除时 — 索引丢失。

**`.codebase_indices/` 中还存储了什么：**（项目内部）

| 目录 | 用途 |
|-----------|---------|
| `lancedb_v2/` | LanceDB 向量数据库（代码索引：块（chunk）+ 嵌入） |
| `branches/` | Git 分支：隔离的按分支索引 |
| `commit_memory/` | 提交历史和语义分析 |
| `intelligence/` | 项目记忆（ADR, known_issues, tech_debt） |

**日志**（v2.4.6 之后）：集中在扩展目录中，不在项目中：
```
%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\.codebase_indices\logs\
```

**Zed 的数据库本身**（我们只读取）：
```
%LOCALAPPDATA%\Zed\db\0-stable\db.sqlite
```

**自索引过滤：** 匹配 `ext_root`、`Zed 安装目录`或系统目录的路径将被丢弃。

**多窗口：** 有多个打开窗口时，选择得分最高的项目（2 = 有 `.git`，1 = 无 `.git`），然后按最新的 `updated_at`。

### 步骤 2：LSP Bridge — 为什么可能为空

```
🌉 BRIDGE: NO JSON FILES — LSP DIDN'T WRITE project_root!
  原因：
  1. 受限模式（未点击"Trust and Continue"）
  2. LSP 启动时崩溃（检查：intel_get_runtime_status）
  3. Python 文件未打开 — LSP 仅在编辑器中打开
     .py/.rs/... 文件时启动
```

---

## 📁 CWD = Zed 启动位置

**重要：** MCP 进程的 CWD（工作目录）继承自 Zed 本身。在 Windows 上，`settings.json` 中的 `current_dir` 无法解析 `$ZED_WORKTREE_ROOT`，因此 MCP 服务器的 CWD = Zed 进程的 CWD。

如果 Zed 从以下位置启动：
- `cmd` 或 `powershell` → CWD 将是启动时的文件夹
- 快捷方式 / 开始菜单 → CWD 通常是包含 `zed.exe` 的目录
- `D:\AI\Zed`（像你的情况）→ CWD = `D:\AI\Zed`

---

## 🔒 其他 Zed 机制

### 动态沙箱（Dynamic Sandbox）

Zed 使用受限的 Windows 权限启动 MCP 服务器。如果进程需要提升的权限（Win32 API，受保护的系统文件夹），操作系统将返回 `Access Denied`。

**解决方案：** 整个索引存储在项目根目录的 `.codebase_indices/` 中 — 进程始终拥有写入权限。

### LSP 初始化超时（约 10-15 秒）

如果 `lsp_main.py` 在 10-15 秒内未响应 `initialize`，Zed 会杀死 LSP 进程，并且在窗口重新加载之前**不会尝试重新启动它**。

**解决方案：** LSP 必须立即返回 `READY`（< 2 秒）。繁重的工作放入后台线程。

### 文件监视器敏感性（File Watcher Sensitivity）

Zed 使用排他锁锁定打开的文件。如果第三方进程（索引器、遥测收集器）过于激进地修改工作区根目录中的文件，Zed 可能会暂时冻结其监视器。

**解决方案：** 连接缓存。严格在 `.codebase_indices/` 中索引文件。

### Windows UNC 路径规范化（UNC Path Normalization）

Windows 路径可能有 `\\?\` 前缀（UNC）。比较路径时，`D:\Project` 和 `\\?\D:\Project` 被视为**不同的字符串**，但它们指向同一目录。

**解决方案：** 比较路径时始终使用 `Path(p).resolve()`。这会去除 UNC 前缀。

---

## 📋 在新电脑上的设置检查清单

1. ✅ 通过 `install.py` 安装扩展
2. ✅ 在项目中打开任意 `.py` 文件
3. ✅ 出现对话框时点击"Trust and Continue"
4. ✅ 勾选"Trust all projects in ..."
5. ✅ 检查 `intel_get_runtime_status` — project_path 应为项目路径，而不是 `ext_root`
6. 如果 `project_path` 显示 ext_root — 打开一个文件并检查步骤 3
7. ✅ 运行 `intel_get_telemetry` — 验证数据正在收集

---

## 📊 故障排除

| 症状 | 查看 | 命令 |
|---------|---------|---------|
| MCP 不知道项目 | 日志：`resolve_project_root: fallback to ext_root` | `intel_get_runtime_status` |
| LSP 不启动 | 日志：`BRIDGE: NO JSON FILES` | 见下文"Zed 1.9.0 中 LSP 不启动"部分 |
| 索引为空 | 状态：0 个块（chunk） | `intel_get_runtime_status` |
| 工具未就绪 | 状态：UNINITIALIZED | 在项目中打开一个文件 |
| 数据库被锁定 | 日志：`database is locked` | 关闭带有该项目的其他窗口 |

---

## 🚫 Zed 1.9.0 中 LSP 不启动（WONTFIX）

**状态：** ⚠️ Zed 1.9.0 在 Windows 上的已知限制。带有源代码引用的详细报告：[`LSP_WONTFIX.md`](investigations/LSP_WONTFIX.md)。

### 什么不起作用

LSP 服务器 `mscodebase-lsp`（Python，`src/lsp_main.py`，基于 pygls）**无法**通过 `settings.json` **注册**。无论我们在 `lsp.<id>.binary.path` 或 `languages.<lang>.language_servers` 中写什么，Zed 都无法在其 `LanguageRegistry` 中找到名为 `mscodebase-lsp` 的适配器，并在 `lsp_store.rs:start_language_server` 中以 panic `expect("To find LSP adapter")` 崩溃。

### 真正原因（来自 Zed 源代码）

来自 `crates/project/src/lsp_store.rs`：

```rust
let adapter = self.languages
    .lsp_adapters(language_name)
    .into_iter()
    .find(|adapter| adapter.name() == disposition.server_name)
    .expect("To find LSP adapter");
```

`lsp_adapters(name)` 仅从以下来源返回适配器：
1. **内置语言** — `crates/languages/src/*.rs`（Python，Rust，Go）
   带有硬编码的 LSP 适配器。
2. **加载的 WASM 扩展** — `extension.toml` + 编译的
   `extension.wasm`，带有 `impl zed::Extension::language_server_command`。

`settings.json` 中的 `lsp.<id>.binary.path` 是**已注册适配器的路径覆盖**，而不是新适配器的注册。**这是设计使然，不是 bug。**

### 这对 MSCodeBase 意味着什么

- **编辑器中通过 mscodebase-lsp 的 LSP 功能（inlay-hints、code-actions、自动补全）在 Zed 1.9.0 Windows 上是不可能的。**
**所有语义和搜索继续通过 MCP 工作** — 37 个工具，
- **LSP 桥接器（bridge）（来自 LSP 的 project_root）** 仍然为空，但 `resolve_project_root()` 通过 SQLite 回退（fallback）补偿了这一点。

### 为什么 settings.json 显示 Serde 错误

来自 `crates/settings_content/src/language.rs`：

```rust
#[schemars(range(min = 1, max = 128))]
pub tab_size: Option<NonZeroU32>,
```

错误 `expected a nonzero u32` **不是关于 `language_servers`**，而是关于同一结构体中的 `tab_size`（或另一个带有 `NonZeroU32` 的字段）。使用 `with_failible_options` 的解析器将此字段重置为 `None`，并在 UI 中显示 `Invalid user settings file` 警告。**LSP 并非因此崩溃 — 它甚至不会尝试启动，因为适配器名称不在注册表中。**

### 应该怎么做

#### 现在（v2.4.4+ 版本）

1. **不要在 `settings.json` 中注册 `mscodebase-lsp`** — 这会在 UI 中产生错误，且没有任何用处。
2. **对所有操作使用 MCP** — 它不依赖于 LSP。
3. **通过 `scripts/check_lsp_health.py` 检查 LSP 状态** — 该脚本会写入清晰的报告"LSP not registered / not starting"，而不是无信息的 Serde 错误。

#### 未来（v3.0+）

- **编写 Rust 封装**（通过 `wasm32-wasip2` 的 WASM），带有 `impl zed::Extension::language_server_command`，调用 `python -m src.lsp_main`。通过 `zed: install dev extension` 安装。这是让 LSP 在 Zed 中工作的唯一方法。
- **或者替换 `pyright`** 通过 `lsp.pyright.binary.path` — 工作量最小，但我们的 LSP 将冒充他人的身份。适用于编辑器内高亮很重要而适配器唯一性不重要的场景。
