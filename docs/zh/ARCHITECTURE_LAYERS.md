# 架构层 — MSCodeBase Intelligence

[🇬🇧 English](../en/ARCHITECTURE_LAYERS.md) • [🇷🇺 Русский](../ru/ARCHITECTURE_LAYERS.md) • [🇨🇳 中文](ARCHITECTURE_LAYERS.md)

每一层恰好回答一个问题。

```
 第 0 层：文件系统        — 磁盘上有哪些文件？
 第 1 层：SystemArtifacts   — 这是系统路径吗？
 第 2 层：桥接            — LSP 报告了哪个项目？
 第 3 层：注册表          — 哪个 Indexer 属于此项目？
 第 4 层：状态机          — 项目处于什么状态？
 第 5 层：RuntimeCoordinator — 可以执行请求吗？
 第 6 层：ProjectContext    — 项目当前看起来如何？
 第 7 层：护照          — 当前运行的是哪个进程？
 第 8 层：Intel 层       — 如何处理这些信息？
 第 9 层：AI 代理          — 返回给用户
```

---

## 第 0 层 — 文件系统

**问题：** 磁盘上有哪些文件？
**代码：** `os.walk`、`Path.rglob`、`FileGuard`
**不知道：** 关于索引、MCP、LSP。

---

## 第 1 层 — SystemArtifacts

**问题：** 这是系统路径吗？
**代码：** `SystemArtifacts.is_system_path()`
**不知道：** 关于 Registry、Bridge、Runtime、Indexer。

4 个子级保护：
1. **目录防护** — `.mscodebase/`、`.codebase_indices/`、`.git/`、`node_modules/`
2. **工件防护** — `chunk_summaries.json`、`incidents.json`、`project_memory.json`
3. **反馈防护** — 索引器自身创建的文件
4. **嵌入防护** — 嵌入前的最终检查

**规则：** `.mscodebase/` 或 `.codebase_indices/` 内的任何文件 = 不索引。

---

## 第 2 层 — 桥接（LSP→MCP）

**问题：** LSP 当前报告了哪个项目？
**代码：** `read_project_from_bridge()`、`write_active_project()`
**不知道：** 关于索引、Runtime。

桥接 — 临时文件（~/.mscodebase/bridge/session_*.json），
LSP 在每次 didOpen/didSave 时写入。MCP 在需要确定 project_root 时读取。

---

## 第 3 层 — 注册表（ProjectIndexerRegistry）

**问题：** 哪个 Indexer 属于此项目？
**代码：** `ProjectIndexerRegistry.get_indexer(path)`
**不知道：** 关于 MCP、Bridge、Runtime。

每个项目的单例 Indexer，带有 LRU 淘汰（最多 5 个）。
每个项目有自己的 LanceDB 锁。

---

## 第 4 层 — 状态机

**问题：** 项目处于什么状态？
**代码：** `ProjectIndexerRegistry.get_state()`、`wait_until_ready()`
**不知道：** 关于 Bridge、MCP 请求。

```
UNINITIALIZED → STARTING → INDEXING → READY → FAILED
```

---

## 第 5 层 — RuntimeCoordinator

**问题：** 可以执行 MCP 请求吗？
**代码：** `RuntimeCoordinator.can_execute()`
**不知道：** 关于代码结构、搜索。

使用：
- SystemArtifacts（第 1 层）— 路径不是系统路径吗？
- Bridge（第 2 层）— LSP 同步了吗？
- Registry + StateMachine（第 3-4 层）— 项目就绪了吗？

返回 `ExecutionVerdict`：
- `ok` — 可以执行
- `reason` — 原因（ready / system_path / project_not_ready / ...）
- `retry_after` — 多久后重试
- `requires_reindex` — 需要重新索引
- `warnings` — 警告

---

## 第 6 层 — ProjectContext

**问题：** 项目当前看起来如何？
**代码：** `ProjectContext.capture()`
**不知道：** 关于 MCP 请求，不启动操作。

返回快照：
- state、index（chunks/files/symbols）、bridge、runtime（PID/uptime）、
  health（warnings/errors）、memory（incidents/ADRs）、jobs

---

## 第 7 层 — 护照

**问题：** 当前运行的是哪个进程？
**代码：** `debug_runtime_passport()` — MCP 工具
**不知道：** 关于索引状态。

显示：RUN_ID、BUILD_ID、PID、运行时间、ext_root、project_root、
env（PROJECT_PATH、ZED_WORKTREE_ROOT、PYTHONPATH）、防护结果。

---

## 第 8 层 — Intel 层

**问题：** 如何处理这些信息？
**代码：** `intel_get_runtime_status`、`intel_get_project_context`、
         `intel_explain_project_state`、`intel_predict_root_cause`
**不知道：** 关于低级细节。

聚合来自下层的原始数据为现成答案。

---

## 第 9 层 — AI 代理

**问题：** 给用户什么答案？
**代码：** 规则系统（AGENTS.md、SKILL.md）
**不知道：** 关于内部架构。

---

### 🔗 相关文档

| 文档 | 描述 |
|----------|----------|
| [README.md](README.md) | 主文档，所有文档的地图 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 项目架构、DI、分层 |
| [TELEMETRY.md](TELEMETRY.md) | 指标和遥测 |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史 |
