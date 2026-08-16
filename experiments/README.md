# experiments/ — Реестр экспериментов MSCodeBase

Единая точка входа: каждый эксперимент — отдельная папка `experiments/<ID>_<тема>/` с
`README.md` (обзор + запуск + результаты + команды тестов). Скрипты harness'ей живут в
`scripts/`, тесты — в `tests/` (единый вход `pytest tests/` для CI, §7 AGENTS.md); README
папки эксперимента ссылается на них.

**Правила папки (см. §0.6 AGENTS.md):** никаких одноразовых скриптов/логов в корне
`experiments/` — либо в папку эксперимента, либо в `_archive/`; никаких дублей README.
`fts5_search.py` и `audit.md` в корне — на них ссылаются src/tests и ISSUE.md.

---

## Эксперименты

| ID | Тема | Папка | Статус | Ключевые выводы (1 строка) |
|---|---|---|---|---|
| **1-L** | Memory Contamination, live-arm (живые LLM) | [`1L_live_arm/`](1L_live_arm/) | ✅ 2026-08-15 | FA=0.00 у qwen3.6/3.7 = fail-closed (recall 0.08), CoT не окупается, qwen3.8-max — срединная опция |
| **1-V / 1-R** | Memory Contamination, proxy-контроль + ретракция (ADR-0002/0003) | [`1V_memory_contamination/`](1V_memory_contamination/) | ✅ 2026-08-11 | verify-on-read: adoption честного → 0.0; present-trap слепота структурна |
| **1-M** | Manifest-anchoring (pkg:-якоря, ADR-0005) | [`1M_manifest_anchoring/`](1M_manifest_anchoring/) | ✅ 11-2026-08-14 | типизированные якоря закрыли 7 ложных REFUTED |
| **2-E** | Evidence Ladder (claim→anchor→file→graph→temporal) | [`2E_evidence_ladder/`](2E_evidence_ladder/) | 🟡 дизайн 2026-08-15 | 5 arm'ов × те же 50 фактов; E3/E4 — новые evidence-форматы |
| Context Engine | Multi-Tool vs Context Aggregator, D-серия + Multi-RAG | [`context_engine/`](context_engine/) | ✅ 2026-08-08 | 1 агрегатор вместо 4-5 MCP-вызовов: −78% calls, recall 0.900; fts5_only recall 0.825 |
| Canary / Shadow | Fail-open ветки, collapse-детектор | [`canary_shadow/`](canary_shadow/) | ✅ 11-2026-08-12 | пустой canary → fail-closed; absolute anchor 0.5 |
| Concurrency | Гонки при замене примитива (§2.3) | [`concurrency/`](concurrency/) | ✅ 2026-08-11 | «0 errors» ≠ верные данные — стресс-тест на корректность |
| Evalmut | Mutation testing для eval-градеров | [`evalmut/`](evalmut/) | ✅ 2026-08-14 | validate_scores: mutation score 8% → 100% (P-006) |
| Root Cause Eval | Аудит root-cause предсказаний | [`root_cause_eval/`](root_cause_eval/) | 🟡 2026-07-22 | датасет инцидентов + gold standard |
| Lock-zombie | PID-lock self-healing (WS9) | [`lock_zombie/`](lock_zombie/) | ✅ 2026-08-08 | orphan 30s→120ms |
| Late Enrichment | Late code chunking (WS3) | [`late_enrichment/`](late_enrichment/) | 🟡 исследование | imports=0.0 — находка, KNOWN_ISSUES |
| Benchmark D | Контекстный бенчмарк (12 задач L3-L5) | [`benchmark2/`](benchmark2/) | ✅ 2026-08-08 | runner.py + tasks.jsonl + README |
| Probes | Одноразовые пробы (без отчётов) | [`misc_probes/`](misc_probes/) | — | см. README папки |

## Исследовательские заметки (в корне experiments/, не эксперименты)

`research_internet_2026-08-04.md`, `research_verification_layers_devto_2026-08-11.md`,
`owp_*.md`, `deep_research_log.md`, `DEV_EXP.md`, `github_research_log.md`,
`second_brain_research.md`, `audit.md` — контекст решений; не выносились в `research/`,
т.к. на них ссылаются docs/archive и CHANGELOG (en/ru/zh).

## Архив

`_archive/` — мусор (старые `_*.bat`/`_*.txt`/`_*.sh`, июль 2026) — сохранён, не удалялся.
