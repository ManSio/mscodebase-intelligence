# Install AI Models — 3 Methods

> Choose your method: **Manual** (UI), **Script** (CLI), or **Agent** (AI-driven)

---

## METHOD 1: Manual — LM Studio GUI

> **Best for:** First-time users who want visual feedback

1. Open **LM Studio**
2. Go to **Search** tab
3. Search and download these 3 models:

| Model | Search Query | Size |
|-------|-------------|------|
| `text-embedding-bge-m3` | `bge-m3` | ~2.2 GB |
| `bge-reranker-v2-m3` | `bge-reranker-v2-m3` | ~1.1 GB |
| `phi-4-mini-instruct` | `phi-4-mini-instruct` | ~2.8 GB |

4. Go to **Local Server** tab → load all 3 → Start Server (port 1234)
5. Verify: `curl http://127.0.0.1:1234/v1/models`

---

## METHOD 2: Script — One-Click Installer

> **Best for:** Users who want automation

```bash
# Quick install (recommended):
python install.py

# Manual download (both models, auto-clean = no garbage):
cd scripts
python download_model.py --model BAAI/bge-m3 --type embedding --auto-clean
python download_model.py --model BAAI/bge-reranker-v2-m3 --type reranker --auto-clean
```

**What happens:**
1. Downloads BAAI/bge-m3 → `.codebase_models/onnx/bge-m3/model.onnx` (438 MB)
2. Downloads BAAI/bge-reranker-v2-m3 → `.codebase_models/onnx/bge-reranker/model.onnx` (636 MB)
3. Auto-clean: removes HuggingFace cache, torch cache, safetensors, bin files
4. **Final disk usage: ~1.1 GB** (only ONNX files, zero garbage)

**System behavior after installation:**
- If LM Studio is online → uses LM Studio (faster, GPU)
- If LM Studio is offline but ONNX models exist → uses ONNX Runtime (CPU)
- If no models at all → degraded BM25-only mode

---

## METHOD 3: Agent — AI-Powered Installation

> **Best for:** Users who want to copy-paste one instruction to any AI agent
> (Zed AI, Claude, ChatGPT, etc.) and let it handle everything

### 📋 Copy this entire block to your AI agent:

```
## Task: Install AI models for MSCodeBase Intelligence

You are an expert Python/systems engineer. Install both ONNX models
for the MSCodeBase code search engine at the project root.

### Prerequisites
- Python 3.10+ with pip
- The project is already cloned and `pip install -r requirements.txt` is done
- Working directory is the project root

### Step 1: Install PyTorch + ONNX Runtime
Run:
```bash
pip install torch onnxruntime onnxscript transformers huggingface-hub
```

### Step 2: Download embedding model (BAAI/bge-m3, 438 MB)
Run:
```bash
python scripts/download_model.py --model BAAI/bge-m3 --type embedding --auto-clean
```

### Step 3: Download reranker model (BAAI/bge-reranker-v2-m3, 636 MB)
Run:
```bash
python scripts/download_model.py --model BAAI/bge-reranker-v2-m3 --type reranker --auto-clean
```

### Step 4: Verify installation
Check that both ONNX files exist:
```bash
ls -la .codebase_models/onnx/bge-m3/model.onnx
ls -la .codebase_models/onnx/bge-reranker/model.onnx
```

Expected output:
```
.../bge-m3/model.onnx    (438 MB)
.../bge-reranker/model.onnx (636 MB)
```

### Step 5: Clean up garbage
```bash
# Remove HuggingFace cache (saves ~2 GB)
rm -rf ~/.cache/huggingface/hub
rm -rf ~/.cache/mscodebase/hf_models

# Remove PyTorch compilation cache
rm -rf ~/.cache/torch/compilation*

# Remove pip cache
pip cache purge
```

### Step 6: System check
Run a quick integration test:
```bash
python -c "
from src.core.config import get_config
from src.core.remote_embedder import RemoteEmbedder
import asyncio

async def test():
    emb = RemoteEmbedder()
    await emb.warmup()
    vec = await emb.embed_async('test query')
    print(f'Embedding OK: {len(vec)} dims')

asyncio.run(test())
"
```

Expected: `Embedding OK: 1024 dims`

### What NOT to do
- Do NOT use `--purge-cache` without `--auto-clean` (leaves HF cache at ~2 GB)
- Do NOT skip the cleanup step (leaves garbage in ~/.cache/)
- Do NOT use the embedder without running warmup first (cold start takes ~30s on CPU)
```

---

## Comparison Table

| Criterion | Method 1 (Manual) | Method 2 (Script) | Method 3 (Agent) |
|-----------|:-----------------:|:-----------------:|:----------------:|
| Time to install | ~20 min | ~10 min | ~10 min |
| User interaction | Full (download, load, config) | One command | None (AI does it) |
| Garbage left | None | **Zero** (auto-clean) | **Zero** (cleanup step) |
| Disk usage (final) | ~6 GB (GGUF) | ~1.1 GB (ONNX) | ~1.1 GB (ONNX) |
| Requires LM Studio? | ✅ Yes | ❌ No (ONNX fallback) | ❌ No (ONNX fallback) |
| GPU support | ✅ Yes | ❌ CPU only | ❌ CPU only |
| mode=ask support | ✅ Yes | ❌ No | ❌ No |
