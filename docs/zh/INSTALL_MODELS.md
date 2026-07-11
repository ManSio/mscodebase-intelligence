# 安装 AI 模型 — 3 种方法

> 选择您的方式：**自动**（install.py）、**手动**（GGUF）或 **LM Studio**（旧版）

---

## 方法 1：自动 — install.py（推荐）

> **最适合：** 所有用户。自动安装 llama.cpp + GGUF 模型。

```bash
python install.py
```

**执行过程：**
1. 检测 Windows/macOS/Linux、AVX2/AVX512、Vulkan GPU
2. 下载 `llama-server.exe`（或对应平台的二进制文件）
3. 下载 **bge-m3 Q4_K_M**（417 MB）— 嵌入模型
4. 下载 **bge-reranker-v2-m3 Q4_K_M**（418 MB）— 重排序模型
5. 启动两个 llama-server 进程，分别监听端口 8080（嵌入）+ 8081（重排序）

**安装后磁盘占用：** ~900 MB（llama 二进制文件 + 2 个 GGUF 模型）

### 系统行为

| 场景 | 运行内容 | 内存 |
|----------|-----------|--------|
| 已安装 llama.cpp | 2× llama-server（嵌入 + 重排序） | ~1.0 GB |
| 有 Vulkan GPU | llama-server 带 `-ngl 99`（GPU 卸载） | ~1.0 GB |
| 仅 CPU（无 Vulkan） | llama-server 带 `-ngl 0`（仅 CPU） | ~700 MB |

---

## 方法 2：手动 — 下载 GGUF

> **最适合：** 希望手动下载模型的用户。

**嵌入模型（bge-m3，必需）：**
```bash
# 从 HuggingFace 下载
huggingface-cli download lm-kit/bge-m3-gguf \
  bge-m3-Q4_K_M.gguf \
  --local-dir extensions/mscodebase-intelligence/models/
```

**重排序模型（bge-reranker-v2-m3，必需）：**
```bash
huggingface-cli download lm-kit/bge-m3-reranker-v2-gguf \
  Bge-M3-568M-Q4_K_M.gguf \
  --local-dir extensions/mscodebase-intelligence/models/
```

**替代嵌入模型（Qwen3，适用于小内存）：**
```bash
huggingface-cli download coolbeev5/Qwen3-Embedding-0.6B-GGUF \
  qwen3-embedding-0.6b-q4_k_m.gguf \
  --local-dir extensions/mscodebase-intelligence/models/
# 设置：在 .env 中设置 EMBEDDING_MODEL=qwen3-embedding（346 MB 内存）
```

---

## 方法 3：LM Studio（旧版）

> **最适合：** 已安装 LM Studio 并带有模型的用户。

LM Studio 仍可作为备选提供者使用。如果 llama.cpp 不可用，
MSCodeBase 会自动切换到 LM Studio。

| 模型 | 大小 | 用途 |
|-------|:----:|---------|
| `text-embedding-bge-m3` | ~2.2 GB | 嵌入（向量搜索） |
| `bge-reranker-v2-m3` | ~1.1 GB | 重排序（交叉编码器） |
| `phi-4-mini-instruct` | ~2.8 GB | `mode=ask` RAG 生成（可选） |

详细设置请参见 [`LM_STUDIO_SETUP.md`](LM_STUDIO_SETUP.md)。

---

## 对比表

| 指标 | 方法 1（自动） | 方法 2（手动） | 方法 3（LM Studio） |
|-----------|:---------------:|:-----------------:|:--------------------:|
| **提供者** | llama.cpp GGUF | llama.cpp GGUF | LM Studio |
| **GPU** | Vulkan（自动） | Vulkan（自动） | 任意（CUDA/Metal） |
| **RAM（总计）** | **~1.0 GB** | **~1.0 GB** | ~3-6 GB |
| **磁盘** | **~900 MB** | **~900 MB** | ~6 GB |
| **安装时间** | **3 分钟** | 5 分钟 | 20 分钟 |
| **mode=ask** | ❌ 否（需要 LM Studio） | ❌ 否 | ✅ 是 |

---

## 模型配置

### `.env` 变量

```ini
# 嵌入模型：bge-m3（默认）或 qwen3-embedding
EMBEDDING_MODEL=bge-m3

# 后端：auto、msvc 或 vulkan
LLAMA_BACKEND=auto

# GPU 层数（0 = 仅 CPU，99 = 所有层在 GPU）
LLAMA_NGL=99

# 上下文大小（1024 = Qwen3 约 500 MB 内存）
LLAMA_CTX_SIZE=1024
```
