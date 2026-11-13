# KNOWN_ISSUES — архив 2026-11

> Закрытые записи, перенесённые из `KNOWN_ISSUES.md` по гейту (≤300 строк).
> Формат записей не меняется; ссылки на них — по дате и заголовку.

---
## 2026-11-11 — `smoke_e2e` шаг 4 требует dense-индекс, дефолт репозитория — текстовый — 🟢

- **Измерено:** `python scripts/smoke_e2e.py --project .` → шаг 4
  `❌ search error: There is no vector column in the data. Please specify the
  vector column name for vector search`; `.mscodebase/` содержит только
  `chunks.db`, потому что индекс собран `scripts/reindex_text_only.py` при
  `MSCODEBASE_DENSE_OFF=true` (дефолт проекта).
- **Не регресс:** шаг не зависит от `_abstains`; `--services-only` проходит
  (`embed dim=768`, `rerank top=1`).
- **Fix:** шаг пробует вектор и при его отсутствии честно падает в текстовый
  индекс SQLite (`chunks_fts`), называя режим в отчёте. Проверка:
  `python scripts/smoke_e2e.py --project .` → `✅ SMOKE E2E: PASSED (проверок: 4)`,
  шаг 4 `режим=text (vector: …); term=…, results=3`.
---
## 2026-11-11 — 4 slow-теста LSP/VFS не проходили на `main` — 🟢

- **Измерено (не наш регресс):** на `origin/main` (`74191a5`) падали
  `tests/test_lsp_vfs_indexing.py::TestLSPVFSIndexing::test_lsp_vfs_content_indexed_without_disk`,
  `…::test_lsp_vfs_content_beats_disk`, `…::test_indexed_at_timestamp`,
  `…::test_hash_based_on_content_not_disk` — все с
  `ValueError: Indexer requires an explicit WorkspaceSource`.
- **Причина:** тесты конструируют `Indexer` без `source=`, а API требует
  explicit `WorkspaceSource`; маркер `slow` исключён `addopts`, поэтому дрейф не
  видел ни pre-commit, ни CI.
- **Fix:** тестовый хелпер передаёт `LocalFsSource(project_path)`; проверка
  `python -m pytest tests/test_lsp_vfs_indexing.py -o addopts="" -q` → `4 passed`.
  Полный прогон с slow: `pytest tests/ -m "not integration and not benchmark"` →
  `2560 passed, 10 skipped`.
---
## 2026-11-09 — RU→EN: перевод сильнее dense; ревью поймало 2 ложных доказательства — 🟢

- **Замер (12 вопросов, 2 репо):** RU-лексика 2/12, слепой EN-перевод 12/12,
  dense 768 8/12, перевод без реранка 12/12 за 14 мс — `ru_vs_dense/REPORT.md`.
- **После ревью:** матчер gold считал тест-файл реализацией (C 9→8); `dense_score
  is not None` всегда истинно → `>0`; negative control был литералом → проверяет
  текст и падает. Guard: `matcher_selftest.py`, `negative_control.py --arm A|C`.
- **Границы:** hard subset = 1/12; старые 4/5 и 5/5 superseded.
- **Gate-долги:** WISDOM test count обновлён (2317 collected). K3 `P-006` был не
  ошибкой реестра, а устаревшим путём гейта: протокол v2 перенёс реестр в
  `agent_docs/pitfalls-registry.md`, а гейт читал старый `skills/...`. Исправлено
  в `tools/knowledge/check_knowledge.py` (оба пути, новый первым; K7 читает таблицу).

---
## 2026-11-08 (позже) — четыре «открытых пункта» закрыты, найден дефект frozen-gold — 🟢

Продолжение записи ниже: по каждому пункту — внешний источник, атака, замер.

- **callers был спор о gold, а не о инструменте.** LSP `textDocument/references`
  включает ссылки внутри файла определения (`includeDeclaration` по умолчанию
  true). Создан `frozen/gold_external_v2.json` (правило до прогона); v1 не правился.
  Вместе с двумя настоящими дефектами — grep обрезал совпадения по `limit` в порядке
  обхода, и вес grep 0.3 для reference-вопросов — rank-1 стал **3/3** против 0/3.
- **`exact: 0` больше не печатает соседей** (+ `include_neighbours=true`). Отказ
  включается только при завершённом канале и неизвестном графу символе, иначе
  fail-open. 4/4 негативные задачи → 0 строк; 3 позитивных — без изменений.
- **Ложные определения:** узлы-места-вызова в графе без `kind`; предпочитаются
  `*_definition`. 54/60 → **60/60** типизированных первых хитов.
- **Зомби-потоки:** cooperative cancel через `threading.Event` каждые 16 файлов;
  отменённый скан не публикует счётчик (это нашёл red team: `0` от неполного
  скана включал отказ и прятал реальный ответ).
- **Red Team 5/5** (`experiments/xerj_2026_11/red_team.py`): границы, конкурентность,
  отказ зависимости, тихий успех, TOCTOU.
- **`check_gold.py`** нашёл невалидную задачу: E1/P03 спрашивает про
  `ModificationGuard`, которого в `src/` нет (класс — только в тесте). Задача
  заморожена по ожиданию (§19.17). Frozen не правился, P03 помечен INVALID,
  счёт пересчитан без неё: A=0.696 / B=0.652 (n=23); positive 0.667 = 0.667.

Открыто: два профиля весов по интенту (definition vs exploratory); «who raises»
фильтруется эвристикой по тексту строки, а не по типу AST-узла; отмена
проверяется раз в 16 файлов.

---
## 2026-11-08 (позже) — профили весов: второй проверен и удалён — 🟢

Гипотезы H7–H10 заморожены до прогона (`frozen/HYPOTHESES_PROFILES.md`), прогон
`run_profiles.py` на 36 задачах двух корпусов, сырьё `profiles.json`.

- `def_first` (с идентификатором): top10 **0.875**, rank-1 **0.656**.
- `exploratory`: 0.750 / 0.344 — строго хуже.
- Без идентификатора: **0.250 / 0.000 у обоих** — профили там не различаются
  (различались 30 задач из 36, но без идентификатора только 1 из 4).
- H7 CONFIRMED, H8 и H9 **REFUTED** (ожидаемо), H10 корректно проверить не удалось:
  единственная изменившаяся негативная задача оказалась невалидной.

Решение: `exploratory` удалён из кода; остались `def_first` и `references` по
интенту. Guard: `test_profiles_are_two_and_intent_driven`.

Найдено по ходу: **N03** помечен негативом, но его вопрос не содержит отсутствующего
токена (он только в колонке «Токен») — контроль измерял `Corpus`/`Hub`, которые
существуют. `check_gold.py` теперь требует токен негатива **в вопросе**.
С E1 без двух невалидных строк (P03, N03): n=22, A=0.682, B=0.682.

---
## 2026-11-08 (позже) — от чего зависит качество поиска: кривые на 70 запросах — 🟡

`experiments/xerj_2026_11/run_curve.py` (сырьё `curves.json`): 70 запросов, 3
проекта (5 / 15 / 523 файла), RU и EN, с идентификатором и без.

```
has_id=True   n=32  recall@1 0.250 → @5 0.625 → @10 0.688 → @20 0.875
has_id=False  n=8   recall@1..@20 = 0.000   (gold отсутствует и в top-40)
itsdangerous  n=12  @10 0.917 | iniconfig n=6 @10 0.667 | ours n=22 @10 0.318
RU vs EN: rank-1 0.150 vs 0.250, к k=5 выравнивается (0.550)
```

**Корень:** `hybrid_search_async` отдаёт только `source='sqlite_fts5'` — это BM25
без векторов (`MSCODEBASE_DENSE_OFF=true` — штатный режим). Поэтому у вопроса без
идентификатора нет канала «по смыслу».

**Отрицательный результат (не повторять):** кириллический keyword-канал со
6-символьным стемом для запросов без идентификатора дал **1 из 8** на no-id
задачах, а слово «переин» встречается в **98 файлах** из 523 — это шум. Канал
убран из кода; идея зафиксирована, чтобы её не строили заново.

**Открыто (решение владельца):** включать ли dense-эмбеддинги — это модель в
памяти + переиндексация 7 103 чанков. Из отдельного процесса dense не проверить:
`RemoteEmbedder.is_ready() == False`, модель живёт внутри процесса хоста.

---
## 2026-11-08 (позже) — dense-режим: размерность модели не совпадает со схемой — 🟡

Проверка «закроет ли dense no-id класс» (REPORT.md §10, `probe_dense.py`).

- llama.cpp-сервер эмбеддингов жив (`127.0.0.1:8080`), модель `embeddinggemma-2`,
  размерность ответа — **768** (проверено прямым `/v1/embeddings`).
- Векторная таблица (LanceDB) — **384**: `.env` содержит
  `EMBEDDING_MODEL=embeddinggemma-2` при `MSCODEBASE_DENSE_OFF=true`, а размерность
  в схеме осталась от прежней модели (e5-small).
- Полный dense-прогон печатает `query dim(768) doesn't match the column vector
  dim(384)` и продолжает работать частично — то есть переключение
  `DENSE_OFF=false` без переиндексации даёт не «dense», а наполовину сломанный поиск.

На маленьком англоязычном корпусе dense не дал выигрыша над BM25 (5/5 против 5/5,
ранги 2/5/1/9/9 против 6/2/3/9/1) — значит включать dense «потому что лучше» пока
нельзя; сначала размерность, потом замер на нашем корпусе.

**Fix:** `embedding_dimension` брать из ответа сервера (или из модели), затем
переиндексация; после — тот же `run_curve.py` в dense-режиме.


---
## 2026-10-25 — README rewritten; RU/ZH synchronized — 🟢
- Root `README.md`, `docs/ru/README.md`, `docs/zh/README.md` now describe the
  Phase 3 text-first runtime (SQLite/FTS5 + PropertyGraph, optional providers),
  measured quality with methodology, limitations and bug-report protocol.
- Old claims removed: LanceDB/vector as default, 65 visible tools, inconsistent
  test counts, 95% quality implication.
- Historical architecture/search docs carry a Phase 3 status banner; they are
  not silently presented as current.

---

## 2026-10-25 — E57: auto docs routing by BM25 margin (no LLM) — 🟢
- `docs_max - code_max > 4.0` -> docs channel, else code.
- same-basename **0.688 → 0.792**, docs 5/8, **0 code false positives**;
  code hit@1 0.825 unchanged; exact 0.708; p50 ~100 ms extra.
- **Реализовано:** `MSCODEBASE_DOCS_MARGIN` (4.0), `Searcher.prefers_docs()`,
  auto-ветка в `SearchCodeTool` при пустом `intent`; tests 27 pass.
- Gold canonicalization (`docs/ru/X` for `docs/en/X`) всё ещё искажает exact.

---

## 2026-10-25 — E45: structured agent plan — +1 h1, p50 72 ms — 🟢 worth API
- **План:** primary + must_include + symbols, один запрос, без multi-query RRF.
- **Результат:** baseline 0.688/0.771/79ms; plan_must **0.708**/0.771/71ms; plan_full 0.708/0.771/72ms.
- **Вердикт:** один primary + must_include — маленький реальный выигрыш; symbols не дают.
  Внедрить как опциональные поля `search_code` + tool `plan_search`. 95% не закрывает.
- **Артефакты:** `experiments/e45_agent_plan/`.

---

## 2026-10-25 — E39: Qwen3-Reranker-0.6B — 29–55 s, хуже — 🔴 rejected
- **Пилот:** 16 запросов E30; demote vs Qwen3 top10/top20 на corrected index.
- **Результат:** demote 0.625/0.688, 116 ms; Qwen3 top10 0.500/0.562, 28.9 s;
  top20 0.438/0.562, 54.8 s. H1–H6 FAIL.
- **Вердикт:** не usable на CPU; качество ниже deterministic. Reranking не рычаг.
  Deterministic 0.688/0.771/84 ms — потолок на этой панели.
- **Артефакты:** `experiments/e39_qwen3_rerank/`.

---

## 2026-10-25 — E38: BGE-reranker-base — хуже deterministic — 🔴 rejected
- **Плечи:** demote / bge_base_top10 / top20 на 48 запросах E30 (corrected index).
- **Результат:** demote 0.688/0.771, 84 ms; BGE-base top10 0.625/0.708, 3139 ms;
  top20 0.583/0.688, 6028 ms. H7 PASS (лучше MiniLM); остальные FAIL.
- **Вердикт:** generic cross-encoder out-of-domain для кода. Детерминированный pipeline 0.688/0.771/84 ms.
  Reranking не рычаг; только Qwen3-Reranker-0.6B как пилот.
- **Артефакты:** `experiments/e38_code_aware_rerank/`.

---

## 2026-10-25 — E37: chunking 32/64/128 — качество не меняется; P3 off — 🟢
- **Результат:** current/split32/split64/split128 — все h1 0.688, h5 0.771, MRR 0.713.
- Нарезка не узкое место; top-5 определяется file-level ranking. P3 off: p50 87 ms,
  качество не падает. `MSCODEBASE_P3_ANCHOR=false` по умолчанию.
- **Артефакты:** `experiments/e37_chunking/`.

---
