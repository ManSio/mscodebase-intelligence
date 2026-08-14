# MSCodeBase Intelligence — Field Notes

> Серия статей-полевых заметок о реальных экспериментах, багах и архитектурных
> решениях при разработке [MSCodeBase Intelligence](https://github.com/ManSio/mscodebase-intelligence).
> Каждая часть — самостоятельная история с воспроизводимыми цифрами; вместе они
> образуют нарратив: контекст → данные → доверие.

## Части

| # | Статья | Тема | Статус |
|---|--------|------|--------|
| Side Quest | [Zed threads.db](zed-threads-db-reverse-engineering.md) | Платформа: формат AI-чат-БД Zed (zstd + JSON v0.3.0) | published |
| 1 | [PageRank Token Savings](pagerank-codebase-myth.md) | Граф → контекст: PageRank vs RAG, Hit@Gold (+14pp/46%) | published |
| 2 | [Silent Vector Contamination](silent-vector-contamination.md) | Concurrent-эмбеддинги: 0 ошибок, чужие векторы | published |
| 3 | [Verify-on-Read](verify-on-read.md) | Память агента: честный UNKNOWN vs структурная догадка | published (dev.to) · source-material локально |

## Как читать серию

- **Side Quest → 1 → 2 → 3**: от платформы к доверию к памяти агента.
- Экспериментальная база всех частей — `EXPERIMENTS_LOG.md`; архитектурные решения — `docs/adr/`.
- Часть 3 продолжается: Experiment 1-M (manifest-anchoring, закрыт) и 1-L (30-day longitudinal, дизайн) — см. `experiments/`.

## Связанное

- RFC-проект верификации (OWP v0.4 + Threat Model TC-1..10): `experiments/owp_rfc_001_v04.md`
- Черновик для GitHub Discussion: `experiments/owp_github_discussion_draft.md`
