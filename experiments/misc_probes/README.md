# Misc probes — одноразовые пробы (не полноценные эксперименты)

Разовые проверки гипотез без собственных отчётов (результаты — в EXPERIMENTS_LOG.md/KNOWN_ISSUES.md
по датам). Полноценные эксперименты — в соседних папках (`1L_live_arm/`, `1V_memory_contamination/`,
`context_engine/`, `canary_shadow/`, `concurrency/`, `evalmut/`, `root_cause_eval/`, `benchmark2/`,
`lock_zombie/`, `late_enrichment/`).

| Файл | Проба (2026-07…08) |
|---|---|
| `run_experiment_*.py` + `*_results.json` | серия поисковых экспериментов (v2-v5, pagerank, fts5, treesitter, smart_summary, e2e, compiler) |
| `sandbox_lancedb_*.py` | песочница LanceDB (drop/inproc/multiproc/race/rmtree) |
| `test_fastmcp_*.py`, `test_subprocess_windows.py` | ранние ручные пробы (не pytest-сюита) |
| `treesitter_parser.py` + results | парсер деревьев |
| `t*.patch` | патчи арм A/B (контекст-эксперименты t1/t4) |
| `compiler_concept*.py` + json | концепт компилятора (июль) |
| `e2e_results*.json` | e2e-прогоны (июль) |
| `embed_bench*.py`, `bench_embed_batch.py` | бенчи embedder |
| `exp_distance_semantics.py`, `exp_dup.py`, `exp_graph_path.py`, `exp_jupyter.py`, `exp2_symbols.py` | граф/семантика (август) |
| `exp_ln_strip_repro.py`, `exp_population_blindspot.py`, `exp_vacuous_scan.py`, `exp_verify_gate.sh` | EXP-1..5 (guard'ы, 2026-08-11) |
| `mmr_prototype.py`, `pagerank_*` | реранк/граф-прототипы |

> ⚠️ `run_experiment_pagerank.py` — исторический артефакт бага D1 («тень эксперимента затеняла
> прод-символ build_call_graph»): упоминания в EXPERIMENTS_LOG/AGENT_DIARY/KNOWN_ISSUES как пример.

> `fts5_search.py` и `audit.md` остались в корне experiments/ — на них ссылаются
> src/tests и ISSUE.md соответственно (см. experiments/README.md).
