# Verification Ledger — E65 fusion arms

Every row is `Verified` (command run in this session) or explicitly not.
The independent reviews found four blockers across two rounds; the rows below
describe the code **after** all of them were fixed and the measurement was re-run.

| # | Claim | Evidence | Status |
|---|---|---|---|
| 1 | Three arms compute different rankings | `python -m pytest tests/test_fusion.py -q` -> 14 passed; `test_rrf_prefers_the_row_two_channels_found` and `test_norm_trades_weight_for_the_channel_score` assert opposite orders on the same input | Verified |
| 2 | The tests can fall | mutation `rrf: 1/(60+idx) -> score+weight` -> `4 failed, 10 passed` (`..._rank_is_the_reciprocal...`, `..._drops_within_channel_position`, `..._keeps_per_channel_ranks_under_interleaved_arrival`, `..._two_channels_on_one_row_count_twice`) | Verified |
| 3 | Shipped default is unchanged | `MSCODEBASE_FUSION` unset -> `weights`; two default-mode tests. Re-proved after the tie-break change: 400 random item sets against `git show HEAD:...` -> **0 real behaviour changes**; 34 cases differ only in tie order (4 of them change which tied row survives truncation) | Verified |
| 4 | Definition demotion holds in every arm | `test_definition_demotion_survives_every_arm` + `..._holds_against_a_low_weight_neighbour` (the `references` profile that broke version 1) | Verified |
| 5 | Concurrent channel appends cannot scramble RRF ranks | `test_rrf_keeps_per_channel_ranks_under_interleaved_arrival`, `test_rrf_order_does_not_depend_on_arrival_order` | Verified |
| 6 | `definition` and `symbol` are two rankings | `test_two_channels_on_one_row_count_twice` -> `2/60`; 4 of the panel tasks depend on this (round-3 bug: merging them was not the frozen formula) | Verified |
| 7 | The suite does not depend on the shell | `tests/conftest.py::_fusion_default` autouse fixture clears `MSCODEBASE_FUSION` | Verified |
| 8 | The A/B is a real measurement | `fusion/run_fusion.py --runs 3`: 53 tasks x 3 arms x 3 repeats, guards `invalid 0`, `scored 53/53/53`, `arms differ: True`. Numbers live in `REPORT.md`; the artifact `results.json` holds the summary table and per-task booleans (**not** raw answers or timings — those exist only in the run log) | Verified |
| 9 | The panel size is pinned | runner aborts when `len(tasks) != 53`; `--limit` runs are labelled SMOKE and never write `results.json` | Verified |
| 10 | Full suite green after the change | `python -m pytest tests/ -q` -> `2439 passed, 7 skipped, 97 deselected in 232.22s`, exit 0 | Verified |
| 11 | Every reported rate has an interval | `python experiments/xerj_2026_11/wilson.py` prints a Wilson 95% CI for each E65 cell | Verified |
| 12 | Speed is not a criterion | `frozen/PLAN.md` Amendment 1 (owner decision, recorded before the first run) | Verified (document) |
