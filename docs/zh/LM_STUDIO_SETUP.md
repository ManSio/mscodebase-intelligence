# LM Studio 配置（可选）

[English](../en/LM_STUDIO_SETUP.md) · [Русский](../ru/LM_STUDIO_SETUP.md) · [中文](LM_STUDIO_SETUP.md)

> 翻译：2026-11-08，来源 docs/en/LM_STUDIO_SETUP.md。英文版为准。

> 版本 3.5.0。**LM Studio 是可选的。** 默认运行时是文本优先：
> `MSCODEBASE_DENSE_OFF=true`，不存储 embedding，不需要任何 provider。只有在你想要
> 外部 embedder/reranker 或 `mode=ask` 时才需要读这一页。

---

## 1. LM Studio 在这里能做什么

| 角色 | 何时使用 | 没有它时 |
|---|---|---|
| Embedder（`lm_studio` 模式） | LM Studio 应答启动探测（它是进程内 ONNX 之后的自动回退，不是按名字选择的东西） | 文本检索仍可用；按需 rerank 回退到融合顺序 |
| Reranker provider | `RERANKER_PROVIDERS` 包含 `lm_studio`（默认列表是 `ollama,lm_studio`） | 结果保持 RRF 顺序 |
| `search_code(mode="ask")` 的聊天后端 | `SYSTEM_PROFILE=server`（默认的 `light` profile 会阻止 `ask` 并静默降级为 `quality`） | 没有生成的回答；只有常规检索 |

没有别的东西依赖它。没有登录、没有云调用，除了本地服务器接受的东西之外也没有 API
密钥校验。

## 2. 端点与默认值

来自 `src/config/settings.py`（`EmbeddingConfig`）：

| 设置项 | 默认值 | 含义 |
|---|---|---|
| `LM_STUDIO_HOST` | `127.0.0.1` | 绑定主机 |
| `LM_STUDIO_PORT` | `1234` | LM Studio 服务器的默认端口 |
| `MODEL_NAME` | `multilingual-e5-small-int8` | 请求中发送的 embedding 模型名 |
| `EMBEDDING_DIMENSION` | `384` | 期望的向量宽度 |
| `EMBEDDING_MODEL` | `qwen3-embedding` | llama.cpp/GGUF 路径的模型名（不是 LM Studio） |
| `API_KEY` | `.env.example` 中的 `sk-local` | LM Studio 内置的占位键 |
| `EMBEDDING_TIMEOUT` | `240.0` s | embedding 批次的请求超时 |

派生出的 URL：

```
http://127.0.0.1:1234/v1/embeddings
http://127.0.0.1:1234/v1/models
http://127.0.0.1:1234/v1/chat/completions
```

如果你在 LM Studio 中改了端口，也要改 `LM_STUDIO_PORT`——服务器不会自动发现它。

## 3. 配置步骤

1. 安装 LM Studio 并打开 **Developer → Local Server**（或 "server" 标签页，取决于
   版本）。
2. 加载一个 embedding 模型。`multilingual-e5-small`（384 维）是与默认
   `EMBEDDING_DIMENSION=384` 最省事的匹配；`multilingual-e5-base`（768 维）也可用，
   前提是你同时设置 `EMBEDDING_DIMENSION=768` 与
   `MODEL_NAME=multilingual-e5-base`。
3. 在 `127.0.0.1:1234` 上启动服务器。若你经常切换模型，请保持 "just-in-time model
   loading" 开启；切换后的第一次请求会较慢。
4. 让 MCP 指向它——扩展旁边的 `.env`（或宿主的环境变量块）：

```dotenv
LM_STUDIO_HOST=127.0.0.1
LM_STUDIO_PORT=1234
MODEL_NAME=multilingual-e5-small-int8
EMBEDDING_DIMENSION=384
```

不存在 `EMBEDDING_PROVIDER=lm_studio` 这样的开关。启动顺序是固定的：进程内 ONNX
（`ONNX_PROVIDERS=cpu`）→ **LM Studio** → Ollama（仅当
`EMBEDDING_PROVIDER=ollama`）→ 第二次 ONNX 尝试 → `fallback`。因此运行中的
LM Studio 会在下次重启时被采用；停掉它则把角色交回 ONNX 或 `fallback`。

5. 重启宿主（OpenCode 会话或 Zed 窗口）。设置在进程启动时读取；`reload_config()`
   存在，但宿主仍持有旧模块。

## 4. 验证

```powershell
# the server is up and lists models
curl http://127.0.0.1:1234/v1/models

# embeddings answer with the expected width
curl -s http://127.0.0.1:1234/v1/embeddings `
  -H "Content-Type: application/json" `
  -d '{\"model\":\"multilingual-e5-small-int8\",\"input\":[\"ping\"]}'
```

在宿主内：`intel_get_telemetry()` 报告**实时** provider 的
`llm.provider` / `llm.model` / `llm.ping_ms` / `llm.tokens_per_sec`；`llm.error`
表示 ping 失败。`get_health_report()` 作为诊断的一部分显示 provider 块。

## 5. 维度不匹配——你实际会遇到的失败

来自不同宽度模型的向量无法与已存的向量比较。`EMBEDDING_DIMENSION` 必须与模型
匹配，切换模型意味着要重建索引中所有存了向量的内容。默认 `dense_off=true` 下不存
任何向量，所以不匹配只影响实时 rerank 打分（表现为排序静默变差，而不是崩溃）——
但如果你启用了稠密路径，就要重建：

```bash
python scripts/reindex_text_only.py --project .   # text-first, no vectors
```

或在完整 profile 下用 `intel_reset_index()`。

## 6. `mode=ask`

`search_code(mode="ask")` 把 top 块作为上下文发到 LM Studio 聊天端点上的
`ASK_MODEL`（默认 `phi-4-mini-instruct`），temperature 0.1、最多 512 tokens，并带
"仅根据上下文回答"的提示。它要求 `SYSTEM_PROFILE=server`；在 `light` 下该工具返回
"mode=ask заблокирован в light profile. Переключение на mode=quality." 并改跑一次
普通的 quality 检索。没有其它工具使用聊天端点。

## 7. 关掉它

删除或注释掉 LM Studio 相关变量并停止 LM Studio 服务器，然后重启宿主。embedder
扫描器以退避重新检查 provider（基准 30 s，上限 300 s），并落到任何一个应答者上；
若无人应答则停留在 `fallback` 模式，而这正是项目自带的文本优先行为。不需要卸载
任何东西。

---

**Verified against:** `src/config/settings.py` (`EmbeddingConfig`,
`PerformanceConfig`, `SYSTEM_PROFILE`, `ASK_MODEL`),
`src/providers/embedder/remote_embedder.py` (mode detection, scan backoff,
LM Studio calls), `src/providers/reranker/multi_provider.py` (LM Studio rerank
ping), `src/core/search/engine.py` (`ask_async`, chat endpoint, fallback to
search), `src/mcp/tools/search_tools.py` (`mode=ask` light-profile block),
`src/core/intelligence/layer.py` (`llm` telemetry block), `.env.example`.
