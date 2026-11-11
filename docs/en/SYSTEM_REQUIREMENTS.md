# System Requirements

[English](SYSTEM_REQUIREMENTS.md) · [Русский](../ru/SYSTEM_REQUIREMENTS.md) · [中文](../zh/SYSTEM_REQUIREMENTS.md)

> Version 3.5.0. Measured values below state the machine and the date. Anything
> not measured says so. Chunk/file/timing figures are not repeated here — they
> live in `docs/FACTS.md`, which also carries the command that regenerates them.

---

## 1. Required

| Component | Requirement | Source of truth |
|---|---|---|
| Python | **3.14 or newer** | `requires-python = ">=3.14"` in `pyproject.toml` |
| OS | Windows (validated) or Linux (CI-tested); macOS untested | `.github/workflows/ci.yml` matrix: `ubuntu-latest` + `windows-latest` |
| Interpreter | CPython only | wheels pinned with `==` in `pyproject.toml` |
| Disk | free space for the chunk store + data root | see §3 |
| Host | OpenCode (primary) or the Zed extension | `install.py`, `extension.toml` |

Python 3.10–3.13 are **not** supported, even though old classifiers in
`pyproject.toml` still list 3.10–3.12. CI installs 3.14 only.

No GPU, no Docker, no WSL, and no network access are needed for the default
text-first runtime. Docker images are built in CI (`docker-build` job) from
`deploy/docker/`; running them locally is optional and unrelated to the normal
MCP setup.

## 2. Host

OpenCode launches the MCP server directly:

```
%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\venv\Scripts\mscodebase-mcp.exe -u -m src.main
```

with `PYTHONPATH` set to the extension directory and `PROJECT_PATH` set to the
workspace. On Windows `mscodebase-mcp.exe` is an NTFS hardlink to `pythonw.exe`
(created once by `install.py`), so no console window appears. The Zed extension
(`extension.toml`, `capabilities = ["context_servers"]`) uses
`venv\Scripts\pythonw.exe -u -m src.main` with `PYTHONUTF8=1`.

Consequence: both hosts run the **copied** code under
`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`, not this checkout.
After editing `src/`, run `python install.py --sync-only` and restart the host.

## 3. Disk (measured on this repository, 2026-11-08)

| Artifact | Size | Note |
|---|---:|---|
| `<project>/.mscodebase/chunks.db` | **77.9 MiB** | text + FTS5 index for this repo; chunk count in `docs/FACTS.md` |
| `<data_root>/` (11 project folders) | **74.3 MiB** | graph, memory, telemetry, commit cache, residual LanceDB tables |
| `.codebase_models/` (optional) | **960.1 MiB** | ONNX + GGUF model files present on this machine |
| `models/` (optional) | **839.4 MiB** | GGUF models copied for the extension |

Rule of thumb: the text index is proportional to the indexed corpus and roughly
an order of magnitude smaller than a vector index over the same corpus. The
optional model directories dominate when they exist and are absent otherwise.
`install.py` downloads models only with `--with-models` (`models_enabled()` in
`install.py`); the default is text-first with no prompt and no download, so a
text-only installation is the size of the code plus the chunk store.

`artifact_paths.check_disk_space()` warns when the data root has less than
**500 MB** free (`MIN_FREE_DISK_MB`); the CI guard fails below 1 GB.
`artifact_gc` prunes inactive project folders, telemetry older than 90 days and
old logs in a background thread 3 s after start.

## 4. Memory

**Not measured in this pass.** No RSS figure is quoted here because no
measurement was taken on a controlled configuration in this session; older
numbers in this file's history (hundreds of MB for llama.cpp servers, GB-scale
for in-process ONNX) described a different provider stack and must not be
reused.

What can be stated from code: the default text-first path loads no model into
the MCP process. Memory grows with the SQLite page cache, the parsed chunk
buffers during a reindex, and the PropertyGraph connection. If you enable an
optional provider, the model process is separate (`llama-server.exe` for GGUF,
`onnx_server.py` for ONNX, or an external LM Studio/Ollama instance), so its
footprint is not the MCP process's footprint.

To measure on your machine:

```powershell
Get-Process | Where-Object { $_.ProcessName -in @('mscodebase-mcp','python','pythonw') } |
  Select-Object ProcessName, Id, @{n='RSS_MB';e={[math]::Round($_.WorkingSet64/1MB,1)}}
```

Record the command and output if you publish the number.

## 5. CPU

x86_64 is the only architecture exercised by measured runs here. ARM64 is
untested. CPU-feature requirements of the pinned `onnxruntime==1.27.0` wheel
(AVX2 and similar) were **not verified** on this project, so no such requirement
is claimed.

Tree-sitter grammars ship as `abi3` wheels, so parsing has no CPU feature
requirement beyond a normal CPython build.

## 6. Optional providers and their defaults

All loopback, all optional, all disabled unless you enable them:

| Provider | Endpoint | Env |
|---|---|---|
| LM Studio | `http://127.0.0.1:1234` | `LM_STUDIO_HOST`, `LM_STUDIO_PORT` |
| Ollama | `http://127.0.0.1:11434` | `OLLAMA_HOST`, `OLLAMA_PORT` |
| llama.cpp embedder | `127.0.0.1:8080` | `LLAMA_CPP_PORT` |
| llama.cpp reranker | `127.0.0.1:8081` | `LLAMA_CPP_RERANK_PORT` |
| ONNX server | `127.0.0.1:1235` | `ONNX_SERVER_PORT` |

A GPU is only relevant to llama.cpp's Vulkan backend (`LLAMA_BACKEND=vulkan`; the
code default is `msvc`, i.e. CPU, and Vulkan is used only when explicitly set)
or to ONNX DirectML/CUDA execution providers (`MSCODEBASE_ONNX_PROVIDER`). The
default path never requires one.

`basedpyright` is required only for the six `lsp_*` tools and for
`check_types=True` on write operations. Without
`basedpyright-langserver` on `PATH`, those tools return a clear
"LSP недоступен (basedpyright не найден)" message and the rest of the server is
unaffected.

## 7. Network

Offline by default. Network is used only for (a) `install.py` model/binary
downloads you approve, (b) `pip install`, (c) the optional
`tree-sitter-language-pack` (`MSCODEBASE_LANGUAGE_PACK=true`), whose extra
parsers are fetched on first use, and (d) pointing a provider at a remote
endpoint yourself. With the flag off, 31 grammars come from pinned wheels.

## 8. Quick preflight

```powershell
python --version                     # must print 3.14.x
python -c "import src.main"          # dependencies importable
python -m pytest tests/ -q           # default selection (slow/benchmark excluded)
```

Then, inside the host: `tool_help()` for the visible surface and
`get_health_report()` for index, providers and disk.

---

**Verified against:** `pyproject.toml`, `.github/workflows/ci.yml`,
`src/core/artifact_paths.py` (`MIN_FREE_DISK_MB`, data-root layout),
`src/core/artifact_gc.py` (retention defaults), `src/config/settings.py`
(provider hosts and ports), `extension.toml`, `install.py`,
`src/providers/reranker/llama_runner.py` (`RERANK_PORT`), `docs/FACTS.md`,
`AGENTS.md` §0.5. Disk sizes measured with `Get-Item` / `Get-ChildItem` on this
checkout, 2026-11-08. RAM: not measured.
