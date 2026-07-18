# 💡 MSCodeBase Research Lab

> Документация исследований, экспериментов и бенчмарков.
> Все выводы основаны на реальных замерах, а не гипотезах.

**Создан:** 2026-07-09
**Последнее обновление:** 2026-07-09

---

## 📋 Содержание

1. [Сводный бенчмарк провайдеров](#1-сводный-бенчмарк-провайдеров)
2. [Исследование утечки памяти MCP](#2-исследование-утечки-памяти-mcp)
3. [AutoTokenizer зависание на Windows](#3-autotokenizer-зависание-на-windows)
4. [patch_zed_settings и кнопка «восстановить»](#4-patch_zed_settings-и-кнопка-восстановить)
5. [llama.cpp: STATUS_ILLEGAL_INSTRUCTION на Zen 3](#5-llamacpp-status_illegal_instruction-на-zen-3)
6. [Zed 1.10.0: анализ совместимости](#6-zed-1100-анализ-совместимости)
7. [Приложение: методология замеров](#7-приложение-методология-замеров)

---

## 1. Сводный бенчмарк провайдеров

### 1.1 Итоговая таблица

**Дата:** 2026-07-09
**CPU:** AMD Ryzen 5 5600H (Zen 3, AVX2)
**RAM:** 16 GB
**OS:** Windows 11
**Python:** 3.14

```
┌─────────────────────┬────────┬────────┬──────────┬──────────┬────────┐
│ Провайдер           │ Старт  │ RAM    │ Embed    │ Rerank   │ Модель │
│                     │        │        │ (5 txts) │ (4 pass) │        │
├─────────────────────┼────────┼────────┼──────────┼──────────┼────────┤
│ 🥇 llama.cpp GGUF   │ 5.0s   │ 523 MB │ 764 ms   │ 813 ms   │ Q4_K_M │
│ 🥈 ONNX server FP32 │ 7.1s   │ 1689 MB│ 988 ms   │ 1441 ms  │ FP32   │
│ 🥉 MCP процесс      │ -      │ 227 MB │ → HTTP   │ → HTTP   │ 0      │
│ 📎 local ONNX       │ 15s+   │ +544 MB│ ~900 ms  │ ~1200 ms │ FP32   │
│ 📎 LM Studio (GPU)* │ 20-30s │ ~3-5GB │ ~100 ms  │ ~300 ms  │ любые  │
└─────────────────────┴────────┴────────┴──────────┴──────────┴────────┘

* LM Studio не установлен на тестовой машине. Данные из документации.
```

### 1.2 Сравнение llama.cpp vs ONNX server

**llama.cpp побеждает ONNX server по всем метрикам:**

| Метрика           | llama.cpp | ONNX server | Разница      |
|-------------------|-----------|-------------|--------------|
| RAM               | 523 MB    | 1689 MB     | **3.2x меньше** |
| Embed (avg 5txt)  | 764 ms    | 988 ms      | **23% быстрее** |
| Rerank (avg 4p)   | 813 ms    | 1441 ms     | **44% быстрее** |
| Startup cold      | 5.0s      | 7.1s        | **30% быстрее** |

**Почему llama.cpp быстрее на CPU:**
- Q4_K_M квантование: 4-bit веса вместо FP32 -> в 8x меньше данных для чтения из RAM
- GGUF-оптимизированные ядра под конкретные CPU-инструкции (AVX2 на Zen 3)
- ONNX Runtime FP32: полная точность, но в 8x больше пропускной способности памяти

### 1.3 Рекомендации по выбору провайдера

| Ситуация | Рекомендация |
|---|---|
| Установлен `llama-server` | **llama.cpp** -- самый быстрый и лёгкий |
| Нет llama.cpp, CPU слабый | **ONNX server** -- стабильно, работает везде |
| Есть GPU (NVIDIA) | **LM Studio** -- максимальная скорость (CUDA) |
| Ничего не установлено | **ONNX server** (устанавливается install.py) |
| Всё сломалось | **local ONNX** -- только fallback, грузит 544MB в MCP |

---

## 2. Исследование утечки памяти MCP

### 2.1 Проблема

MCP-процесс потреблял ~1.2 GB RAM. Раньше (без ONNX, только HTTP к LM Studio) было ~300 MB.

### 2.2 Root Cause

**Причина 1: `RemoteEmbedder._detect_model_dir()`**
- Создавал `ort.InferenceSession()` только чтобы прочитать размерность модели
- 544 MB временного спайка
- session не закрывалась явно -> GC не сразу отпускал

**Причина 2: `MultiProviderReranker._init_onnx_reranker()`**
- Загружал bge-reranker-v2-m3 (545 MB) прямо в MCP-процесс
- `ort.InferenceSession` с полной моделью

**Причина 3: `RemoteEmbedder._init_onnx()`**
- Загружал bge-m3 (544 MB) прямо в MCP-процесс
- Когда ONNX-сервер недоступен, падал на local ONNX

**Итого в MCP:** 544 + 544 = ~1.1 GB только ONNX модели

### 2.3 Исправление

```
Было:                         Стало:
MCP: 1.2 GB                   MCP: 227 MB (HTTP-клиенты, 0 моделей)
ONNX server: 3.5 GB           ONNX server: 1.7 GB (обе модели в подпроцессе)
Total: 4.7 GB                 Total: 1.9 GB
```

**Что изменилось:**
- `_detect_model_dir()`: `onnx.shape_inference` вместо `ort.InferenceSession`
- `reranker.py`: удалён `_init_onnx_reranker()` с in-process ONNX
- `onnx_server.py`: `gc.collect()` после каждого запроса

**Результат:** MCP 227 MB (-81%), ONNX server 1.7 GB (-51%), total 1.9 GB (-60%)

---

## 3. AutoTokenizer зависание на Windows

### 3.1 Симптомы

- ONNX сервер не стартует (порт 1235 CLOSED)
- В логах: "connection refused, fallback to local ONNX"
- Все инструменты таймаутят
- `get_index_status` показывает 127 чанков вместо 2561

### 3.2 Root Cause

```python
# БЫЛО (висело навсегда):
tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
# transformers делает HEAD-запрос к huggingface.co
# на Windows без интернета/firewall -- зависание
```

`AutoTokenizer.from_pretrained()` делает HTTP-запрос к huggingface.co для проверки версии токенизатора даже когда все файлы есть локально. На Windows без доступа к HF -- зависание навсегда.

### 3.3 Исправление

```python
# СТАЛО (1.1 секунды, без network):
from tokenizers import Tokenizer
tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
tokenizer.enable_padding(pad_token="<pad>", pad_id=1)
tokenizer.enable_truncation(max_length=2048)

# Использование:
encoded = tokenizer.encode_batch(texts, add_special_tokens=True)
ids = np.array([e.ids for e in encoded], dtype=np.int64)
mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
```

**Затронутые файлы:**
- `src/core/onnx_server.py` -- `init_embedder()`, `init_reranker()`, `embed_texts()`, `rerank()`
- `src/core/remote_embedder.py` -- `_init_onnx()`, `embed_batch()`

**Результат:** ONNX сервер стартует за 7.1s (было: бесконечное зависание)

### 3.4 API tokenizers vs AutoTokenizer

| Операция | AutoTokenizer | Tokenizer |
|----------|---------------|-----------|
| Загрузка | `from_pretrained(dir)` - network | `from_file("tokenizer.json")` - локально |
| Padding | `__call__(texts, padding=True)` | `enable_padding(pad_token, pad_id)` |
| Truncation | `__call__(texts, truncation=True)` | `enable_truncation(max_length=N)` |
| Batch encode | `__call__(texts)` -> BatchEncoding | `encode_batch(texts)` -> list[Encoding] |
| Input IDs | `encoded["input_ids"]` (numpy) | `[e.ids for e in encoded]` -> np.array |
| Attention mask | `encoded["attention_mask"]` | `[e.attention_mask for e in encoded]` |
| Token type ids | `encoded["token_type_ids"]` | `[e.type_ids for e in encoded]` |
| Зависимости | transformers + huggingface_hub | tokenizers (часть transformers) |

---

## 4. patch_zed_settings и кнопка «восстановить»

### 4.1 Проблема

Каждый запуск `install.py` показывал кнопку "восстановить" в Zed.

### 4.2 Root Cause

```python
# Чтение: удалял все // комментарии
settings = json.loads(re.sub(r"^\s*//.*$", "", content, flags=re.MULTILINE))
# Запись: писал без комментариев
json.dump(settings, f, indent=4)
```

Цикл разрушения:
1. `install.py` читает `settings.json` -> вырезает `//` комментарии
2. Пишет обратно -- комментариев нет
3. Zed видит, что файл изменился -> кнопка "восстановить"
4. Пользователь жмёт "восстановить" -> Zed восстанавливает старую версию
5. MCP сервер пропадает -> пользователь запускает install.py снова
6. GOTO 1

### 4.3 Исправление

Три стратегии в `patch_zed_settings()`:

1. **No-op guard**: если `"mscodebase-intelligence"` уже есть в файле И команда совпадает -- return True (ничего не пишем)
2. **Текст-хирургия**: при первой установке -- вставка JSON-блока перед последней `}` -- все `//` сохранены
3. **JSON dump**: только если команда изменилась (комментарии уже потеряны)

---

## 5. llama.cpp: STATUS_ILLEGAL_INSTRUCTION на Zen 3

### 5.1 Ошибка

```
OSError: [WinError -1073741795] Windows Error 0xc000001d
```

`STATUS_ILLEGAL_INSTRUCTION` -- процесс попытался выполнить инструкцию CPU, которой нет.

### 5.2 Расследование

**CPU:** AMD Ryzen 5 5600H (Zen 3, Cezanne)
- Поддерживает: AVX2, AVX, SSE4.2, FMA3
- **НЕ поддерживает:** AVX512, AVX-VNNI

**Проблема:** `pip install llama-cpp-python` скачал wheel `llama_cpp_python-0.3.33-cp314-cp314-win_amd64.whl`, собранный с **AVX512** на GitHub Actions.

### 5.3 Решение

Официальный `llama.cpp` бинарник (`llama-b9940-bin-win-cpu-x64.zip`) содержит **все варианты CPU-ядер** и авто-детекцию:

```
llama-b9940-bin-win-cpu-x64.zip
  ggml-cpu-haswell.dll        # AVX2   <- используется на Zen 3
  ggml-cpu-zen4.dll           # AVX512 <- только Zen 4+
  ggml-cpu-alderlake.dll      # AVX2+VNNI
  ggml-cpu-sandybridge.dll    # SSE4.2 (fallback)
```

### 5.4 Запуск на Zen 3

```bash
llama-server --host 127.0.0.1 --port 8080 \
  -m bge-m3-Q4_K_M.gguf -c 8192 --embedding

llama-server --host 127.0.0.1 --port 8080 \
  -m bge-reranker-v2-m3-Q4_K_M.gguf -c 8192 --reranking
```

**Замеры на Zen 3 (Q4_K_M):**
| Модель | Startup | RAM |
|--------|---------|-----|
| bge-m3 (embedding) | 5.0s | 523 MB |
| bge-reranker-v2-m3 | 4.8s | 551 MB |

---

## 6. Zed 1.10.0: анализ совместимости

### 6.1 Изменения

| PR | Изменение | Статус |
|----|-----------|--------|
| 59964 | llama.cpp как нативный провайдер | Реализован |
| 59860 | MCP в Settings Editor | Совместим (JSON-формат не менялся) |
| 60098 | Batch file watcher | Авто-выигрыш |
| 59929 | Stale HTTP drop | Реализован (httpx.Limits) |
| 59310 | Queue steering | Не влияет |
| 59710 | Format-on-save OFF | Не влияет |

---

## 7. Приложение: методология замеров

### 7.1 Метрики

| Метрика | Метод |
|---------|-------|
| Cold start | Время от Popen до первого успешного GET /health |
| RAM (RSS) | psutil.Process(pid).memory_info().rss в MB |
| Embed latency | 5x POST /v1/embeddings с 5 текстами |
| Rerank latency | 5x POST /v1/rerank с 4 пассажами |

### 7.2 Тестовые данные

```python
test_texts = [
    'How to implement binary search in Python?',
    'What is dependency injection in software engineering?',
    'Explain the difference between TCP and UDP protocols',
    'How does garbage collection work in Python?',
    'What is the capital of France?',
]
rerank_passages = [
    'Binary search halves the array O(log n)',
    'Python by Guido van Rossum',
    'TCP reliable stream delivery',
    'DI externalizes dependencies',
]
```

### 7.3 Воспроизведение

```bash
# llama.cpp benchmark
python .cache/bench_llama2.py

# ONNX server benchmark
python -c "
from src.core.onnx_server import init_embedder, init_reranker, embed_texts, rerank
import time; t0 = time.time()
init_embedder(); init_reranker()
print(f'Startup: {time.time()-t0:.1f}s')
print(f'Embed: {embed_texts([\"test\"])[0][:5]}...')
print(f'Rerank: {rerank(\"test\", [\"doc\"])}')
"
```
