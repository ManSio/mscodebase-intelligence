# Поисковый пайплайн — текущий контракт

> **Актуально на 2026-10-25.** Дефолтный runtime — Phase 3 text-first:
> SQLite FTS5/BM25 плюс PropertyGraph. Dense, LanceDB и reranker-стадии
> опциональны и выключены без конфигурации. Документ описывает реальный
> дефолтный путь, а не старый pipeline как будто он всё ещё основной.

---

## 1. Контракт

Вход:

- natural-language или identifier query;
- `mode`: `fast`, `quality`, `deep`, `context`, `ask`, `auto`;
- опционально `layer`, `intent`, `limit`, `explain`.

Выход:

- ранжированные chunks/files с metadata (`file`, `chunk_index`, `symbol_name`,
  `symbol_kind`, `layer`, line range, source);
- stale-index banner, если freshness check не прошёл;
- опциональные security metadata для недоверенного контента.

Агент может передать `intent="docs"` или `intent="code"`. Если `intent` пуст,
tool сравнивает лучший docs-only BM25 score с лучшим code score и уходит в
docs-канал, когда разрыв больше `MSCODEBASE_DOCS_MARGIN` (default `4.0`).
LLM в этом решении нет.

## 2. Дефолтный Phase 3 путь

```text
query
  │
  ├─ normalize / optional RU synonyms
  │
  ├─ SQLiteChunkStore.search(query, limit=20..50)
  │     └─ FTS5/BM25 по chunk text, symbol_name, docstring, file_path
  │
  ├─ если query похож на identifier/path:
  │     └─ PropertyGraph stage добавляет exact symbol/file candidates
  │
  ├─ optional on-demand rerank (только если настроен)
  │
  ├─ exact-name boost
  ├─ symbol deduplication
  │
  └─ return top-N
```

SQLite path намеренно короче исторического LanceDB pipeline. В частности, по
умолчанию он **не** запускает RRF над BM25+dense+graph, MMR, co-change boosts
или P3 module-head anchors. Эти стадии живут в опциональном dense/LanceDB path
или в старых путях.

## 3. Источники candidates

### 3.1 SQLite FTS5/BM25

`SQLiteChunkStore.search` строит FTS5 `MATCH` из терминов запроса (OR, quoted),
ранжирует через SQLite `bm25()` и возвращает:

- chunk text и full text;
- file path, chunk index, symbol name/kind, docstring, layer;
- start/end line;
- `final_score` из BM25 rank.

Таблица content-linked (`content='chunks'`) с insert/update/delete triggers:
удаление файла удаляет и его FTS rows.

### 3.2 Symbol и path signals

Identifier-shaped запросы (`snake_case`, `CamelCase`, paths, `::`) получают
детерминированный graph stage. Граф возвращает exact definition/reference rows,
которые FTS может поставить ниже generic text matches. Дубликаты убираются по
`file + chunk_index`.

### 3.3 Канал документации

`Searcher.search_docs()` использует тот же FTS5 store и оставляет только
`docs/**`. Он схлопывает языковые варианты (`docs/en/X`, `docs/ru/X`,
`docs/zh/X`) в один ключ, предпочитая язык запроса. Это отдельный канал, а не
изменение ranking кода.

### 3.4 Опциональный dense/vector path

При `MSCODEBASE_DENSE_OFF=false` и доступном provider vector search идёт через
LanceDB или настроенный backend. Этот путь может добавлять candidates, но не
требуется для дефолтного контракта.

## 4. Ranking и fusion

Дефолтный Phase 3:

1. BM25 order из SQLite.
2. Graph candidates добавляются для identifier queries.
3. Опциональный on-demand rerank top pool.
4. Exact-name boost для identifier queries.
5. Deduplicate by symbol.

Опциональный/исторический path:

- reciprocal rank fusion BM25, dense и FTS5;
- bucket weighting по intent и типу файла;
- co-change и exact-symbol boosts;
- non-code demotion (`tests/`, `docs/`, `experiments/`, `fixtures/`);
- MMR diversification;
- identifier anchors и P3 module-head anchors;
- multi-provider reranking.

Эти стадии конфигурируемы и применяются не к каждому запросу. Не используйте
старое описание pipeline, чтобы предсказать дефолтный порядок результатов.

## 5. Маршрутизация документации

Это одно дешёвое сравнение:

```text
docs_max = лучший BM25 score среди docs/**
code_max = лучший BM25 score среди src/**, tools/**, scripts/**, tests/**
if docs_max - code_max > MSCODEBASE_DOCS_MARGIN:
    use search_docs()
else:
    use code search
```

Свойства:

- один дополнительный FTS-запрос; без вызова модели;
- explicit `intent` важнее эвристики;
- threshold настраивается и подобран на панели 48 запросов;
- code-запрос с сильной docs-лексикой всё ещё может уйти в docs;
  `intent="code"` — escape hatch.

На панели margin `4.0` дал 0 code false positives, docs top-1 в 5/8 docs-вопросов
и 0.792 same-basename hit@1 overall. Это результат панели, не универсальная
константа.

## 6. Режимы

| Mode | Путь | Для чего |
|---|---|---|
| `fast` | FTS5 + optional dense; без reranker | Exact names, известные пути, latency |
| `quality` | Дефолтный hybrid path + optional rerank | Обычные code/doc вопросы |
| `deep` | Quality + graph context expansion | Cross-module investigation |
| `context` | Similar-code search по фрагменту | Поиск похожих реализаций |
| `ask` | Retrieval + optional local LLM generation | Только при настроенном LLM profile |
| `auto` | Выбор режима по форме запроса | Дефолтный вход tool |

`fast` заметно менее точен на смешанных natural-language вопросах, чем
`quality`, на внутренней панели (0.542 vs 0.688 hit@1). Используйте осознанно.

## 7. Опциональные слои

| Слой | Флаг / условие | Эффект |
|---|---|---|
| Dense retrieval | `MSCODEBASE_DENSE_OFF=false` + provider | Добавляет vector candidates |
| On-demand rerank | `MSCODEBASE_ONDEMAND_RERANK=true` + provider | Re-score top candidates |
| P3 module-head anchors | `MSCODEBASE_P3_ANCHOR=true` | Добавляет module-head chunks |
| RU synonyms | `MSCODEBASE_RU_SYNONYMS=true` | Расширяет Russian query variants |
| Non-code demotion | `MSCODEBASE_DEMOTE_NON_CODE=true` | Понижает tests/docs/experiments |
| Intent-aware demotion | `MSCODEBASE_DEMOTE_INTENT_AWARE=true` | Оставляет docs для docs intent |
| Docs auto-route | `MSCODEBASE_DOCS_MARGIN` | Выбор docs/code канала |

## 8. Контракт выдачи

Каждый результат несёт достаточно metadata для объяснения:

- `file`, `chunk_index`, `start_line`, `end_line`;
- `symbol_name`, `symbol_kind`, `layer`;
- `final_score` и `source` (`sqlite_fts5`, `graph`, `docs_fts`, ...);
- опционально `docstring`, callers/callees, security flags.

Ответ tool может содержать stale-index warning. Warning — не ошибка поиска; он
означает, что агенту стоит обновить индекс до того, как доверять свежести.

## 9. Измеренное поведение

Внутренняя панель: 48 реальных запросов, clean index, `experiments/**`
исключён, граф присутствует.

| Путь | hit@1 | hit@5 |
|---|---:|---:|
| Code, quality | 0.825 | 0.900 |
| Docs, exact path | 0.000 | 0.125 |
| Docs, same basename | 0.750 | 0.750 |
| Overall quality | 0.688 | 0.750 |
| Overall auto docs route | 0.792 | 0.875 |
| Fast | 0.542 | 0.729 |

Границы:

- это внутренняя, не универсальная панель;
- docs exact-path занижает корректные переводы;
- ни одна статическая конфигурация и ни один протестированный локальный
  reranker не дали 95% hit@1;
- two-channel repo map дал около 40/62/73% gold-file coverage на 1k/2k/4k
  токенов при идеальном routing; PageRank отдельно — ниже.

## 10. Отладка поиска

```text
debug_runtime_passport()
intel_get_runtime_status()
codebase(action="index", path="status")
search_code(query="...", explain=true)
```

Полезные проверки:

1. `chunks.db` не пуст? Если пуст — `scripts/reindex_text_only.py`.
2. `graph.db` пуст? — `scripts/rebuild_graph.py`.
3. Запрос похож на docs? Попробуйте `intent="docs"` / `intent="code"`.
4. Сравните exact-path и same-basename, прежде чем называть docs-результат
   промахом.
5. Для `fast` vs `quality` прогоните один запрос в обоих режимах.

## 11. Non-goals

- LLM-router на каждый запрос. Routing лексический и дешёвый.
- Статическая repo map вместо итеративного поиска. Это context selection, не
  оракул.
- Заявлять 95% retrieval accuracy по маленькой внутренней панели.
- Прятать пустой граф или stale index за уверенным ответом.
