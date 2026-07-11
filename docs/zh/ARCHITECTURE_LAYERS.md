# 架构层 — MSCodeBase Intelligence

[🇬🇧 English](../en/ARCHITECTURE_LAYERS.md) • [🇷🇺 Русский](../ru/ARCHITECTURE_LAYERS.md) • [🇨🇳 中文](ARCHITECTURE_LAYERS.md)

每一层只回答一个问题。

```
 Layer 0: Filesystem        — 磁盘上有哪些文件？
 Layer 1: SystemArtifacts   — 这是系统路径吗？
 Layer 2: Bridge            — LSP 报告了哪个项目？
 Layer 3: Registry          — 哪个 Indexer 属于该项目？
 Layer 4: StateMachine      — 项目处于什么状态？
 Layer 5: RuntimeCoordinator — 可以执行请求吗？
 Layer 6: ProjectContext    — 项目当前的状态如何？
 Layer 7: Passport          — 当前运行的是哪个进程？
 Layer 8: Graph (v3.0)      — PropertyGraph: SQLite nodes/edges/cypher?
 Layer 9: Intel Layer       — 如何处理这些信息？
 Layer 10: AI Agent         — 给用户什么回答？
```

---

## 第 0 层 — Filesystem

**问题：** 磁盘上有哪些文件？
**代码：** `os.walk`, `Path.rglob`, `FileGuard`
**不了解：** 索引、MCP、LSP。

---

## 第 1 层 — SystemArtifacts

**问题：** 这是系统路径吗？
**代码：** `SystemArtifacts.is_system_path()`
**不了解：** Registry、Bridge、Runtime、Indexer。

4 个子保护级别：
1. **Directory Guard** — `.mscodebase/`, `.codebase_indices/`, `.git/`, `node_modules/`
2. **Artifact Guard** — `chunk_summaries.json`, `incidents.json`, `project_memory.json`
3. **Feedback Guard** — 由索引器自身创建的文件
4. **Embedding Guard** — 在 embedding 之前的最终检查

**规则：** `.mscodebase/` 或 `.codebase_indices/` 内的任何文件 = 不索引。

---

## 第 2 层 — Bridge (LSP→MCP)

**问题：** LSP 当前报告了哪个项目？
**代码：** `read_project_from_bridge()`, `write_active_project()`
**不了解：** 索引、Runtime。

Bridge — 一个临时文件（~/.mscodebase/bridge/session_*.json），
由 LSP 在每次 didOpen/didSave 时写入。MCP 在需要确定
project_root 时读取。

---

## 第 3 层 — Registry (ProjectIndexerRegistry)

**问题：** 哪个 Indexer 属于这个项目？
**代码：** `ProjectIndexerRegistry.get_indexer(path)`
**不了解：** MCP、Bridge、Runtime。

每个项目单例 Indexer，带 LRU 驱逐（最多 5 个）。
每个项目都有自己的 LanceDB 锁。

---

## 第 4 层 — StateMachine

**问题：** 项目处于什么状态？
**代码：** `ProjectIndexerRegistry.get_state()`, `wait_until_ready()`
**不了解：** Bridge、MCP 请求。

```
UNINITIALIZED → STARTING → INDEXING → READY → FAILED
```

---

## 第 5 层 — RuntimeCoordinator

**问题：** 可以执行 MCP 请求吗？
**代码：** `RuntimeCoordinator.can_execute()`
**不了解：** 代码结构、搜索。

使用：
- SystemArtifacts（第 1 层）— 路径不是系统路径？
- Bridge（第 2 层）— LSP 是否已同步？
- Registry + StateMachine（第 3-4 层）— 项目是否已就绪？

返回 `ExecutionVerdict`：
- `ok` — 可以执行
- `reason` — 原因（ready / system_path / project_not_ready / ...）
- `retry_after` — 多久后重试
- `requires_reindex` — 需要重新索引
- `warnings` — 警告

---

## 第 6 层 — ProjectContext

**问题：** 项目当前的状态如何？
**代码：** `ProjectContext.capture()`
**不了解：** MCP 请求，不启动操作。

返回 Snapshot：
- state, index (chunks/files/symbols), bridge, runtime (PID/uptime),
  health (warnings/errors), memory (incidents/ADRs), jobs

---

## 第 7 层 — Passport

**问题：** 当前运行的是哪个进程？
**代码：** `debug_runtime_passport()` — MCP 工具
**不了解：** 索引状态。

显示：RUN_ID, BUILD_ID, PID, uptime, ext_root, project_root,
env (PROJECT_PATH, ZED_WORKTREE_ROOT, PYTHONPATH), guard result。

---

## 第 8 层 — Intel Layer

**问题：** 如何处理这些信息？
**代码：** `intel_get_runtime_status`, `intel_get_project_context`,
         `intel_explain_project_state`, `intel_predict_root_cause`
**不了解：** 底层细节。

聚合来自下层的数��以生成现成的答案。

---

## 第 9 层 — AI Agent

**问题：** 给用户什么回答？
**代码：** 规则系统（AGENTS.md, SKILL.md）
**不了解：** 内部架构。

---

### 🔗 相关文档

| 文档 | 描述 |
|----------|----------|
| [README.md](../../README.md) | 主文档，所有文档的导览 |
| [ARCHITECTURE.md](../en/ARCHITECTURE.md) | 项目架构，DI，分层 |
| [TELEMETRY.md](TELEMETRY.md) | 指标与遥测 |
| [CHANGELOG.md](../en/CHANGELOG.md) | 版本历史 |
