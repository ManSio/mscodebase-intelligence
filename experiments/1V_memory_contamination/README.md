# Exp 1-V / 1-R — Memory Contamination (proxy-контроль) + Retraction

**Детерминированный proxy-агент** («проверь claim по паттернам в коде») — контрольная группа
для live-arm [Exp 1-L](../1L_live_arm/README.md). Измеряет заражение памяти ложными
утверждениями (contamination) и эффект ретракции/verify-on-read (ADR-0002/0003).

**Статус:** ✅ завершён (2026-08-11); контрольная группа 1-L (live-arm).

---

## Серия экспериментов (хронология)

| Эксперимент | Что измерено | Ключевые числа |
|---|---|---|
| **1-V** (N=24) | contamination без отзыва, память-контекст ×22 токенов | code_contradictability 0.714; correction_capability 1.0; memory_confidence_effect = 4 (SILENT-факты) |
| **1-R** (v3+retraction) | эффект ADR-0002 (статусы VERIFIED/REFUTED + `intel_retract_memory_node`) | persistent contamination **−88%**; memory_first adoption 1.0→0.12 |
| **1-V** (verify-on-read) | эффект ADR-0003 (Lazy Validation Layer) | adoption честного (code_first) **→ 0.0** (было 0.12); steady-state 0.6ms |
| **1-V REP** (facts v4, N=50) | репликация на независимых данных | adoption 0.0 воспроизведён; 0 ложных REFUTED TRUE при типизированных якорях; present-trap слепота воспроизведена (memory_first 0.24) |

**Ограничения (зафиксированы честно):** proxy всегда решает (unknown=0), false_accept=0 by
construction; headline-числа — свойство эвристики, НЕ поведения LLM → измерено в 1-L (live-arm).

---

## Структура папки

| Файл | Назначение |
|---|---|
| `memory_contamination.py` | Основной harness (детерминированный агент, вердикты decide()) |
| `memory_contamination_generator*.py` | Генераторы фактов v1-v3 / v4_rep |
| `memory_contamination_retraction.py` | Harness 1-R (ретракция) |
| `memory_contamination_verify.py` | Harness 1-V (verify-on-read) |
| `verify_memory_contamination.py` | Верификация вердиктов (3 оси ALL PASS, 2026-08-11) |
| `memory_contamination_facts*.json` | Датасеты ground truth (v1, v2, v3_generated, **v4_rep** — N=50, fingerprint `820bbbf60a0fc930`, используется также Exp 1-L). ⚠️ **СНОСКА 2026-08-16:** 4/6 trap-фактов v4_rep mislabeled (R43/R45/R46/R47 по факту true — см. corrected-копию `memory_contamination_facts_v4_rep_corrected.json`, fingerprint `e5f7373d50a3e640`); прокси-вердикты VERIFIED по trap-фактам с corrected-лейблами — правильные, а не «видимый ложный» |
| `memory_contamination_results*.json` | Результаты прогонов (v1, v2, v3_generated, v3_retraction, v3_verify, v4_rep) |

## Запуск и тесты

```bash
# факты v4_rep — общий датасет с Exp 1-L (FACTS-путь в scripts/run_1L_live_arm.py)
python experiments/1V_memory_contamination/memory_contamination_verify.py \
  experiments/1V_memory_contamination/memory_contamination_facts_v4_rep.json

# связанные тесты (ретракция/verify-on-read — код ADR-0002/0003, не только эксперимент)
python -m pytest tests/test_memory_retraction.py tests/test_verify_on_read.py -q
```

## Ссылки

- EXPERIMENTS_LOG.md — 2026-08-11: memory-contamination, 1-R, 1-V, 1-V-REP
- AGENT_DIARY.md — 2026-08-11 22:40/22:40/23:10/23:55 (серия)
- docs/adr/0002-retraction-receipt.md, docs/adr/0003-verify-on-read.md, docs/adr/0005-pkg-anchors.md
- KNOWN_ISSUES.md — 2026-08-11 memory-addonly (решено ADR-0002), footgun verify-скрипта
- Live-контроль: [Exp 1-L](../1L_live_arm/README.md)
