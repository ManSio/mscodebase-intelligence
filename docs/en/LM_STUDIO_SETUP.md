# LM Studio Setup Guide for MSCodeBase Intelligence

> **Last updated:** 2026-07-07 | **Applies to:** v2.7.0+

## Why LM Studio?

MSCodeBase uses **local AI models** for semantic code search. LM Studio provides
an OpenAI-compatible API that runs **fully offline** on your machine — no cloud,
no data egress, no API costs.

### Required Models

| Model | Type | Purpose | Required | Size |
|-------|------|---------|----------|------|
| `text-embedding-bge-m3` | Embedding (1024-dim) | Vector semantic search | **YES** | ~2.2 GB |
| `bge-reranker-v2-m3` | Cross-encoder | Result reranking | **YES** | ~1.1 GB |
| `phi-4-mini-instruct` | LLM (3.8B) | `mode=ask` RAG generation | Optional | ~2.8 GB |

### Fallback: ONNX Runtime (No GPU Required)

If LM Studio is not available, MSCodeBase automatically falls back to
**ONNX Runtime** with the `BAAI/bge-m3` model (~800 MB). This provides
basic vector search without requiring a separate server.

```bash
# Install ONNX fallback via the installer:
python install.py
# Or manually:
pip install onnxruntime transformers torch huggingface-hub
python scripts/download_model.py
```

> **Note:** ONNX fallback is CPU-only and does **not** support reranking
> or `mode=ask` LLM generation. For full functionality, use LM Studio.

---

## Method 1: Install via MSCodeBase Installer (Recommended)

```bash
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence
python install.py
```

The installer will:
1. Detect LM Studio on your machine
2. If LM Studio is **online** → show which models to load
3. If LM Studio is **offline** → offer to download ONNX fallback model
4. Guide you through the remaining setup

---

## Method 2: Manual LM Studio Setup

### Step 1: Install LM Studio

1. Download from [lmstudio.ai](https://lmstudio.ai/)
2. Install and launch LM Studio
3. Go to **Settings** → **Local Server** tab
4. Enable **"Serve at"** with port: `1234`
5. Enable **CORS** (all origins)
6. Enable **"Auto-load models on startup"**

### Step 2: Download Models

In LM Studio's **Search** tab, search for and download each model:

#### 1. text-embedding-bge-m3 (Required)
```
Search: "bge-m3"
→ Select: "text-embedding-bge-m3" 
→ Click Download (Quant: Q8_0 recommended)
```

#### 2. bge-reranker-v2-m3 (Required)
```
Search: "bge-reranker-v2-m3"  
→ Select the model
→ Click Download (Quant: Q8_0 recommended)
```

#### 3. phi-4-mini-instruct (Optional, for mode=ask)
```
Search: "phi-4-mini-instruct"
→ Select the model
→ Click Download (Quant: Q4_K_M recommended)
```

### Step 3: Load Models

In LM Studio's **Local Server** tab, load models in this order:

1. Click **"Add Model"** → select `text-embedding-bge-m3`
2. Click **"Add Model"** → select `bge-reranker-v2-m3`
3. Click **"Add Model"** → select `phi-4-mini-instruct`
4. Click **"Start Server"**

### Step 4: Verify

```bash
# Check LM Studio API
curl http://127.0.0.1:1234/v1/models

# Expected output (3 models):
# {
#   "data": [
#     {"id": "text-embedding-bge-m3", ...},
#     {"id": "bge-reranker-v2-m3", ...},
#     {"id": "phi-4-mini-instruct", ...}
#   ]
# }
```

---

## Method 3: Download via Hugging Face CLI

If you prefer downloading models from the terminal:

```bash
# Install Hugging Face CLI
pip install huggingface-hub

# Download bge-m3 embedding model (GGUF, Q8_0)
huggingface-cli download mradermacher/bge-m3-GGUF \
  bge-m3.Q8_0.gguf \
  --local-dir %USERPROFILE%\.lmstudio\models

# Download bge-reranker-v2-m3 (GGUF, Q8_0)
huggingface-cli download mradermacher/bge-reranker-v2-m3-GGUF \
  bge-reranker-v2-m3.Q8_0.gguf \
  --local-dir %USERPROFILE%\.lmstudio\models

# Download phi-4-mini-instruct (GGUF, Q4_K_M)
huggingface-cli download mradermacher/phi-4-mini-instruct-GGUF \
  phi-4-mini-instruct.Q4_K_M.gguf \
  --local-dir %USERPROFILE%\.lmstudio\models
```

> **Note:** LM Studio models directory is `%USERPROFILE%\.lmstudio\models\`
> on Windows, `~/.lmstudio/models/` on macOS/Linux.

---

## Configuration Reference

### `.env` Variables for LM Studio

```ini
# Embedding provider: auto, lm_studio, onnx, ollama
EMBEDDING_PROVIDER=auto

# LM Studio connection
LM_STUDIO_HOST=127.0.0.1
LM_STUDIO_PORT=1234

# Default embedding model name
MODEL_NAME=text-embedding-bge-m3
EMBEDDING_DIMENSION=1024

# mode=ask LLM settings
ASK_MODEL=phi-4-mini-instruct
ASK_TIMEOUT=60.0

# Reranker providers (comma-separated)
RERANKER_PROVIDERS=ollama,lm_studio
```

---

## Troubleshooting

### LM Studio not detected
```
LM Studio / Ollama not running. Vector search will be unavailable.
```
- Ensure LM Studio is running with the server enabled on port 1234
- Check firewall settings (allow LM Studio on private networks)
- Verify: `curl http://127.0.0.1:1234/v1/models`

### Embedded model returns wrong dimension
```
LM Studio вернул пустой список embeddings.
Проверьте что модель 'text-embedding-bge-m3' поддерживает embeddings.
```
- Ensure you loaded the `text-embedding-bge-m3` model (not `phi-4` for embeddings)
- Check that `EMBEDDING_DIMENSION=1024` matches your model
- Restart LM Studio server after loading a new model

### Reranker not working
- Ensure `bge-reranker-v2-m3` is loaded in LM Studio
- Check `RERANKER_PROVIDERS=ollama,lm_studio`
- If using Ollama: ensure `bge-reranker-v2-m3` is pulled: `ollama pull bge-reranker-v2-m3`

### phi-4 not responding (mode=ask)
```
mode=ask заблокирован в light profile
```
- Set `SYSTEM_PROFILE=server` in `.env`
- Ensure `phi-4-mini-instruct` is loaded in LM Studio
- Check `ASK_TIMEOUT=60.0` (increase if model is slow)

---

## ONNX Fallback Path (No LM Studio)

If you cannot run LM Studio, MSCodeBase can use **ONNX Runtime** as a fallback
for basic vector search:

```bash
# 1. Install dependencies
pip install onnxruntime transformers torch huggingface-hub

# 2. Download and export the ONNX model
python scripts/download_model.py --model BAAI/bge-m3

# 3. Model will be saved to .codebase_models/onnx/model.onnx
#    (~800 MB, 1024-dimension embeddings)
```

**Limitations of ONNX fallback:**
- CPU-only (no GPU acceleration)
- No reranking support
- No `mode=ask` (RAG generation)
- Slower embedding for large batches
