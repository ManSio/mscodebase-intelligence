# 贡献指南 — MSCodeBase Intelligence

[English](../en/CONTRIBUTING.md) · [Русский](../ru/CONTRIBUTING.md) · [中文](CONTRIBUTING.md)

> 翻译：2026-11-08，来源 docs/en/CONTRIBUTING.md。英文版为准。

> 版本 3.5.0 · Python >= 3.14 · MIT

一个本地 MCP 服务器：用 Tree-sitter 索引仓库，把块文本存入 SQLite FTS5 与
PropertyGraph，并通过 MCP 回答代码问题。在第一次改动之前先读 `AGENTS.md`（仓库根
目录）——它载有操作规则与根目录卫生契约（§0.6：允许的根目录集合）。

## 1. 目录布局

```
src/core/        indexing, search, graph, intelligence, guards (never imports mcp)
src/mcp/         server, tool classes, transports (depends on core, not the reverse)
src/providers/   embedder / reranker implementations (llama.cpp, LM Studio, ONNX)
src/config/      settings.py — every knob is an env var with a default
scripts/         operational + gate scripts (reindex, verify_clean_state, lint)
tools/           developer tooling (verification gates, knowledge checks, pipelines)
experiments/     probes and frozen inputs; excluded from indexing and from pytest
tests/           ~240 test modules at top level, plus tests/e2e and tests/fixtures
docs/            canonical documentation; docs/FACTS.md owns every quotable number
```

分层是被强制的：`scripts/check_layer_boundaries.py` 会在出现 `core → mcp` 导入，
以及工具层绕过 core 的依赖时失败。

## 2. 环境搭建

```powershell
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence
python -m venv venv; venv\Scripts\activate; pip install -e ".[dev]"
```

文本优先的运行时只需要 `pip install -e .`。模型是可选的，且绝不会静默下载：
`python install.py` 在每次下载前询问，并接受 `--skip-models`；`--sync-only` 只把
代码复制进扩展目录，不碰 pip 也不碰模型。

## 3. 测试与 lint

`pyproject.toml` 设置了 `addopts = "-v --tb=short -m 'not slow and not benchmark'"`。
这个默认值很重要：

```bash
python -m pytest tests/ -q                    # slow + benchmark excluded (addopts)
python -m pytest tests/ -m "not benchmark"     # includes slow tests
python -m pytest tests/ -q -n auto --cov=src   # what CI does (coverage gate: 38%)
```

`pytest tests/ -q` 变绿**并不**意味着 slow 测试通过。CI 在 ubuntu-latest 与
windows-latest 上、仅 Python 3.14，以 `--cov=src --cov-fail-under=38` 运行
`not slow and not benchmark` 选择集。Lint：`ruff check src/ tests/`（CI）或
`python scripts/ruff_gate.py`（pre-commit）。

## 4. 新增一个工具

一个工具 = 一个类 + 一条注册项 + 一个 profile 决策。

```python
class MyTool(MCPTool):
    def __init__(self, services):
        super().__init__(services, tool_name="my_tool")

    async def execute(self, query: str) -> str | dict:
        indexer = self.resolve_indexer()   # per-project, not a global singleton
        ...
```

1. **类** —— 在 `src/mcp/tools/<area>.py` 中继承 `MCPTool`。由评审与门禁强制的
   规则：依赖通过 `self._services`（DI）注入，不允许模块级全局变量；就绪状态来自
   `RuntimeCoordinator` / `require_index()`，不要自己写检查；返回 `str` 或可
   JSON 序列化的 `dict`；失败时抛出 `ToolError`（或
   `IndexNotReadyError` / `RateLimitError`），以便调用方拿到 `status`
   （`error`/`warning`/`timeout`）与 `recoverable` 标志；用
   `@error_boundary("<tool>", timeout_ms=...)` 装饰 `execute`。
2. **写入** —— 走 `WriteTool.execute`（`src/mcp/tools/write_tools.py`），它被
   `@modification_guard(pagerank_min=0.05, blast_min=10, ack_ttl=600)` 装饰。
   对承重文件，在被 guard 拿到有效影响令牌（`ack_impact`）之前，写入会被拒绝；
   不要另加一条未加装饰的写入路径。
3. **注册** —— 把类追加到
   `src/mcp/server_tools.py::register_all_tools()` 中的 `tool_classes`。不要在别处
   直接把它注册到 MCP 应用上：profile 过滤器在所有分组注册完成之后才运行。
4. **Profile** —— 放进 `CORE_PROFILE`（17 个工具的默认表面，一个意图一个入口），
   或让它只在 `MSCODEBASE_MCP_PROFILE=full` 下可见。计数在模块 docstring 中被
   断言：36 core + 16 intel + 13 inline + 4 dev = 69。
5. **测试与文档** —— 在 `tests/` 下加一个单元测试；任何触及检索或索引的东西都需要
   一个"若工具静默返回空就会失败"的用例。若表面发生变化，更新 `tool_help` 可见的
   文本以及任何列出工具的文档。

## 5. 提交与 Pull Request

Conventional Commits，祈使语气，原子化：

```
feat(search): add code-aware BM25 term field

Restate the diff, not the intent. Explain why when the why is not obvious.
```

- Subject <= 72 字符，结尾不加句点，正文之前空一行；破坏性变更写作
  `type(scope)!:` 并加 `BREAKING CHANGE:` 脚注。
- 显式暂存文件（`git add src/core/x.py tests/test_x.py`）。禁止 `git add -A`、
  `git add .` 与 `git commit -a`——一个 checkout 可能与其他 agent 或 worktree
  共享，批量 add 会把它们未完成的工作一并扫进来。先运行 `git worktree list` 与
  `git status`；在别处被编辑过的文件会被 `scripts/check_parallel_sessions.py`
  拦下。
- 不提交生成物或一次性文件：`docs/generated/MODULE_INDEX.md` 不被跟踪，
  `experiments/**/results` 不被索引，根目录集合由 `AGENTS.md` §0.6 固定。一个 PR
  只做一件事；请求评审前先自查 diff：每一行删除都是有意的，描述不比 diff 更丰富。

## 6. 门禁

`core.hooksPath = .githooks`；`.githooks/pre-commit` 运行以下内容（每道门禁 900 s
预算，`MSCB_PRECOMMIT_GATE_TIMEOUT`）：

| 门禁 | 脚本 |
|---|---|
| gate-zero + 日记 | `scripts/verify_diary.py`（完整 `pytest tests/`；docs-only 提交或 `--skip-gate-zero` 时跳过） |
| 版本漂移 | `scripts/stale_detector.py --staged` |
| 工具名 | `scripts/check_tool_names.py` |
| 负控制 | `scripts/negative_controls_runner.py` |
| 层边界 | `scripts/check_layer_boundaries.py` |
| 架构不变量 | `scripts/architecture_linter.py` |
| git 锁（advisory） | `scripts/lock_guard.py` |
| known-issues 体量 | `scripts/check_known_issues.py` |
| 第三方数据 | `scripts/check_third_party_data.py` |
| 并行会话 | `scripts/check_parallel_sessions.py` |
| lint | `scripts/ruff_gate.py` |

CI 还追加 `bump_version.py --check`、`disk_guard.py --check`、`pip-audit`、
`verify_clean_state.sh --no-clone`、`manifest_parity.py`，以及传输等价性 e2e 作业。
用 `gh run list --branch <branch>` 与 `gh run view <id> --log-failed` 检查 CI，
而不是靠假设。

## 7. 文档与登记册

- 数字（块数、文件数、节点、边、质量、计时）**只**存在于 `docs/FACTS.md`，并附
  上可重新生成它们的命令。
- 规范页面有三种语言（`docs/en`、`docs/ru`、`docs/zh`）；改一处就是改三个文件。
  `docs/blog`、`docs/research`、`docs/archive` 中的历史材料保留其横幅与日期——
  不要重写。引用事实用 `(file, commit SHA, record ID)`，不要用 `file:line`：
  行号会腐烂。
- 登记册：`AGENT_DIARY.md`（只有一个日记；`DEV_DIARY.md` 是重定向）、
  `KNOWN_ISSUES.md`（<= 300 行，较早条目移入
  `docs/archive/KNOWN_ISSUES_YYYY_MM.md`）、`EXPERIMENTS_LOG.md`、`WISDOM.md`。
  在同一个提交中更新它们；第二个日记或第二个 `KNOWN_ISSUES.md` 是缺陷，不是变体。

**Verified against:** `pyproject.toml`, `.github/workflows/ci.yml`,
`.githooks/pre-commit`, `src/mcp/server_tools.py`, `src/mcp/tools/base.py`,
`src/core/modification_guard.py`, `src/core/error_handler.py`, `install.py`,
`AGENTS.md` (§0.6), directory listing of `src/`, `tests/`, `scripts/`, `tools/`,
`experiments/`.
