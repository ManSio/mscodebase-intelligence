# Настройка LM Studio (опционально)

> Перевод: 2026-11-08, источник — docs/en/LM_STUDIO_SETUP.md. Английская версия — канон.

[English](../en/LM_STUDIO_SETUP.md) · [Русский](LM_STUDIO_SETUP.md) · [中文](../zh/LM_STUDIO_SETUP.md)

> Версия 3.5.0. **LM Studio опционален.** Дефолтный runtime — text-first:
> `MSCODEBASE_DENSE_OFF=true`, эмбеддинги не хранятся, провайдер не требуется.
> Читайте эту страницу только если вам нужен внешний эмбеддер/реранкер или
> `mode=ask`.

---

## 1. Что LM Studio может здесь делать

| Роль | Когда используется | Без него |
|---|---|---|
| Эмбеддер (режим `lm_studio`) | LM Studio отвечает на стартовую пробу (это автоматический fallback после in-process ONNX, а не то, что вы выбираете по имени) | текстовый поиск всё равно работает; on-demand реранк откатывается к объединённому порядку |
| Провайдер реранкера | `RERANKER_PROVIDERS` содержит `lm_studio` (список по умолчанию — `ollama,lm_studio`) | результаты сохраняют порядок RRF |
| Chat-бэкенд для `search_code(mode="ask")` | `SYSTEM_PROFILE=server` (дефолтный профиль `light` блокирует `ask` и молча понижает до `quality`) | сгенерированных ответов нет; только обычный поиск |

Больше от него ничего не зависит. Здесь нет входа в аккаунт, нет облачного вызова,
нет проверки API-ключа сверх того, что принимает локальный сервер.

## 2. Эндпоинт и значения по умолчанию

Из `src/config/settings.py` (`EmbeddingConfig`):

| Настройка | Значение по умолчанию | Смысл |
|---|---|---|
| `LM_STUDIO_HOST` | `127.0.0.1` | хост привязки |
| `LM_STUDIO_PORT` | `1234` | дефолтный порт сервера LM Studio |
| `MODEL_NAME` | `multilingual-e5-small-int8` | имя модели эмбеддингов, отправляемое в запросе |
| `EMBEDDING_DIMENSION` | `384` | ожидаемая размерность вектора |
| `EMBEDDING_MODEL` | `qwen3-embedding` | имя модели для пути llama.cpp/GGUF (не для LM Studio) |
| `API_KEY` | `sk-local` в `.env.example` | встроенный ключ-заглушка LM Studio |
| `EMBEDDING_TIMEOUT` | `240.0` s | таймаут запроса для пакетов эмбеддингов |

Производные URL:

```
http://127.0.0.1:1234/v1/embeddings
http://127.0.0.1:1234/v1/models
http://127.0.0.1:1234/v1/chat/completions
```

Если вы меняете порт в LM Studio, поменяйте и `LM_STUDIO_PORT` — сервер его не
обнаруживает сам.

## 3. Настройка

1. Установите LM Studio и откройте **Developer → Local Server** (или вкладку
   «server», в зависимости от версии).
2. Загрузите модель эмбеддингов. `multilingual-e5-small` (384-dim) — самое
   дешёвое соответствие дефолтному `EMBEDDING_DIMENSION=384`; `multilingual-e5-base`
   (768-dim) работает, если вы также зададите `EMBEDDING_DIMENSION=768` и
   `MODEL_NAME=multilingual-e5-base`.
3. Запустите сервер на `127.0.0.1:1234`. Держите включённой «just-in-time
   загрузку модели», если часто переключаете модели; первый запрос после смены
   медленнее.
4. Направьте MCP на него — `.env` рядом с расширением (или блок окружения
   вашего хоста):

```dotenv
LM_STUDIO_HOST=127.0.0.1
LM_STUDIO_PORT=1234
MODEL_NAME=multilingual-e5-small-int8
EMBEDDING_DIMENSION=384
```

Переключателя `EMBEDDING_PROVIDER=lm_studio` нет. Порядок старта фиксирован:
in-process ONNX (`ONNX_PROVIDERS=cpu`) → **LM Studio** → Ollama (только если
`EMBEDDING_PROVIDER=ollama`) → вторая попытка ONNX → `fallback`. То есть
запущенный LM Studio подхватывается при следующем перезапуске; его остановка
возвращает роль ONNX или `fallback`.

5. Перезапустите хост (сессию OpenCode или окно Zed). Настройки читаются при
   старте процесса; `reload_config()` существует, но хост всё равно держит старые
   модули.

## 4. Проверка

```powershell
# the server is up and lists models
curl http://127.0.0.1:1234/v1/models

# embeddings answer with the expected width
curl -s http://127.0.0.1:1234/v1/embeddings `
  -H "Content-Type: application/json" `
  -d '{\"model\":\"multilingual-e5-small-int8\",\"input\":[\"ping\"]}'
```

Внутри хоста: `intel_get_telemetry()` сообщает
`llm.provider` / `llm.model` / `llm.ping_ms` / `llm.tokens_per_sec` для
**живого** провайдера; `llm.error` означает, что пинг не удался.
`get_health_report()` показывает блок провайдера как часть диагностики.

## 5. Несовпадение размерности — сбой, который вы действительно встретите

Векторы модели другой размерности нельзя сравнивать с сохранёнными.
`EMBEDDING_DIMENSION` должен соответствовать модели, а смена модели означает
переиндексацию всего, что сохранило векторы. При дефолтном `dense_off=true`
ничего не сохраняется, поэтому несовпадение влияет только на живой скоринг
реранка (и проявляется как молча ухудшившийся порядок, а не падение) — но если
вы включили dense-путь, пересоберите:

```bash
python scripts/reindex_text_only.py --project .   # text-first, no vectors
```

или `intel_reset_index()` под полным профилем.

## 6. `mode=ask`

`search_code(mode="ask")` отправляет top-чанки как контекст в `ASK_MODEL`
(по умолчанию `phi-4-mini-instruct`) на chat-эндпоинт LM Studio, temperature 0.1,
512 максимум токенов, с промптом «отвечай только из контекста». Требуется
`SYSTEM_PROFILE=server`; в `light` инструмент возвращает
«mode=ask заблокирован в light profile. Переключение на mode=quality.» и вместо
этого выполняет обычный quality-поиск. Никакой другой инструмент chat-эндпоинт не
использует.

## 7. Как отключить

Удалите или закомментируйте переменные LM Studio и остановите сервер LM Studio,
затем перезапустите хост. Сканер эмбеддера перепроверяет провайдеров с backoff
(база 30 s, потолок 300 s) и останавливается на том, что отвечает; если не
отвечает никто, он остаётся в режиме `fallback`, что и есть ровно то text-first
поведение, с которым проект поставляется. Удалять ничего не нужно.

---

**Verified against:** `src/config/settings.py` (`EmbeddingConfig`,
`PerformanceConfig`, `SYSTEM_PROFILE`, `ASK_MODEL`),
`src/providers/embedder/remote_embedder.py` (mode detection, scan backoff,
LM Studio calls), `src/providers/reranker/multi_provider.py` (LM Studio rerank
ping), `src/core/search/engine.py` (`ask_async`, chat endpoint, fallback to
search), `src/mcp/tools/search_tools.py` (`mode=ask` light-profile block),
`src/core/intelligence/layer.py` (`llm` telemetry block), `.env.example`.
