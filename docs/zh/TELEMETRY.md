# 遥测 — MCP 运行时指标收集

[🇬🇧 English](../en/TELEMETRY.md) • [🇷🇺 Русский](../ru/TELEMETRY.md) • [🇨🇳 中文](TELEMETRY.md)

自动指标收集，用于构建图表和性能分析。

## 工作原理

两个独立的遥测系统收集指标：

### 1. 每个工具的指标（进程内，自动持久化）

每次对任何 MCP 工具的调用都会被 `error_boundary` 装饰器自动记录。
指标保存在内存中，每 10 次调用 + 关闭时保存到 JSON：

```
{ext_root}/telemetry/tool_metrics.json
```

**示例表格**（通过 `intel_get_telemetry` 可见）：

| 工具 | 调用次数 | 错误 | 最短 ms | 平均 ms | 最长 ms | 最后调用 |
|------|-------|--------|--------|--------|--------|-----------|
| search_code | 31 | 0 | 1676 | 2525 | 14264 | 23:04:41 |
| structural_search | 20 | 0 | 35 | 2179 | 4479 | 23:07:44 |
| impact_analysis | 4 | 0 | 1343 | 1353 | 1370 | 23:03:49 |
| get_symbol_info | 3 | 0 | 1332 | 1338 | 1348 | 23:00:55 |

指标在 MCP 服务器重启后仍然保留 — `load_metrics()` 在启动时读取已保存的 JSON。

### 2. 外部收集器（定时快照）

脚本 `scripts/collect_telemetry.py` 捕获所有运行时计数器的快照
并保存到带日期的 JSON 文件中。文件累积在目录中：

```
.mscodebase/telemetry/
├── 2026-07-05.json    ← 7 月 5 日的所有快照
├── 2026-07-06.json    ← 7 月 6 日的所有快照
└── ...
```

---

### 🔗 相关文档

| 文档 | 描述 |
|----------|-------------|
| [README.md](../../README.md) | 主文档，所有文档的导览 |
| [TELEMETRY.md](TELEMETRY.md) | 本文档 |
| [CHANGELOG.md](../en/CHANGELOG.md) | 版本历史 |

每个文件是一个记录数组：
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

### 安排在每天 23:00 收集
```bash
python scripts/collect_telemetry.py --daily
```
创建 Windows 任务计划程序任务 "MSCodeBase Telemetry Collector"。

### 查看 N 天的历史记录
```bash
python scripts/collect_telemetry.py --history 7
```
输出最近 7 天的 JSON。

## 收集的指标

### 运行时计数器（来自 RuntimeCoordinator）

| 指标 | 说明 |
|--------|---------------|
| `can_execute_calls` | MCP 检查项目就绪状态的次数 |
| `verdict_ready` | 项目就绪的次数（正常） |
| `verdict_blocked_not_ready` | 项目未就绪的次数（需要重新索引） |
| `verdict_blocked_system_path` | 尝试处理系统目录的次数 |
| `verdict_blocked_failed` | 项目初始化失败的次数 |
| `verdict_blocked_resolution` | 项目解析失败的次数 |
| `verdict_blocked_registry_error` | Registry 出错的次数 |
| `warnings_bridge_not_synced` | LSP 未同步的次数 |
| `warnings_indexing_in_progress` | 索引进行中的次数 |
| `warnings_just_started` | MCP 刚启动的次数 |
| `total_wait_time_sec` | MCP 等待项目就绪的总秒数 |

### 项目统计

| 指标 | 说明 |
|--------|---------------|
| `state` | 当前项目状态（READY/INDEXING/FAILED） |
| `index_chunks` | LanceDB 中的块数 |
| `index_files` | 已索引的文件数 |
| `index_symbols` | 已识别的 Tree-sitter 符号数 |
| `index_latency_ms` | 获取索引状态的时间 |

### 护照

| 指标 | 说明 |
|--------|---------------|
| `uptime_sec` | MCP 进程已运行的秒数 |
| `run_id` | 唯一的运行 ID |
| `build_id` | Git 提交哈希 |

## 构建图表

积累的 JSON 文件可以加载到任何 BI 系统中：

- **Excel** — 通过 Power Query 导入 JSON
- **Grafana** — 如果您添加提供这些文件的 HTTP 服务器
- **Python/matplotlib** — `python scripts/collect_telemetry.py --history 30`

## 正常值参考

| 指标 | 良好 | 需关注 |
|--------|------|------------|
| `verdict_ready / can_execute_calls` | > 95% | < 80% |
| `verdict_blocked_not_ready` | < 5% | > 20% |
| `verdict_blocked_system_path` | 0 | > 1 |
| `total_wait_time_sec` | < 10 秒/天 | > 60 秒/天 |
| `warnings_bridge_not_synced` | < 3 次/天 | > 20 次/天 |
| `index_latency_ms` | < 50ms | > 500ms |

## 📊 压力测试结果（2026-07-07）

17 次 `search_code` 调用 — **0 错误，0 超时，P@5=1.00**

### 搜索模式性能

| 模式 | 查询 | 时间 | Top-1 | 噪声 |
|------|-------|------|-------|-------|
| `fast` | `class MultiProviderReranker` | **315ms** | `reranker.py` 代码 | 0/5 ✅ |
| `fast` | `TaskQueue` | 374ms | `task_queue.py` 代码 | 0/6 ✅ |
| `fast` | `def can_execute` | 363ms | `runtime_coordinator.py` 代码 | 0/6 ✅ |
| `quality` | `memory leak gc objects` | **426ms** | AGENT_DIARY.md + `intelligence_layer.py` 代码 | 0/5 ✅ |
| `quality` | `dependency injection` | 486ms | CHANGELOG.md 文档 | 0/5 ✅ |
| `quality` | `RuntimeCoordinator bridge` | 1567ms | AGENTS.md 架构 | 0/5 ✅ |
| `deep` | `почему MCP не отвечает` | **~3s** | `docs/ru/FAQ.md` 俄语文档 | 0/5 ✅ |
| `deep` | `мульти-оконность` | ~5.3s | `docs/ru/ARCHITECTURE.md` | 0/5 ✅ |

### 流水线延迟（5 个块，`quality` 模式）

| 阶段 | 模型 | 时间 |
|-------|-------|------|
| 向量搜索 | LanceDB | ~300ms |
| 重排序 | bge-reranker-v2-m3-m3（余弦相似度） | ~200ms |
| **总计** | | **~500ms** |

### LM Studio 模型（已加载）

| 模型 | 类型 | 角色 |
|-------|------|------|
| text-embedding-bge-m3 Q4_K_M | embeddings | 向量搜索 |
| bge-reranker-v2-m3-m3 Q8_0 | embeddings (reranker) | **评分** |
| phi-4-mini-instruct Q4_K_M | llm | 为 RAG 预留 |

### 结论

| 方面 | 状态 |
|--------|--------|
| 稳定性 | ✅ 20/20 成功 |
| 准确性 | ✅ P@5=1.00 |
| 速度 | ✅ 500ms-5s 取决于模式 |
| 内存泄漏 | ⚠️ RAM 268 MB（稳定） |
