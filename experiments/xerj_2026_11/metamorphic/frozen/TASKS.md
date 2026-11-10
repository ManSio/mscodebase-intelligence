# Metamorphic triples — frozen before the run

Date: 2026-11-10. Purpose: separate "form of the question" from "retrieval".
Each base task is asked in three formulations that must have the same answer:

- `name` — the identifier itself;
- `ru` — Russian prose (the form users actually type);
- `en` — English prose.

Gold file is fixed per base task. If `name` hits and `ru` misses, the gap is the
form (identifier extraction), not the corpus. If `en` also misses, it is the
prose-to-answer gap, not the language.

| base | name | ru | en | gold |
|---|---|---|---|---|
| T1 | `where is FreshnessChecker defined` | `Где решается, нужно ли переиндексировать файл?` | `where is the decision to reindex a file` | `src/core/indexing/freshness.py` |
| T2 | `where is get_progress_file defined` | `Какая функция возвращает путь прогресса?` | `which function returns the progress path` | `src/core/artifact_paths.py` |
| T3 | `where is ETAPredictor defined` | `Где задан профиль ETA для impact_analysis?` | `where is the ETA profile for impact_analysis` | `src/core/eta_predictor.py` |
| T4 | `where is get_call_chain defined` | `Где считается call chain?` | `where is the call chain computed` | `src/core/indexing/symbol_index.py` |

Predictions (frozen):

| # | Prediction | Expected | Falsifier |
|---|---|---|---|
| M1 | `name` hits every base task at top-1 | PASS | any name formulation misses |
| M2 | `ru` is worse than `name` on at least 2 of 4 | PASS | `ru` equals or beats `name` |
| M3 | `en` is better than `ru` on at least 2 of 4 | PASS | `en` equals or is worse than `ru` |
| M4 | the gate's verdict is `answer` for `name` and not for `ru` misses | PASS | a miss reports `answer` |

If M2 and M3 both pass, the lever is identifier extraction for prose (the RU
lexicon / name-variant channel), not the retrieval stack. If M2 fails, the form
is not the problem and the lexicon experiment is not justified.
