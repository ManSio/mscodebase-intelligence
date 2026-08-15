# Exp 1-M — Manifest-Anchoring (pkg:-якоря, ADR-0005)

**Проблема:** VOR имел 3 типа якорей (file/import/env); SILENT-fact trap не ловил прозу без
«import», а fastmcp-класс давал 7 ложных REFUTED (dist name ≠ import path). Решение: манифест
(pyproject.toml + requirements) как закрытый мир — отсутствие там = доказательство.

**Статус:** ✅ 11-2026-08-14 (маппинг → ADR-0005 → верификация 1-V-REP: 0 ложных REFUTED).

**Артефакты:**
- `exp_1M_manifest_anchoring.md` — маппинг гипотезы: 7 false-REFUTED [G07,G25,G11,G24,G23,G18,G21] → ADR-0005 pkg:-анкоры → evidence.
- Реализация: `src/core/intelligence/verify_on_read.py` (4-й тип якоря `pkg:`), тесты `tests/test_verify_on_read.py` (+7).
- Датасет: `experiments/1V_memory_contamination/memory_contamination_facts_v4_rep.json`.

**Ссылки:** EXPERIMENTS_LOG.md (2026-08-11/14), docs/adr/0005-pkg-anchors.md, KNOWN_ISSUES.md#2026-08-14-ADR-0005.
