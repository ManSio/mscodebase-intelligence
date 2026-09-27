# 4A — F3 Research note (prior art + design deltas)

**Дата:** 2026-09-26. **Назначение:** gate для F5 (без применения дельт F5 не замораживается).
**Метод:** первоисточники открыты и сверены построчно 2026-09-26 (arXiv HTML).
Числа — **цитаты с указанием Table/Section**; интерпретации помечены `[инференс агента]`.

---

## 1. Verified: Mem2ActBench

Shen, Li, Zhou, Hu. *Mem2ActBench: A Benchmark for Evaluating Long-Term Memory Utilization in
Task-Oriented Autonomous Agents.* **ACL 2026**; arXiv:2601.19935v1. Код `github.com/Cantaloupe-M/Mem2ActBench`.
*(проверено по arXiv HTML 2601.19935v1)*

- Масштаб: **2 029 сессий**, **400** tool-use задач, avg 13 turns; human-verified memory dependency
  **91.3%** `[verified: §3.6, Table 2 — "Memory Dependency Validity 200 / 91.3"]`.
- **Плечи уже есть** `[verified: §5.1, Table 4]`:
  - `No Retrieval` (closed book): Recall@k `–`, **F1 10.0**, BLEU 8.9, **TSA 73.8**;
  - `Passive` (BM25/Dense/Hybrid, k=1/5/10); лучший passive — Hybrid k=5, **F1≈30.7**;
  - `Perfect Retrieval (Oracle)`: **F1 53.8**, BLEU 53.7, TSA 88.2 (разрыв >23 F1 → бутылочное горлышко = retrieval).
- **Hard negatives** `[verified: §5.4, Table 5]`: defined as «distractor tools **most semantically similar** to the
  ground-truth tool». Random negatives TSA почти не падает (93.50–95.50%); **hard negatives TSA 94.50% → 69.75%**
  (N=1→5); EM 14.25–18.25%; Arg_F1 29.88→22.64.
- **Failure taxonomy — ПЯТЬ типов** `[verified: §5.5]`: (i) Retrieval Miss, (ii) Retrieved-but-Unused,
  (iii) Hallucinated Default, (iv) Lossless Retention Failure, (v) Tool Selection Error.
  *(В черашней версии я написал 4 + «+1» — неверно: их ровно 5, пятый — Tool Selection Error.)*

## 2. Verified: Coin Flip Judge (надёжность LLM-судьи)

Yagubyan. *The Coin Flip Judge? Reliability and Bias in LLM-as-a-Judge Evaluation.* arXiv:2606.13685v1.
*(проверено по arXiv HTML 2606.13685v1)*

- **Cross-judge agreement 76%, κ=0.51** `[verified: §5.6 — "22 of 29 questions (76%), yielding Cohen's κ=0.51"]`.
  Прямая цитата: «approximately one in four evaluation outcomes depends on which judge model is selected».
- **Noise budget** `[verified: §6.2]`: single-trial mean flip rate **13.6%** → «a 100-question benchmark has an
  expected noise budget of **13.6** incorrect outcomes per run»; 3 trials ≈10%; **11 trials ≈5%**; 20 trials ≈3%.
- **Reliability curve** `[verified: §5.9, Table 6]`: single trial = **86.6%** fidelity; 90% → **3 trials**
  (averaged); 95% → **11 trials**; для high-flip вопросов (FR≥10%) — **15 trials на 90%**, 50+ на 95%.
- **Рекомендация** `[verified: §5.9/§6.4]`: **10–20 trials с majority voting**; для high-stakes до 50.
  `t=0` снижает flip на 43–79% (GPT-4o-mini 13.3%→2.8%; GPT-4.1-mini 13.9%→7.9%), **но residual остаётся** —
  `t=0` necessary but not sufficient (3–5 reps всё равно).
- Ограничение автора: оба судьи — OpenAI; cross-provider replication не сделана `[verified: Abstract]`.

> ⚠ **Поправка к вчерашней формулировке.** Я написал «≥10 trials при t=0» — это **смешало два факта**:
> (а) рекомендация — 10–20 trials majority; (б) t=0 — отдельная мера, снижающая, но не убирающая flip.
> Верная формулировка: **10–20 trials majority; t=0 как дополнительная мера (3–5 reps)**.

## 3. Chunking / unit of return

- *Long Context vs RAG* (arXiv:2501.01880): «too many chunks harms», единица длиннее, top 5–10 оптимум.
- *Three Sides of Retrieval* (arXiv:2607.24781): чанкинг разрушает структуру (заголовки, cross-refs).

## 4. Design deltas (ОБЯЗАТЕЛЬНЫ для F5)

| # | Дельта | Источник | Что меняется |
|---|---|---|---|
| **D1** | 4-arm (closed-book/oracle/hard-neg) — **prior art**, не наша новизна | Mem2ActBench Table 4–5 `[verified]` | Claim пере-позиционировать: **репликация на публичном code+prose + plumbing-level partial**. «Впервые closed book» убрать. |
| **D2** | Failure taxonomy (5 типов) | Mem2ActBench §5.5 `[verified]` | В отчёт: Retrieval Miss / Retrieved-but-Unused / Hallucinated Default / Lossless Retention Failure / Tool Selection Error. Второе и четвёртое = наш EXP-24 и «hits and arrives partial». |
| **D3** | Judge — конфаунд | Coin Flip §6.2/§5.9 `[verified]` | Judged-плечи: **10–20 trials + majority + рандомизированный порядок + κ/flip-rate + t=0 как доп. мера**. «5 прогонов» невалидно. |
| **D4** | Hard negatives = «most semantically similar» | Mem2ActBench §5.4 `[verified]` | Наш hard-negative контроль — ближайший семантически кандидат, не random. |
| **D5** | Closed-book — prior art | Mem2ActBench Table 4 `[verified]` | Плечо D подаём как Mem2ActBench-aligned, не как находку Tom. |

## 5. Дифференциация Tom — это ИНТЕРПРЕТАЦИЯ, не факт статьи

`[инференс агента]` Tom в `4745130` сам цитирует Mem2ActBench и разделяет:
- Mem2ActBench `Retrieved-but-Unused` = доказательство **дошло** до контекста, модель не применила (model-side);
- Tom-случай = заметка **сматчена и обрезана бюджетом**, до модели не дошла вообще (plumbing-side).

Отнесение нашего EXP-24 (молчаливое усечение `search_memory`) к **plumbing-side** — это **наша интерпретация**,
согласованная с формулировкой Tom, но **не claim первоисточника**. В отчёте держать как `[инференс]`, отделяя
от verified-цитат. Проверяемо это станет только через F5 (репликация).

## 6. Что это значит для ответа Tom (F7)

- Не заявлять протокол как наш/его вклад. Заявлять: (a) репликация на публичном корпусе;
  (b) `[инференс]` грань Mem2ActBench «Retrieved-but-Unused» (model-side) ↔ plumbing-level lossless retention
  (не дошло) — как проверяемую гипотезу, а не факт.
- Наш вклад = **измерение plumbing-level partial на публичном корпусе** + метод F4b (held-out),
  которого у Tom не было (его 5/5 — confirmation).

## 7. Ledger (сверено с первоисточником 2026-09-26)

| # | Утверждение | Источник | Статус |
|---|---|---|---|
| 1 | 4-arm (closed book/oracle) — prior art | Mem2ActBench Table 4 | ✅ verified (HTML) |
| 2 | Hard negatives 94.50→69.75 (N=1→5) | Mem2ActBench Table 5 | ✅ verified |
| 3 | No Retrieval TSA 73.8 / Oracle F1 53.8 | Mem2ActBench Table 4 | ✅ verified |
| 4 | Taxonomy — 5 типов | Mem2ActBench §5.5 | ✅ verified |
| 5 | κ=0.51, 1-in-4 исходов зависит от судьи | Coin Flip §5.6 | ✅ verified |
| 6 | 10–20 trials majority; single-trial 86.6% | Coin Flip §5.9/§6.4 | ✅ verified |
| 7 | Наш EXP-24 = plumbing-level «Lossless Retention» класс | наш EXP-24 | ✅ (наш замер) |
| 8 | Это именно plumbing, а не model-side | — | 🧠 `[инференс агента]` |
| 9 | Репликация на публичном корпусе | — | ⏳ F5 |
