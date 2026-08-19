# syntax=docker/dockerfile:1
# MSCodeBase remote — Streamable HTTP MCP server (Универсальный MCP движок, Фаза 3 шаг 5).
#
# Вариант A (v1): python-only образ.
#   * BM25/FTS5 + SymbolIndex — основной носитель recall (план §10), ON всегда;
#   * Embedder — ONNX in-process CPU fallback (e5-small, данные в /data/models);
#   * llama.cpp embedder (8080) / reranker (8081) — опциональные ВНЕШНИЕ сервисы,
#     подключаются через env (LLAMA_CPP_HOST/PORT и т.д.); reranker off по умолчанию.
# Полный мульти-контейнер с llama-server (Вариант C) — follow-up, образ api не меняется.
#
# Сборка (context = корень репо):
#   docker build -t mscodebase-remote:local -f deploy/docker/Dockerfile .
# Запуск:
#   docker compose -f deploy/docker/docker-compose.yml up -d

FROM python:3.12-slim

# 3.12 — стабильная линия CI-матрицы движка (3.10..3.12). Некритично для протокола.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    MSCODEBASE_DATA_DIR=/data

WORKDIR /app

# 1) Манифесты ДО исходников — слой pip-кэша переиспользуется при правках src.
COPY pyproject.toml requirements.txt ./

# 2) Исходники движка (src/) — единственное, что нужно рантайму.
COPY src ./src

# 3) Все runtime-зависимости — manylinux/abi3 колеса, сборка компилятором не нужна.
RUN pip install --no-cache-dir -r requirements.txt

# 4) Не-рут пользователь (best practice); /data — точка монтирования артефактов.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /app /data
USER app

EXPOSE 8089

# /healthz освобождён от auth и rate-limit (uptime-мониторинг) — см. remote_main.py.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8089/healthz',timeout=3).status==200 else 1)"

ENTRYPOINT ["python", "-m", "src.remote_main", "--host", "0.0.0.0", "--port", "8089"]
