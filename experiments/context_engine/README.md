# Context Engine — эксперименты (D-серия) + Multi-RAG ablation

Две независимые группы экспериментов (после выноса memory-contamination в
[`1V_memory_contamination/`](../1V_memory_contamination/README.md)).

**Статус:** ✅ завершены (2026-08-08 — D-серия; 2026-08-11 — multi-RAG).

---

## 1. Context Engine (D-серия): Multi-Tool vs Context Aggregator

**Вопрос:** что эффективнее для агента — 4-5 отдельных MCP-вызовов (multi-tool) или 1
контекстный агрегатор `get_edit_context`-стиля?

| Файл | Назначение |
|---|---|
| `bench_v2.py` | Harness D v3 (30 задач, paired-статистика) |
| `compose_eval.py` | Harness D v1 (4 задачи, 4 руки) |
| `get_edit_context_v2.py` | Реализация агрегатора (прототип) |
| `b_scheme_design.md` | Дизайн B-схемы (intent-фильтр) |
| `tasks*.json`, `strategy_a_data*.json`, `results_*.json` | Задачи/данные/результаты (v1-v3) |

**Ключевые числа:**
- D v3 (N=30): recall B vs C2 **неразличим** (Δ +0.025, CI ±0.054, ничьи 27/30) — разрыв v2 был шумом; токены B стабильно ниже на ~980 → **B-схема (intent-фильтр) = оптимум**: recall 0.900 ≥ A 0.875 при 1 RT и 275 токенах.
- D v1 (N=4): агрегатор −78% tool_calls, −89% latency, −19% tokens при паритете success.
- Дефекты D1-D3 → KNOWN_ISSUES (🟡), фикс после повторного прогона.

## 2. Multi-RAG ablation

**Вопрос:** даёт ли multi-RAG (vector+BM25+FTS5+graph) выигрыш над single-компонентами?

| Файл | Назначение |
|---|---|
| `multi_rag_ablation.py` | Harness v2 (реальная изоляция компонентов + изоляция кэша per-arm) |
| `multi_rag_design.md` | Дизайн |
| `multi_rag_ablation_tasks_v3.json` | Задачи (11MB) |
| `multi_rag_full_run_2026-08-11.log` | Лог полного прогона |

**Ключевые числа:**
- recall-максимум даёт `fts5_only` 0.825 ≥ full 0.775 — H1 (multi > single) по recall **опровергнута**;
- multi-RAG выигрывает по precision (quality 0.719 vs fts5 0.523);
- инкременты: BM25 над vector +0.430, FTS5 над V+BM25 +0.178, vector над BM25 −0.098 (вредит);
- graph-enrichment 0.000 (метаданные, не текст);
- **production-баг найден:** hybrid_search_async кэш-хит пропускает dense-тир → KNOWN_ISSUES#2026-08-11-hybrid-cache.

## Запуск

```bash
python experiments/context_engine/bench_v2.py          # D v3 (30 задач)
python experiments/context_engine/multi_rag_ablation.py  # multi-RAG v2
```

## Ссылки

- EXPERIMENTS_LOG.md — 2026-08-08 (context-engine v1/v2/v3), 2026-08-11 (multi-rag)
- AGENT_DIARY.md — 2026-08-08 (D-серия), 2026-08-11 (multi-rag)
- KNOWN_ISSUES.md — D1-D3 (🟡), hybrid-cache (ждало решения)
