# Installing Models (optional)

[English](INSTALL_MODELS.md) · [Русский](../ru/INSTALL_MODELS.md) · [中文](../zh/INSTALL_MODELS.md)

> Version 3.5.0. **No model is required for the default runtime.** Text-first
> search (`MSCODEBASE_DENSE_OFF=true`) reads chunks from SQLite FTS5 and the
> PropertyGraph, so a fresh install is usable before any model exists. Install
> models only if you want live embedding/reranking quality or a local chat model.

---

## 1. What can be installed, and why

| Artifact | Role | Size (declared in code) |
|---|---|---|
| `multilingual-e5-small-int8` (ONNX) | in-process embedder, 384-dim | ~113 MB |
| `reranker-bge-reranker-v2-m3` (ONNX) | in-process/HTTP reranker | ~544 MB |
| `multilingual-e5-small-Q8_0.gguf` | llama.cpp embedder, 384-dim | ~126 MB |
| `bge-reranker-v2-m3` GGUF (`Bge-M3-568M-Q4_K_M`) | llama.cpp reranker | ~418 MB |
| `llama-server.exe` (llama.cpp build `b11476`) | host for the GGUF models | depends on build |
| `qwen3-embedding-0.6b-q4_k_m.gguf` (optional) | alternative embedder, 1024-dim | ~379 MB |
| `bge-m3-Q4_K_M.gguf` (optional) | alternative embedder, 1024-dim | ~417 MB |
| `embeddinggemma-2-Q8_0.gguf` (optional) | alternative embedder, 768-dim | ~296 MB |

The GGUF table (`GGUF_MODELS` in `src/providers/reranker/llama_install.py`) also
carries the embedding dimension each model produces — that dimension must match
`EMBEDDING_DIMENSION` if you store vectors. SHA-256 values are recorded for some
entries (qwen3-embedding, bge-m3, bge-reranker-v2-m3) and logged at download
time; the download path does not compare them, so a hash here is a reference
value, not a verified-pin. (The llama.cpp **binary** archive *is* hash-checked
before extraction.)

## 2. Method 1 — `install.py` (models are opt-in)

```bash
python install.py --with-models
```

Without `--with-models` the installer is text-first: `step_models` and `step_gguf`
return immediately (`install.py::models_enabled`), so no model is downloaded, no
model directory is created and no prompt is shown. With `--with-models`:

- ONNX: `multilingual-e5-small-int8` (~113 MB) + `bge-reranker-v2-m3` (~544 MB);
- GGUF + llama.cpp: the GGUF step downloads `multilingual-e5-small` and
  `bge-reranker-v2-m3` and the llama.cpp binary for the selected backend;
- every step offers `[r]etry / [s]kip / [c]ancel` on failure.

Useful flags:

| Flag | Effect |
|---|---|
| `--sync-only` / `--sync` | copy the code into the install root, touch nothing else (use this after editing `src/`) |
| `--with-models` | run the model steps (ONNX + GGUF); this is the only way to get them |
| `--skip-models` / `--no-models` | accepted for old scripts; models are already skipped by default |
| `--no-zed` | do not touch Zed settings (host-neutral install) |
| `--yes` / `-y` | accept every step instead of prompting |
| `--verbose` / `-v` | full step output instead of the compact view |

Files land in the install root (`MSCODEBASE_INSTALL_ROOT`, default the historical
extension directory `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`):

- ONNX → `<ext>/.codebase_models/onnx/<slug>/model_quantized.onnx`
  (its specialised reranker subfolder uses `model.onnx`);
- GGUF → `<ext>/models/<file>.gguf`;
- existing copies are reused from the extension dir, then
  `~/.cache/mscodebase/models`, then the project root, and copied instead of
  re-downloaded.

After the run, restart the host. Nothing is hot-reloaded.

## 3. Method 2 — manual

Models are plain files in known places; there is no registration step.

```bash
# ONNX (embedder + reranker)
mkdir -p .codebase_models/onnx/multilingual-e5-small-int8
# place model_quantized.onnx there (repo: keisuke-miyako/multilingual-e5-small-onnx-int8)

# GGUF copies are looked up by exact filename
ls models/            # multilingual-e5-small-Q8_0.gguf, Bge-M3-568M-Q4_K_M.gguf
```

Lookup order for GGUF is the extension `models/` dir, then
`~/.cache/mscodebase/models` (see `_get_models_dir`). Put the file in either;
duplicating it into the extension dir avoids surprises after an upgrade.

## 4. Ports and processes

| Process | Default port | Env |
|---|---|---|
| llama.cpp embedder (`llama-server.exe`) | `8080` | `LLAMA_CPP_PORT`, `LLAMA_CPP_HOST` |
| llama.cpp reranker | `8081` | `LLAMA_CPP_RERANK_PORT` |
| ONNX server (subprocess) | `1235` | `ONNX_SERVER_PORT`, `ONNX_SERVER_HOST` |
| LM Studio (external) | `1234` | `LM_STUDIO_PORT` |
| Ollama (external) | `11434` | `OLLAMA_PORT` |

llama.cpp's backend is `msvc` (CPU) by default; `LLAMA_BACKEND=vulkan` switches
to the GPU binary and sets `-ngl` from `LLAMA_NGL` (default 99). Ports are
validated to stay inside `8080-8090` before a spawn; a port outside that range is
skipped with a warning.

Two model contexts are tuned separately: `LLAMA_EMBED_MAX_TOKENS` (default 480,
truncated by the client) and `LLAMA_RERANK_MAX_TOKENS` (default 1000, a
query+passage pair). The physical batch is derived per role
(`resolve_ubatch`): embed → 512, rerank → 1024.

## 5. Naming defaults — a real inconsistency

Two different defaults exist in the code:

- `src/config/settings.py`: `EMBEDDING_MODEL` defaults to `qwen3-embedding`;
- `src/providers/reranker/llama_install.py`: `DEFAULT_EMBEDDING_MODEL` defaults
  to `embeddinggemma-2` (env `EMBEDDING_MODEL` overrides it).

`install.py`'s GGUF step downloads `multilingual-e5-small` for the embedder
regardless of either default. Pin the model explicitly in `.env`
(`EMBEDDING_MODEL=...`) if the choice matters to you; do not rely on the default
agreeing between modules.

## 6. Verifying

```powershell
curl http://127.0.0.1:8080/health     # llama.cpp embedder
curl http://127.0.0.1:8081/health     # llama.cpp reranker
curl http://127.0.0.1:1235/health     # ONNX server
```

In the host: `intel_get_telemetry()` shows the live `provider`, `model`,
`ping_ms` and `tokens_per_sec`; `llm.error` means the ping failed rather than
being skipped. `get_health_report()` includes the provider block.

## 7. Removing models

Delete the files; no registry entry survives them:

```powershell
Remove-Item .codebase_models\onnx\<slug> -Recurse -Force
Remove-Item models\<file>.gguf -Force
```

If the dense path was enabled and vectors exist, also
`python scripts/reindex_text_only.py --project .` (or `intel_reset_index()`),
otherwise stored vectors keep the old dimension. Model directories are
git-ignored (`.codebase_models/`, `models/`), so nothing appears in `git status`.

---

**Verified against:** `install.py` (`STEPS`, `models_enabled`, `step_models`,
`step_gguf`, `--sync-only`, `--with-models`, `--skip-models`, `--yes`, `--no-zed`),
`src/providers/reranker/llama_install.py` (`GGUF_MODELS` sizes/dims/SHA-256,
`LLAMA_VERSION`, `LLAMA_PORT`, `DEFAULT_EMBEDDING_MODEL`, `resolve_ubatch`,
`_patch_dll_imports`), `src/providers/reranker/llama_runner.py`
(`RERANK_PORT`, port range check, `LLAMA_BACKEND`/`LLAMA_NGL`),
`src/config/settings.py` (provider ports, `EMBEDDING_MODEL`),
`.env.example`, `.gitignore`.
