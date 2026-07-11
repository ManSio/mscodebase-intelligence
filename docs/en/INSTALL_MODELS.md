# Install AI Models — 3 Methods

> Choose your method: **Auto** (install.py), **Manual** (GGUF), or **LM Studio** (legacy)

---

## METHOD 1: Auto — install.py (Recommended)

> **Best for:** All users. Installs llama.cpp + GGUF models automatically.

```bash
python install.py
```

**What happens:**
1. Detects Windows/macOS/Linux, AVX2/AVX512, Vulkan GPU
2. Downloads `llama-server.exe` (or binary for your platform)
3. Downloads **bge-m3 Q4_K_M** (417 MB) — embedding model
4. Downloads **bge-reranker-v2-m3 Q4_K_M** (418 MB) — reranker model
5. Starts both llama-server processes on ports 8080 (embed) + 8081 (rerank)

**Disk usage after install:** ~900 MB (llama binary + 2 GGUF models)

### System behavior

| Scenario | What runs | Memory |
|----------|-----------|--------|
| llama.cpp installed | 2× llama-server (embed + rerank) | ~1.0 GB |
| Vulkan GPU available | llama-server with `-ngl 99` (GPU offload) | ~1.0 GB |
| CPU only (no Vulkan) | llama-server with `-ngl 0` (CPU only) | ~700 MB |

---

## METHOD 2: Manual — GGUF Download

> **Best for:** Users who want to download models manually.

**Embedding model (bge-m3, required):**
```bash
# From HuggingFace
huggingface-cli download lm-kit/bge-m3-gguf \
  bge-m3-Q4_K_M.gguf \
  --local-dir extensions/mscodebase-intelligence/models/
```

**Reranker model (bge-reranker-v2-m3, required):**
```bash
huggingface-cli download lm-kit/bge-m3-reranker-v2-gguf \
  Bge-M3-568M-Q4_K_M.gguf \
  --local-dir extensions/mscodebase-intelligence/models/
```

**Alternative embedding (Qwen3, for smaller RAM):**
```bash
huggingface-cli download coolbeev5/Qwen3-Embedding-0.6B-GGUF \
  qwen3-embedding-0.6b-q4_k_m.gguf \
  --local-dir extensions/mscodebase-intelligence/models/
# Set: EMBEDDING_MODEL=qwen3-embedding in .env (346 MB RAM)
```

---

## METHOD 3: LM Studio (Legacy)

> **Best for:** Users who already have LM Studio with models installed.

LM Studio can still be used as a fallback provider. If llama.cpp is not available,
MSCodeBase automatically switches to LM Studio.

| Model | Size | Purpose |
|-------|:----:|---------|
| `text-embedding-bge-m3` | ~2.2 GB | Embedding (vector search) |
| `bge-reranker-v2-m3` | ~1.1 GB | Reranking (cross-encoder) |
| `phi-4-mini-instruct` | ~2.8 GB | `mode=ask` RAG generation (optional) |

See [`LM_STUDIO_SETUP.md`](LM_STUDIO_SETUP.md) for detailed setup.

---

## Comparison Table

| Criterion | Method 1 (Auto) | Method 2 (Manual) | Method 3 (LM Studio) |
|-----------|:---------------:|:-----------------:|:--------------------:|
| **Provider** | llama.cpp GGUF | llama.cpp GGUF | LM Studio |
| **GPU** | Vulkan (auto) | Vulkan (auto) | Any (CUDA/Metal) |
| **RAM (total)** | **~1.0 GB** | **~1.0 GB** | ~3-6 GB |
| **Disk** | **~900 MB** | **~900 MB** | ~6 GB |
| **Install time** | **3 min** | 5 min | 20 min |
| **mode=ask** | ❌ No (needs LM Studio) | ❌ No | ✅ Yes |

---

## Model Configuration

### `.env` Variables

```ini
# Embedding model: bge-m3 (default) or qwen3-embedding
EMBEDDING_MODEL=bge-m3

# Backend: auto, msvc, or vulkan
LLAMA_BACKEND=auto

# GPU layers (0 = CPU only, 99 = all layers on GPU)
LLAMA_NGL=99

# Context size (1024 = ~500 MB RAM for Qwen3)
LLAMA_CTX_SIZE=1024
```
