# Windows 上的怪癖（以及宿主现状）

[English](../en/ZED_WINDOWS_QUIRKS.md) · [Русский](../ru/ZED_WINDOWS_QUIRKS.md) · [中文](ZED_WINDOWS_QUIRKS.md)

> 翻译：2026-11-08，来源 docs/en/ZED_WINDOWS_QUIRKS.md。英文版为准。

> 版本 3.5.0。文件名为了链接稳定性而保留。**现在的主要宿主是 OpenCode；Zed 扩展
> 仍受支持。** 仅限 Zed 的事故在末尾标记为历史，不是当前行为。

## 1. 宿主

| 宿主 | 启动命令行 | 状态 |
|---|---|---|
| OpenCode | `…\Zed\extensions\mscodebase-intelligence\venv\Scripts\mscodebase-mcp.exe -u -m src.main`，`PYTHONPATH` = 扩展目录 | 主要 |
| Zed 扩展 | `extension.toml` → `venv\Scripts\pythonw.exe -u -m src.main`，`PROJECT_PATH = $ZED_WORKTREE_ROOT`，`PYTHONUTF8=1` | 受支持 |

两者运行的都是复制到 `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence` 中的
代码。修改 `src/` 不会有任何效果，直到 `python install.py --sync-only` 并重启宿主。
这是最常见的"我的修复没生效"原因。

## 2. 没有控制台窗口：到处都用 `CREATE_NO_WINDOW`

Windows 会为每个控制台子系统子进程生成一个控制台。服务器会启动很多这类子进程
（`git`、`llama-server.exe`、`basedpyright`、空闲探测），因此该标志分两层施加：

1. **全局** —— `src/core/silent_subprocess.py` 由 `src/main.py` 最先导入，在 win32
   上修补 `subprocess.Popen/run/check_output/check_call`，按位或上
   `CREATE_NO_WINDOW` 并设置 `STARTUPINFO(wShowWindow=SW_HIDE)`。任何会调外部命令
   的库都会被覆盖，而无须它知情。
2. **局部** —— 数十个调用点显式传入 `creationflags=CREATE_NO_WINDOW`
   （`git_tools`、`commit_memory`、`execution_contract`、`resource_monitor`、
   `verify_on_read`、`graph`、`sandbox/executor`，……）。该标志是按位或上去的，
   从不覆盖已有的集合。

长生命周期的模型服务器额外加上 `DETACHED_PROCESS | CREATE_NO_WINDOW`
（`llama_runner._popen_with_job`），从而在父进程退出后仍存活，且每次重启都不会闪出
窗口。这不是表面问题：每约 30 s 闪一次控制台（空闲探测）曾是被记录的事故，用户把
它读作恶意软件。

## 3. `pythonw.exe` 与 `python.exe`，以及进程名

`pythonw.exe` 是 GUI 子系统解释器：没有控制台，但 stdio 仍可通过宿主提供的管道
工作。因此 `install.py` 用 `venv\Scripts\pythonw.exe` 作为 `MCP_PYTHON`，并创建
一次性 NTFS 硬链接 `mscodebase-mcp.exe → pythonw.exe`
（`process_titles.ensure_mcp_hardlink`），若链接失败则退回普通 `pythonw.exe`。

之所以需要这个硬链接，是因为 `pythonw.exe` 没有控制台，也无法设置窗口标题——任务
管理器只会显示一个裸的 `python.exe`。有了它，进程就可辨识。
`apply_mcp_process_title()` 构造 `mscodebase-mcp:<project>-<hash8>`；
`start_server.bat` 用 `python.exe` 加 `PYTHONUTF8=1` 运行，并从批处理文件设置标题。
出于同样原因，`llama-server` 子进程获得 `llama-embed.exe` / `llama-rerank.exe`
硬链接。

## 4. `Popen` + `communicate`，绝不用 `capture_output`

在 MCP 进程内禁止 `capture_output=True` 与 `check_output()`：当 stdout 已被重定向
进管道时（在 MCP 宿主下就是如此），它们会在工作线程中把管道锁死，调用永不返回。
本项目惯用写法：

```python
proc = subprocess.Popen([...], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace",
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
try:
    out, _ = proc.communicate(timeout=...)
except subprocess.TimeoutExpired:
    proc.kill()
    proc.communicate()   # reap; never leave a zombie
```

`stdin=DEVNULL` 可阻止读取 stdin 的子进程永久阻塞。`.githooks/pre-commit` 使用相同
的写法，并把超时当作一种裁决（"门禁没有应答"），而不是崩溃。

## 5. 编码

- 两个宿主配置（`extension.toml`、OpenCode 的 MCP 块）中都设置了 `PYTHONUTF8=1`，
  因此解释器不会回退到 OEM 代码页。
- 打印 emoji 的脚本要重配置 stdout
  （`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`）；否则 cp1251/cp866
  控制台会抛 `UnicodeEncodeError`，门禁会因错误的理由失败。
- 在 PowerShell 中，读日志前按会话设置：
  `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`。
- 库代码中绝不向 stdout `print()`——stdout 是 JSON-RPC 通道。诊断信息走 logger，
  它写入 `<data_root>/logs/`。

## 6. 路径

- MCP 参数接受原生 Windows 路径（`C:\work\app\src\main.py`）；`notify_change` 用
  相对项目根的路径，`project_root` 用绝对路径。
- 内部比较键是规范 POSIX 形式（`Path.resolve().as_posix()`），在 `win32` 上转为小写，
  因为文件系统不区分大小写（`modification_guard._normalize_path`）。
- 超过 `MAX_PATH` 的路径经过 `to_win_long_path()`（`\\?\` 前缀；在 POSIX 上为
  no-op）。
- 比较 `git worktree list` 的输出与 `pathlib` 路径时若不归一化分隔符，会让门禁把
  自己的树看成外来的——这正是 `scripts/check_parallel_sessions.py` 中专用归一化器
  的由来。

## 7. Git、锁与 Insider 构建

从无窗口进程调用时，git 可能在图形化凭据管理器上阻塞，因此每次调用都使用
`GIT_TERMINAL_PROMPT=0`、`GIT_ASKPASS=echo`、`GIT_PAGER=cat`，外加
`CREATE_NO_WINDOW` 与超时（`git_tools._git_run`，15 s）。

只要句柄未关闭，Windows 就会锁定内存映射的数据库文件。因此 `intel_reset_index()`
先关闭句柄、释放 PID 锁、删除、再重新获取——在持有锁的情况下 `rmtree` 过去会留下
半删除的索引。若删除仍遇到 `PermissionError`，管理器切换到新的数据库路径，而
`artifact_gc` 会跳过被锁定的文件并报告，而不是强制删除。拒绝删除的目录通常意味着
另一个 MCP 进程仍持有它。

在 Windows Insider 构建上，UCRT API-set DLL（`api-ms-win-crt-*`）缺失，上游的
`llama-server.exe` 无法加载；`_patch_dll_imports` 在首次运行前把这些导入重写为
`ucrtbase.dll`。这是机器级别的变通做法，不是要求。

## 8. 历史（仅作背景）

- **Zed 的 LSP 服务器** —— 一个独立的 `mscodebase-lsp` 进程已被移除（Zed 需要
  Rust/WASM 适配器才能支持自定义语言服务器）。内部的 LSP *客户端*（basedpyright）
  存活下来；LSP→MCP 桥已于 2026-07-20 移除，`lsp_*` 工具不再需要桥。
- **"MCP 不重启"** —— Zed 没有对 context server 的自动重启，所以每次代码改动都
  需要完全退出。在 OpenCode 下等价操作是重启会话；规则（进程保留旧模块）不变。
- **受限模式 / 工作区信任** —— Zed 首次打开时的对话框。不是本服务器的属性，也无法
  在代码中验证（宿主行为）。
- **项目解析** —— 仍会查询 Zed 的 SQLite 状态，但不再优先：显式参数 → CWD →
  `PROJECT_PATH` → 多工作区 SQLite → Zed `workspaces` DB → `ZED_WORKTREE_ROOT` →
  扩展根（`project_resolution.resolve_project_root`）。CWD 先于数据库，因为它是
  多窗口打开时唯一按进程的信号；参见
  `investigations/ACTIVE_WORKSPACE_RESOLUTION.md`。
- **控制台闪烁** —— 已由 §2 修复；保留在此是因为它解释了全局补丁存在的原因。

---

**Verified against:** `src/main.py` (silent_subprocess import, console title),
`src/core/silent_subprocess.py`, `src/core/process_titles.py`,
`src/providers/reranker/llama_runner.py` (`_popen_with_job`, DETACHED_PROCESS),
`src/mcp/tools/git_tools.py` (`GIT_TERMINAL_PROMPT`/`GIT_ASKPASS`/`GIT_PAGER`),
`src/core/modification_guard.py` (`_normalize_path`),
`src/sources/local_fs/windows.py` (`to_win_long_path`),
`src/core/sandbox/executor.py` (Popen + communicate), `src/core/artifact_gc.py`,
`src/core/intelligence/tools_reg.py` (`intel_reset_index`), `install.py`
(`MCP_EXE`, `_ensure_mcp_hardlink`), `start_server.bat`, `extension.toml`,
`.githooks/pre-commit`, `src/providers/reranker/llama_install.py`
(`_patch_dll_imports`), `src/core/project_resolution.py`,
`src/core/lsp_client.py`, `src/mcp/tools/lsp_tools.py`.
