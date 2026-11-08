# 安全策略 — MSCodeBase Intelligence

[English](../en/SECURITY.md) · [Русский](../ru/SECURITY.md) · [中文](SECURITY.md)

> 翻译：2026-11-08，来源 docs/en/SECURITY.md。英文版为准。

> 版本 3.5.0 · MIT · 本地 MCP 服务器，无托管后端

---

## 1. 受支持版本

| 版本 | 受支持 |
|---|---|
| 3.5.x | 是——当前版本线（`pyproject.toml`） |
| < 3.5 | 否；请先升级，再报告 |

只有最新的 3.5.x 会被修补。这是一项政策声明，而不是代码强制的东西。运行时下限是
Python 3.14（`requires-python = ">=3.14"`）；针对更旧解释器的报告不在范围内。

## 2. 威胁模型

服务器以 **stdio MCP 进程**运行，**拥有启动它的用户的权限**——通常是宿主的用户，
没有权限分离、没有容器、没有 seccomp、默认不监听网络。这一句话决定了以下全部内容：

- 它能读用户能读的任何文件，也能写用户能写的任何文件。服务器本身外面没有沙箱。
- 它索引并读取**不可信内容**。仓库的 `AGENTS.md`、`SKILL.md`、源码注释，或抓取到的
  页面都是*数据*。它们永远不是权威。`src/core/trust_boundary.py` 把根目录分类为
  `TRUSTED`、`UNTRUSTED` 或 `UNKNOWN`；`MSCODEBASE_TRUSTED_ROOTS`（以 `;` 或 `,`
  分隔）是显式允许列表。来自 `UNTRUSTED` 根目录的指令不会被执行，在其中运行脚本 /
  推送 / 安装需要所有者明确确认（`docs/TRUST_BOUNDARY.md`）。
- 现实的攻击是**通过被索引内容的提示注入**，而不是远程漏洞利用。防御手段是受限的
  工具、写入前预览，以及一个默认关闭的危险能力。

## 3. `execute_script` —— RCE 表面

`execute_script` **默认禁用**。只有当
`MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true` 时它才被注册，此时它是第 70 个工具，
与 69 个分开计数。

代码实际做了什么（启用前请先读这段）：

- `src/core/sandbox/executor.py` 在**执行之前**校验源码：标准库模块允许列表
  （`ALLOWED_MODULES`）、被禁止的字符串模式（`os.system`、`subprocess`、
  `open(`、`eval(`、`__import__`、`sys.modules`、`win32`，……），以及针对混淆导入
  的 AST 级拦截。
- 执行是一个最小环境的子进程：`PATH=""`、不复制 `os.environ`（因此父进程的密钥
  永远到不了子进程）、`PYTHONPATH` 设为项目根、默认 30 s 超时、stdout/stderr
  上限 1 MB。
- 存在三种模式：`strict`（默认）、`permissive`、`off`。

模块 docstring 说得很明确：**"NOT a security boundary for untrusted code.
Defense-in-depth for agent tools."** 启用它等同于在你的账号下授予任意代码执行。
注意 `.env.example` 与启动日志把它描述为"without sandbox isolation"地运行；上面
那个 executor 才是工具真正调用的东西，诚实的总结是"经 AST 校验的子进程，不是
牢笼"。

## 4. 写入：预览、影响守卫、回执

- `WriteTool.execute` 默认 `apply=False`：每次 rename/move/replace/insert/delete
  都返回一个**预览**。在 `apply=True` 之前什么都不会写入。
- 同一个方法被
  `@modification_guard(pagerank_min=0.05, blast_min=10, ack_ttl=600)` 装饰。对
  承重文件（高 PageRank，或影响半径 >= 10 个连接），guard 会**拒绝**写入，并返回
  一个绑定到该文件当前 `mtime:size` 的 HMAC `impact_token`。
- `ack_impact(file_path, impact_token)` 打开一个 600 s 的窗口。若文件发生变化，
  令牌即失效，因此过期的确认无法授权针对不同内容的写入。没有令牌的裸确认会被拒绝。
- 歧义被拒绝而不是被消解：一个裸符号匹配到多个定义时返回 `denied` 及候选列表，
  而不是静默取第一个。
- 失败即关闭（fail-closed）：若 PageRank 或影响半径查询失败，guard 假定该文件是
  热文件（PageRank 1.0 / blast 100）并要求确认。
- 每次写入都通过 `ActionReceipt` 记录；`get_action_receipt`（完整 profile）返回
  改动了什么。

## 5. 路径、读取与索引

- `SecurityConfig` 会从环境解析 `MAX_FILE_SIZE_MB`（10）、`ALLOWED_EXTENSIONS`、
  `ALLOW_SYMLINKS`（`true`）与 `STRICT_PATH_VALIDATION`（`true`），但**今天没有
  任何其它模块读取这四个值**。真正的文件过滤在
  `src/core/indexing/file_guard.py`（大小上限常量、扩展名允许列表、压缩/二进制
  检测、`.gitignore` 模式），真正的路径包含是下面那些显式的 `is_relative_to`
  检查。不要把环境标志当作生效的安全控制。
- 路径包含只在真正重要的地方强制，通过 `Path.resolve()` + `is_relative_to`：
  `read_live_file` 在 `MSCODEBASE_RESTRICTED_READ=true` 时（默认关闭——项目之外的
  绝对路径可读）、`grep_code`（必须留在项目根内）、上传目标，以及
  `autonomous_fix`。
- 拒绝自我索引：`resolve_indexer_for_request()` 会拒绝扩展目录与 MCP 安装路径，
  而不是悄悄索引自己的代码。
- 索引器跳过 `.git`、系统目录、二进制文件、压缩文件、超大文件、`.gitignore`
  覆盖的路径以及 `experiments/**`（`file_guard.py`）。
- 除非你配置了传输方式，服务器不会打开 TCP 端口（`MCP_HOST`/`MCP_PORT`，SSE 桥接
  默认 `127.0.0.1:8765`）。默认情况下没有任何东西暴露到网络；llama.cpp/ONNX/
  LM Studio 端点也都是回环地址。

## 6. 密钥

- 密钥只放在 `.env` 中。`.env`、`.env.local`、`.mscodebase/`、`.codebase_models/`
  与 `models/` 都在 git 忽略之列。
- `.env.example` 中的 LM Studio 默认键 `sk-local` 是有文档说明的占位符，不是凭据。
- 永远不要把密钥粘进工具参数、文档、测试夹具或日志行。`src/core/redact.py` 在文本
  被注入 agent 上下文之前剥离 `PREFIX` 锚定的凭据形态，它自己的 docstring 也说明
  它**不是**安全边界——它只捕获已知形态。

## 7. 本仓库是公开的

MIT 许可、公开可读。因此：

- 不要第三方转储：抓取的页面、个人资料导出、别人的邮箱、整篇文章。属于这里的是
  我们自己的结论，加上 `sha256`、来源 URL 和一段简短引用。
- 逐字复制还会引入来源的许可证（一篇 CC BY-NC-SA 文章会污染 MIT 仓库）。
- 门禁：`scripts/check_third_party_data.py` 在 pre-commit 中运行。R1（个人邮箱）
  与 R2（抓取资料特征）阻断；R3（大批量逐字第三方文本）为 advisory；R4 捕获线程
  转储。
- 必须保留的原始材料放在仓库**之外**，位于 `<data_root>/audit-cache/<task>/`。

## 8. 报告漏洞

1. 开一个私密 advisory：
   https://github.com/ManSio/mscodebase-intelligence/security/advisories/new
2. 标题加上 `[SECURITY]` 前缀，并包含：受影响版本、宿主（OpenCode / Zed）、涉及的
   工具、最小复现，以及 `execute_script` 是否被启用。
3. 不要先开公开 issue，也不要在报告中包含密钥或第三方个人数据。

预期在几天内得到初次回复。由于这是单人维护的项目，修复可能作为普通补丁版本发布，
而不是 backport。

---

**Verified against:** `pyproject.toml`, `src/mcp/server_tools.py`,
`src/mcp/tools/codebase_tool.py`, `src/mcp/tools/write_tools.py`,
`src/core/sandbox/executor.py`, `src/core/modification_guard.py`,
`src/core/trust_boundary.py`, `src/core/error_handler.py`,
`src/config/settings.py`, `src/mcp/tools/system_tools.py`,
`src/mcp/tools/grep_tool.py`, `src/core/indexing/file_guard.py`,
`src/core/autonomous_fix.py`, `src/sources/upload/__init__.py`, `src/core/change_preview.py`,
`src/core/redact.py`, `scripts/check_third_party_data.py`, `.env.example`,
`.gitignore`, `docs/TRUST_BOUNDARY.md`.
