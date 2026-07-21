# 安装 AI 模型 — 3 种方法

> 选择您的方法：**自动**（install.py）、**手动**（ONNX + GGUF）或 **LM Studio**（旧版回退 fallback）

> **提供者（provider）现状（2026-07-12）：** **嵌入器（embedder）进程内** 运行，通过
> **ONNX multilingual-e5-small-int8 / OpenVINO INT8**（`multilingual-e5-small-int8`，384 维，Windows CPU 上 ~37 ch/s）。
> `install.py` 自动下载它。**重排序器（reranker）** 是独立的 `llama-server.exe` 进程，提供 `bge-reranker-v2-m3`
> GGUF 模型。`LM Studio` 仅是可选回退（fallback），当本地 ONNX 模型不可用时。

---

## 方法 1: 自动 — install.py（推荐）

> **最适合：** 所有用户。自动安装 llama.cpp + ONNX + GGUF 模型。

```bash
python install.py
```

**发生了什么：**
1. 检测 Windows/macOS/Linux、AVX2/AVX512、Vulkan GPU
2. 下载 `llama-server.exe`（或您的平台二进制）— 用于 **重排序器（reranker）**
3. 下载 **multilingual-e5-small-int8**（~113 MB）— **嵌入模型（进程内）**
4. 下载 **bge-reranker-v2-m3 GGUF**（`BAAI/bge-reranker-v2-m3`，~544 MB）— **重排序器（reranker）模型**
5. 在端口 `:8081` 启动重排序器（reranker）的 llama-server 进程

**安装后磁盘占用：** ~900 MB（llama 二进制 + ONNX 嵌入器（embedder）+ GGUF 重排序器（reranker））

### 系统行为

| 场景 | 运行内容 | 内存 |
|----------|-----------|--------|
| ONNX/OpenVINO E5-base（默认） | 进程内嵌入器（embedder）+ 1× llama-server（重排序） | ~1.0 GB |
| 有 Vulkan GPU | llama-server 带 `-ngl 99`（GPU offload，仅重排序） | ~1.0 GB |
| 仅 CPU（无 Vulkan） | llama-server 带 `-ngl 0`（仅 CPU，重排序） | ~700 MB |
| LM Studio 回退（fallback） | `:1234` 上的外部 API（若启用） | ~3-6 GB |

---

## 方法 2: 手动 — ONNX + GGUF 下载

> **最适合：** 想手动下载模型的用户。

**嵌入模型（E5-base v2 ONNX，必需 — 进程内）：**
```bash
python scripts/download_model.py --model intfloat/multilingual-e5-small-int8
# → .codebase_models/onnx/e5-base-v2/model_quantized.onnx (INT8)
```

**重排序模型（bge-reranker-v2-m3 GGUF，必需）：**
```bash
# 从 HuggingFace
huggingface-cli download lm-kit/bge-reranker-v2-m3-gguf \
  Bge-M3-reranker-2-3-568M-Q4_K_M.gguf \
  --local-dir extensions/mscodebase-intelligence/models/
```

> ONNX 嵌入器（embedder）是 **默认且主要** 的路径。GGUF 重排序器（reranker）作为独立的 `llama-server.exe` 进程运行。
> 搜索不需要 GGUF *嵌入* 模型。

---

## 方法 3: LM Studio（旧版回退 Fallback）

> **最适合：** 已安装 LM Studio 并希望作为回退（fallback）的用户。

LM Studio 仍可用作回退（fallback）嵌入提供者（provider）。如果本地 ONNX 模型不可用，MSCodeBase 可切换到
LM Studio（设置 `EMBEDDING_PROVIDER=lm_studio`）。

| 模型 | 大小 | 用途 |
|-------|:----:|---------|
| `text-embedding-bge-m3` | ~2.2 GB | 嵌入回退（embedding fallback）（向量搜索） |
| `bge-reranker-v2-m3` | ~1.1 GB | 重排序（交叉编码器） |
| `phi-4-mini-instruct` | ~2.8 GB | `mode=ask` RAG 生成（可选） |

详见 [`LM_STUDIO_SETUP.md`](LM_STUDIO_SETUP.md)。

---

## 比较表

| 标准 | 方法 1（自动） | 方法 2（手动） | 方法 3（LM Studio） |
|-----------|:---------------:|:-----------------:|:--------------------:|
| **嵌入器（embedder）** | ONNX E5-base INT8（进程内） | ONNX E5-base INT8 | LM Studio（bge-m3） |
| **重排序器（reranker）** | llama.cpp GGUF | llama.cpp GGUF | LM Studio |
| **GPU** | Vulkan（仅重排序） | Vulkan（仅重排序） | 任意（CUDA/Metal） |
| **RAM（总计）** | **~1.0 GB** | **~1.0 GB** | ~3-6 GB |
| **磁盘** | **~900 MB** | **~900 MB** | ~6 GB |
| **安装时间** | **3 分钟** | 5 分钟 | 20 分钟 |
| **mode=ask** | ❌ 否（需要 LLM profile） | ❌ 否 | ✅ 是 |

---

## 模型配置

### `.env` 变量

```ini
# 嵌入提供者：e5_onnx（默认，进程内）| openvino | lm_studio
EMBEDDING_PROVIDER=e5_onnx

# ONNX 模型 slug（由 install.py 下载）
#   multilingual-e5-small-int8  → intfloat/multilingual-e5-small-int8（384 维，INT8）
ONNX_MODEL=multilingual-e5-small-int8

# 由 llama-server 在 :8081 提供服务的重排序器（reranker）GGUF 模型
RERANKER_MODEL=bge-reranker-v2-m3

# 重排序器（reranker）的 llama.cpp 后端：auto, msvc, 或 vulkan
LLAMA_BACKEND=auto

# 重排序器（reranker）的 GPU 层数（0 = 仅 CPU，99 = 所有层在 GPU）
LLAMA_NGL=99

# 重排序器（reranker）的上下文大小（1024 对 bge-reranker-v2-m3 足够）
LLAMA_CTX_SIZE=1024
```
