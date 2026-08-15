# Late Enrichment — late code chunking (WS3)

**Проблема:** обогащение результатов поиска метаданными (imports, вызовы) на этапе индексации
vs позднего обогащения при запросе.

**Статус:** 🟡 исследование (2026-08-08): late-enrichment за флагом `MSCODEBASE_LATE_ENRICHMENT`;
**находка:** imports=0.0 на поисковых чанках (~186 ток/чанк) — см. KNOWN_ISSUES.

**Артефакты:**
- `bench.py` — замер фаз (chunks/imports) по реальным чанкам проекта.

**Ссылки:** EXPERIMENTS_LOG.md (2026-08-08 WS1-WS6), AGENT_DIARY.md (2026-08-08), KNOWN_ISSUES.md.
