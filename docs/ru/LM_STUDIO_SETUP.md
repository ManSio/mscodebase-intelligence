# Руководство по настройке LM Studio для MSCodeBase Intelligence

> **Последнее обновление:** 2026-07-12 | **Применяется к:** v3.2.0+

## ⚠️ LM Studio теперь второстепенен

**С 2026-07-12 основным провайдером эмбеддингов является ONNX E5-base INT8 (in-process CPU, 768-dim).**
LM Studio — **запасной провайдер** и требуется для:
- **`mode=ask`** (RAG-генерация через phi-4) — llama.cpp не поддерживает чат
- Пользователей, предпочитающих GUI LM Studio для управления моделями

**Приоритет провайдеров по умолчанию:**
```
1. ONNX E5-base INT8 (in-process CPU, 768-dim)
2. LM Studio (внешний API, порт 1234)
3. Ollama (внешний API, порт 11434)
4. Только BM25 (ключевой поиск)
```

См. [`INSTALL_MODELS.md`](INSTALL_MODELS.md) для основного способа установки.

---

## Зачем нужна LM Studio (Legacy)?

MSCodeBase может использовать **локальные AI-модели** через OpenAI-совместимый API LM Studio.
Оно работает **полностью офлайн** на вашей машине — никакого облака, никакой передачи данных, никаких затрат на API.

### Модели для ONNX/OpenVINO (Основной, in-process)

| Модель | Тип | Назначение | Размер |
|--------|-----|------------|:------:|
| `multilingual-e5-base` INT8/FP32 | Эмбеддинг (768-dim) | Векторный семантический поиск | 105 МБ / 266 МБ |
| `bge-reranker-v2-m3` (ONNX) | Кросс-энкодер | Реранкинг результатов | 544 МБ |

> **E5-base ONNX** — основной эмбеддер, запускается в процессе MCP без внешних зависимостей.
> BGE-M3 реранкер — ONNX-модель через onnx_server.py (порт 1235) или llama.cpp (порт 8081).

### Модели для LM Studio (Только fallback)

| Модель | Тип | Назначение | Размер |
|--------|-----|------------|:------:|
| `text-embedding-bge-m3` | Эмбеддинг (1024-dim) | Fallback векторный поиск | ~2.2 ГБ |
| `bge-reranker-v2-m3` | Кросс-энкодер | Fallback реранкинг | ~1.1 ГБ |

> LM Studio используется **только если ONNX/OpenVINO модель недоступна**.
> По умолчанию LM Studio — fallback.

### Альтернатива: llama.cpp GGUF (Рекомендуется для реранкера)

| Модель | Размер | RAM | Назначение |
|--------|:------:|:---:|------------|
| bge-reranker-v2-m3 Q4_K_M | **418 МБ** | 684 МБ | Реранкинг (кросс-энкодер, рекомендуется) |

**Преимущества перед LM Studio:**
- В 5 раз меньше RAM (~1.0 ГБ всего против ~6 ГБ)
- Не требуется внешнее приложение (запускается как подпроцесс)
- Автоустановка через `install.py`
- Поддержка Vulkan GPU

---

## Способ 1: Установка через инсталлятор MSCodeBase (Рекомендуется)

```bash
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence
python install.py
```

Инсталлятор:
1. Определит LM Studio на вашей машине
2. Если LM Studio **запущена** — покажет, какие модели загрузить
3. Если LM Studio **не запущена** — предложит скачать ONNX запасную модель
4. Проведёт вас через оставшуюся настройку

---

## Способ 2: Ручная настройка LM Studio

### Шаг 1: Установка LM Studio

1. Скачайте с [lmstudio.ai](https://lmstudio.ai/)
2. Установите и запустите LM Studio
3. Перейдите в **Settings** → вкладка **Local Server**
4. Включите **"Serve at"** с портом: `1234`
5. Включите **CORS** (все источники)
6. Включите **"Auto-load models on startup"**

### Шаг 2: Загрузка моделей

На вкладке **Search** в LM Studio найдите и скачайте каждую модель:

#### 1. text-embedding-bge-m3 (Обязательная)
```
Поиск: "bge-m3"
→ Выберите: "text-embedding-bge-m3"
→ Нажмите Download (Рекомендуется Quant: Q8_0)
```

#### 2. bge-reranker-v2-m3 (Обязательная)
```
Поиск: "bge-reranker-v2-m3"
→ Выберите модель
→ Нажмите Download (Рекомендуется Quant: Q8_0)
```

#### 3. phi-4-mini-instruct (Опционально, для mode=ask)
```
Поиск: "phi-4-mini-instruct"
→ Выберите модель
→ Нажмите Download (Рекомендуется Quant: Q4_K_M)
```

### Шаг 3: Загрузка моделей в сервер

На вкладке **Local Server** в LM Studio загрузите модели в таком порядке:

1. Нажмите **"Add Model"** → выберите `text-embedding-bge-m3`
2. Нажмите **"Add Model"** → выберите `bge-reranker-v2-m3`
3. Нажмите **"Add Model"** → выберите `phi-4-mini-instruct`
4. Нажмите **"Start Server"**

### Шаг 4: Проверка

```bash
# Проверка API LM Studio
curl http://127.0.0.1:1234/v1/models

# Ожидаемый вывод (3 модели):
# {
#   "data": [
#     {"id": "text-embedding-bge-m3", ...},
#     {"id": "bge-reranker-v2-m3", ...},
#     {"id": "phi-4-mini-instruct", ...}
#   ]
# }
```

---

## Способ 3: Загрузка через Hugging Face CLI

Если вы предпочитаете скачивать модели из терминала:

```bash
# Установка Hugging Face CLI
pip install huggingface-hub

# Скачать bge-m3 модель эмбеддингов (GGUF, Q8_0)
huggingface-cli download mradermacher/bge-m3-GGUF \
  bge-m3.Q8_0.gguf \
  --local-dir %USERPROFILE%\.lmstudio\models

# Скачать bge-reranker-v2-m3 (GGUF, Q8_0)
huggingface-cli download mradermacher/bge-reranker-v2-m3-GGUF \
  bge-reranker-v2-m3.Q8_0.gguf \
  --local-dir %USERPROFILE%\.lmstudio\models

# Скачать phi-4-mini-instruct (GGUF, Q4_K_M)
huggingface-cli download mradermacher/phi-4-mini-instruct-GGUF \
  phi-4-mini-instruct.Q4_K_M.gguf \
  --local-dir %USERPROFILE%\.lmstudio\models
```

> **Примечание:** Директория моделей LM Studio — `%USERPROFILE%\.lmstudio\models\`
> на Windows, `~/.lmstudio/models/` на macOS/Linux.

---

## Справочник конфигурации

### Переменные `.env` для LM Studio

```ini
# Провайдер эмбеддингов: auto, lm_studio, onnx, ollama
EMBEDDING_PROVIDER=auto

# Подключение к LM Studio
LM_STUDIO_HOST=127.0.0.1
LM_STUDIO_PORT=1234

# Имя модели эмбеддингов по умолчанию
MODEL_NAME=text-embedding-bge-m3
EMBEDDING_DIMENSION=1024

# Настройки mode=ask LLM
ASK_MODEL=phi-4-mini-instruct
ASK_TIMEOUT=60.0

# Провайдеры реранкера (через запятую)
RERANKER_PROVIDERS=ollama,lm_studio
```

---

## Устранение неполадок

### LM Studio не обнаружена
```
LM Studio / Ollama not running. Vector search will be unavailable.
```
- Убедитесь, что LM Studio запущен с включённым сервером на порту 1234
- Проверьте настройки брандмауэра (разрешите LM Studio в частных сетях)
- Проверьте: `curl http://127.0.0.1:1234/v1/models`

### Модель эмбеддингов возвращает неверную размерность
```
LM Studio вернул пустой список embeddings.
Проверьте что модель 'text-embedding-bge-m3' поддерживает embeddings.
```
- Убедитесь, что вы загрузили модель `text-embedding-bge-m3` (а не `phi-4` для эмбеддингов)
- Проверьте, что `EMBEDDING_DIMENSION=1024` соответствует вашей модели
- Перезапустите сервер LM Studio после загрузки новой модели

### Реранкер не работает
- Убедитесь, что `bge-reranker-v2-m3` загружен в LM Studio
- Проверьте `RERANKER_PROVIDERS=ollama,lm_studio`
- При использовании Ollama: убедитесь, что `bge-reranker-v2-m3` скачан: `ollama pull bge-reranker-v2-m3`

### phi-4 не отвечает (mode=ask)
```
mode=ask заблокирован в light profile
```
- Установите `SYSTEM_PROFILE=server` в `.env`
- Убедитесь, что `phi-4-mini-instruct` загружен в LM Studio
- Проверьте `ASK_TIMEOUT=60.0` (увеличьте, если модель медленная)

---

## Путь ONNX-запасного варианта (без LM Studio)

Если вы не можете запустить LM Studio, MSCodeBase может использовать **ONNX Runtime** для
эмбеддингов И реранкинга. Инсталлятор скачивает обе модели:

```bash
# Полная установка ONNX (рекомендуется):
python install.py
# → Шаг 6 скачает обе модели

# Ручная установка:
pip install onnxruntime transformers torch huggingface-hub

# 1. Модель эмбеддингов (BAAI/bge-m3, 438 МБ)
python scripts/download_model.py --model BAAI/bge-m3 --type embedding
# → Сохраняется в .codebase_models/onnx/bge-m3/model.onnx

# 2. Модель реранкера (BAAI/bge-reranker-v2-m3, 636 МБ)
python scripts/download_model.py --model BAAI/bge-reranker-v2-m3 --type reranker
# → Сохраняется в .codebase_models/onnx/bge-reranker/model.onnx
```

**Ограничения ONNX-запасного варианта:**
- Только CPU (без ускорения GPU)
- Медленнее LM Studio для больших пакетов
- Нет `mode=ask` (генерация RAG требует phi-4 в LM Studio)
- ~1.1 ГБ общего дискового пространства для обеих моделей
