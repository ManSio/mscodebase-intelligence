---
title: "Memory Turns an Honest UNKNOWN State into a Structural Guess"
description: "Part 3 of MSCodeBase Intelligence — Field Notes. Source material (not the published article): verify-on-read memory verification — Exp 1-V, ADR-0003/0005, honest 0.0 adoption."
tags: machinelearning, python, rag, llm, memory
---

> **Part 3 of: [MSCodeBase Intelligence — Field Notes](README.md)** — *[Part 1: PageRank](pagerank-codebase-myth.md) · [Part 2: Silent Vector Contamination](silent-vector-contamination.md) · Part 3: Verify-on-Read · [Side Quest: Zed threads.db](zed-threads-db-reverse-engineering.md)*

> **Статус:** статья опубликована на dev.to. Этот файл — ЛОКАЛЬНЫЙ source-material
> (не дубль текста): числа, эксперименты и решения, на которых статья построена.
> URL dev.to — TODO владельцу (не выдумываем).

## Ключевая фраза

> *"Memory turns an honest UNKNOWN state into a structural guess"* — если верификатор
> не проверил факт, а память уже отвечает «как будто знает», честный UNKNOWN
> превращается в структурную догадку. (Процитировано Skillselion в комментариях.)

## Экспериментальная база

| Эксперимент | Числа | Место |
|---|---|---|
| Exp 1-V (2026-08-11) | VERIFIED=10 REFUTED=28 INCONCLUSIVE=12; false REFUTED среди TRUE: **7** [G07,G25,G11,G24,G23,G18,G21] (наивная типизация токенов) | `EXPERIMENTS_LOG.md#1-V` |
| Exp 1-V REPLICATION | VERIFIED=22 REFUTED=19 INCONCLUSIVE=9; **0** false REFUTED при корректной типизации; adoption честного 0.0 воспроизведён; steady-state 0.6ms | `EXPERIMENTS_LOG.md#1-V-REP` |
| ADR-0003 | verify-on-read: INCONCLUSIVE-вердикт, бюджет ≤50ms | `docs/adr/0003-verify-on-read.md` |
| ADR-0005 | pkg:-анкоры (closed-world манифест): отсутствие = REFUTED(SILENT_ABSENCE) | `docs/adr/0005-pkg-anchors.md` |

## Три конфигурации агента (контроль)

- **B** (baseline) — память без verify.
- **A_code_first** — код до памяти (adoption 1-V: **0.0** — честный агент не верит неотозванному).
- **A_memory_first** — память до кода (adoption 1-V: 0.16; v3: 1.0).

## Ограничение (честно)

Эксперименты — на детерминированном proxy-агенте (эвристики), не на живой LLM.
Цифры доказывают архитектурное свойство, а не измеряют поведение живой модели.
→ Experiment 1-L (30-day longitudinal, live-model arm): `experiments/exp_1L_longitudinal_30d.md`

## Продолжения

- Experiment 1-M (manifest-anchoring, гипотеза Skillselion — проверена): `experiments/exp_1M_manifest_anchoring.md`
- Experiment 1-L (30-day longitudinal — дизайн): `experiments/exp_1L_longitudinal_30d.md`
