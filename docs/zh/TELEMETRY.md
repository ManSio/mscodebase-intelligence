# 遥测

[English](../en/TELEMETRY.md) · [Русский](../ru/TELEMETRY.md) · [中文](TELEMETRY.md)

> 翻译：2026-11-08，来源 docs/en/TELEMETRY.md。英文版为准。

> 版本 3.5.0。本页所有内容都在本地。服务器不向网络发送任何东西，也没有分析端点。

---

## 1. 两个独立的记录器

| 记录器 | 存什么 | 存在哪里 | 生命周期 |
|---|---|---|---|
| 每工具指标 | 调用、错误、延迟样本、重复率、route | `<ext_root>/telemetry/tool_metrics.json` | 跨重启（每 10 次调用及退出时写入） |
| 每日快照 | 运行时计数器、索引大小、RAM/CPU、provider ping | `<data_root>/projects/<hash8>/telemetry/YYYY-MM-DD.json` | 90 天，之后清理 |

`<ext_root>` 是代码运行所在的目录
（`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`）。`<data_root>` 在
Windows 上是 `%LOCALAPPDATA%\mscodebase`，在 macOS 上是
`~/Library/Caches/mscodebase`，在 Linux 上是 `~/.cache/mscodebase`；可用
`MSCODEBASE_DATA_DIR` 覆盖。`<hash8>` 是 `md5(normalised project path)[:8]`
（`artifact_paths.project_hash`）。

两个记录器都不是用户提示词的日志。不存在请求/响应载荷的存储：工具参数与代码文本
不会写入遥测。

## 2. 每工具指标

`@error_boundary` 在每次工具调用之前调用 `record_tool_call()`、之后调用
`record_tool_result()`。每个工具保留：

- `calls`、`errors`、`total_ms`、`min_ms`；
- 一个有界的延迟样本（`deque(maxlen=1000)`）——P50/P95/P99 由**最近 1000 次调用**
  计算，而不是全部历史；
- `repeat_count`（同一工具连续被调用两次）占调用的百分比；
- 调用之间的空闲时间，以及工具上报时的 `route` 计数器。

持久化：一个 `atexit` 处理器加上每 10 次调用的刷写，通过临时文件与 `os.replace`
把整个注册表写到 `<ext_root>/telemetry/tool_metrics.json`（原子操作，不会写出半个
JSON）。启动时指标**不会**被读回，所以该文件是已完成会话的快照，而不是累积数据库。

读取方式：

| 工具 | Profile | 返回 |
|---|---|---|
| `intel_tool_health()` | full | 健康条、调用次数、P50/P95、重复 %、routes、空闲 vs 活跃 % |
| `intel_execution_timeline(limit=15)` | full | 最近 N 次调用，含工具、ms、ok/fail、route、confidence |
| `intel_get_telemetry(days=7)` | full | 运行时计数器 + 工具摘要 + 资源 + provider ping + 历史 |

`intel_get_telemetry` 是唯一还会写快照的工具（见 §3）。没有 `get_index_status`
工具——索引状态用 `codebase(action="index", path="status")`。

## 3. 每日快照

每次 `intel_get_telemetry()` 调用向
`<data_root>/projects/<hash8>/telemetry/<date>.json` 追加一条记录。文件是 JSON
数组；形状如下，数值仅为示意：

```json
[{
  "date": "2026-11-08",
  "captured_at": "2026-11-08T12:34:56",
  "uptime_sec": 1234.5,
  "counters": { "can_execute_calls": 12, "verdict_ready": 12, "total_wait_time_sec": 0.0 },
  "project": { "project_path": "...", "index_chunks": 0, "index_files": 0 },
  "resources": { "rss_mb": 0, "cpu_percent": 0 },
  "llm": { "ping_ms": 0.0, "batch_10_ms": 0.0, "tokens_per_sec": 0,
           "provider": "fallback", "model": "...", "configured_model": "..." },
  "token_savings": { "avg_savings_percent": 95.0, "total_searches": 0 },
  "_meta": { "index_age_days": 0 }
}]
```

关于你可能会过度解读的字段：

- `llm` 是通过真正 embedding `"ping"` 与一批十条来测量的；若 provider 不可用，
  该键改为 `{"error": ...}`。`provider` 是实时模式（`onnx`、`llama_cpp`、
  `lm_studio`、`ollama`、`onnx_server`、`fallback`），不是配置的偏好。
- 若某个小节失败，该小节变为 `{"error": "..."}`——快照仍会写出。部分快照是一个
  信号，不是坏文件。
- `token_savings.avg_savings_percent` 是写入器中的固定常量，不是测量值。不要引用它。

## 4. 运行时计数器

`get_runtime_counters()`（完整 profile）格式化
`runtime_coordinator._COUNTERS`：`can_execute_calls`、`verdict_ready`、
`verdict_blocked_system_path`、`verdict_blocked_not_ready`、`verdict_blocked_failed`、
`verdict_blocked_resolution`、`verdict_blocked_registry_error`、
`warnings_bridge_not_synced`、`warnings_indexing_in_progress`、
`warnings_just_started`、`total_wait_time_sec`。

当检查数为零时，它打印 "Checks: 0 — данных нет" 而不是 "100% blocked"，因为分母
为空的比率不是测量。

## 5. 独立收集器

要在没有运行中的 MCP 会话时获取快照：

```bash
python scripts/collect_telemetry.py            # one snapshot into data_root/.../telemetry
python scripts/collect_telemetry.py --history 7 # print the last 7 days as JSON
python scripts/collect_telemetry.py --daily     # register a Windows scheduled task (23:00)
```

计划任务在 `pythonw.exe` 存在时使用它，因此不会闪出控制台窗口。脚本通过
`resolve_project_root()` 解析项目，并通过 `artifact_paths.get_telemetry_dir()` 写入，
因此它永远不会在项目目录里乱丢东西。

## 6. 资源

RAM/CPU 来自 `src/core/indexing/resource_monitor.py`
（`get_global_resource_monitor().get_summary()`），由监视器采样，而不是按需计算。
`get_health_report()` 呈现同样的数字，外加磁盘警告：低于
`MIN_FREE_DISK_MB = 500` 时 data root 会收到警告。

## 7. 保留期与清理

`artifact_gc.prune_stale_artifacts()` 在启动 3 s 后于后台线程运行：

- 超过 **90 天**的遥测文件被删除；
- 不活跃的项目目录（**30 天**无写入）被整体移除，除非该项目在注册表中是活跃的；
- 超过 **7 天**的日志被清理；
- 被锁定的文件会被跳过并报告，从不强制删除。

默认值在 `artifact_gc.py` 中（`DEFAULT_TELEMETRY_MAX_AGE_DAYS`、
`DEFAULT_PROJECT_MAX_AGE_DAYS`、`DEFAULT_LOG_RETENTION_DAYS`）。

## 8. 隐私摘要

- 一切都在本机；代码中不存在上传路径。
- 不持久化任何源码文本、提示词或工具参数。
- `read_live_file` 的内容、错误中的绝对路径与回溯会被记录（不返回到响应中）；
  `src/core/redact.py` 在文本到达 agent 上下文之前剥离前缀锚定的凭据形态，并且
  明确不是边界。
- 删除 `<data_root>/projects/<hash8>/telemetry/` 是安全的：它移除历史，索引、图与
  记忆不受影响。

---

**Verified against:** `src/core/error_handler.py` (`record_tool_call`,
`get_tool_metrics_summary`, `set_metrics_path`, deque size, save cadence),
`src/mcp/server_factory.py` (`set_metrics_path(_ext_root/telemetry/...)`),
`src/core/intelligence/layer.py` (`intel_get_telemetry` snapshot writer),
`src/core/intelligence/tools_reg.py` (`intel_get_telemetry` registration),
`src/utils/ui_formatter.py` (`format_telemetry`),
`src/mcp/server_tools.py` (`get_runtime_counters`, `intel_tool_health`,
`intel_execution_timeline`), `src/core/runtime_coordinator.py` (counter names),
`src/core/artifact_paths.py` (data-root layout), `src/core/artifact_gc.py`
(retention), `scripts/collect_telemetry.py`, `src/core/redact.py`.
