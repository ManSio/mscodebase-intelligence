# FROZEN — набор задач для замера `investigate` vs grep

> **Замораживается ДО первого прогона.** После первого взгляда на результаты не меняется (§17).
> Репозиторий: `D:\Project\MSCodeBase` @ `0b81a37` (2026-11-08).
> Gold-ответы получены чтением кода, а не из памяти. Любая правка gold = новый эксперимент.

## Формат

`ID | категория | вопрос | gold | must-not`

- **positive (16):** gold — минимум один `file:line`; зачёт по попаданию файла и символа.
- **ambiguity (4):** правильный ответ — **перечислить оба** места; выбор одного = провал.
- **negative (4):** в репозитории ответа нет; правильный ответ — «не найдено»; любой выдуманный `file:line` = провал.

Метрики: correctness (0/1), turns, wall time, input tokens, **negative-rate**.
Плечи: A = grep/read без MCP, B = `investigate`, C = профиль `full`.

---

## Positive (16)

| ID | Вопрос | Gold |
|---|---|---|
| P01 | Где определяется `build_call_graph` и что оно возвращает? | `src/core/indexing/symbol_index.py:548` |
| P02 | Кто вызывает `get_impact_analysis`? | `src/core/graph_rag.py:93`, `src/core/modification_guard.py:165`, `src/mcp/tools/search_tools.py:800`, `src/mcp/tools/investigate_tool.py:221` |
| P03 | Что сломается, если изменить сигнатуру `ModificationGuard`? | `src/mcp/tools/write_tools.py:379`, `src/mcp/server_tools.py:936` |
| P04 | Где решается, нужно ли переиндексировать файл? | `src/core/indexing/freshness.py:56` (`stat-first → hash-confirm`) |
| P05 | Где вычисляется путь `progress.json` вне проекта? | `src/core/artifact_paths.py:24` (`projects/<hash8>`) |
| P06 | Какая функция возвращает путь прогресса? | `get_progress_file` — `src/core/artifact_paths.py` |
| P07 | Где выдаётся и проверяется impact-токен? | `src/core/modification_guard.py:66` (TTL 600s) |
| P08 | Где в `investigate` появляется строка `degraded`? | `src/mcp/tools/investigate_tool.py:203-205` |
| P09 | Где определяется allowlist/профиль инструментов? | `src/mcp/server_tools.py:43,263` |
| P10 | Где задан профиль ETA для `impact_analysis`? | `src/core/eta_predictor.py:37` |
| P11 | Где объявлен `SymbolIndexAdapter`? | `src/core/search/graph_adapter.py:41` |
| P12 | Где считается call chain? | `src/core/indexing/symbol_index.py:353` |
| P13 | Где хранится схема `file_hash` / `file_mtime_ns`? | `src/core/indexing/db_manager.py:143-162` |
| P14 | Какой документ является каноном публичных чисел? | `docs/FACTS.md` |
| P15 | Где LSP-инструмент отправляет за ссылками? | `src/mcp/tools/lsp_tools.py:210` |
| P16 | Где описан контракт «артефакты вне проекта»? | `AGENTS.md` §0 + `src/core/artifact_paths.py:14` |

## Ambiguity (4) — нужны **оба** ответа

| ID | Вопрос | Gold |
|---|---|---|
| A01 | Где реализован `build_call_graph`? | `src/core/indexing/symbol_index.py:548` **и** `src/core/search/graph_adapter.py:597` |
| A02 | Где реализован `get_call_chain`? | `src/core/indexing/symbol_index.py:353` **и** `src/core/search/graph_adapter_pure.py:477` |
| A03 | Где считается «устаревание» (staleness)? | `src/core/indexing/freshness.py` (`FreshnessChecker`) **и** `src/core/auto_doc_updater.py:149` (`check_staleness`, другой смысл) |
| A04 | Где определён `Indexer`? | `src/core/indexing/indexer.py:37` **и** `src/core/indexing/indexer_table.py:17` (`IndexerTableMixin`) |

## Negative (4) — ответа в репозитории нет

| ID | Вопрос | Токен для проверки | Ожидание |
|---|---|---|---|
| N01 | Где реализовано «согласие партнёрской модели» (`partner_agreement`)? | `partner_agreement` | 0 совпадений в `src/` → «не найдено» |
| N02 | Где читается `XERJ_FACTS_MODEL_DIR`? | `facts_model_dir` | 0 совпадений → «не найдено» |
| N03 | Где ключ подписи Corpus Hub? | `corpus_hub_signing_key` | 0 совпадений → «не найдено» |
| N04 | Где `consensus_partner_agreement`? | `consensus_partner_agreement` | 0 совпадений → «не найдено» |

## Как считать

```
correctness = найдено gold / всего positive+ambiguity
negative-rate = ложных «нашёл» / 4
```

Порог для заявления «investigate лучше grep»: correctness_B > correctness_A **и** negative-rate_B = 0,
при 3 прогонах на задачу и одинаковой модели. Иначе — публикуем как есть, с losses.
