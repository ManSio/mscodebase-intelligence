# MSCodeBase remote — деплой через Docker (Фаза 3 шаг 5, Вариант A)

Streamable HTTP вход движка (`src/remote_main.py`) в контейнере: тот же
`create_mcp_server()`, те же тулы, тот же DI. Внешние MCP-клиенты (Claude Code,
VS Code, Zed remote) подключаются по HTTP с Bearer-auth.

## Что в образе (Вариант A)

- `python:3.12-slim` + runtime-зависимости из `requirements.txt` (manylinux/abi3
  колёса — компилятор не нужен).
- **BM25/FTS5 + SymbolIndex** — ON всегда (основной носитель recall, план §10).
- **Embedder** — ONNX in-process CPU fallback (e5-small). Модели ожидаются в
  `/data/models` (том `mcp-data`), при отсутствии — graceful-деградация.
- **llama.cpp embedder (8080) / reranker (8081)** — опциональные ВНЕШНИЕ сервисы
  (подключаются через env `LLAMA_CPP_HOST/PORT`). Reranker off по умолчанию (§10).
- Модели и артефакты — во внешнем томе `/data` (`MSCODEBASE_DATA_DIR=/data`), не в
  образе.

> Вариант C (полный мульти-контейнер с `llama-server`-embedder/reranker) — follow-up:
> добавляется как второй/третий сервис в compose, образ `api` не меняется.

## Сборка и запуск

```bash
cd deploy/docker
cp .env.example .env        # задать MSCODEBASE_REMOTE_TOKEN (ОБЯЗАТЕЛЬНО)
docker compose up -d --build
docker compose ps           # HEALTHCHECK: healthy
curl -s http://127.0.0.1:8089/healthz   # {"status":"ok","service":"mscodebase-remote"}
```

Контекст сборки — корень репо (там `.dockerignore`, исключающий `experiments/`
и прочее, не нужное в образе).

## Клиентские конфиги (remote)

- **Claude Code / Desktop** — `.mcp.json`: `"type": "http"`, `"url": "http://<host>:8089/mcp"`,
  `"headers": {"Authorization": "Bearer <token>"}`.
- **VS Code** — `.vscode/mcp.json`: `"type": "http"` + `"headers"` (Bearer),
  fallback HTTP→SSE по клиентской конвенции.
- **Zed** — `settings.json`: `context_servers` с `"url"` + `"Authorization"` header.

## Безопасность

- `MSCODEBASE_REMOTE_TOKEN` обязателен для сети; пустой = access-gate выключен
  (не выставлять в интернет без токена).
- Rate-limit на гейте: per-token (sha256) + per-IP, `MSCODEBASE_REMOTE_RATE_LIMIT_RPS`
  (default 30.0/сек на ключ). Circuit breaker на `/mcp` (5xx→503). `/healthz`
  освобождён (uptime-мониторинг).
- Контейнер — не-рут (`app` uid 10001), том `/data` принадлежит `app`.
- Флуд в `/healthz` — вне лимита (тривиальный эндпоинт; у провайдера мониторинга
  отдельный бюджет).

## Обновление (v1: stop → update → start)

```bash
docker compose -f deploy/docker/docker-compose.yml down
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

Rolling-restart для multi-instance — задокументировать позже (ТЗ §9б-7; сейчас
единый инстанс, том `mcp-data` переживает пересоздание контейнера).

## Проверка

- `python -m pytest tests/test_remote_main.py -q` — гейт auth/rate-limit/breaker.
- Локально образ не собирался (Docker вне песочницы) — полный build + smoke E-07
  (equiv stdio↔HTTP) выполняются на CI-джобе / машине владельца.
