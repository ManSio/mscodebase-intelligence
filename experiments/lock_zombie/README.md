# Lock-zombie — PID-lock self-healing (WS9)

**Проблема:** MCP-бут ждал DB PID-lock до 30s (fail-closed) → превышал Zed timeout → сервер
убивался, зомби оставался → вечный цикл; `_is_pid_alive` не отличал здоровый MCP от сироты.

**Статус:** ✅ Fixed 2026-08-08 (код+тесты; 1022 passed, ruff чист).

**Артефакты:**
- `benchmark_selfhealing.py` — бенчмарк: orphan 30s→**120ms**, healthy 30s→1.5s soft, free/stale без изменений. ⚠️ **Статус числа (2026-10-03):** `SUPERSEDED` — измерено на `3798d6a9`; ORPHAN-ветка вырезана из прод-MCP по R3TF, поэтому прогон больше недостижим (`experiments/claims_audit/RESULTS.md` A10 = NOT REPRODUCED). Оставлено как запись прогона, не переписано.
- `orphan_holder.py` / `spawn_orphan.py` / `zombie_probe.py` / `check_signals.py` / `probe_terminate.py` — пробы для live-теста Windows.
- Фикс: `src/core/database_lock.py` — классификация holder'а (DEAD/HEALTHY/ORPHAN/AMBIGUOUS), TOCTOU-guard, retry-unlink; тесты `tests/test_database_lock_selfhealing.py` (+17).

**Ссылки:** EXPERIMENTS_LOG.md (2026-08-08), AGENT_DIARY.md (2026-08-08), KNOWN_ISSUES.md (multi-window PID-lock).
