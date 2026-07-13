# Установка AI-моделей — 3 способа

> Выберите свой способ: **Авто** (install.py), **Вручную** (ONNX + GGUF) или **LM Studio** (legacy fallback)

> **Реальность провайдеров (2026-07-12):** **эмбеддер работает in-process** через
> **ONNX E5-base INT8 / OpenVINO INT8** (`intfloat/multilingual-e5-base`, 768-dim, ~350 ch/s
> на Windows CPU). `install.py` скачивает его автоматически. **Реренкер** — отдельный процесс
> `llama-server.exe`, обслуживающий GGUF-модель `bge-reranker-v2-m3`. `LM Studio` — лишь
> опциональный fallback, если локальная ONNX-модель недоступна.

---

## СПОСОБ 1: Авто — install.py (Рекомендуется)

> **Лучше всего для:** Всех пользователей. Устанавливает llama.cpp + ONNX + GGUF автоматически.

```bash
python install.py
```

**Что происходит:**
1. Определяет Windows/macOS/Linux, AVX2/AVX512, Vulkan GPU
2. Скачивает `llama-server.exe` (или бинарник для платформы) — используется для **реренкера**
3. Скачивает **E5-base v2 ONNX** (`intfloat/multilingual-e5-base`, ~265 МБ) — **модель эмбеддинга (in-process)**
4. Скачивает **bge-reranker-v2-m3 GGUF** (`BAAI/bge-reranker-v2-m3`, ~544 МБ) — **модель реренкера**
5. Запускает процесс реренкера llama-server на порту `:8081`

**Использование диска после установки:** ~900 МБ (llama бинарник + ONNX эмбеддер + GGUF реренкер)

### Поведение системы

| Сценарий | Что запускается | Память |
|----------|-----------------|--------|
| ONNX/OpenVINO E5-base (дефолт) | in-process эмбеддер + 1× llama-server (rerank) | ~1.0 ГБ |
| Vulkan GPU доступен | llama-server с `-ngl 99` (GPU offload, только реренкер) | ~1.0 ГБ |
| Только CPU (без Vulkan) | llama-server с `-ngl 0` (только CPU, реренкер) | ~700 МБ |
| LM Studio fallback | внешний API на `:1234` (если включён) | ~3-6 ГБ |

---

## СПОСОБ 2: Вручную — ONNX + GGUF

> **Лучше всего для:** Пользователей, желающих скачать модели вручную.

**Модель эмбеддинга (E5-base v2 ONNX, обязательно — in-process):**
```bash
python scripts/download_model.py --model intfloat/multilingual-e5-base
# → .codebase_models/onnx/e5-base-v2/model_quantized.onnx (INT8)
```

**Модель реренкера (bge-reranker-v2-m3 GGUF, обязательно):**
```bash
# Из HuggingFace
huggingface-cli download lm-kit/bge-reranker-v2-m3-gguf \
  Bge-M3-reranker-2-3-568M-Q4_K_M.gguf \
  --local-dir extensions/mscodebase-intelligence/models/
```

> ONNX-эмбеддер — **дефолтный и основной** путь. GGUF-реренкер работает как отдельный
> процесс `llama-server.exe`. Вам НЕ нужна GGUF-*эмбеддинг*-модель для поиска.

---

## СПОСОБ 3: LM Studio (Legacy Fallback)

> **Лучше всего для:** Пользователей с уже установленной LM Studio, желающих fallback.

LM Studio всё ещё можно использовать как fallback-провайдер эмбеддинга. Если локальная
ONNX-модель недоступна, MSCodeBase может переключиться на LM Studio (установите
`EMBEDDING_PROVIDER=lm_studio`).

| Модель | Размер | Назначение |
|-------|:----:|---------|
| `text-embedding-bge-m3` | ~2.2 ГБ | Эмбеддинг fallback (векторный поиск) |
| `bge-reranker-v2-m3` | ~1.1 ГБ | Реренкинг (cross-encoder) |
| `phi-4-mini-instruct` | ~2.8 ГБ | `mode=ask` RAG-генерация (опционально) |

См. [`LM_STUDIO_SETUP.md`](LM_STUDIO_SETUP.md) для деталей.

---

## Таблица сравнения

| Критерий | Способ 1 (Авто) | Способ 2 (Вручную) | Способ 3 (LM Studio) |
|-----------|:---------------:|:-----------------:|:--------------------:|
| **Эмбеддер** | ONNX E5-base INT8 (in-process) | ONNX E5-base INT8 | LM Studio (bge-m3) |
| **Реренкер** | llama.cpp GGUF | llama.cpp GGUF | LM Studio |
| **GPU** | Vulkan (только реренкер) | Vulkan (только реренкер) | Any (CUDA/Metal) |
| **RAM (всего)** | **~1.0 ГБ** | **~1.0 ГБ** | ~3-6 ГБ |
| **Диск** | **~900 МБ** | **~900 МБ** | ~6 ГБ |
| **Время установки** | **3 мин** | 5 мин | 20 мин |
| **mode=ask** | ❌ Нет (нужен LLM profile) | ❌ Нет | ✅ Да |

---

## Конфигурация моделей

### Переменные `.env`

```ini
# Провайдер эмбеддинга: e5_onnx (дефолт, in-process) | openvino | lm_studio
EMBEDDING_PROVIDER=e5_onnx

# ONNX model slug (скачивается install.py)
#   e5-base-v2  → intfloat/multilingual-e5-base (768-dim, INT8)
ONNX_MODEL=e5-base-v2

# Reranker GGUF модель, обслуживаемая llama-server на :8081
RERANKER_MODEL=bge-reranker-v2-m3

# llama.cpp backend для реренкера: auto, msvc, или vulkan
LLAMA_BACKEND=auto

# GPU layers для реренкера (0 = только CPU, 99 = все слои на GPU)
LLAMA_NGL=99

# Context size для реренкера (1024 достаточно для bge-reranker-v2-m3)
LLAMA_CTX_SIZE=1024
```
