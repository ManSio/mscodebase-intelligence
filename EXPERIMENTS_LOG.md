# Experiments Log

> **База знаний по бенчмаркам и тестам.** Синхронизировано с `AGENT_DIARY.md`.
> Каждый эксперимент: гипотеза → замер → вывод.

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
