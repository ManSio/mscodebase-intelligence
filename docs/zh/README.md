<div align="center">

<img src="../../logo/baner.png" alt="MSCodeBase Banner" width="100%"/>

[English](../../README.md) · [Русский](../ru/README.md) · [中文](README.md)

# MSCodebase Intelligence

**面向 Zed 的本地优先代码智能：词法搜索、调用图、影响分析、项目记忆和安全写入工具，通过 MCP 提供。**

[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![Zed](https://img.shields.io/badge/Zed-extension-orange.svg)](https://zed.dev/)
[![CI](https://github.com/ManSio/mscodebase-intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/ManSio/mscodebase-intelligence/actions/workflows/ci.yml)

*更新于 2026-10-25。英文页面为准；本翻译可能滞后。*

</div>

---

## 这是什么

MSCodebase Intelligence 是一个**本地 MCP 服务器**，让 Zed 中的 AI 助手对代码库
获得有依据的视图。它不是聊天模型，也不是编辑器 LSP 的替代品。它回答：

- 符号在哪里定义？谁在调用？修改后会破坏什么？
- 哪些文件与问题相关——代码、测试还是文档？
- 项目已经做过哪些决定？哪些事故仍未关闭？
- rename/move/replace 能否安全预览并应用？

当前默认是**文本优先检索**：SQLite FTS5/BM25 加 Tree-sitter/PropertyGraph 索引。
Embedding 和 reranker 提供程序存在，但都是可选的，默认路径不需要它们。这是
刻意选择：服务器离线仍可用，延迟可预测，向量数据库不会成为单点故障。

## 当前可用的能力

| 领域 | 作用 | 备注 |
|---|---|---|
| 代码搜索 | 对解析后的 chunk 做 BM25/FTS5；符号/路径信号；可选图扩展 | `search_code` |
| 文档搜索 | 独立的 `docs/**` FTS 通道，BM25 分差足够大时自动启用 | 无 LLM 路由器 |
| 符号智能 | 定义、callers/callees、references、impact、structural search | `get_symbol_info`, `impact_analysis`, `structural_search` |
| 图 | 文件/符号 PropertyGraph：call、import、assignment、decorator、override | 用 `scripts/rebuild_graph.py` 重建 |
| 项目记忆 | ADR、事故、known issues、retract/supersede | `intel_*` |
| 安全写入 | rename、move、delete、replace、insert，带 preview/impact | `codebase(action=...)` |
| 诊断 | runtime passport、health、index status、logs、jobs | `debug_runtime_passport`, `get_health_report` |
| LSP rename | 基于 basedpyright 的跨文件 rename + SymbolIndex fallback | 仅 rename |

## 搜索质量：有测量，也有边界

没有测量方法的数字没有意义。下面是内部的 **48 查询面板**（33 个真实项目问题
加 15 个 docstring 派生问题），在干净索引上评估，排除 `experiments/**`，图存在。
这不是通用 benchmark，也不代表所有语言或仓库。

| 路径 | hit@1 | hit@5 | 含义 |
|---|---:|---:|---|
| 代码，quality | 0.825 | 0.900 | 40 个代码问题中 33 个首位命中正确的文件 |
| 文档，精确路径 | 0.000 | 0.125 | Gold 指向 `docs/en/X`，检索常返回 `docs/ru/X` |
| 文档，同文件名 | 0.750 | 0.750 | 把翻译视为同一文档 |
| 总体 quality | 0.688 | 0.750 | 代码和文档按面板标注混合 |
| 总体 auto docs route | 0.792 | 0.875 | BM25-margin 路由 + 文档通道；翻译已归一化 |
| Fast | 0.542 | 0.729 | 质量较低、延迟较低；用于精确/简单查找 |

这些数字**不**代表：

- **不是 95% 准确率。** 该面板上没有任何静态方案达到这个水平。双通道 repo map
  （代码 PageRank + 文档 BM25）在 1k/2k/4k token 下、理想路由时约 40%/62%/73%
  gold 文件覆盖率；单独 PageRank 在代码查询上约 33%/55%/68%。它是上下文选择
  工具，不是搜索替代品。
- **不是所有本地 reranker 都有帮助。** 多个模型被测量后拒绝：它们降低 hit@1
  或增加不可接受的延迟。
- **不是文档通道坏了。** 它经常返回另一种语言的正确文档（`docs/ru/X` 而不是
  `docs/en/X`）。这是 gold 标注问题，不是检索失败。

面板、原始运行、假设和 summary 位于 `experiments/`。它是可复现的实验记录，
不是营销文案。

## 搜索如何工作

默认路径是确定性的：

1. **Parse/index** — 文件 → chunk + PropertyGraph。
2. **Retrieve** — SQLite FTS5/BM25、符号/路径信号，可选图邻居。
3. **Rank/clean** — 可选 on-demand rerank、exact-name boost 和符号去重。
   RRF/MMR/dense fusion 属于可选 LanceDB/vector 路径，不是每个默认查询都会执行。
4. **Docs routing** — 最佳 docs 分数超过最佳 code 分数达到可配置 margin
   （`MSCODEBASE_DOCS_MARGIN`，默认 `4.0`）时走文档通道。
5. **Return** — 带 metadata 的 chunk/文件；`intent="docs"` 或
   `intent="code"` 可覆盖自动选择。

路由中没有 LLM。它只是一次额外 FTS 查询和分数比较：本地、可解释、成本低。

可选层：

- Embedding 提供程序（llama.cpp GGUF、ONNX、LM Studio/Ollama）提供 vector
  candidates。
- 配置提供程序时的 on-demand rerank。
- Graph expansion 和 PageRank 风格 repo ranking。

当 `MSCODEBASE_DENSE_OFF=true`（当前默认）时，代码/文档查询不依赖 embedding
server。

## 快速开始

要求：Windows 是已验证平台；Python 3.14+；Zed 安装
`mscodebase-intelligence` 扩展。

```bash
cd <repo-root>
python install.py
# 仅同步代码，不提问：
python install.py --sync
# CI 模式，不提问：
python install.py --yes
```

`install.py` 会把服务器复制到 Zed 扩展目录、安装依赖、可选准备模型，并写入
MCP 配置。完成后重启 Zed。

在 agent panel 中验证：

```text
debug_runtime_passport()
intel_get_runtime_status()
codebase(action="index", path="status")
```

如果图为空但 chunk 存在，只重建图（不计算 vector）：

```bash
python scripts/rebuild_graph.py
```

如果索引过期或缺失，重建文本 chunk 和图：

```bash
python scripts/reindex_text_only.py --project .
```

然后重启 MCP/Zed，让新进程打开重建后的存储。

## 工具

服务器注册 **66 个工具**，分为四组；启用
`MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true` 时增加一个可选的
`execute_script`。默认 allowlist 暴露精选子集；隐藏工具可通过
`MSCODEBASE_MCP_TOOLS` 启用（空字符串显示全部）。准确列表见 MCP 启动日志和
`intel_get_runtime_status`。

| 组 | 示例 | 用途 |
|---|---|---|
| 搜索与分析 | `search_code`, `plan_search`, `get_symbol_info`, `impact_analysis`, `structural_search`, `graph_query` | 代码、符号、关系、impact |
| 索引与系统 | `codebase(action="index"...)`, `notify_change`, `read_live_file`, `get_health_report`, `get_logs` | 索引新鲜度和诊断 |
| Intelligence | `intel_get_runtime_status`, `intel_get_project_memory`, `intel_log_incident`, `intel_analyze_incident`, `intel_predict_root_cause` | 记忆、事故、runtime |
| 写入与生命周期 | `codebase(action="rename"...)`, `move`, `safe_delete`, `replace`, `insert_before/after`, `ack_impact` | 预览/应用安全修改 |
| Dev | `bump_version`, `auto_update_docs`, `install_git_hooks`, `generate_docs` | 仓库维护 |

`codebase` 是 hub：`action` 选择 index、git 或 write。请查看 MCP 客户端中的
tool schema，不要依赖可能过时的手写列表。

## 架构

```text
Zed
 │
 ├── built-in LSP (autocomplete, diagnostics)
 │
 └── MCP client
      │
      ▼
 MSCodebase MCP server
   ├── Search      SQLite FTS5/BM25, symbol/path signals, optional graph
   ├── Graph       PropertyGraph: calls, imports, assignments, decorators, overrides
   ├── Index       parser → chunks → FTS5 + graph; freshness checks
   ├── Memory      ADRs, incidents, known issues, retract/supersede
   ├── Writes      rename/move/delete/replace/insert with impact guards
   ├── Diagnostics runtime passport, health, jobs, logs, telemetry
   └── Optional    embedding providers, reranker, LSP rename
```

规范数据位置在仓库之外：

- `%LOCALAPPDATA%/mscodebase/projects/<hash>/` — 每项目 graph、memory、jobs。
- `%LOCALAPPDATA%/mscodebase/logs/` — 服务器日志。
- `<project>/.mscodebase/chunks.db` — Phase 3 文本 chunk store。

LanceDB 仍属于 legacy/可选 vector path；默认 text-first 模式不需要它。

## 配置

所有设置都是 environment variables，defaults 在 `src/config/settings.py`。搜索
相关重点：

| 变量 | 默认 | 作用 |
|---|---|---|
| `MSCODEBASE_DENSE_OFF` | `true` | 跳过 dense/vector retrieval；使用 FTS5、symbols、graph |
| `MSCODEBASE_SQLITE_CHUNKS` | `true` | 使用 SQLite/FTS5 chunk store |
| `MSCODEBASE_DEMOTE_NON_CODE` | `false` | 在 fused pool 中降低 tests/docs/experiments |
| `MSCODEBASE_DEMOTE_INTENT_AWARE` | `false` | docs intent 时不降低 docs |
| `MSCODEBASE_DOCS_MARGIN` | `4.0` | 自动文档路由阈值（docs − code score） |
| `MSCODEBASE_ONDEMAND_RERANK` | `true` | 可选 live rerank；需要 provider |
| `MSCODEBASE_P3_ANCHOR` | `false` | module-head anchors；无 reranker 时增加延迟 |
| `MSCODEBASE_MCP_TOOLS` | default set | 工具 allowlist；空 = 全部 |

`experiments/**` 被有意排除在索引之外。那里是 frozen 面板和运行产物；索引它们
曾让 BM25 返回面板本身而不是代码。文件仍保留在 git 中。

## 支持的语言

Python 是主要且完整验证的语言。Tree-sitter 解析覆盖 JavaScript、
TypeScript/TSX、Rust、Go、Java、C#、Ruby、PHP、Kotlin、Swift、C、C++、Scala
和 Dart。SQL、YAML、TOML、HTML、CSS、HCL/Terraform 作为上下文索引，不保证
同等 call graph 覆盖。图和 data-flow 深度取决于 grammar；并非所有语言都有
相同边类型。

## 限制与已知问题

这些是有意记录、公开的边界，不是隐藏行为：

- **Docs gold 与语言：** 文档通道可能返回 `docs/ru/X.md`，而 gold 是
  `docs/en/X.md`。文档是正确的，精确路径指标不是。评估翻译时按 basename 归一化。
- **自动文档路由是启发式：** margin 可配置，并在 48 查询面板上调过。带有强
  文档词的代码查询仍可能被路由到 docs；`intent="code"` 是退路。
- **Graph rebuild 与 text reindex 分离：** `MSCODEBASE_DENSE_OFF=true` 时
  完整 vector reindex 被有意阻止。图用 `scripts/rebuild_graph.py`，chunk 用
  `scripts/reindex_text_only.py`。
- **不宣称 95%：** 静态检索和测试过的本地 reranker 在该内部面板上都没有达到。
  LLM planner/agent loop 是另一个实验，不是默认路径。
- **Fast mode 不是 quality mode：** 更快，但在混合自然语言问题上明显更不准确。
  用于精确名称和已知路径。
- **可见工具受 allowlist 控制：** 源码里的“66 tools”不代表某个客户端能看到
  全部 64 个；检查 `MSCODEBASE_MCP_TOOLS`。

## 报告问题

有用的报告是一个小实验，而不只是一个数字。请包含：

1. 准确的 tool call 和参数（`query`、`mode`、`intent`、`limit`）。
2. `debug_runtime_passport()` 和 `codebase(action="index", path="status")`。
3. 是否重建过图（`scripts/rebuild_graph.py`），以及是否启用
   `MSCODEBASE_DENSE_OFF` / `MSCODEBASE_ONDEMAND_RERANK`。
4. 期望文件与实际返回文件；是精确路径还是同文件名（翻译算同一文档）。
5. 可复现的最小查询，以及 `%LOCALAPPDATA%/mscodebase/logs/` 的相关日志。

这样可以把四种看起来相似的问题分开：排序差、候选缺失、索引过期/为空、
gold 标注不匹配。

## 项目结构

```text
src/
  main.py                 MCP entry point
  mcp/
    server.py             server creation
    server_factory.py     DI and lifecycle
    server_tools.py       tool registration and inline tools
    tools/                search, index, graph, memory, write, lifecycle tools
  core/
    search/               engine, FTS5/BM25, scoring, query plan, graph adapter
    indexing/             parser, chunk store, index pipeline, file guard
    intelligence/         project memory, incidents, health, jobs
    graph.py              PropertyGraph
    di_container.py       service collection
  config/settings.py      environment-backed settings
  providers/              optional embedders and rerankers
experiments/              frozen panels, run artifacts, summaries
scripts/                  install/reindex/graph/smoke utilities
tests/                    pytest suite
docs/                     architecture, installation, operations, research
```

## 开发

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 聚焦搜索测试
pytest tests/test_search_docs.py tests/test_query_plan.py \
  tests/test_experiment_output_guard.py tests/test_searcher.py -q

# 完整测试套件（integration/benchmark 由 marker 选择）
pytest tests/ -m "not integration and not benchmark"

# Live smoke：真实服务，无 mock
python scripts/smoke_e2e.py --project .
```

仓库使用 Conventional Commits，实验输入保存在 `experiments/**/frozen/`，结果记录
在 `EXPERIMENTS_LOG.md`、`AGENT_DIARY.md` 和 `KNOWN_ISSUES.md`。

## 文档地图

| 文档 | 内容 |
|---|---|
| [docs/en/INSTALL.md](../en/INSTALL.md) | 安装、卸载、平台说明 |
| [docs/en/ARCHITECTURE.md](../en/ARCHITECTURE.md) | 分层、DI、模块边界 |
| [docs/en/ARCHITECTURE_DEEP.md](../en/ARCHITECTURE_DEEP.md) | Pipeline 与 lifecycle |
| [docs/en/SEARCH_PIPELINE.md](../en/SEARCH_PIPELINE.md) | Retrieval、fusion、scoring、rerank |
| [docs/en/GRACEFUL_DEGRADATION.md](../en/GRACEFUL_DEGRADATION.md) | provider 不可用时的行为 |
| [docs/en/ZED_WINDOWS_QUIRKS.md](../en/ZED_WINDOWS_QUIRKS.md) | Windows 与 Zed |
| [docs/en/CHANGELOG.md](../en/CHANGELOG.md) | 版本历史 |
| [AGENTS.md](../../AGENTS.md) | AI agent 规则 |
| [KNOWN_ISSUES.md](../../KNOWN_ISSUES.md) | 开放问题与技术债 |
| [EXPERIMENTS_LOG.md](../../EXPERIMENTS_LOG.md) | 实验假设与原始结果 |

## Research notes

- [PageRank vs RAG on a real codebase](https://dev.to/mansio/i-measured-pagerank-token-savings-on-a-real-codebase-the-result-will-surprise-you-5bnj)
- [Fact-checking one AI's audit with another](https://dev.to/mansio/i-asked-one-ai-to-fact-check-another-ais-audit-of-my-own-code-1ac3)
- [The silent vector contamination bug](https://dev.to/mansio/the-silent-vector-contamination-bug-why-your-concurrent-embeddings-might-be-lying-to-you-5fg7)

## 许可证

MIT。见 [LICENSE](../../LICENSE)。

## 致谢

Zed、Model Context Protocol、Tree-sitter、SQLite/FTS5，以及让离线优先助手
变得实用的本地推理项目。
