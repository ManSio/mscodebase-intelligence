# Exp 1-L — Memory Contamination, Live-Arm

**Верификация утверждений памяти живыми LLM** (в противовес детерминированному proxy-агенту 1-V).
Измеряет: насколько живые модели принимают ложные утверждения из «памяти» проекта
(контаминация), доверяют ли памяти без кода, и — главное — **не режут ли вместе с ложью
правдивую память** (recall на категории `real`).

**Статус:** ✅ завершён (14.08–2026-08-15, 4087 вызовов OpenRouter по серверному аудиту, $0.72; см. `openrouter_activity_2026-08-15.csv`).

---

## Ключевые результаты (1 экран)

| Вывод | Числа |
|---|---|
| **Лучшие для VOR (zero-shot): qwen3.6/3.7-flash** | FA=0.00, $0.0005–0.003/100 выз. |
| ⚠️ **Но FA=0.00 = fail-closed, не фильтрация** | qwen3.6 code_first: recall(real)=**0.08** — принимает 2/25 правды, **активно отвергает 7/25** |
| Красные флаги | glm-4.7-flash FA 0.24–0.30, nemotron-nano FA 0.38 |
| **CoT НЕ окупается** (V3/Part 5) | qwen3.6 code recall 0.08→0.20 при цене ×30–65; glm −26% данных (EMPTY_CONTENT) |
| qwen3.8-max (CoT) — срединная опция | code recall **0.36**, FA 0.04, $0.10/100, err=0 |
| Детерминизм на OpenRouter — иллюзия | маршрутизация ≥8 апстримов (серверный CSV), разброс FA ±0.05–0.10 |

Полные таблицы, per-category разбивка и разбор 5 «точек укуса» ревью — в [report.md](report.md).

---

## Структура папки

| Файл | Назначение |
|---|---|
| `report.md` | Полный отчёт: методология, мастер-матрица 14 моделей, per-category метрики (§6.5), CoT vs Zero-Shot (§6.6), 5 «точек укуса» (§11.1), воспроизведение (§12) |
| `design_longitudinal.md` | Дизайн 30-дневного протокола наблюдения реального дрифта памяти |
| `openrouter_activity_2026-08-15.csv` | Серверный экспорт OpenRouter (независимый аудит: 4087 вызовов, $0.72, маршрутизация) |

## Запуск и тесты

```bash
# harness (live-прогон; ключ OPENROUTER_API_KEY в .env)
python scripts/run_1L_live_arm.py --provider openrouter --arm both \
  --models "qwen/qwen3.7-flash" --prompt-version v2 --no-reasoning --tag v2_en

# CoT-рука (V3/Part 5)
python scripts/run_1L_live_arm.py --provider openrouter --arm both \
  --models "qwen/qwen3.6-flash,qwen/qwen3.7-flash" --prompt-version v2 \
  --reasoning --max-tokens 1500 --tag v3_cot

# per-category метрики (recall на real / FA по категориям)
python scripts/summarize_1L_categories.py --tag v2_en

# тесты (остаются в tests/ — единый вход pytest для CI)
python -m pytest tests/test_run_1L_live_arm.py tests/test_summarize_1L_categories.py -q
```

## Данные

- **Факты** (ground truth, N=50): `experiments/1V_memory_contamination/memory_contamination_facts_v4_rep.json`
  (25 real / 16 absent / 6 trap / 3 silent; fingerprint `820bbbf60a0fc930`).
- **Вердикты (progress-файлы):** вне проекта — `%LOCALAPPDATA%/mscodebase/projects/bfe9644b/experiments/`
  (`live_arm_1L_progress_*.json`; теги: v1, v2_en, ru_v2, nemotron_family, premium_v2, v3_cot,
  v3_cot_run2, v3_cot_max).
- **Серверный аудит:** `openrouter_activity_2026-08-15.csv` (этой папки).

## Ссылки

- EXPERIMENTS_LOG.md — Day 1, Day 2, Red Team фаза 2, follow-up (V2/RU/premium), Day 3 (per-category + CoT), Day 3b (run2 + qwen3.8-max + аудит)
- AGENT_DIARY.md — 2026-08-14 23:20, 23:55; 2026-08-15 (V3/Part 5)
- Связанные: Exp 1-V/1-R (proxy-контроль) — см. `experiments/context_engine/`, EXPERIMENTS_LOG#2026-08-11
- Литература: arXiv 2306.05685 · 2310.13548 · 2305.11747 · NAACL-2025 (Beyond English)
