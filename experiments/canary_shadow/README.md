# Canary / Shadow — Fail-open ветки и collapse-детектор

**Проблема:** shadow-canary embedder'а пропускал атаки: collapse-to-constant `[1.0]*384`,
пустой canary = доверие, сбой базлайна = доверие (fail-open).

**Статус:** ✅ FIXED 2026-08-12 (P2): fail-closed на пустой canary/сбой базлайна, абсолютный
якорь `_ABS_MIN_QUALITY` (0.5), collapse-детектор (дисперсия < 1e-3), eligible_seen в лог.

**Артефакты:**
- `exp_canary_attack.py` — 5/5 атак прошли до фикса (EXP-1, 2026-08-11).
- Тесты: `tests/test_shadow_canary.py` (13/13 — реалистичные per-pair векторы, регрессии EXP-1).

**Ссылки:** EXPERIMENTS_LOG.md (2026-08-11), KNOWN_ISSUES.md (2026-08-11 Shadow Canary).
