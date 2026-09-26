# 4A — F3 Research note (prior art + design deltas)

**Дата:** 2026-09-26. **Назначение:** gate для F5 (без применения дельт F5 не замораживается).
**Метод:** целевые веб-поиски (arxiv/ACL/ICML), 2026. Числа — цитаты источников, не наши замеры.

---

## 1. Что нашлось (и что это меняет)

### 1.1 Mem2ActBench — наш 4-arm уже существует
Shen, Li, Zhou, Hu. *Mem2ActBench: A Benchmark for Evaluating Long-Term Memory Utilization in
Task-Oriented Autonomous Agents.* **ACL 2026**, arXiv:2601.19935; код `github.com/Cantaloupe-M/Mem2ActBench`.

- 400 memory-dependent tool-use задач из 2 029 сессий; human-verified **91.3%** не решаемы без памяти.
- **У них уже есть плечи: `No Retrieval` (closed book), `Passive Retrieval` (BM25/dense/hybrid), `Perfect Retrieval (Oracle)`.**
  Сырые числа: No Retrieval TSA **73.8** / F1 10.0; BM25@5 TSA 90.2; Hybrid@5 TSA 86.0; Oracle F1 **53.8**.
- **Hard negatives определены явно:** «distractor tools **most semantically similar** to the ground-truth tool».
  Замер: random-negatives TSA почти не падает (93.5–95.5%), **hard negatives 94.5% → 69.75%** (N=1→5);
  EM 14.25–18.25%; Arg_F1 29.88→22.64.
- Failure taxonomy: **Retrieval Miss / Retrieved-but-Unused / Hallucinated Default / Lossless Retention Failure** (+1).

**Вывод (инверсивный):** протокол «4 плеча + closed book + oracle + hard negatives» — **prior art**, а не
изобретение Tom. Наш claim нельзя подавать как «мы впервые ставим closed book».

### 1.2 Tom это уже признаёт
Tom в `4745130` (Crystals) сам цитирует Mem2ActBench и **дифференцируется**: его случай — «раньше, в
plumbing: заметка правильно сматчена и обрезана бюджетом, до модели не дошла». То есть наша ниша =
**plumbing-level partial arrival**, а НЕ retrieval-провал.

### 1.3 LLM-as-judge — судья это конфаунд, с числами
- *The Coin Flip Judge? Reliability and Bias in LLM-as-a-Judge* (arXiv:2606.13685): cross-judge **κ=0.51**
  → «**1 из 4 исходов зависит от выбора судьи**»; noise budget: 100-вопросный single-trial бенчмарк
  содержит **~14 неверных** исходов, при 11 trials majority → **~5**. Minimum standard: **≥10 trials при t=0,
  рандомизированный порядок**, отчёт majority + flip rate + CI.
- *When the Judge Changes, So Does the Measurement* (2026): evaluator-replacement ambiguity — score
  двигается при замене судьи. *Reliability without Validity* (arXiv:2606.19544): exact-match agreement
  завышает; κ-дефляция 33–41 п.п.
- *Reasoning Model Is Superior LLM-Judge, Yet Suffers from Biases* (ACL EvalEval 2026): даже reasoning-судьи
  несут bias.

**Вывод:** любой judged-arm у нас требует **≥10 trials + majority**, отчёта κ и flip rate. «5 прогонов» из
нашего черновика — **недостаточно**.

### 1.4 Chunking / unit of return
- *Long Context vs RAG* (arXiv:2501.01880): «слишком много чанков вредит», «единица должна быть длиннее»,
  top 5–10 чанков — оптимум; chunk-based уступает index/summarization.
- *Three Sides of Retrieval* (arXiv:2607.24781): чанкинг разрушает структуру документа (заголовки,
  cross-refs) — прямо в одну линию с «whole document vs chunks».

---

## 2. Design deltas (ОБЯЗАТЕЛЬНЫ для F5)

| # | Дельта | Что меняется у нас |
|---|---|---|
| **D1** | Новизна 4-arm опровергнута (Mem2ActBench) | Claim пере-позиционируется: **репликация на ПУБЛИЧНОМ code+prose корпусе** + наш plumbing-level partial-arrival. «Мы впервые ставим closed book» **убрать**. |
| **D2** | Failure taxonomy Mem2ActBench | В отчёт добавить `Retrieval Miss` / `Retrieved-but-Unused` / `Lossless Retention Failure` — второе и третье прямо закрывают наш EXP-24 (21.7M withheld) и вывод Tom «hits and arrives partial». |
| **D3** | Judge — конфаунд (κ=0.51, noise ~14/100) | Judged-плечи: **≥10 trials при t=0 + рандомизированный порядок + majority**; публиковать κ и flips per question + CI. Чердак «5 прогонов» → невалидно. |
| **D4** | Hard negatives = «most semantically similar» | Наш hard-negative контроль — ближайший по семантике кандидат (не random). Совпадает с Mem2ActBench. |
| **D5** | Closed-book = prior art | Плечо D подаём как Mem2ActBench-aligned, не как находку Tom. |

---

## 3. Что это значит для ответа Tom (F7)

- **Не** заявлять протокол как наш/его вклад. Заявлять: (a) репликация протокола на публичном корпусе;
  (b) **дифференциация Tom подтверждена independently**: его differentiation (plumbing vs model-side) — это
  грань между Mem2ActBench «Retrieved-but-Unused» (дошло, модель не использовала) и нашим/Tom
  «**Lossless Retention Failure на уровне канала**» (не дошло вообще). Это цитируемо и проверяемо.
- Наш вклад = **измерение plumbing-level partial на публичном корпусе** + метод F4b (held-out generalization),
  которого у Tom не было (его 5/5 — confirmation).

## 4. Источники
1. arXiv:2601.19935 / ACL 2026 — Mem2ActBench.
2. arXiv:2606.13685 — The Coin Flip Judge.
3. arXiv:2606.19544 — Reliability without Validity.
4. arXiv:2607.08535 — When the Judge Changes.
5. ACL EvalEval 2026 — Reasoning Model Is Superior LLM-Judge.
6. ACL GEM 2026 (Yamauchi et al.) — LLM-as-Judge design choices.
7. arXiv:2501.01880 — Long Context vs RAG.
8. arXiv:2607.24781 — Three Sides of Retrieval.

## 5. Ledger
| # | Утверждение | Источник | Статус |
|---|---|---|---|
| 1 | 4-arm (closed book/oracle) — prior art | Mem2ActBench | ✅ verified (citation) |
| 2 | Hard negatives ≫ random | Mem2ActBench таблица 5 | ✅ |
| 3 | Judge κ=0.51, ~14/100 single-trial noise | Coin Flip Judge | ✅ |
| 4 | Наш EXP-24 = Lossless Retention Failure класса | наш EXP-24 | ✅ (наш замер) |
| 5 | Репликация на публичном корпусе всё ещё не сделана | — | ⏳ F5 |
