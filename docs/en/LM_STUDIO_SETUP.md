# LM Studio Setup (optional)

[English](LM_STUDIO_SETUP.md) · [Русский](../ru/LM_STUDIO_SETUP.md) · [中文](../zh/LM_STUDIO_SETUP.md)

> Version 3.5.0. **LM Studio is optional.** The default runtime is text-first:
> `MSCODEBASE_DENSE_OFF=true`, no embeddings stored, no provider required. Read
> this page only if you want an external embedder/reranker or `mode=ask`.

---

## 1. What LM Studio can do here

| Role | Used when | Without it |
|---|---|---|
| Embedder (`lm_studio` mode) | LM Studio answers the startup probe (it is an automatic fallback after in-process ONNX, not something you select by name) | text retrieval still works; on-demand rerank falls back to fused order |
| Reranker provider | `RERANKER_PROVIDERS` contains `lm_studio` (default list is `ollama,lm_studio`) | results keep RRF order |
| Chat backend for `search_code(mode="ask")` | `SYSTEM_PROFILE=server` (the default `light` profile blocks `ask` and silently downgrades to `quality`) | no generated answers; normal retrieval only |

Nothing else depends on it. There is no sign-in, no cloud call, no API key
validation beyond what the local server accepts.

## 2. Endpoint and defaults

From `src/config/settings.py` (`EmbeddingConfig`):

| Setting | Default | Meaning |
|---|---|---|
| `LM_STUDIO_HOST` | `127.0.0.1` | bind host |
| `LM_STUDIO_PORT` | `1234` | default LM Studio server port |
| `MODEL_NAME` | `multilingual-e5-small-int8` | embedding model name sent in the request |
| `EMBEDDING_DIMENSION` | `384` | expected vector width |
| `EMBEDDING_MODEL` | `qwen3-embedding` | model name for the llama.cpp/GGUF path (not LM Studio) |
| `API_KEY` | `sk-local` in `.env.example` | LM Studio's built-in placeholder key |
| `EMBEDDING_TIMEOUT` | `240.0` s | request timeout for embedding batches |

Derived URLs:

```
http://127.0.0.1:1234/v1/embeddings
http://127.0.0.1:1234/v1/models
http://127.0.0.1:1234/v1/chat/completions
```

If you change the port in LM Studio, change `LM_STUDIO_PORT` too — the server
does not discover it.

## 3. Setup

1. Install LM Studio and open **Developer → Local Server** (or the "server" tab,
   depending on version).
2. Load an embedding model. `multilingual-e5-small` (384-dim) is the cheapest
   match for the default `EMBEDDING_DIMENSION=384`; `multilingual-e5-base`
   (768-dim) works if you also set `EMBEDDING_DIMENSION=768` and
   `MODEL_NAME=multilingual-e5-base`.
3. Start the server on `127.0.0.1:1234`. Keep "just-in-time model loading"
   enabled if you switch models often; the first request after a swap is slower.
4. Point the MCP at it — `.env` next to the extension (or the environment block
   of your host):

```dotenv
LM_STUDIO_HOST=127.0.0.1
LM_STUDIO_PORT=1234
MODEL_NAME=multilingual-e5-small-int8
EMBEDDING_DIMENSION=384
```

There is no `EMBEDDING_PROVIDER=lm_studio` switch. Startup order is fixed:
in-process ONNX (`ONNX_PROVIDERS=cpu`) → **LM Studio** → Ollama (only if
`EMBEDDING_PROVIDER=ollama`) → a second ONNX attempt → `fallback`. So a running
LM Studio is picked up on the next restart; stopping it hands the role back to
ONNX or to `fallback`.

5. Restart the host (an OpenCode session or the Zed window). Settings are read
   at process start; `reload_config()` exists but the host still holds the old
   modules.

## 4. Verify

```powershell
# the server is up and lists models
curl http://127.0.0.1:1234/v1/models

# embeddings answer with the expected width
curl -s http://127.0.0.1:1234/v1/embeddings `
  -H "Content-Type: application/json" `
  -d '{\"model\":\"multilingual-e5-small-int8\",\"input\":[\"ping\"]}'
```

In the host: `intel_get_telemetry()` reports
`llm.provider` / `llm.model` / `llm.ping_ms` / `llm.tokens_per_sec` for the
**live** provider; `llm.error` means the ping failed. `get_health_report()` shows
the provider block as part of the diagnostic.

## 5. Dimension mismatch — the failure you will actually hit

Vectors from a model of a different width cannot be compared with stored ones.
`EMBEDDING_DIMENSION` must match the model, and switching models means
re-indexing anything that stored vectors. With the default `dense_off=true`
nothing is stored, so a mismatch only affects live rerank scoring (and shows up
as a silently worse ordering, not a crash) — but if you enabled the dense path,
rebuild:

```bash
python scripts/reindex_text_only.py --project .   # text-first, no vectors
```

or `intel_reset_index()` under the full profile.

## 6. `mode=ask`

`search_code(mode="ask")` sends the top chunks as context to
`ASK_MODEL` (default `phi-4-mini-instruct`) at the LM Studio chat endpoint,
temperature 0.1, 512 max tokens, with a "answer only from the context" prompt.
It requires `SYSTEM_PROFILE=server`; in `light` the tool returns
"mode=ask заблокирован в light profile. Переключение на mode=quality." and runs
a normal quality search instead. No other tool uses the chat endpoint.

## 7. Turning it off

Remove or comment the LM Studio variables and stop the LM Studio server, then
restart the host. The embedder scanner re-checks providers with backoff (30 s
base, 300 s cap) and settles on whatever answers; with nothing answering it stays
in `fallback` mode, which is exactly the text-first behaviour the project ships
with. Nothing needs to be uninstalled.

---

**Verified against:** `src/config/settings.py` (`EmbeddingConfig`,
`PerformanceConfig`, `SYSTEM_PROFILE`, `ASK_MODEL`),
`src/providers/embedder/remote_embedder.py` (mode detection, scan backoff,
LM Studio calls), `src/providers/reranker/multi_provider.py` (LM Studio rerank
ping), `src/core/search/engine.py` (`ask_async`, chat endpoint, fallback to
search), `src/mcp/tools/search_tools.py` (`mode=ask` light-profile block),
`src/core/intelligence/layer.py` (`llm` telemetry block), `.env.example`.
