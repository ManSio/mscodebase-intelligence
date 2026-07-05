# 遥测 — MCP 工作指标收集

[🇬🇧 English](../en/TELEMETRY.md) • [🇷🇺 Русский](../ru/TELEMETRY.md) • [🇨🇳 中文](TELEMETRY.md)

自动收集指标用于图表绘制和性能分析。

## 工作原理

两个独立的遥测系统收集指标：

### 1. 按工具指标（进程内，自动持久化）

每次调用任何 MCP 工具都会由 `error_boundary` 装饰器自动记录。
指标保存在内存中，每 10 次调用 + 关闭服务器时保存到 JSON：

```
{ext_root}/telemetry/tool_metrics.json
```

**示例表格**（通过 `intel_get_telemetry` 查看）：

| 工具 | 调用 | 错误 | 最小毫秒 | 平均毫秒 | 最大毫秒 | 最后调用 |
|------|------|------|---------|---------|---------|---------|
| search_code | 31 | 0 | 1676 | 2525 | 14264 | 23:04:41 |
| structural_search | 20 | 0 | 35 | 2179 | 4479 | 23:07:44 |
| impact_analysis | 4 | 0 | 1343 | 1353 | 1370 | 23:03:49 |
| get_symbol_info | 3 | 0 | 1332 | 1338 | 1348 | 23:00:55 |

跨 MCP 服务器重启持久化 — `load_metrics()` 在启动时读取保存的 JSON。

### 2. 外部收集器（按计划）

脚本 `scripts/collect_telemetry.py` 收集所有运行时计数器的快照
并保存到带日期的 JSON 文件中。文件累积在目录中：

```
.mscodebase/telemetry/
├── 2026-07-05.json    ← 7 月 5 日的所有快照
├── 2026-07-06.json    ← 7 月 6 日的所有快照
└── ...

---

### 🔗 相关文档

| 文档 | 描述 |
|----------|----------|
| [README.md](README.md) | 主文档，所有文档的地图 |
| [TELEMETRY.md](TELEMETRY.md) | 本文件 |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史 |
```

每个文件都是一个记录数组：
```json
[
  {
    "date": "2026-07-05",
    "captured_at": "2026-07-05T23:00:00",
    "uptime_sec": 43200,
    "counters": {
      "can_execute_calls": 152,
      "verdict_ready": 148,
      "verdict_blocked_not_ready": 3,
      "verdict_blocked_system_path": 0,
      "total_wait_time_sec": 2.4,
      "warnings_bridge_not_synced": 1,
      "warnings_indexing_in_progress": 2
    },
    "project": {
      "project_path": "D:\\Project\\MSCodeBase",
      "state": "READY",
      "index_chunks": 1362,
      "index_files": 106,
      "index_symbols": 1080,
      "index_latency_ms": 13.2
    }
  }
]
```

## 使用方法

### 单次收集
```bash
python scripts/collect_telemetry.py
```

### 设置每天 23:00 自动收集
```bash
python scripts/collect_telemetry.py --daily
```
在 Windows 任务计划程序中创建任务 "MSCodeBase Telemetry Collector"。

### 查看 N 天历史
```bash
python scripts/collect_telemetry.py --history 7
```
输出最近 7 天的 JSON。

## 收集哪些指标

### 运行时计数器（来自 RuntimeCoordinator）

| 指标 | 显示什么 |
|---|---|
| `can_execute_calls` | MCP 检查项目就绪状态的次数 |
| `verdict_ready` | 项目就绪的次数（正常） |
| `verdict_blocked_not_ready` | 项目未就绪的次数（需要重新索引） |
| `verdict_blocked_system_path` | 尝试使用系统目录的次数 |
| `verdict_blocked_failed` | 项目无法初始化的次数 |
| `verdict_blocked_resolution` | 无法确定项目的次数 |
| `verdict_blocked_registry_error` | Registry 出错的次数 |
| `warnings_bridge_not_synced` | LSP 未同步的次数 |
| `warnings_indexing_in_progress` | 索引正在进行的次数 |
| `warnings_just_started` | MCP 刚启动的次数 |
| `total_wait_time_sec` | MCP 等待项目就绪的秒数 |

### 项目统计

| 指标 | 显示什么 |
|---|---|
| `state` | 项目当前状态（READY/INDEXING/FAILED） |
| `index_chunks` | LanceDB 中的块数 |
| `index_files` | 索引的文件数 |
| `index_symbols` | 识别的 Tree-sitter 符号数 |
| `index_latency_ms` | 获取索引状态的时间 |

### 护照

| 指标 | 显示什么 |
|---|---|
| `uptime_sec` | MCP 进程运行秒数 |
| `run_id` | 唯一运行 ID |
| `build_id` | Git 提交哈希 |

## 生成图表

累积的 JSON 文件可以加载到任何 BI 系统中：

- **Excel** — 通过 Power Query 导入 JSON
- **Grafana** — 如果添加提供这些文件的 HTTP 服务器
- **Python/matplotlib** — `python scripts/collect_telemetry.py --history 30`

## 什么是正常范围

| 指标 | 良好 | 需要关注 |
|---|---|---|
| `verdict_ready / can_execute_calls` | > 95% | < 80% |
| `verdict_blocked_not_ready` | < 5% | > 20% |
| `verdict_blocked_system_path` | 0 | > 1 |
| `total_wait_time_sec` | < 10秒/天 | > 60秒/天 |
| `warnings_bridge_not_synced` | < 3次/天 | > 20次/天 |
| `index_latency_ms` | < 50ms | > 500ms |
