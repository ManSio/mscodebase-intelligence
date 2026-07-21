# LM Studio 设置指南 — MSCodeBase Intelligence

> **最后更新：** 2026-07-12 | **适用版本：** v3.2.0+

## ⚠️ LM Studio 现为次要方案

**自 2026-07-12 起，主要嵌入提供者（provider）为 ONNX E5-base INT8（进程内 CPU，768 维）。**
LM Studio 是**回退（fallback）提供者（provider）**，在以下场景中必需：
- **`mode=ask`**（通过 phi-4 进行 RAG 生成）— llama.cpp 不支持聊天功能
- 偏好使用 LM Studio GUI 进行模型管理的用户

**默认提供者（provider）优先级：**
```
1. ONNX E5-base INT8（进程内 CPU，768 维）
2. LM Studio（外部 API，端口 1234）
3. Ollama（外部 API，端口 11434）
4. 仅 BM25（关键词搜索）
```

主要安装方法请参见 [`INSTALL_MODELS.md`](INSTALL_MODELS.md)。

---

## 为什么选择 LM Studio（旧版）？

MSCodeBase 可以通过 LM Studio 的 OpenAI 兼容 API 使用 **本地 AI 模型**。
它在您的机器上 **完全离线** 运行 — 无需云服务、无数据外传、无 API 费用。

### ONNX/OpenVINO 模型（主要，进程内）

| 模型 | 类型 | 用途 | 大小 |
|-------|------|---------|:----:|
| `multilingual-e5-base` INT8/FP32 | 嵌入（768 维） | 向量语义搜索 | 105 MB / 266 MB |
| `bge-reranker-v2-m3`（ONNX） | 交叉编码器 | 结果重排序 | 544 MB |

> **E5-base ONNX** — 主要的嵌入器（embedder），在 MCP 进程内运行，无需外部依赖。
> BGE-M3 重排序器（reranker）为 ONNX 模型，通过 onnx_server.py（端口 1235）或 llama.cpp（端口 8081）运行。

### LM Studio 模型（仅回退 fallback）

| 模型 | 类型 | 用途 | 大小 |
|-------|------|---------|:----:|
| `text-embedding-bge-m3` | 嵌入（1024 维） | 回退（fallback）向量搜索 | ~2.2 GB |
| `bge-reranker-v2-m3` | 交叉编码器 | 回退（fallback）重排序 | ~1.1 GB |

> LM Studio **仅当 ONNX/OpenVINO 模型不可用时**才使用。
> 默认情况下 LM Studio 为回退（fallback）。

### 替代方案：llama.cpp GGUF（重排序器推荐）

| 模型 | 大小 | RAM | 用途 |
|-------|:----:|:---:|---------|
| bge-reranker-v2-m3 Q4_K_M | **418 MB** | 684 MB | 重排序（交叉编码器，推荐） |

**相比 LM Studio 的优势：**
- 内存占用小 5 倍（总计 ~1.0 GB vs ~6 GB）
- 无需外部应用程序（作为子进程运行）
- 由 `install.py` 自动安装
- 支持 Vulkan GPU

---

## 方法 1：通过 MSCodeBase 安装程序安装（推荐）

```bash
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence
python install.py
```

安装程序将：
1. 检测您机器上的 LM Studio
2. 如果 LM Studio **在线** → 显示需要加载哪些模型
3. 如果 LM Studio **离线** → 提供下载 ONNX 回退（fallback）模型的选项
4. 引导您完成剩余的设置

---

## 方法 2：手动设置 LM Studio

### 步骤 1：安装 LM Studio

1. 从 [lmstudio.ai](https://lmstudio.ai/) 下载
2. 安装并启动 LM Studio
3. 进入 **设置** → **本地服务器** 选项卡
4. 启用 **"服务地址"**，端口设为：`1234`
5. 启用 **CORS**（允许所有来源）
6. 启用 **"启动时自动加载模型"**

### 步骤 2：下载模型

在 LM Studio 的 **搜索** 选项卡中，搜索并下载每个模型：

#### 1. text-embedding-bge-m3（必需）
```
搜索："bge-m3"
→ 选择："text-embedding-bge-m3" 
→ 点击下载（建议量化：Q8_0）
```

#### 2. bge-reranker-v2-m3（必需）
```
搜索："bge-reranker-v2-m3"  
→ 选择模型
→ 点击下载（建议量化：Q8_0）
```

#### 3. phi-4-mini-instruct（可选，用于 mode=ask）
```
搜索："phi-4-mini-instruct"
→ 选择模型
→ 点击下载（建议量化：Q4_K_M）
```

### 步骤 3：加载模型

在 LM Studio 的 **本地服务器** 选项卡中，按以下顺序加载模型：

1. 点击 **"添加模型"** → 选择 `text-embedding-bge-m3`
2. 点击 **"添加模型"** → 选择 `bge-reranker-v2-m3`
3. 点击 **"添加模型"** → 选择 `phi-4-mini-instruct`
4. 点击 **"启动服务器"**

### 步骤 4：验证

```bash
# 检查 LM Studio API
curl http://127.0.0.1:1234/v1/models

# 预期输出（3 个模型）：
# {
#   "data": [
#     {"id": "text-embedding-bge-m3", ...},
#     {"id": "bge-reranker-v2-m3", ...},
#     {"id": "phi-4-mini-instruct", ...}
#   ]
# }
```

---

## 方法 3：通过 Hugging Face CLI 下载

如果您更倾向于从终端下载模型：

```bash
# 安装 Hugging Face CLI
pip install huggingface-hub

# 下载 bge-m3 嵌入模型（GGUF，Q8_0）
huggingface-cli download mradermacher/bge-m3-GGUF \
  bge-m3.Q8_0.gguf \
  --local-dir %USERPROFILE%\.lmstudio\models

# 下载 bge-reranker-v2-m3（GGUF，Q8_0）
huggingface-cli download mradermacher/bge-reranker-v2-m3-GGUF \
  bge-reranker-v2-m3.Q8_0.gguf \
  --local-dir %USERPROFILE%\.lmstudio\models

# 下载 phi-4-mini-instruct（GGUF，Q4_K_M）
huggingface-cli download mradermacher/phi-4-mini-instruct-GGUF \
  phi-4-mini-instruct.Q4_K_M.gguf \
  --local-dir %USERPROFILE%\.lmstudio\models
```

> **注意：** LM Studio 模型目录在 Windows 上为 `%USERPROFILE%\.lmstudio\models\`，
> 在 macOS/Linux 上为 `~/.lmstudio/models/`。

---

## 配置参考

### LM Studio 的 `.env` 变量

```ini
# 嵌入提供者：auto, lm_studio, onnx, ollama
EMBEDDING_PROVIDER=auto

# LM Studio 连接
LM_STUDIO_HOST=127.0.0.1
LM_STUDIO_PORT=1234

# 默认嵌入模型名称
MODEL_NAME=text-embedding-bge-m3
EMBEDDING_DIMENSION=1024

# mode=ask LLM 设置
ASK_MODEL=phi-4-mini-instruct
ASK_TIMEOUT=60.0

# 重排序提供者（逗号分隔）
RERANKER_PROVIDERS=ollama,lm_studio
```

---

## 故障排除

### 未检测到 LM Studio
```
LM Studio / Ollama not running. Vector search will be unavailable.
```
- 确保 LM Studio 正在运行且服务器已启用，端口为 1234
- 检查防火墙设置（允许 LM Studio 在专用网络上通信）
- 验证：`curl http://127.0.0.1:1234/v1/models`

### 嵌入模型返回错误的维度
```
LM Studio вернул пустой список embeddings.
Проверьте что модель 'text-embedding-bge-m3' поддерживает embeddings.
```
- 确保您加载的是 `text-embedding-bge-m3` 模型（而非用于嵌入的 `phi-4`）
- 检查 `EMBEDDING_DIMENSION=1024` 是否与您的模型匹配
- 加载新模型后重启 LM Studio 服务器

### 重排序不工作
- 确保 `bge-reranker-v2-m3` 已在 LM Studio 中加载
- 检查 `RERANKER_PROVIDERS=ollama,lm_studio`
- 如果使用 Ollama：确保已拉取 `bge-reranker-v2-m3`：`ollama pull bge-reranker-v2-m3`

### phi-4 无响应（mode=ask）
```
mode=ask заблокирован в light profile
```
- 在 `.env` 中设置 `SYSTEM_PROFILE=server`
- 确保 `phi-4-mini-instruct` 已在 LM Studio 中加载
- 检查 `ASK_TIMEOUT=60.0`（如果模型较慢可适当增加）

---

## ONNX 备用方案（无 LM Studio）

如果无法运行 LM Studio，MSCodeBase 可以使用 **ONNX Runtime**
进行嵌入和重排序。安装程序会下载两个模型：

```bash
# 完整 ONNX 设置（推荐）：
python install.py
# → 第 6 步将下载两个模型

# 手动设置：
pip install onnxruntime transformers torch huggingface-hub

# 1. 嵌入模型（BAAI/bge-m3，438 MB）
python scripts/download_model.py --model BAAI/bge-m3 --type embedding
# → 保存至 .codebase_models/onnx/bge-m3/model.onnx

# 2. 重排序模型（BAAI/bge-reranker-v2-m3，636 MB）
python scripts/download_model.py --model BAAI/bge-reranker-v2-m3 --type reranker
# → 保存至 .codebase_models/onnx/bge-reranker/model.onnx
```

**ONNX 备用方案的限制：**
- 仅 CPU（无 GPU 加速）
- 处理大批量时比 LM Studio 慢
- 不支持 `mode=ask`（RAG 生成需要 LM Studio 中的 phi-4）
- 两个模型共占用约 ~1.1 GB 磁盘空间
