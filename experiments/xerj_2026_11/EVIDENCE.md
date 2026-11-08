# EVIDENCE — реестр фактов сессии 2026-11-08

> Правило: число/утверждение живёт здесь, только если его можно получить **сегодняшней командой**.
> `Verified` — выполнено в этой сессии. `Recalled` — по памяти/из пересказа, не проверять как факт.
> `Claim` — заявление XERJ, не нами измерено.

## A. XERJ: состояние и движение

| # | Утверждение | Статус | Источник / перепроверка |
|---|---|---|---|
| A1 | Репозиторий создан 2026-06-30, 18 594 звезды, 1 373 форка, 147 открытых issue+PR | Verified | `gh repo view xerj-org/xerj --json createdAt,stargazerCount,forkCount,openIssuesCount` |
| A2 | Релизы rc.1 (2026-07-08) → rc.102 (2026-11-07), 101 v-релиз | Verified | `gh release list -R xerj-org/xerj --limit 400` |
| A3 | 4 173 коммита; 772 коммита за 2026-10-20…11-08 | Verified | `gh api 'repos/xerj-org/xerj/commits?per_page=1' -i` (link last page); постраничный обход |
| A4 | 14 450 скачиваний v-бинарей, 45 176 всех ассетов | Verified | `metrics/release-downloads.jsonl`, последний снапшот |
| A5 | 24 MCP-тула с hub-ключом, 21 без; схемы = 62 373 B | Verified | `landing/docs/agents/schemas/mcp-tools.json` |
| A6 | #1791 «symbol + call graph», создан 2026-10-19, **rank 7/10, 7.6**, open | Verified | `gh api repos/xerj-org/xerj/issues/1791` |
| A7 | #1793 «сессии как память», rank 9/10, **closed completed 2026-10-29**, зашиплено в rc.101 (05.11) | Verified | `.../issues/1793`; CHANGELOG rc.101, строки 312-315 |
| A8 | 1.0-шортлист: 10 пунктов, зашиплен **1** (#1793) | Verified | `ROADMAP.md`, блок «1.0 feature shortlist» |
| A9 | Их #3016: RRF ниже kNN на −0.057 nDCG@10 (p≈0.0001) | Claim (их замер) | issue #3016 |
| A10 | Их #3015: count теряет «or», отдаёт неверный ответ с `partner_agreement:true` | Claim (их issue) | issue #3015 |
| A11 | Их #3021: `GET /_facts` = 200 при `model.state: unavailable` | Claim (их issue) | issue #3021 |
| A12 | Их #3036: `PUT /_bulk` → 405, ломает `elasticsearch-py helpers.bulk` | Claim (их issue) | issue #3036 |
| A13 | Их `xerj-logs` не вызывается из non-test кода | Verified | `xerj-common/src/config.rs:1504`; ROADMAP «wire it or remove it» |
| A14 | ~~Их детектор устаревания — mtime-only, допуск 2 с~~ → **REFUTED 2026-11-08** | Not reproduced | Файла `xerj-autoindex/src/staleness.rs` нет (42 файла, `Get-ChildItem`). `source.rs:315-333`: локальная папка → `change_token = None`, «the walk's own answer is a full content hash, because file metadata cannot prove byte identity», `last_modified` — «never used as change identity on its own». То есть они хешируют содержимое. Подробно: `RESEARCH.md` → «Дрейф». |
| A15 | Их клиент считает 200 = «Query-1 доступна» | Verified | `xerj-autoindex/src/facts_rows.rs:480-483` |
| A16 | Их `--help` признаёт футган «data/ внутри индексируемого дерева» | Verified | `xerj-server/src/main.rs:374-375` |
| A17 | 21 из 101 релиза открывается словами про честность/тишину; `silent` 131 раз | Verified | `CHANGELOG.md`, подсчёт регуляркой (см. `check_evidence.py` — не проверяет, ручной) |
| A18 | Публикуемая сборка не воспроизводится из public `main` (private tree, format 3 vs 4, проприетарные крейты) | Verified | CHANGELOG rc.102, «Provenance» |
| A19 | Внешней дискуссии не найдено: HN 1 story / 3 балла / 1 комментарий | Verified | `hn.algolia.com/api/v1/search?query=xerj` |

## B. Письмо и Corpus Hub

| # | Утверждение | Статус | Источник / перепроверка |
|---|---|---|---|
| B1 | Коммит `64215b1` существует, 2026-10-03, 64 файла, +6382/−504 | Verified | `git show --stat 64215b1` |
| B2 | «39 files, about 4,700 lines, Python» = 39 `.py`, **+4155/−503** | Verified | `git show --numstat 64215b1` |
| B3 | Цитата из письма дословно есть в теле нашего коммита | Verified | `git log -1 --format=%B 64215b1` |
| B4 | Наш репозиторий **не** в хабе: 0 совпадений в `hub.xerj.org/llms.txt` (559 корпусов) | Verified | `Invoke-WebRequest https://hub.xerj.org/llms.txt` |
| B5 | Нет пака `mansio*` в релизах, нет строки в `CONTRIBUTORS.jsonl` | Verified | `gh release list`; `CONTRIBUTORS.jsonl` (ветка `corpus-hub`) |
| B6 | Конвейер: PR #2895 «10 044 repos … generated daily by the outreach pipeline» | Verified | `gh api .../pulls/2895` |
| B7 | ~~12 000 манифестов кандидатов, 2 890 записей согласия (≈24%)~~ → **NOT REPRODUCED 2026-11-08** | Not reproduced | В публичном дереве `corpus-hub` (sha `708e9745`) нет ни `candidates/`, ни `hub/` (обход `git/trees?recursive=1`). Consent-конвейер снаружи не виден. |
| B8 | ~~Аудит 2026-10-28: 5 строк…~~ → **NOT REPRODUCED 2026-11-08** | Not reproduced | `hub/audits/` отсутствует в публичной ветке; в клоне остаётся только `docs/CORPUS_PACKS.md` и код пакетов. |
| B9 | #3002: страница утверждала «with the author's permission», автор сказал обратное | Claim (их issue) | issue #3002 |
| B10 | Пак несёт `licence.spdx` + класс, но не текст copyright/LICENSE | Verified (по формату и коду) | `docs/CORPUS_PACKS.md`; `xerj-hub/src/ask.rs` (LicenceClass) |
| B11 | Заголовки письма (DKIM/Return-Path) не проверены | **не проверено** | нет доступа к исходному .eml |

## C. Наша сторона (проверено в этой сессии)

| # | Утверждение | Статус | Источник |
|---|---|---|---|
| C1 | `build_call_graph` / `get_impact_analysis` есть в коде | Verified | `src/core/indexing/symbol_index.py:548,684` |
| C2 | Тесты доказывают callers/callees/depth/impact | Verified | `tests/test_symbol_index_call_graph.py:148-208` |
| C3 | Наш freshness = stat-first → hash-confirm | Verified | `src/core/indexing/freshness.py:56,120-130` |
| C4 | Артефакты вне проекта | Verified | `src/core/artifact_paths.py:24` |
| C5 | `degraded[]` в ответе `investigate` | Verified | `src/mcp/tools/investigate_tool.py:134,203,205,315` |
| C6 | T10-гвард: `sys.exit(2)` на пустой популяции | Verified | `tools/verification/heldout_g5.py:48` |
| C7 | 774 коммита, первый 2026-07-18 (squash), тегов/релизов/PyPI нет | Verified | `git rev-list --count HEAD`; `gh release list`; pypi 404 |
| C8 | ~~`pyproject.toml` рекламирует 57 tools при FACTS 69; classifiers 3.10–3.12 при `>=3.14`~~ → **FIXED 2026-11-08** | Verified | `python experiments/xerj_2026_11/check_metadata.py` → 6/6 PASS: «69 MCP tools», classifiers = `['3.14']`, `requires-python = ">=3.14"`, mojibake 0. Исходное расхождение закрыто коммитами `aa96f96`/`f6c234c`. |
| C9 | Наш репозиторий создан 2026-06-22 | Verified | `gh repo view ManSio/mscodebase-intelligence --json createdAt` |
| C10 | `investigate` терял grep-канал на своём же репозитории: 23.0 s, `degraded: grep:timeout` | Verified → fixed | До: MCP-вызов 23019 ms с `degraded: grep:timeout`. Причина: `grep_tool._search` парсил tree-sitter'ом **каждый** файл даже при нуле совпадений. После prefilter — 7.2–8.1 s in-process, канал не деградирует (`bench_investigate.py`). |
| C11 | «`partner_agreement` = 0 совпадений в `src/`» перестало быть правдой из-за нашей же правки | Verified | Токен попал в docstring `investigate_tool.py`; заменён на `missing_widget`, `git grep` = 0. Иначе negative-контроль N01 измерял бы наш собственный текст. |

## D. Что из этого **не** доказано

- Что «мы были первыми в мире» — squash убил историю до 2026-07-18.
- Что молчание в ответ на письмо = согласие — обратного пути в публичном коде нет.
- Что их reconcile-путь (в отличие от staleness-детектора) не использует хеши — не читал.
- Что наши callers точнее их — у них кода нет, сравнивать нечего; нужен E2.
