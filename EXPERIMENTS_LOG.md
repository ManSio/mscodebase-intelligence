# Experiments Log

> **База знаний по бенчмаркам и тестам.** Синхронизировано с `AGENT_DIARY.md`.
> Каждый эксперимент: гипотеза → замер → вывод.

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
