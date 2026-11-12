# 系统要求

[English](../en/SYSTEM_REQUIREMENTS.md) · [Русский](../ru/SYSTEM_REQUIREMENTS.md) · [中文](SYSTEM_REQUIREMENTS.md)

> 翻译：2026-11-08，来源 docs/en/SYSTEM_REQUIREMENTS.md。英文版为准。

> 版本 3.5.0。下文中的实测值会注明机器与日期。任何未测量的内容都会明说。块数/
> 文件数/计时数字不在此重复——它们在 `docs/FACTS.md` 中，那里也载有重新生成它们的
> 命令。

---

## 1. 必需项

| 组件 | 要求 | 事实来源 |
|---|---|---|
| Python | **3.14 或更新** | `pyproject.toml` 中的 `requires-python = ">=3.14"` |
| 操作系统 | Windows（已验证）或 Linux（CI 已测）；macOS 未测 | `.github/workflows/ci.yml` 矩阵：`ubuntu-latest` + `windows-latest` |
| 解释器 | 仅 CPython | `pyproject.toml` 中以 `==` 固定版本的 wheel |
| 磁盘 | 用于块存储 + data root 的空闲空间 | 见 §3 |
| 宿主 | OpenCode（主要）或 Zed 扩展 | `install.py`、`extension.toml` |

Python 3.10–3.13 **不**受支持，尽管 `pyproject.toml` 中旧的 classifiers 仍列出
3.10–3.12。CI 只安装 3.14。

默认的文本优先运行时不需要 GPU、Docker、WSL，也不需要网络访问。Docker 镜像在 CI
（`docker-build` 作业）中从 `deploy/docker/` 构建；本地运行它们是可选的，与常规
MCP 搭建无关。

## 2. 宿主

OpenCode 直接启动 MCP 服务器：

```
%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\venv\Scripts\mscodebase-mcp.exe -u -m src.main
```

其中 `PYTHONPATH` 设为扩展目录，`PROJECT_PATH` 设为工作区。在 Windows 上
`mscodebase-mcp.exe` 是指向 `pythonw.exe` 的 NTFS 硬链接（由 `install.py` 创建
一次），因此不会出现控制台窗口。Zed 扩展（`extension.toml`，
`capabilities = ["context_servers"]`）使用 `venv\Scripts\pythonw.exe -u -m src.main`
并带 `PYTHONUTF8=1`。

后果：两个宿主运行的都是在
`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence` 下**被复制**的代码，而不是
这个 checkout。修改 `src/` 之后要执行 `python install.py --sync-only` 并重启宿主。

## 3. 磁盘（在本仓库实测，2026-11-08）

| 产物 | 大小 | 说明 |
|---|---:|---|
| `<project>/.mscodebase/chunks.db` | **77.9 MiB** | 本仓库的文本 + FTS5 索引；块数在 `docs/FACTS.md` |
| `<data_root>/`（11 个项目目录） | **74.3 MiB** | 图、记忆、遥测、提交缓存、残留的 LanceDB 表 |
| `.codebase_models/`（可选） | **960.1 MiB** | 本机上存在的 ONNX + GGUF 模型文件 |
| `models/`（可选） | **839.4 MiB** | 为扩展复制的 GGUF 模型 |

经验法则：文本索引与被索引语料成正比，并且大致比同一语料上的向量索引小一个数量级。
可选模型目录在存在时占主导，不存在时为零。`install.py` 只在指定 `--with-models`
时下载模型（`install.py` 的 `models_enabled()`）；默认 text-first，既不提示也不下载，
所以纯文本安装的体积 = 代码 + 块存储。

当 data root 的空闲空间低于 **500 MB** 时，`artifact_paths.check_disk_space()` 会
警告（`MIN_FREE_DISK_MB`）；CI 守卫在低于 1 GB 时失败。`artifact_gc` 在启动 3 s
后于后台线程中清理不活跃的项目目录、超过 90 天的遥测以及旧日志。

## 4. 内存

**本轮未测量。** 这里不引用任何 RSS 数字，因为本次会话没有在受控配置上做过测量；
本文件历史中的旧数字（llama.cpp 服务器数百 MB、进程内 ONNX 达 GB 级）描述的是另一套
provider 栈，不得复用。

从代码可以确定的是：默认的文本优先路径不把任何模型加载进 MCP 进程。内存随 SQLite
页缓存、重建索引期间的已解析块缓冲区，以及 PropertyGraph 连接而增长。若启用可选
provider，模型进程是独立的（GGUF 用 `llama-server.exe`，ONNX 用
`onnx_server.py`，或外部的 LM Studio/Ollama 实例），因此它的占用不是 MCP 进程的
占用。

在你的机器上测量：

```powershell
Get-Process | Where-Object { $_.ProcessName -in @('mscodebase-mcp','python','pythonw') } |
  Select-Object ProcessName, Id, @{n='RSS_MB';e={[math]::Round($_.WorkingSet64/1MB,1)}}
```

如果你要公布这个数字，请连同命令与输出一起记录。

## 5. CPU

x86_64 是这里实测运行唯一涉及的架构。ARM64 未测。固定版本的
`onnxruntime==1.27.0` wheel 的 CPU 特性要求（AVX2 及类似）在本项目上**未经验证**，
因此不主张任何此类要求。

Tree-sitter 语法以 `abi3` wheel 形式发布，所以解析除正常的 CPython 构建外没有 CPU
特性要求。

## 6. 可选 provider 及其默认值

全部回环、全部可选、除非你启用否则全部关闭：

| Provider | 端点 | 环境变量 |
|---|---|---|
| LM Studio | `http://127.0.0.1:1234` | `LM_STUDIO_HOST`、`LM_STUDIO_PORT` |
| Ollama | `http://127.0.0.1:11434` | `OLLAMA_HOST`、`OLLAMA_PORT` |
| llama.cpp embedder | `127.0.0.1:8080` | `LLAMA_CPP_PORT` |
| llama.cpp reranker | `127.0.0.1:8081` | `LLAMA_CPP_RERANK_PORT` |
| ONNX server | `127.0.0.1:1235` | `ONNX_SERVER_PORT` |

GPU 只与 llama.cpp 的 Vulkan 后端（`LLAMA_BACKEND=vulkan`；代码默认是 `msvc`，
即 CPU，Vulkan 仅在显式设置时使用）或 ONNX 的 DirectML/CUDA 执行提供程序
（`MSCODEBASE_ONNX_PROVIDER`）有关。默认路径从不需要 GPU。

`basedpyright` 仅在六个 `lsp_*` 工具以及写入操作的 `check_types=True` 时需要。
若 `PATH` 中没有 `basedpyright-langserver`，这些工具会返回明确的
"LSP недоступен (basedpyright не найден)" 消息，服务器其余部分不受影响。

## 7. 网络

默认离线。网络仅用于 (a) 你批准的 `install.py` 模型/二进制下载，(b) `pip install`，
(c) 可选的 `tree-sitter-language-pack`（`MSCODEBASE_LANGUAGE_PACK=true`），其额外
解析器在首次使用时抓取，以及 (d) 你自己把 provider 指向远程端点。关闭该开关时，
31 个语法来自固定版本的 wheel。

## 8. 快速预检

```powershell
python --version                     # must print 3.14.x
python -c "import src.main"          # dependencies importable
python -m pytest tests/ -q           # default selection (slow/benchmark excluded)
```

然后在宿主内：`tool_help()` 查看可见表面，`get_health_report()` 查看索引、provider
与磁盘。

---

**Verified against:** `pyproject.toml`, `.github/workflows/ci.yml`,
`src/core/artifact_paths.py` (`MIN_FREE_DISK_MB`, data-root layout),
`src/core/artifact_gc.py` (retention defaults), `src/config/settings.py`
(provider hosts and ports), `extension.toml`, `install.py`,
`src/providers/reranker/llama_runner.py` (`RERANK_PORT`), `docs/FACTS.md`,
`AGENTS.md` §0.5. Disk sizes measured with `Get-Item` / `Get-ChildItem` on this
checkout, 2026-11-08. RAM: not measured.
