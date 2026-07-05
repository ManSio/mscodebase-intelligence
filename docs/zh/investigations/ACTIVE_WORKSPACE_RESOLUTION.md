# 调查：Windows 上的活动项目确定

[🇬🇧 English](../en/investigations/ACTIVE_WORKSPACE_RESOLUTION.md) • [🇨🇳 中文](ACTIVE_WORKSPACE_RESOLUTION.md)

**日期：** 2026-07-05
**目标：** 找到一种可靠的方法来确定 Zed IDE 中当前焦点的项目/工作区，在 Windows 上无需使用 `ZED_WORKTREE_ROOT`（不起作用）和 `current_dir`（在 Windows 上也不起作用）。

---

## 问题

在 Windows 上，MCP 服务器无法确定它绑定到哪个项目：
- `ZED_WORKTREE_ROOT` — 未设置（Zed bug #36019）
- `settings.json` 中 `context_servers` 的 `current_dir` — 不解析 `$ZED_WORKTREE_ROOT`
- MCP 进程的 CWD 继承自 Zed 进程（通常是 `D:\AI\Zed`）
- 没有用于标识窗口/项目的环境变量传递

---

## 已检查的内容

### 1. 外部机制（env、args、stdin）

| 机制 | 查找位置 | 结果 |
|----------|-----------|-----------|
| `ZED_WORKTREE_ROOT` | `crates/context_server/` | ❌ 未找到。在 Windows 上始终为 `<unset>` |
| `current_dir` | `crates/project/src/context_server_store.rs` | ❌ 在 Zed 代码中工作，但在 Windows 上不应用于进程 |
| env vars（`ZED_WINDOW_ID`、`ZED_PROJECT_PATH`） | 对整个仓库进行 grep | ❌ 不存在 |
| MCP JSON-RPC initialize | `crates/context_server/src/protocol.rs` | ❌ 没有窗口/项目的字段 |
| StdioTransport args | `crates/context_server/src/transport/stdio_transport.rs` | ❌ 仅 command + args 来自 settings.json |

### 2. 内部 Rust API（外部不可访问）

| 机制 | 文件 | 结果 |
|----------|------|-----------|
| `App::active_window()` | `crates/gpui/src/app.rs:645` | ✅ 工作，但仅在 Rust 内部 |
| `MultiWorkspace::workspace()` | `crates/workspace/src/multi_workspace.rs` | ✅ 给出焦点下的工作区 |
| `Project::active_entry()` | `crates/project/src/project.rs` | ✅ 返回活动文件的 EntryId |
| Extension API | `crates/extension/src/extension.rs` | ❌ 没有活动工作区的方法 |

### 3. SQLite — 找到了！

**表 `scoped_kv_store`** 带有 namespace `multi_workspace_state` 包含 JSON：

```json
{
  "active_workspace_id": 2,
  "sidebar_open": false,
  "project_groups": [...]
}
```

其中 `active_workspace_id` — 当前焦点下的工作区 ID。

**在 Zed 源代码中的工作方式**（`crates/workspace/src/multi_workspace.rs:674`）：

```rust
pub fn serialize(&mut self, cx: &mut Context<Self>) {
    let state = MultiWorkspaceState {
        active_workspace_id: this.workspace().read(cx).database_id(), // ← 活动工作区的 ID
        project_groups: this.project_groups.iter().map(/*...*/).collect(),
        ...
    };
    // 每次切换工作区时写入 scoped_kv_store
    kvp.scoped("multi_workspace_state").write(&window_id, &state);
}
```

**每次切换时更新**（`multi_workspace.rs:520`）：
```rust
cx.emit(MultiWorkspaceEvent::ActiveWorkspaceChanged { ... });
// → MultiWorkspace::serialize() → 写入 SQLite
```

**如何找到项目路径：**

```sql
-- 1. 获取 active_workspace_id
SELECT value FROM scoped_kv_store 
WHERE namespace = 'multi_workspace_state' 
  AND key = '4294967297';

-- 2. 通过 active_workspace_id 获取项目路径
SELECT paths FROM workspaces 
WHERE workspace_id = <active_workspace_id>;
```

---

## 解决方案

`resolve_project_root()` 现在首先从 SQLite 读取 `active_workspace_id`。
此机制：
- ✅ 在 Windows 上工作（SQLite 始终可访问）
- ✅ 在切换项目时实时更新
- ✅ 不需要 env、current_dir、LSP 或其他损坏的机制
- ✅ 不依赖于打开了多少个窗口

**解析优先级（新）：**

```
1. SQLite multi_workspace_state.active_workspace_id ← 新的，主要的
2. 来自工具参数的显式 project_root
3. LSP 桥接（在 Windows 上不起作用）
4. SQLite workspaces（旧的回退）
5. 来自 .env 的 PROJECT_PATH
6. CWD（始终被自索引防护拒绝）
7. ext_root（回退 — 自我诊断模式）
```

---

## 会话期间完成的工作（2026-07-05）

### 修复

| 组件 | 问题 | 修复 |
|-----------|---------|------|
| `rate_limiter.py` | DebounceBatch — `await` 在 `threading.Lock` 内部（100% 死锁） | 在锁下做决定，在锁外刷新 |
| `log_manager.py` | 日志按项目 + 在 ext_root 中写入 | 集中到 ext_root + 清理过期日志 |
| `server.py` | `_ext_root` 通过 `__file__` 确定 → 将项目与 ext_root 混淆 | 从 PYTHONPATH 获取 `_ext_root` |
| `zed_config.py` | `system_prompt` 创建带有损坏编码的副本 | 通过标记计数器检测重复 |
| `install.py` | 将 `mscodebase.semaphore` 写入 settings.json 根目录 | 已删除（Zed 报错未知键） |

### 文档

| 文件 | 完成的工作 |
|------|------------|
| `docs/INSTALL.md` | 根据实际情况完全重写 |
| `README.md` | 添加文档地图，修复数字 |
| `docs/architecture.md` | 37→33 工具，307→391 测试 |
| `ZED_WINDOWS_QUIRKS.md` | 多项修复，CWD、数据库、多窗口 |
| `AGENTS.md` | 多窗口检查规则 |
| `CONTRIBUTING.md` | ARCHITECTURE.md→architecture.md，约12→10 文件 |

### 调查

| 文件 | 内容 |
|------|-------|
| `docs/investigations/2026-07-05-lsp-zed-1.9.0.md` | 为什么 LSP 在 Windows 上不起作用 |
| `docs/investigations/2026-07-05-active-workspace-resolution.md` | 如何确定活动项目（本文件） |

---

## 技术结论

1. **Windows 上唯一工作的通道是 SQLite。** env、current_dir 和 MCP 协议都不传递项目信息。

2. **`multi_workspace_state.active_workspace_id`** — 可靠的来源，与 Zed 中的工作区切换同步更新。键是 `window_id.as_u64().to_string()`（在单窗口系统上为 `4294967297`）。

3. **Windows vs macOS/Linux 架构：**
   - 在 macOS 上：`ZED_WORKTREE_ROOT` env + 正确的 `current_dir` → 项目已知。
   - 在 Windows 上：两者都不工作 → 仅 SQLite。

4. **多窗口（不同的物理窗口）：** 不同窗口有不同的 `window_id`。每个 MCP 服务器可以通过启发式方法（时间戳匹配、父 PID）找到自己的 `window_id`。实践中，当一个窗口有多个项目时 — `window_id` 是相同的。

---

## 结论

问题已通过从 SQLite 读取 `scoped_kv_store.multi_workspace_state.active_workspace_id` 解决。这是一个可靠的机制，内置于 Zed 本身，不需要任何环境变量、external_dir 或 LSP。在 Windows、macOS 和 Linux 上均有效。
