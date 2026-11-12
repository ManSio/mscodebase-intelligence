# 安装模型（可选）

[English](../en/INSTALL_MODELS.md) · [Русский](../ru/INSTALL_MODELS.md) · [中文](INSTALL_MODELS.md)

> 翻译：2026-11-08，来源 docs/en/INSTALL_MODELS.md。英文版为准。

> 版本 3.5.0。**默认运行时不需要任何模型。** 文本优先检索
> （`MSCODEBASE_DENSE_OFF=true`）从 SQLite FTS5 与 PropertyGraph 读取块，因此在任何
> 模型存在之前，全新安装就已可用。只有当你想要实时 embedding/reranking 质量或本地
> 聊天模型时，才安装模型。

---

## 1. 可以安装什么，以及为什么

| 产物 | 角色 | 大小（代码中声明） |
|---|---|---|
| `multilingual-e5-small-int8`（ONNX） | 进程内 embedder，384 维 | ~113 MB |
| `reranker-bge-reranker-v2-m3`（ONNX） | 进程内/HTTP reranker | ~544 MB |
| `multilingual-e5-small-Q8_0.gguf` | llama.cpp embedder，384 维 | ~126 MB |
| `bge-reranker-v2-m3` GGUF（`Bge-M3-568M-Q4_K_M`） | llama.cpp reranker | ~418 MB |
| `llama-server.exe`（llama.cpp 构建 `b11476`） | GGUF 模型的宿主 | 取决于构建 |
| `qwen3-embedding-0.6b-q4_k_m.gguf`（可选） | 备选 embedder，1024 维 | ~379 MB |
| `bge-m3-Q4_K_M.gguf`（可选） | 备选 embedder，1024 维 | ~417 MB |
| `embeddinggemma-2-Q8_0.gguf`（可选） | 备选 embedder，768 维 | ~296 MB |

GGUF 表（`src/providers/reranker/llama_install.py` 中的 `GGUF_MODELS`）还载有每个
模型产出的 embedding 维度——如果你要存储向量，该维度必须与 `EMBEDDING_DIMENSION`
匹配。部分条目录有 SHA-256 值（qwen3-embedding、bge-m3、bge-reranker-v2-m3）并在
下载时写入日志；下载路径并不比对它们，所以这里的哈希是参考值，不是已验证的固定值。
（llama.cpp **二进制**归档在解压前*确实*会做哈希校验。）

## 2. 方法一 —— `install.py`（模型需显式开启）

```bash
python install.py --with-models
```

不带 `--with-models` 时安装器为 text-first：`step_models` 与 `step_gguf` 立即返回
（`install.py::models_enabled`），不下载任何模型、不创建模型目录、也不弹出任何提示。
带 `--with-models` 时：

- ONNX：`multilingual-e5-small-int8`（约 113 MB）+ `bge-reranker-v2-m3`（约 544 MB）；
- GGUF + llama.cpp：GGUF 步骤下载 `multilingual-e5-small` 与
  `bge-reranker-v2-m3`，以及所选后端的 llama.cpp 二进制；
- 每一步在失败时都提供 `[r]etry / [s]kip / [c]ancel`。

有用的标志：

| 标志 | 作用 |
|---|---|
| `--sync-only` / `--sync` | 把代码复制进安装根，不碰其它任何东西（修改 `src/` 之后用这个） |
| `--with-models` | 执行模型步骤（ONNX + GGUF）；获取模型的唯一途径 |
| `--skip-models` / `--no-models` | 为旧脚本保留；默认已跳过 |
| `--no-zed` | 不修改 Zed 设置（宿主中立安装） |
| `--yes` / `-y` | 接受每个步骤，而不是提示 |
| `--verbose` / `-v` | 输出完整步骤内容，而不是紧凑视图 |

文件写入安装根（`MSCODEBASE_INSTALL_ROOT`，默认历史路径
`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`）：

- ONNX → `<ext>/.codebase_models/onnx/<slug>/model_quantized.onnx`
  （其专用 reranker 子目录使用 `model.onnx`）；
- GGUF → `<ext>/models/<file>.gguf`；
- 已存在的副本会从扩展目录、然后是 `~/.cache/mscodebase/models`、然后是项目根复用，
  被复制而不是重新下载。

运行结束后重启宿主。没有任何东西是热重载的。

## 3. 方法二 —— 手动

模型就是已知位置上的普通文件；没有注册步骤。

```bash
# ONNX (embedder + reranker)
mkdir -p .codebase_models/onnx/multilingual-e5-small-int8
# place model_quantized.onnx there (repo: keisuke-miyako/multilingual-e5-small-onnx-int8)

# GGUF copies are looked up by exact filename
ls models/            # multilingual-e5-small-Q8_0.gguf, Bge-M3-568M-Q4_K_M.gguf
```

GGUF 的查找顺序是扩展的 `models/` 目录，然后是 `~/.cache/mscodebase/models`
（见 `_get_models_dir`）。把文件放在其中任一处；同时复制进扩展目录可避免升级后的
意外。

## 4. 端口与进程

| 进程 | 默认端口 | 环境变量 |
|---|---|---|
| llama.cpp embedder（`llama-server.exe`） | `8080` | `LLAMA_CPP_PORT`、`LLAMA_CPP_HOST` |
| llama.cpp reranker | `8081` | `LLAMA_CPP_RERANK_PORT` |
| ONNX server（子进程） | `1235` | `ONNX_SERVER_PORT`、`ONNX_SERVER_HOST` |
| LM Studio（外部） | `1234` | `LM_STUDIO_PORT` |
| Ollama（外部） | `11434` | `OLLAMA_PORT` |

llama.cpp 的后端默认是 `msvc`（CPU）；`LLAMA_BACKEND=vulkan` 切到 GPU 二进制并从
`LLAMA_NGL`（默认 99）设置 `-ngl`。端口在启动前会被校验为落在 `8080-8090` 内；
超出该范围的端口会被跳过并给出警告。

两个模型上下文分别调优：`LLAMA_EMBED_MAX_TOKENS`（默认 480，由客户端截断）与
`LLAMA_RERANK_MAX_TOKENS`（默认 1000，一个查询+段落对）。物理批次按角色推导
（`resolve_ubatch`）：embed → 512，rerank → 1024。

## 5. 命名默认值 —— 一处真实的不一致

代码中存在两个不同的默认值：

- `src/config/settings.py`：`EMBEDDING_MODEL` 默认为 `qwen3-embedding`；
- `src/providers/reranker/llama_install.py`：`DEFAULT_EMBEDDING_MODEL` 默认为
  `embeddinggemma-2`（环境变量 `EMBEDDING_MODEL` 会覆盖它）。

无论这两个默认值是什么，`install.py` 的 GGUF 步骤都会为 embedder 下载
`multilingual-e5-small`。如果这个选择对你重要，在 `.env` 中显式固定模型
（`EMBEDDING_MODEL=...`）；不要指望各模块的默认值彼此一致。

## 6. 验证

```powershell
curl http://127.0.0.1:8080/health     # llama.cpp embedder
curl http://127.0.0.1:8081/health     # llama.cpp reranker
curl http://127.0.0.1:1235/health     # ONNX server
```

在宿主内：`intel_get_telemetry()` 显示实时的 `provider`、`model`、`ping_ms` 与
`tokens_per_sec`；`llm.error` 表示 ping 失败，而不是被跳过。`get_health_report()`
包含 provider 块。

## 7. 移除模型

删除文件即可；没有任何注册项在它们之后存活：

```powershell
Remove-Item .codebase_models\onnx\<slug> -Recurse -Force
Remove-Item models\<file>.gguf -Force
```

如果曾启用稠密路径且已存在向量，还要执行
`python scripts/reindex_text_only.py --project .`（或 `intel_reset_index()`），否则
已存的向量会保留旧维度。模型目录在 git 忽略之列（`.codebase_models/`、`models/`），
因此 `git status` 中不会出现任何内容。

---

**Verified against:** `install.py` (`STEPS`, `step_models`, `step_gguf`,
`--sync-only`, `--skip-models`, `--yes`, prompt strings),
`src/providers/reranker/llama_install.py` (`GGUF_MODELS` sizes/dims/SHA-256,
`LLAMA_VERSION`, `LLAMA_PORT`, `DEFAULT_EMBEDDING_MODEL`, `resolve_ubatch`,
`_patch_dll_imports`), `src/providers/reranker/llama_runner.py`
(`RERANK_PORT`, port range check, `LLAMA_BACKEND`/`LLAMA_NGL`),
`src/config/settings.py` (provider ports, `EMBEDDING_MODEL`),
`.env.example`, `.gitignore`.
