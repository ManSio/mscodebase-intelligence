# Установка AI-моделей — 3 способа

> Выберите свой способ: **Авто** (install.py), **Вручную** (GGUF) или **LM Studio** (legacy)

---

## СПОСОБ 1: Авто — install.py (Рекомендуется)

> **Лучше всего для:** Всех пользователей. Устанавливает llama.cpp + GGUF модели автоматически.

```bash
python install.py
```

**Что происходит:**
1. Определяет Windows/macOS/Linux, AVX2/AVX512, Vulkan GPU
2. Скачивает `llama-server.exe` (или бинарник для вашей платформы)
3. Скачивает **bge-m3 Q4_K_M** (417 МБ) — модель эмбеддингов
4. Скачивает **bge-reranker-v2-m3 Q4_K_M** (418 МБ) — модель реранкера
5. Запускает оба процесса llama-server на портах 8080 (embed) + 8081 (rerank)

**Использование диска после установки:** ~900 МБ (llama бинарник + 2 GGUF модели)

### Поведение системы

| Сценарий | Что запускается | Память |
|----------|-----------------|--------|
| llama.cpp установлен | 2× llama-server (embed + rerank) | ~1.0 ГБ |
| Vulkan GPU доступен | llama-server с `-ngl 99` (GPU offload) | ~1.0 ГБ |
| Только CPU (без Vulkan) | llama-server с `-ngl 0` (только CPU) | ~700 МБ |

---

## СПОСОБ 2: Вручную — Загрузка GGUF

> **Лучше всего для:** Пользователей, которые хотят скачать модели вручную.

**Модель эмбеддингов (bge-m3, обязательная):**
```bash
# Из HuggingFace
huggingface-cli download lm-kit/bge-m3-gguf \
  bge-m3-Q4_K_M.gguf \
  --local-dir extensions/mscodebase-intelligence/models/
```

**Модель реранкера (bge-reranker-v2-m3, обязательная):**
```bash
huggingface-cli download lm-kit/bge-m3-reranker-v2-gguf \
  Bge-M3-568M-Q4_K_M.gguf \
  --local-dir extensions/mscodebase-intelligence/models/
```

**Альтернативный эмбеддинг (Qwen3, для меньшего RAM):**
```bash
huggingface-cli download coolbeev5/Qwen3-Embedding-0.6B-GGUF \
  qwen3-embedding-0.6b-q4_k_m.gguf \
  --local-dir extensions/mscodebase-intelligence/models/
# Установите: EMBEDDING_MODEL=qwen3-embedding в .env (346 МБ RAM)
```

---

## СПОСОБ 3: LM Studio (Legacy)

> **Лучше всего для:** Пользователей, у которых уже установлена LM Studio с моделями.

LM Studio всё ещё может использоваться как запасной провайдер. Если llama.cpp недоступен,
MSCodeBase автоматически переключается на LM Studio.

| Модель | Размер | Назначение |
|--------|:------:|------------|
| `text-embedding-bge-m3` | ~2.2 ГБ | Эмбеддинг (векторный поиск) |
| `bge-reranker-v2-m3` | ~1.1 ГБ | Реранкинг (кросс-энкодер) |
| `phi-4-mini-instruct` | ~2.8 ГБ | `mode=ask` генерация RAG (опционально) |

См. [`LM_STUDIO_SETUP.md`](LM_STUDIO_SETUP.md) для подробной настройки.

---

## Сравнительная таблица

| Критерий | Способ 1 (Авто) | Способ 2 (Вручную) | Способ 3 (LM Studio) |
|----------|:---------------:|:------------------:|:--------------------:|
| **Провайдер** | llama.cpp GGUF | llama.cpp GGUF | LM Studio |
| **GPU** | Vulkan (авто) | Vulkan (авто) | Любой (CUDA/Metal) |
| **RAM (всего)** | **~1.0 ГБ** | **~1.0 ГБ** | ~3-6 ГБ |
| **Диск** | **~900 МБ** | **~900 МБ** | ~6 ГБ |
| **Время установки** | **3 мин** | 5 мин | 20 мин |
| **mode=ask** | ❌ Нет (нужна LM Studio) | ❌ Нет | ✅ Да |

---

## Конфигурация моделей

### Переменные `.env`

```ini
# Модель эмбеддингов: bge-m3 (по умолчанию) или qwen3-embedding
EMBEDDING_MODEL=bge-m3

# Бэкенд: auto, msvc или vulkan
LLAMA_BACKEND=auto

# Слои GPU (0 = только CPU, 99 = все слои на GPU)
LLAMA_NGL=99

# Размер контекста (1024 = ~500 МБ RAM для Qwen3)
LLAMA_CTX_SIZE=1024
```
