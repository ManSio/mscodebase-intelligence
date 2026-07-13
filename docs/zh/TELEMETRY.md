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

### 🔗 相关文档

| 文档 | 描述 |
|----------|-------------|
| [README.md](../../README.md) | 主文档，所有文档的导览 |
| [TELEMETRY.md](TELEMETRY.md) | 本文档 |
| [CHANGELOG.md](../en/CHANGELOG.md) | 版本历史 |
| [KNOWN_ISSUES.md](../../KNOWN_ISSUES.md) | 已知问题，含 RAM 画像（KI-002） |

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

## 实时遥测工具（MCP）

除了后台收集器（`scripts/collect_telemetry.py`），指标还可通过 MCP 工具实时获取：

### `intel_get_telemetry`
进程运行时快照：
- **Runtime State**：Ready/Blocked、Warnings、Total wait
- **Per-Tool Calls**：表格 `Tool | Calls | Errors | Min/Avg/Max ms | Last call`
- **Resources**：`RAM`（MB）、`CPU`（%）、`Threads`
- **LLM Provider**：模型、ping、batch-10 延迟、吞吐（tok/s）
- **ETA Predictor**：`Total measurements`、`Learned: N/8 ops`
- **History**：最近快照（日期 / chunks / files / RAM / LLM ping）

### `intel_execution_timeline`
最近调用表：`Time | Tool | ms | Status | Route | Confidence | Results`。显示实时会话中每个工具的真实延迟。

### `get_runtime_counters`
`Checks` / `Ready` / `Blocked`（%）、`Blocks`、`Warnings`、`Performance.Wait`。

### `debug_runtime_passport`
扩展护照：`RUN_ID`、`BUILD_ID`、`PID`、`Uptime`、`CWD`、`Ext Root`、`Bridge State`、`Registry`、`Env`。

### `intel_tool_health`
每工具健康面板：成功率、延迟、置信度、路由。

### 示例（实时运行 2026-07-12）

| 工具 | 调用 | 平均 ms | 状态 |
|------|-------|--------|--------|
| get_index_status | 1 | 295 | ✅ |
| get_symbol_info | 1 | 1611 | ✅ |
| impact_analysis | 1 | 1588 | ✅ |
| search_code | 1 | 1651 | ✅ |
| rename_symbol | 1 | 2624 | ✅（预览） |
| get_health_report | 1 | 21618 | ✅（重量级：日志扫描） |

> MCP 服务器空闲 RAM ~1GB，负载峰值 ~2.8GB（非泄漏，见 KNOWN_ISSUES KI-002）。

---

## 模型流水线（实际，2026-07-12）

嵌入/重排序流水线是 **本地且进程内** 的 — 语义搜索不需要外部 LLM 服务器：

| 阶段 | 引擎 | 模型 | 说明 |
|------|------|------|------|
| 嵌入 | ONNX INT8 / OpenVINO INT8（进程内） | `intfloat/multilingual-e5-base`（768 维） | Windows CPU 上 ~350 ch/s。文件：`model_quantized.onnx`。LM Studio 仅是 **fallback 提供方**。 |
| 重排序 | llama.cpp（`llama-server.exe`，独立进程，`:8081`） | `BAAI/bge-reranker-v2-m3`（GGUF Q4_K_M） | 由 `install.py` 的 `step_gguf` 加载。 |
| LLM（RAG，可选） | 保留 | — | 搜索不需要。 |

> ⚠️ **文档漂移已修复（2026-07-12）**：旧遥测文档将 "LM Studio bge-m3 / phi-4-mini"
> 描述为嵌入提供方。这 **已过时** — 嵌入已进程内迁移到 ONNX/OpenVINO E5-base INT8
> （见 CHANGELOG 3.2.1）。LM Studio 仅作为本地 ONNX/OpenVINO 模型不可用时的可选 fallback。

---

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
| MCP RAM（空闲） | ~1.0 GB | > 2.0 GB 空闲持续 |
| MCP RAM（负载峰值） | < 3.0 GB 瞬时 | 持续 > 3.0 GB |

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

| 阶段 | 引擎 | 时间 |
|-------|-------|------|
| 向量搜索 | LanceDB | ~300ms |
| 重排序 | bge-reranker-v2-m3（余弦相似度） | ~200ms |
| **总计** | | **~500ms** |

### 结论

| 方面 | 状态 |
|--------|--------|
| 稳定性 | ✅ 20/20 成功 |
| 准确性 | ✅ P@5=1.00 |
| 速度 | ✅ 500ms–5s 取决于模式 |
| 内存泄漏 | ⚠️ 无 — 空闲 ~1GB，瞬时峰值 ~2.8GB（KI-002） |

---

## 📊 实时工具审计（2026-07-12）

完整负载测试：**所有 59 个注册工具** 通过真实 MCP 服务器实时调用。

### 工具面
- **共 59 个工具** = 42 core + 14 intel + 3 diagnostic（按服务器启动日志）。
- **默认过滤器**：除非设置 `MSCODEBASE_MCP_TOOLS`，否则仅显示 **12 个工具**。
  设置 `MSCODEBASE_MCP_TOOLS=""` 显示全部 59 个。逗号列表显示子集。
- ~19 个工具返回实时数据；~36 个被默认过滤器隐藏（按设计，非 bug）。

### 每工具延迟（实时运行）

| 工具 | 调用 | 平均 ms | 状态 |
|------|-------|--------|--------|
| get_index_status | 1 | 295 | ✅ |
| get_symbol_info | 1 | 1611 | ✅ |
| impact_analysis | 1 | 1588 | ✅ |
| search_code | 1 | 1651 | ✅ |
| replace_symbol | 1 | 1598 | ✅（预览） |
| rename_symbol | 1 | 2624 | ✅（预览） |
| get_health_report | 1 | 21618 | ✅（重量级：日志扫描） |

### 审计中发现并修复的 bug（见 KNOWN_ISSUES / CHANGELOG 3.2.1）
- **INC-58EA** — IVF 索引 "0 vectors"：`_init_onnx` 加载了 `model.onnx`，但磁盘文件是
  `model_quantized.onnx` → embedder 返回零 → 所有向量 norm 为 0.0 → KMeans 失败。
  修复：`_init_onnx` 现在优先使用 `model_quantized.onnx`（同 `_init_openvino`）。
- **INC-9573** — `intel_get_runtime_status` 显示 `symbol_index_count: 0`，而
  `get_health_report` 显示 `3197`。修复：使用实时 `get_symbol_count()` + 磁盘重载。
- **INC-0AA6** — job 卡在 80% "Finalizing"：`await future_symbols`（Tree-sitter 符号索引）
  无超时。修复：`asyncio.wait_for(..., timeout=120)` 优雅完成 job。

### RAM 画像（通过 `psutil` 测量）
- 空闲 MCP ~1.0 GB，重索引峰值 ~1.1 GB，负载下瞬时 2.8 GB。
- 确认 **非泄漏**：2.8 GB 瞬时来自孤儿 benchmark 进程（`PID 15620`），已终止；
  steady-state RSS 回到 ~1.0 GB。
