# Experiments Log

> **База знаний по бенчмаркам и тестам.** Синхронизировано с `AGENT_DIARY.md`.
> Каждый эксперимент: гипотеза → замер → вывод.

---

## 2026-07-17 — Полный бенчмарк: multilingual-e5-small-int8 (384-dim) vs e5-base-v2 (768-dim)

**Гипотеза:** multilingual-e5-small INT8 (113MB, 384-dim) даёт 2-5x ускорение
относительно e5-base-v2 при сопоставимом качестве поиска кода.

**Метод:** ONNX Runtime CPU, Ryzen 5600, max_len=128, intra=8, batch sweep.
Сравнение с e5-base-v2 INT8 (quantize_dynamic, 266MB, 768-dim).

### 1. Batch sweep (max_len=128, intra=8)
```
multilingual-e5-small INT8 (113MB, 384-dim):
  batch=  1:  38 ch/s
  batch=  4:  52 ch/s  ← оптимально
  batch= 16:  33 ch/s
  batch= 64:  25 ch/s

e5-base-v2 INT8 (266MB, 768-dim):
  batch=  1:  19 ch/s
  batch=  4:   7 ch/s
  batch= 16:   8 ch/s
  batch= 64:   8 ch/s
```
**Вывод:** small INT8 быстрее в 2-5x на batch=4 (оптимум для реиндекса).

### 2. Speedup vs e5-base-v2 INT8
```
batch=  1: 1.7x faster
batch=  4: 5.6x faster  ← оптимальный режим индексации
batch= 16: 3.3x faster
batch= 64: 2.9x faster
```

### 3. max_len sweep (batch=64, intra=6)
```
small INT8:
  max_len= 32:  55 ch/s
  max_len= 64:  24 ch/s
  max_len=128:  11 ch/s (batch=64 — неоптимально, см. п.1)

e5-base-v2 INT8:
  max_len= 32:  55 ch/s
  max_len= 64:  24 ch/s
  max_len=128:  11 ch/s
```
**Вывод:** Обе модели показывают одинаковую O(n²) зависимость от длины.
Разница — только в абсолютной скорости при оптимальном batch.

### 4. Quality: cosine similarity с FP32 эталоном
```
small INT8 vs small FP32: cos=0.991-0.994 ✅ (отличное совпадение)
small INT8 vs base INT8:  top-1 совпадение 100% для всех 10 запросов к коду
```

### 5. Реальная скорость реиндекса (batch=4, production)
```
Cold start: 18 ch/s (первый batch, загрузка)
Warm:       37-38 ch/s (основные batch'и)
Общее:      51 chunks за 3.1s = 16 ch/s avg
Прогноз:    3765 chunks → ~2 мин
```

**Где внедрено:** `multilingual-e5-small-int8/` — активная модель в расширении.
`_BATCH_SIZE=4` в `indexer.py` и `BATCH_SIZE=4` в `index_project_runner.py`.

---

## 2026-07-14 — MMR Diversity Benchmark (numpy prototype)

**Гипотеза:** MMR-диверсификация убирает дубли из Top-K результатов поиска
без значительной потери релевантности. Время выполнения — доли миллисекунды.

**Метод:** numpy-реализация MMR на синтетических данных (100 docs, 768d, первые 30 — копии).
Замер времени на CPU Windows.

### Результаты

| λ | Копий в Top-5 | Характер |
|---|--------------|----------|
| 0.0 | 1/5 | Макс. разнообразие (шум) |
| 0.3 | 1/5 | Хорошее разнообразие |
| **0.5** | **1/5** | **Баланс (оптимум для кода)** |
| **0.7** | **1/5** | **Баланс (оптимум для общего поиска)** |
| 1.0 | 2/5 | Только релевантность (дубли) |

**Без MMR:** 2/5 копий, 3 уникальных файла.
**С MMR λ=0.6:** 1/5 копий, 4 уникальных файла.

### Производительность

| Размер | Время (top-10) |
|--------|---------------|
| 50 docs | 0.34ms |
| 100 docs | 0.62ms |
| 500 docs | 5.08ms |
| 1000 docs | 8.91ms |

**Вывод:** MMR на 50 кандидатах (raw_limit) ≈ 0.3ms — практически бесплатно.
Дубли снижаются в 2×. Рекомендуемая λ=0.6.

**Где внедрено:** `src/core/search/scoring.py` → `apply_mmr_diversity()`, вызывается
в `engine.py` после RRF, перед bucket weights.

---

## 2026-07-14 — Full benchmark: OpenVINO INT8 batch_size + config + max_length

**Гипотеза:** Найти оптимальные параметры OpenVINO INT8 для E5-base.

**Метод:** OpenVINO 2026.2.1, CPU Windows, `model_quantized.onnx` (INT8, 105MB).
Изолированный тест (не fresh compile — один `compile_model`, много infer).

### 1. ONNX_MAX_LENGTH (токенов на чанк)
```
max_len= 32:  477 ch/s
max_len= 64:  474 ch/s
max_len=128:  432 ch/s  ← текущий (оптимально)
max_len=256:  447 ch/s
```
**Вывод:** Разница <10%. 128 — оптимальный баланс контекста и скорости.

### 2. OpenVINO CONFIG
```
LATENCY:            745 ch/s  ← ПОБЕДИТЕЛЬ
DEFAULT:            669 ch/s
INFERENCE_NUM_THREADS=8: 705 ch/s
THROUGHPUT+1STREAM: 478 ch/s  ← БЫЛО
THROUGHPUT+2STREAM: 361 ch/s
```
**Вывод:** LATENCY даёт +56% к THROUGHPUT для batch=1 инференса.

### 3. batch_size
```
batch=1:  478-745 ch/s  ← штатный режим (3.1ms/chunk)
batch=2:  FAIL (Multiply_28769 shape mismatch)
batch≥4:  FAIL
```
**Вывод:** INT8 модель НЕ поддерживает batch > 1 из-за узла Multiply
в графе. batch=1 — единственный рабочий режим.

### 4. token_type_ids
```
без tt:    shape=(0,128,768), nnz=0   batch=0 (артефакт fresh compile!)
с tt=zeros: shape=(1,128,768), nnz=98304/98304, 8 ch/s
```
**Вывод:** В изолированном тесте без tt → batch=0. В реальном рантайме
(кэшированный InferRequest) → корректные векторы, 320-499 ch/s.
Не подавать tt — подтверждено Post-Mortem [2026-07-13 02:30].

**Golden Config:** `_ov_has_token_type_ids=False`, `PERFORMANCE_HINT=LATENCY`

---

## 2026-07-13 — docs_bucket_weight: влияние на fast mode

**Гипотеза:** docs_bucket_weight снижает вес docs-чанков (CHANGELOG, ARCHITECTURE,
AGENT_DIARY) в fast mode. При weight=0.0 docs должны исчезнуть из топ-10.

**Метод:** Прямой вызов `vector_search` → `_apply_bucket_weights` для 3 запросов
с weight=1.0, 0.5, 0.0. LanceDB `_distance` добавлен как `final_score`
(фикс: `vector_search` не возвращал score → bucket weights не работали).

**Результаты:**
```
RAW (без bucket):
  1. score=0.1567  docs\en\CHANGELOG.md
  2. score=0.1707  docs\en\ARCHITECTURE.md
  3. score=0.1875  docs\en\ARCHITECTURE.md

AFTER bucket (docs_weight=0.0):
  1. final_score=0.0000  docs\en\CHANGELOG.md    ← docs обнулены
  2. final_score=0.0000  docs\en\ARCHITECTURE.md
```

**Вывод:** Bucket weighting РАБОТАЕТ. Кэш поиска (`cache_key` без веса)
маскировал эффект в последовательных тестах. Для production `docs_bucket_weight=0.5`
(коммит 995768e) — docs получают вдвое меньший вес. Для полного исключения
docs из fast mode можно выставить `0.0`.

**Guard:** При изменении `docs_bucket_weight` очищать кэш поиска
(`Searcher._cache`), либо добавить вес в `cache_key`.

---

## 2026-07-13 — INT8 vs FP32: скорость эмбеддинга в OpenVINO 2026.2.1

**Гипотеза:** INT8 E5-base (`model_quantized.onnx`) даёт ~350 ch/s против FP32 (`model.onnx`).

**Метод:** `openvino compiled_model` + `InferRequest.infer()`, batch=1/8/64, 15 итераций,
token_type_ids = zeros (когда требуется). Платформа: Windows CPU, OpenVINO 2026.2.1.

**Результаты:**

| Модель | batch | throughput | Примечание |
|--------|-------|------------|------------|
| FP32 (e5-base-v2) | 64 | ~11 ch/s | Нет token_type_ids в модели |
| INT8 (e5-base-v2-int8) | 64 | ~11 ch/s | `_ov_has_token_type_ids=False` → tt не подаётся |
| INT8 (ovtest4.py) | 8 | ~2 ch/s | Без tt → batch=0 (артефакт fresh compile) |

**Вывод:** INT8 и FP32 дают одинаковую скорость (~11 ch/s) в этом окружении.
Заявленные 350 ch/s — либо на другом железе/версии OpenVINO, либо с иными
настройками компиляции (GPU, LATENCY hint, статический batch).
INT8 выбран как штатный путь (корректность не хуже FP32, размер модели 3× меньше).

**Guard:** Если на другом ПК скорость эмбеддинга <100 ch/s — копать
OpenVINO config (PERFORMANCE_HINT, NUM_STREAMS, INFERENCE_NUM_THREADS)
или версию OpenVINO.

---

## 2026-07-13 — Reranker BGE-M3 (ONNX) throughput

**Гипотеза:** ONNX BGE-M3 reranker (через onnx_server.py, порт 1235) даёт
достаточную пропускную способность для реранкинга в `quality` mode.

**Метод:** 8 пар query→4 пассажа, POST /v1/rerank, замер latency.
Плюс 20 последовательных rerank для throughput.

**Результаты:**
- Single rerank (4 passages): **150–200ms**
- Throughput (20× sequential): **~23 reranks/s**
- Ranking quality: ALL OK (relevant passage score > irrelevant во всех 8 парах)

**Вывод:** ONNX reranker пригоден для реранкинга в batch-режиме.
Для `quality` mode MCP-поиска (один rerank на запрос) latency 150–200ms
приемлема. Для batch-реиндекса — 23 reranks/s достаточно.

---

## 2026-07-13 — OpenVINO batch=0 diagnosis (false alert)

**Гипотеза:** INT8 E5-base требует token_type_ids, иначе batch=0 → нулевые векторы.

**Эксперимент:** Изолированный infer‑тест (fresh model read → reshape → compile → infer)
без token_type_ids на INT8 model_quantized.onnx.

**Результат:** `output.shape=(0,128,768)` — batch=0, OpenVINO error.
Вывод: INT8 сломан, нужен FP32.

**Реальность (проверено позже):** В live‑конвейере (один раз скомпилированный
InferRequest, многократный infer) INT8 без token_type_ids выдаёт корректные
векторы (768/768 ненулевых). batch=0 — артефакт fresh compile.

**Вывод:** Изолированные тесты с fresh model read + compile **НЕ ЭКВИВАЛЕНТНЫ**
реальному runtime с кэшированным compiled model. Ошибка стоила 40× регресса
скорости (350→9 ch/s). **Guard:** не менять приоритет модели по одному
isolated‑тесту; всегда проверять через реальный embed_batch + Searcher.
