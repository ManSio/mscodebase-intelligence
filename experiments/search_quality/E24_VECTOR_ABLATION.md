# E24 HYPOTHESES (frozen до прогонов; входы — scripts/e2e_quality_search.py CASES, N=10)
# H1: без вектора hit@5 падает (вектор даёт recall-массу) — ожидаю PASS
# H2: hit@1 fast остаётся 0 (пол, падать некуда) — ожидаю PASS
# H3: ни одного ERR/исключения — деградация graceful (engine ловит) — ожидаю PASS
# H4: BM25/FTS полностью компенсируют (hit@5_B == hit@5_A) — ожидаю FAIL
# H5: quality-режим не страдает (rerank на fused-пуле) — ожидаю FAIL
# Порог значимости: дельта ≥2/10 — сигнал; 1/10 — шум (N=10).
