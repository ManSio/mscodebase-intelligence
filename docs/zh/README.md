<div align="center">

<img src="../logo/baner.png" alt="MSCodeBase Banner" width="100%"/>

[English](../../README.md) · [Русский](../ru/README.md) · [中文](README.md)

# MSCodebase Intelligence

**面向 OpenCode 与 Zed 的本地代码智能：一个问题，多通道并行检索 —— 词法搜索、调用图、影响分析、项目记忆和安全写入，通过 MCP 提供。**

*重写于 2026-11-08。本文描述当前代码；英文版为准，本页为完整中文镜像。*

</div>

---

## 这是什么

一个本地 MCP 服务器，让 OpenCode（或 Zed）中的 AI 助手获得有依据的代码库视图。它不是聊天模型，也不替代编辑器的语言服务器。它回答四类问题：

- 这个符号在哪里定义、谁在调用、修改会破坏什么？
- 针对这个问题哪些文件重要 —— 代码、测试还是文档？
- 项目已经做过什么决定、哪些事故仍未关闭？
- rename/move/replace 能否先预览再安全执行？

默认运行时是 **text-first**：对解析后的 chunk 使用 SQLite FTS5/BM25，加上 Tree-sitter/PropertyGraph 索引。嵌入与重排是可选的；回答代码问题不需要 GPU、网络或向量数据库。

## 规范仓库

本项目的文档中，`rag-mcp` 指 **本** 仓库：
<https://github.com/ManSio/mscodebase-intelligence>（MIT，`main` 分支）。该名称在公共
平台上并不唯一，因此本文档中所有 `rag-mcp` 的提及都只指向上面的 URL。

## 今天可用的能力

| 领域 | 作用 | 入口 |
|---|---|---|
| **一次调用完成调查** | 一个问题 → 并行 search + symbols + grep，再对已找到的内容运行 impact + callers + tests + 项目记忆；按 file:line 合并，带来源与 `degraded[]` | `investigate` |
| 代码搜索 | 对 chunk 的 BM25/FTS5；标识符走图短路；可选对顶部候选重排 | `search_code` |
| 文档搜索 | 独立的 `docs/**` FTS 通道，按 BM25 差值自动选择（无 LLM 路由器） | `search_code` |
| 正则搜索 | 带 AST 感知 `scope=code` 的正则，跳过注释与字符串（逐匹配判断） | `grep_code` |
| 符号智能 | 定义、调用者、被调用者、引用、影响、结构化搜索 | `get_symbol_info`、`impact_analysis` |
| 图 | PropertyGraph：call/import/assignment/decorator/override 边 | `graph_query`、`codebase` |
| 项目记忆 | ADR、事故、已知问题、retract/supersede | `intel_*`（默认隐藏） |
| 安全写入 | rename/move/delete/replace/insert，带影响防护与回执 | `codebase(action=…)` |
| 诊断 | 健康、索引状态、日志、计数器、变更预测 | `get_health_report`、`predict_change` |
| 工具发现 | 当前配置档、可见与隐藏工具 | `tool_help` |

## 一次问题如何被回答

`investigate` 是默认入口。模型不需要挑选工具；服务器自己运行相关通道并合并结果。

```
investigate("索引器如何决定重新索引一个文件")
        │
        ├─ 第一轮（并行）   search ─ symbols ─ grep
        ▼
        ├─ 第二轮（并行）   impact ─ callers ─ tests ─ 项目记忆
        │                    只针对第一轮找到的内容
        ▼
   按 (file, line) 合并：一次命中一行，通道合并  [search+graph]
   每项带来源；慢或失败的通道进入 degraded[]
```

规则：

- 慢通道**降级**回答（`degraded: grep:timeout`），不会让调用失败。
- 没有匹配时明确返回“未找到”，绝不编造答案。
- 输出有上限（默认 8 行、每行 180 字符），避免淹没上下文。
- `search_code`、`grep_code`、`get_symbol_info`、`impact_analysis` 保留用于精确追问。

## 搜索质量：有度量，也有边界

数字来自内部 **48 条查询面板**（33 条真实项目问题 + 15 条由 docstring 生成），在排除 `experiments/**` 的干净索引上测得。快照日期：**2026-10-25**；引用前请重跑 `experiments/` 下的测试装置。

| 路径 | hit@1 | hit@5 |
|---|---:|---:|
| 代码，quality 模式 | 0.825 | 0.900 |
| 总体，quality 模式 | 0.688 | 0.750 |
| 总体，自动 docs 路由 | 0.792 | 0.875 |
| Fast 模式 | 0.542 | 0.729 |
| 文档，精确路径 | 0.000 | 0.125 |
| 文档，同 basename | 0.750 | 0.750 |

这些数字**不**意味着：

- **不是** 95% 准确率。该面板上的静态检索没有达到；双通道仓库地图在 1k / 2k / 4k token 下最高约 40% / 62% / 73%（即使路由完美）。
- 不意味着任何重排器都有帮助：多个本地重排器经实测被拒绝。
- 不意味着文档通道坏了：它常返回另一种语言的正确文档（`docs/ru/X` 对 `docs/en/X`），这是标注问题。

所有公开数字及复现命令见 **[docs/FACTS.md](../FACTS.md)**。

## 快速开始

要求：以 Windows 为验证平台；Python 3.14+；MCP 宿主（**主要是 OpenCode**，Zed 扩展也可用）。

```bash
cd <repo-root>
python install.py            # 完整安装：venv、pip、可选模型
python install.py --sync     # 仅同步代码到已安装副本
```

`install.py` 完成后重启宿主：OpenCode 会话或 Zed 窗口。已安装副本位于
`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`，两种宿主都启动该 venv。
在助手面板验证：

```text
tool_help()                        # 配置档、可见与隐藏工具
get_health_report()                # 索引、embedder、资源
codebase(action="index", path="status")
```

若文本索引缺失或过期，重建 chunk 与图（本仓库实测：498 文件、7 375 chunk、262–266 秒）：

```bash
python scripts/reindex_text_only.py --project .
```

若只有图为空而 chunk 存在：

```bash
python scripts/rebuild_graph.py
```

随后重启 MCP 服务器，让新进程打开重建后的存储。

## 工具与配置档

服务器注册 **69 个工具**（36 core + 16 intel + 13 inline + 4 dev）；`execute_script` 是第 70 个可选工具，需 `MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`。对模型来说选择过多，因此客户端看到的是**配置档**：

| 配置档 | 可见 | 内容 |
|---|---:|---|
| `core`（默认） | **17** | 每个意图一个入口 + 4 个维护工具 |
| `full` | **69** | 全部注册工具 |

`MSCODEBASE_MCP_TOOLS` 仍是显式 allowlist，设置后覆盖配置档。`tool_help()` 报告当前配置档、可见工具及其用途、以及隐藏工具名称。

默认可见 17 个：`investigate`、`search_code`、`grep_code`、`get_symbol_info`、`impact_analysis`、`graph_query`、`codebase`、`read_live_file`、`notify_change`、`get_health_report`、`intel_get_project_memory`、`predict_change`、`tool_help`、`generate_docs`、`bump_version`、`auto_update_docs`、`install_git_hooks`。

索引是异步的：`codebase(action="index", path="project_dir", project_root=...)` 启动后台任务并立即返回；
用 `codebase(action="index", path="progress", ...)` 查询 `state` / `files` / `elapsed`。尚未索引的项目会
快速拒绝并给出准确的修复提示，而不是等待 5 秒。

默认隐藏：六个 `lsp_*`、`plan_search`、`structural_search`、16 个 `intel_*`（变更/生命周期）、`submit_background_task` / `get_task_status` / `verify_action` / `get_action_receipt`、`ack_impact` 以及 frame/rank/scan 辅助工具。设置 `MSCODEBASE_MCP_PROFILE=full` 可全部暴露；服务器不删除任何工具，只过滤客户端可见面。

## 架构

```text
MCP 宿主：OpenCode（主要）或 Zed
 │
 ├── 宿主内置 LSP（补全、诊断）
 │
 └── MCP 客户端
      │
      ▼
 MSCodebase MCP server
  ├── investigate   两轮并行 fan-out，带来源合并
  ├── Search        SQLite FTS5/BM25、符号/路径信号、文档路由
  ├── Graph         PropertyGraph：calls、imports、assignments、decorators、overrides
  ├── Index         parser → chunks → FTS5 + 图；增量新鲜度检查
  ├── Memory        ADR、事故、已知问题、retract/supersede
  ├── Writes        rename/move/delete/replace/insert，带影响防护
  ├── Diagnostics   健康、任务、日志、遥测、变更预测
  └── Optional      embedders、reranker、LSP rename
```

规范数据位置（在仓库之外）：

- `%LOCALAPPDATA%/mscodebase/projects/<hash>/` —— 项目图、记忆、任务状态、commit memory、遥测。
- `%LOCALAPPDATA%/mscodebase/logs/` —— 服务器日志。
- `<project>/.mscodebase/chunks.db` —— 默认搜索路径使用的文本 chunk 存储。

LanceDB 属于可选向量路径，默认 text-first 配置不需要它。

## 配置

配置项是环境变量，默认值在 `src/config/settings.py`。最关键的：

| 变量 | 默认 | 作用 |
|---|---|---|
| `MSCODEBASE_DENSE_OFF` | `true` | 跳过 dense/向量检索；只用 FTS5、符号、图 |
| `MSCODEBASE_SQLITE_CHUNKS` | `true` | 使用 SQLite/FTS5 chunk 存储 |
| `MSCODEBASE_ONDEMAND_RERANK` | `false` | 用实时嵌入重排顶部候选；单次调用：`investigate(rerank=true)` |
| `MSCODEBASE_DOCS_MARGIN` | `4.0` | 文档路由阈值（docs − code） |
| `MSCODEBASE_AUGMENT_CHUNKS` | `true` | 在 chunk 文本前加 FILE/SYMBOLS/DOC |
| `MSCODEBASE_TESTS_SIGNAL` | `false` | 在符号结果后追加覆盖测试 |
| `MSCODEBASE_CODE_BM25` | `false` | 标识符感知的 BM25 |
| `MSCODEBASE_RU_SYNONYMS` | `false` | 俄语 → 英语术语扩展 |
| `MSCODEBASE_MCP_PROFILE` | `core` | 工具面：17 个可见，或 `full` 全部 69 |
| `MSCODEBASE_MCP_TOOLS` | — | 显式 allowlist；覆盖配置档 |

`experiments/**` 被有意排除在索引之外：其中是冻结面板与运行产物，索引它们曾让 BM25 返回面板本身而非代码。文件仍保留在 git 中。

## 支持的语言

Python 是主要且完整验证的语言。Tree-sitter 解析 JavaScript、TypeScript/TSX、Rust、Go、Java、C#、Ruby、PHP、Kotlin、Swift、C、C++、Scala 与 Dart；SQL、YAML、TOML、HTML、CSS、HCL/Terraform 作为上下文索引，没有同等深度的调用图。当前构建加载 **31 种语法**；图与数据流深度取决于语法。

<!-- stale-ignore -->
版本为可复现性而固定：`tree-sitter==0.26.0`（PyPI 上最新的 Python 绑定）、`tree-sitter-language-pack==1.25.0`，每种语法各自固定一个版本。语法升级会改变分块，因此需要重建索引并比较符号数量，而不是例行升级。
<!-- stale-ignore -->

## 限制

有意的、被记录的边界，而非隐藏行为：

- **文档 gold 与语言：** 文档通道可能在 gold 为 `docs/en/X.md` 时返回 `docs/ru/X.md`；评估时按 basename 归一化。
- **自动文档路由是启发式：** 含强文档词的代码查询可能被路由到文档；`intent="code"` 是出口。
- **完整向量重建被阻止**（`MSCODEBASE_DENSE_OFF=true`）：图用 `scripts/rebuild_graph.py`，chunk 用 `scripts/reindex_text_only.py`。
- **不声称 95%：** 静态检索与已测本地重排器都未达到；LLM 规划器是另一项实验，不是默认路径。
- **Fast 模式不是 quality 模式：** 更快，但在混合自然语言问题上明显更不准确。
- **工具可见性由配置档决定：** 注册 69，默认可见 17；找不到时用 `tool_help()` 并切换配置档。
- **LSP 工具需要可用的 basedpyright：** 缺失时快速失败并给出明确信息，结果缓存 30 秒。

## 开发

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 聚焦搜索测试
pytest tests/test_search_docs.py tests/test_query_plan.py tests/test_searcher.py -q

# 全量（integration/benchmark 由标记选择）
pytest tests/ -m "not integration and not benchmark"

# 真实服务 smoke，无 mock
python scripts/smoke_e2e.py --project .
```

仓库使用 Conventional Commits，实验输入保存在 `experiments/**/frozen/`，结果记录在 `EXPERIMENTS_LOG.md`、`AGENT_DIARY.md`、`KNOWN_ISSUES.md`。

## 报告问题

有用的报告是一个小实验：

1. 精确的调用与参数（`query`、`mode`、`intent`、`limit`）。
2. `tool_help()` / `get_health_report()` 与 `codebase(action="index", path="status")`。
3. 是否重建过图、开启了哪些标志（`MSCODEBASE_DENSE_OFF`、`MSCODEBASE_ONDEMAND_RERANK`、配置档）。
4. 期望文件与实际文件，以及是精确路径还是同 basename。
5. `%LOCALAPPDATA%/mscodebase/logs/` 的日志尾部。

这样能区分四种相似故障：排序差、候选缺失、索引过期/为空、gold 标注错误。

## 文档地图

| 文档 | 内容 |
|---|---|
| [docs/FACTS.md](../FACTS.md) | 所有公开数字与复现命令 |
| [docs/zh/ARCHITECTURE.md](ARCHITECTURE.md) | 分层、DI、模块边界、工具配置档 |
| [docs/zh/SEARCH_PIPELINE.md](SEARCH_PIPELINE.md) | 检索、排序、文档路由、`investigate` fan-out |
| [docs/zh/INSTALL.md](INSTALL.md) | 安装、sync+restart 循环、故障排查 |
| [docs/zh/CONFIGURATION.md](CONFIGURATION.md) | 所有环境变量及其默认值 |
| [docs/zh/CLIENTS.md](CLIENTS.md) | OpenCode、Zed、Claude Code、VS Code、CLI、Docker |
| [docs/zh/HOOKS_AND_GATES.md](HOOKS_AND_GATES.md) | OpenCode 钩子、12 个 pre-commit 门禁、CI 任务 |
| [docs/zh/FAQ.md](FAQ.md) | 常见问题的简短回答 |
| [docs/zh/SECURITY.md](SECURITY.md) | 本地 MCP 服务器的威胁模型 |
| [docs/zh/GRACEFUL_DEGRADATION.md](GRACEFUL_DEGRADATION.md) | 提供者不可用时的行为 |
| [docs/zh/ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md) | 两种宿主共有的 Windows 行为 |
| [docs/zh/CHANGELOG.md](CHANGELOG.md) | 版本历史 |
| [AGENTS.md](../../AGENTS.md) | 本仓库的 AI 代理规则 |
| [KNOWN_ISSUES.md](../../KNOWN_ISSUES.md) | 未决技术债与观察 |
| [EXPERIMENTS_LOG.md](../../EXPERIMENTS_LOG.md) | 实验假设与原始结果 |

英文原版在 `docs/en/`，俄文译版在 `docs/ru/`，文件名相同。

历史材料（博客、研究笔记、归档日记）为溯源保留并带有状态横幅；它们不是今天的说明。

## 许可证

MIT。见 [LICENSE](../../LICENSE)。
