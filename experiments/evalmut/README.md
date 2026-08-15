# Evalmut — mutation testing для eval-градеров

**Проблема:** детерминированный градер (validate_scores реранкера) имеет дыры, которые не
ловит обычное тестирование: NaN/Infinity проходят isinstance → clamp → максимальный скор.

**Статус:** ✅ 2026-08-14: mutation score 8% → **100%** (11/11 дыр с полюсностью) после фикса
(P-006: валидация типов без валидации значений).

**Артефакты:**
- `probe_evalmut_transfer.py` — 12 мутаций по каталогу evalmut (адаптация к validate_scores).
- Фикс: `src/providers/reranker/reranker_scoring.py` (math.isfinite, decline на дубликатах,
  regex-путь через validate_scores); тесты `tests/test_reranker.py` (+13).

**Ссылки:** EXPERIMENTS_LOG.md (2026-08-14), AGENT_DIARY.md (2026-08-14 15:55/16:20), KNOWN_ISSUES.md.
