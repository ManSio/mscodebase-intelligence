# Install AI Models — 3 Methods

> Choose your method: **Auto** (install.py), **Manual** (ONNX + GGUF), or **LM Studio** (legacy fallback)

> **Provider reality (2026-07-12):** The **embedder runs in-process** via
> **ONNX multilingual-e5-small-int8 / OpenVINO INT8** (`multilingual-e5-small-int8`, 384-dim, ~37 ch/s
> on Windows CPU). `install.py` downloads this automatically. The **reranker** is a separate
> `llama-server.exe` process serving the `bge-reranker-v2-m3` GGUF model. `LM Studio` is only
> an optional fallback if the local ONNX model is unavailable.

---

## METHOD 1: Auto — install.py (Recommended)

> **Best for:** All users. Installs llama.cpp + ONNX + GGUF models automatically.

```bash
python install.py
```

**What happens:**
1. Detects Windows/macOS/Linux, AVX2/AVX512, Vulkan GPU
2. Downloads `llama-server.exe` (or binary for your platform) — used for the **reranker**
3. Downloads **multilingual-e5-small-int8** (~113 MB) — **embedding model (in-process)**
4. Downloads **bge-reranker-v2-m3 GGUF** (`BAAI/bge-reranker-v2-m3`, ~544 MB) — **reranker model**
5. Starts the reranker llama-server process on port `:8081`

**Disk usage after install:** ~900 MB (llama binary + ONNX embedder + GGUF reranker)

### System behavior

| Scenario | What runs | Memory |
|----------|-----------|--------|
| ONNX/OpenVINO E5-base (default) | in-process embedder + 1× llama-server (rerank) | ~1.0 GB |
| Vulkan GPU available | llama-server with `-ngl 99` (GPU offload, reranker only) | ~1.0 GB |
| CPU only (no Vulkan) | llama-server with `-ngl 0` (CPU only, reranker) | ~700 MB |
| LM Studio fallback | external API on `:1234` (if enabled) | ~3-6 GB |

---

## METHOD 2: Manual — ONNX + GGUF Download

> **Best for:** Users who want to download models manually.

**Embedding model (E5-base v2 ONNX, required — in-process):**
```bash
python scripts/download_model.py --model intfloat/multilingual-e5-small-int8
# → .codebase_models/onnx/e5-base-v2/model_quantized.onnx (INT8)
```

**Reranker model (bge-reranker-v2-m3 GGUF, required):**
```bash
# From HuggingFace
huggingface-cli download lm-kit/bge-reranker-v2-m3-gguf \
  Bge-M3-reranker-2-3-568M-Q4_K_M.gguf \
  --local-dir extensions/mscodebase-intelligence/models/
```

> The ONNX embedder is the **default and primary** path. The GGUF reranker runs as a
> separate `llama-server.exe` process. You do NOT need a GGUF *embedding* model for search.

---

## METHOD 3: LM Studio (Legacy Fallback)

> **Best for:** Users who already have LM Studio with models installed and want it as a fallback.

LM Studio can still be used as a fallback embedding provider. If the local ONNX model is
unavailable, MSCodeBase can switch to LM Studio (set `EMBEDDING_PROVIDER=lm_studio`).

| Model | Size | Purpose |
|-------|:----:|---------|
| `text-embedding-bge-m3` | ~2.2 GB | Embedding fallback (vector search) |
| `bge-reranker-v2-m3` | ~1.1 GB | Reranking (cross-encoder) |
| `phi-4-mini-instruct` | ~2.8 GB | `mode=ask` RAG generation (optional) |

See [`LM_STUDIO_SETUP.md`](LM_STUDIO_SETUP.md) for detailed setup.

---

## Comparison Table

| Criterion | Method 1 (Auto) | Method 2 (Manual) | Method 3 (LM Studio) |
|-----------|:---------------:|:-----------------:|:--------------------:|
| **Embedder** | ONNX E5-base INT8 (in-process) | ONNX E5-base INT8 | LM Studio (bge-m3) |
| **Reranker** | llama.cpp GGUF | llama.cpp GGUF | LM Studio |
| **GPU** | Vulkan (reranker only) | Vulkan (reranker only) | Any (CUDA/Metal) |
| **RAM (total)** | **~1.0 GB** | **~1.0 GB** | ~3-6 GB |
| **Disk** | **~900 MB** | **~900 MB** | ~6 GB |
| **Install time** | **3 min** | 5 min | 20 min |
| **mode=ask** | ❌ No (needs LLM profile) | ❌ No | ✅ Yes |

---

## Model Configuration

### `.env` Variables

```ini
# Embedding provider: e5_onnx (default, in-process) | openvino | lm_studio
EMBEDDING_PROVIDER=e5_onnx

# ONNX model slug (downloaded by install.py)
#   multilingual-e5-small-int8  → intfloat/multilingual-e5-small-int8 (384-dim, INT8)
ONNX_MODEL=multilingual-e5-small-int8

# Reranker GGUF model served by llama-server on :8081
RERANKER_MODEL=bge-reranker-v2-m3

# llama.cpp backend for reranker: auto, msvc, or vulkan
LLAMA_BACKEND=auto

# GPU layers for reranker (0 = CPU only, 99 = all layers on GPU)
LLAMA_NGL=99

# Context size for reranker (1024 is sufficient for bge-reranker-v2-m3)
LLAMA_CTX_SIZE=1024
```
