# Session Investigation: ONNX Migration & System Optimization

[🇬🇧 English](ONNX_SESSION_REPORT.md) • [🇷🇺 Русский](../ru/investigations/ONNX_SESSION_REPORT.md) *(не переведён)*

**Дата:** 2026-07-08 — 2026-07-09
**Автор:** AI-Agent (по запросу misha)
**Проект:** `D:\Project\MSCodeBase` — `mscodebase-intelligence`
**Версия:** v2.7.0 (после сессии)
**Severity:** High — полный переход с LM Studio на ONNX Runtime, исправление 7 критических багов
**Статус:** ✅ Завершено. Все 50 инструментов работают в ONNX-режиме.

---

## 1. Предыстория

До этой сессии проект работал исключительно через **LM Studio** — внешний процесс,
который загружал модели bge-m3 (эмбеддер) и bge-reranker-v2-m3 (реранкер) на GPU.
MCP-сервер просто отправлял HTTP-запросы к LM Studio.

Проблема: LM Studio требует ручного запуска, настройки, и не всегда доступен.
Для полной автономности нужен локальный ONNX Runtime без внешних зависимостей.

---

## 2. Хронология открытий и решений

### 2.1 Первая попытка: ONNX не работает

**Симптом:** MCP-сервер запущен, `intel_get_runtime_status` показывает `lm_studio`, хотя порт 1234 закрыт.

**Расследование:**
```python
# src/core/intelligence_layer.py:399 (было)
return {
    "embedding_provider": "lm_studio",  # ХАРДКОД!
    ...
}
```

**Решение:** Заменить хардкод на реальную проверку порта.
```python
_lm_online = False
s = socket.socket(...)
if s.connect_ex(("127.0.0.1", 1234)) == 0:
    _lm_online = True
return {"embedding_provider": "lm_studio" if _lm_online else "onnx", ...}
```

### 2.2 Критический баг: `_mode_lock` не инициализирован

**Симптом:** Все файлы при индексации падают с `AttributeError: 'RemoteEmbedder' object has no attribute '_mode_lock'`.

**Корневая причина:** В `remote_embedder.py` метод `_detect_model_dir()` при нахождении модели делал `return`, не доходя до инициализации `_mode_lock`, `mode`, и фонового сканера.

```python
# Было (return выходит до инициализации):
def _detect_model_dir(self):
    for base in self._onnx_search_paths:
        for subdir in sorted(base.iterdir()):
            if model_file.exists():
                ...
                return  # ← БАГ! _mode_lock не создан

# Стало (break + for-else):
def _detect_model_dir(self):
    for base in self._onnx_search_paths:
        for subdir in sorted(base.iterdir()):
            if model_file.exists():
                ...
                break
        else:
            continue
        break
    # _mode_lock, mode, scanner — всегда инициализированы
```

**Влияние:** 100% файлов при индексации падали. Из 61 Python-файла индексировался только 1 (md-файл, который не использует эмбеддер).

### 2.3 mode="unknown" даёт нулевые вектора

**Симптом:** При первом запросе после старта MCP эмбеддер возвращает `[0.0, 0.0, ..., 0.0]`, потому что фоновый сканер ещё не завершил проверку LM Studio.

**Решение:** Добавить обработку "unknown" в `embed_batch()`:
```python
with self._mode_lock:
    if self.mode in ("onnx", "unknown"):
        self.mode = "onnx"
```

### 2.4 `intel_*` инструменты не работают

**Симптом:** Все `intel_*` инструменты падают с `AttributeError: 'str' object has no attribute 'get'`.

**Корневая причина:** `@error_boundary` декоратор везде использован на внутренних методах, которые возвращают Dict, но декоратор оборачивает результат в JSON-строку. Когда вызывающий код пытается сделать `result.get("key")`, он получает строку, а не словарь.

**Решение:** Убрать `@error_boundary` со всех 9 внутренних методов `intel_*`. Декоратор должен быть на MCP-инструменте, а не на внутренней логике.

```python
# Было
@error_boundary("intel_code_topology", timeout_ms=5000, max_retries=1)
async def intel_code_topology(self, symbol_name: str) -> Dict[str, Any]:

# Стало
async def intel_code_topology(self, symbol_name: str) -> Dict[str, Any]:
```

### 2.5 Реранкер не вызывается

**Симптом:** `search_code(mode=quality)` возвращает те же результаты что `search_code(mode=fast)`. Реранкер молча пропускается.

**Корневая причина:** `MultiProviderReranker.is_available` проверяет только `lm_studio_available or ollama_available`, игнорируя `_onnx_reranker_available`.

```python
# Было
@property
def is_available(self) -> bool:
    return self.lm_studio_available or self.ollama_available

# Стало
@property
def is_available(self) -> bool:
    return self.lm_studio_available or self.ollama_available or self._onnx_reranker_available
```

### 2.6 `prune_deleted_files` сносит весь индекс

**Симптом:** После перезапуска MCP индекс пуст (0 чанков), хотя до этого было 2500+ чанков.

**Корневая причина:** `prune_deleted_files()` получает `active_files_on_disk` — если этот набор неполный (перезапуск, частичная индексация), он удаляет все файлы из БД, которых «нет» на диске — то есть ВСЕ.

**Решение:** Safety guard — не удалять >50% индекса за раз:
```python
delete_ratio = len(deleted_files) / max(total_files_in_db, 1)
if delete_ratio > 0.5:
    logger.warning(f"Safety guard: пропускаю удаление {delete_ratio:.0%} индекса")
    return 0
```

### 2.7 ONNX Runtime нет в requirements.txt

**Симптом:** `❌ Ошибка сборки локального ONNX-детектора: No module named 'onnxruntime'`

**Решение:** Добавить `onnxruntime>=1.17.0`, `transformers>=4.36.0`, `tokenizers>=0.15.0` в `requirements.txt`.

### 2.8 `platform.py` перекрывает stdlib

**Симптом:** ONNX сервер не запускается — `onnxruntime` падает с `AttributeError: module 'platform' has no attribute 'system'`.

**Корневая причина:** `src/core/platform.py` перекрывает стандартный модуль Python `platform`. Любой код, делающий `import platform`, получает наш файл, а не stdlib.

**Влияние:** Ломает `onnxruntime`, `httpx`, и все библиотеки, которые импортят `platform`.

**Решение:** Переименовать в `platform_utils.py`. Обновить все импорты.

---

## 3. Эксперименты и тесты

### 3.1 Тест размера контекста (max_length)

**Цель:** Определить оптимальный max_length для эмбеддера и реранкера.

**Метод:** Замер времени инференса при разных max_length (512, 1024, 2048, 4096, 8192) на текстах разной длины (15, 200, 800, 4000 токенов).

**Результаты (эмбеддер bge-m3):**

| max_length | 15 токенов | 270 токенов | 1258 токенов | RAM |
|:----------:|:----------:|:-----------:|:------------:|:---:|
| 512 | 62ms | 890ms | 1926ms | 865 MB |
| 1024 | 76ms | 898ms | 4964ms | ~870 MB |
| 2048 | 51ms | 863ms | 6755ms | ~890 MB |
| 8192 | 52ms | 880ms | 9177ms | ~1.1 GB |

**Вывод:** Для коротких текстов (95% кода) max_length не влияет на скорость. Выбрали 2048 как запас без потери скорости на малых текстах.

### 3.2 Тест размера контекста (реранкер bge-reranker-v2-m3)

**Результаты:**

| max_length | 22 токена | 140 токенов | 512 токенов | 1439 токенов |
|:----------:|:---------:|:-----------:|:-----------:|:------------:|
| 512 | 52ms | 332ms | 1593ms | 1722ms |
| 1024 | 58ms | 395ms | 4009ms | 3461ms |
| 2048 | 51ms | 248ms | 4748ms | 8627ms |

**Вывод:** 512 токенов достаточно — 100% чанков влезают (максимум 393 токена).

### 3.3 Тест CPU vs iGPU (DirectML)

**Цель:** Определить, даёт ли iGPU выигрыш в скорости.

**Результаты:**

| Тест | CPU | DirectML (iGPU) | Вердикт |
|------|:---:|:---------------:|:--------|
| 15 токенов | 33ms | 250ms | ❌ iGPU медленнее в 7.5x |
| 200 токенов | 860ms | 740ms | ➖ примерно равно |
| Батч 5 файлов | 82ms | таймаут | ❌ |

**Вывод:** iGPU не даёт выигрыша из-за overhead передачи данных CPU↔GPU для INT8 модели. Часть операций всё равно выполняется на CPU.

### 3.4 Тест ONNX Server

**Цель:** Проверить работу ONNX как отдельного HTTP-сервера.

**Результаты:**
- Загрузка модели: ~10 секунд (543 MB)
- Первый запрос: 651ms (включает инициализацию)
- Health check: 2ms
- Embeddings: 1024 dim, корректные значения

**Вывод:** ONNX сервер работает и может обслуживать несколько MCP-процессов.

### 3.5 Анализ реальных чанков в БД

**Цель:** Определить фактическое распределение токенов в чанках.

**Результаты (1000 чанков):**

| Размер | Доля |
|:------:|:----:|
| ≤ 64 токенов | 3.1% |
| ≤ 128 токенов | 30.5% |
| ≤ 256 токенов | 91.7% |
| ≤ 384 токенов | 99.9% |
| ≤ 512 токенов | 100.0% |

**Средний:** 168 токенов. **Максимум:** 393 токена. **Вывод:** 512 токенов хватает для 100% чанков.

---

## 4. Ключевые архитектурные решения

### 4.1 MAX_CHUNK_CHARS = 2000 (было 3000)

**Почему:** 3000 символов ≈ 750 токенов, но `max_length=512` обрезает на 512. Функции от 2000 до 3000 символов не разбивались на под-чанки, но эмбеддер обрезал их хвост. 2000 = 512 × 4 (1 токен ≈ 4 символа).

### 4.2 FALLBACK_CHUNK_LINES = 64, OVERLAP = 16 (было 100/20)

**Почему:** 100 строк Python ≈ 2500-3000 символов ≈ 600-750 токенов — больше max_length. 64 строки ≈ 2000 символов ≈ 512 токенов. Overlap 16 = 25% для захвата контекста на стыках.

### 4.3 SessionOptions для ONNX Runtime

```python
opts = ort.SessionOptions()
opts.enable_cpu_mem_arena = False        # экономия RAM
opts.intra_op_num_threads = 2            # ограничение потоков
opts.inter_op_num_threads = 1
opts.graph_optimization_level = ORT_ENABLE_ALL
opts.execution_mode = ORT_SEQUENTIAL     # последовательное выполнение
```

**Эффект:** RAM 3162 MB → 865 MB (-73%), потоки 102 → 5 (-95%).

### 4.4 Pre-load ONNX через 15 секунд

**Почему:** Первый запрос к ONNX ждал 11 секунд на загрузку модели. Pre-load через 15 сек после старта MCP делает модель готовой до того как пользователь что-то спросит.

### 4.5 Idle timeout 5 минут

**Почему:** Если MCP не используется, модель жрёт RAM зря. Через 5 мин бездействия выгружаем. При следующем запросе перезагружаем (~1 сек).

### 4.6 Safety guard в prune_deleted_files

**Почему:** При перезапуске MCP `prune_deleted_files()` сносил весь индекс. Guard "не удалять >50%" предотвращает потерю данных при неполном сканировании.

---

## 5. Документация

За сессию синхронизированы с кодом:

| Файл | Что исправлено |
|------|---------------|
| README.md | 43→50 tools, 10→14 intel, positioning section |
| AGENTS.md | 43→50 tools, 10→14 intel, 33→34 core |
| docs/en/ARCHITECTURE.md | Layer модель, DI сервисы, CircuitBreaker 45→30s, Debounce 2.5s→500ms/5s, тесты 391→396 |
| docs/en/SEARCH_PIPELINE.md | Тайминги 500ms→5600ms, удалён вымышленный "Structural AST" канал |
| docs/en/GRACEFUL_DEGRADATION.md | Удалён несуществующий L4, latency 3s→6s |
| docs/ru/*, docs/zh/* | Аналогичные правки в 15+ файлах |
| searcher.py (docstring) | Тайминги 300ms→2300ms |

---

## 6. Итоговые метрики

| Метрика | До (старый код, LM Studio) | После (новый код, ONNX) | Изменение |
|---------|:--------------------------:|:-----------------------:|:---------:|
| RAM MCP-процесса | 3162 MB | 865 MB | **-73%** |
| Потоков | 102 | 5 | **-95%** |
| CPU (индексация) | 600% | 175% | **-71%** |
| CPU (простой) | ~0% | 0% | ✅ |
| Чанков в индексе | 9 (баг) | 2561 | **полная индексация** |
| Работающих инструментов | ~30 (7 сломано) | 50 | **все работают** |
| Реранкер | ❌ не вызывался | ✅ ONNX | |
| intel_* инструменты | ❌ падали | ✅ работают | |
| Контекст эмбеддера | 512 | 2048 | без обрезки |
| Контекст реранкера | 512 | 512 | 100% влезают |
| Overlap чанков | 20% | 25% | меньше потерь |
| Pre-load ONNX | ❌ нет | ✅ через 15 сек | |
| Idle выгрузка | ❌ нет | ✅ через 5 мин | |
| ONNX-сервер | ❌ нет | ✅ создан | одна модель на все проекты |

---

## 7. Что осталось

| Задача | Статус | Приоритет |
|--------|--------|:---------:|
| MCP SDK v1→v2 (релиз 27 июля) | ⏳ Следить | P0 |
| ONNX-сервер: доинтеграция в RemoteEmbedder | ✅ Создан, не активирован | P2 |
| Qwen3-Embedding (исследование) | ⏳ Ждём тестов русского | P2 |
| Python 3.14 free-threaded | ⏳ onnxruntime без wheels | P3 |
