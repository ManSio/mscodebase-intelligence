# Hooks 与门禁

> 翻译：2026-11-08，来源 docs/en/HOOKS_AND_GATES.md。英文版为准。

> 2026-11-08 依据 `.githooks/pre-commit`、`.opencode/plugin/mscodebase_gate.ts`、
> `scripts/*` 和 `.github/workflows/ci.yml` 重写。下面每个门禁都在源码中阅读过；
> 标注处的运行时间经过实测。

一次提交要经过**三层**。它们有意重叠：宿主级插件在模型侧拦截，git 钩子拦截所有
提交（无论宿主是谁），CI 拦截脏工作区可能掩盖的问题。

```
agent/host ──► .opencode/plugin/mscodebase_gate.ts   (per git commit, in-session)
git commit ──► .githooks/pre-commit                   (12 gates + gate-zero pytest)
push / PR  ──► .github/workflows/ci.yml               (6 jobs)
```

## 1. OpenCode 插件（宿主级钩子）

文件：`.opencode/plugin/mscodebase_gate.ts`。它只对命令匹配 `git commit` 的
`bash` 工具调用运行。

| 门禁 | 模式 | 作用 |
|---|---|---|
| `stale_detector` | **block**（`MSCODEBASE_STALE_GATE=off` 可关闭） | 比较文档中的版本声明与代码；漂移 > 0 时中止提交 |
| `graph_query isolation` | **advisory**（可用 `block`/`off`） | 统计会因本次提交而成为孤儿的节点；文本追加到工具结果中，而不是阻断 |

调试时值得注意的细节：

- 它在项目目录中调用 `python -m src.cli <tool> '<json>'`，即与 MCP 相同的工具
  类，但不走协议。
- 解释器：`MSCODEBASE_PY`，默认 `<repo>/venv/Scripts/python.exe`。
- 每次调用都以 JSON 行记录到 `MSCODEBASE_GATE_LOG`（默认
  `%TEMP%/opencode/mscodebase_gate.log`）。
- 任何失败都会被吞掉并记录；只有刻意阻断才抛出。
- 隔离门禁每次 `git commit` 约耗时 8 s（日志实测），stale 门禁很快。两者都在
  git 钩子之前运行，所以第一个门禁慢会被 agent 直接感受到。
- 自 2026-11-08 起，当暂存区全部是文档（`*.md`、`*.txt`、`*.rst`）时插件跳过隔离门禁：
  文档不会造成图节点孤立，这样文档提交不再等待。stale 门禁仍会运行——它检查的正是文档。
  用临时仓库驱动插件验证：暂存 `README.md` → `isolation_skipped`，暂存 `a.py` → `isolation`。
- 已知限制：MCP 进程持有数据库锁时，CLI 最多等待 8 s，然后返回 `base: cached` 与空的
  变更文件列表。把该 advisory 视为尽力而为：git 钩子与 CI 不依赖它。

## 2. Git pre-commit 钩子（仓库级）

当 `git config core.hooksPath` = `.githooks`（本仓库）时生效。可由
`install_git_hooks` 工具（`action = install | uninstall | status`）安装或检查，
也可手动设置 `core.hooksPath`。

每个门禁的预算：`MSCB_PRECOMMIT_GATE_TIMEOUT`（默认 900 s）。gate-zero（完整
`pytest tests/`）在只暂存文档文件时自动跳过，也可用
`MSCB_PRECOMMIT_FAST=1` 跳过。

| # | 命令 | 阻断条件 |
|---|---|---|
| 0 | `pytest tests/` | 任何测试失败（仅文档提交时跳过） |
| 1 | `scripts/verify_diary.py` | `AGENT_DIARY.md` 中矛盾台账无法确认的 `✅` 声明 |
| 2 | `scripts/stale_detector.py --staged` | 暂存文档与 `pyproject.toml` 之间的版本漂移 |
| 3 | `scripts/check_tool_names.py` | 文档中已失效的 `intel_*`/工具名 |
| 4 | `scripts/negative_controls_runner.py` | 已注册但无法失败的保护检查 |
| 5 | `scripts/check_layer_boundaries.py` | `core` 在过渡 allowlist 之外导入 `mcp`/`sources` |
| 6 | `scripts/architecture_linter.py` | 架构不变量（注册表、环、失效名称） |
| 7 | `scripts/lock_guard.py` | 活跃的 git 锁文件（advisory） |
| 8 | `scripts/check_known_issues.py` | `KNOWN_ISSUES.md` 超过 300 行或缺少月度归档 |
| 9 | `scripts/check_third_party_data.py` | 暂存文件中的个人数据/逐字第三方转储 |
| 10 | `scripts/check_parallel_sessions.py` | 暂存文件正被另一个 worktree 编辑 |
| 11 | `scripts/ruff_gate.py` | 暂存 Python 的 lint 错误 |
| 12 | `scripts/gate_cli.py`（`tools/verification/gates.py`） | G1 population、G2 referent、G3 generalization、G4 control |

两个值得记住的后果：

- 因另一个会话的未跟踪文件而变红的门禁仍然是红门禁。修正原因，或使用显式记录在案的
  `--no-verify` 提交。
- 钩子会在每次非文档提交时运行 `pytest`；在因一次 3 分钟的提交而责怪 agent 之前，
  先测量。

## 3. CI（`.github/workflows/ci.yml`）

| 任务 | 证明什么 |
|---|---|
| `test (ubuntu-latest, 3.14)` | 带覆盖率（`-n auto`）的完整测试套件 |
| `test (windows-latest, 3.14)` | 已验证平台；捕获 Windows 特有的死锁 |
| `clean-state` | 全新 clone + venv + lock 安装 + 完整套件；同时运行 negative control |
| `manifest-parity` | 我们的 manifest 提取器与固定版本 `osv-scanner` 在 polygon 语料上的对比 |
| `docker-build` | 远程镜像仍可构建 |
| `transport-equiv-e2e` | stdio 与 Streamable HTTP 返回相同答案 |

CodeQL 单独运行（`.github/workflows/codeql.yml`）。Python 3.14 是唯一受支持的
版本。

## 4. 每一层的作用

- **插件** —— 在 `git commit` 返回前拦截 agent，并给出模型可读的消息。
- **Git 钩子** —— 拦截人类和任何宿主；是默认运行完整测试套件的唯一一层。
- **CI** —— 拦截依赖干净工作区的问题：lockfile 漂移、clean-state 安装、Docker、
  transport 等价性。

不要通过禁用来“修复”红色门禁。如果规则有错，就在同一次提交中同时修改规则和守护
它的测试。
