# RESEARCH — XERJ 2026-11 (R1–R5)

> Правило файла: утверждение о чужом коде — с `file:line` из **сегодняшнего** клона
> (`D:\Project\_reference_repos\xerj-org__xerj__main-42f4798`, sha `42f4798`);
> утверждение о нашем коде — с `file:line` из `HEAD`. Заявления самих XERJ помечены
> `Claim`, даже когда они про собственный замер. Всё, что не удалось перепроверить,
> помечено `NOT REPRODUCED` — и это часть результата, а не пропуск.
>
> Дата: 2026-11-08. Клон **shallow** (`git rev-list --count HEAD` = 1), поэтому
> «было раньше» проверить нельзя — такие места помечены.

---

## Дрейф относительно `EVIDENCE.md` (сначала это, иначе дальше читать нельзя)

| ID | Что было записано | Что сегодня |
|---|---|---|
| A14 | «их детектор устаревания — mtime-only, допуск 2 с», `xerj-autoindex/src/staleness.rs:49-51` | **NOT REPRODUCED.** Файла `staleness.rs` в `xerj-autoindex/src` нет (42 файла, `Get-ChildItem`). На его месте `source.rs:315-333`: у локальной папки `change_token = None`, потому что «the walk's own answer is a full content hash, because file metadata cannot prove byte identity across every filesystem», а `last_modified` — «never used as change identity on its own unless there is no ETag at all». То есть по этому пину они **хешируют содержимое**, а не полагаются на mtime. |
| B7/B8 | «12 000 манифестов кандидатов, 2 890 согласий», `candidates/authors/`; «аудит 2026-10-28, 5 строк» | **NOT REPRODUCED.** В публичном дереве ветки `corpus-hub` (sha `708e9745`) нет ни `candidates/`, ни `hub/audits/` (проверено обходом `git/trees?recursive=1`). Consent-конвейер снаружи не виден; схему согласия можно брать только из кода пакетов (R4). |

Следствие: два тезиса пакета ослаблены. Их «слабость freshness» больше не факт —
наоборот, они тратят больше IO на каждый прогон, чем мы. Наш `stat-first →
hash-confirm` (`src/core/indexing/freshness.py:56,120-130`) дешевле, но **не**
строже: коллизия «mtime + size» у нас возможна, у них — нет. Это разные свойства,
и заявлять превосходство нельзя ни в одну сторону.

---

## R1. Как устроен их `def`-ранкинг (и почему 94%)

Прочитано: `engine/crates/xerj-autoindex/src/def.rs:151-316, 355-481`;
`engine/crates/xerj-common/src/xccode/render.rs:292-341`.

Что делает их ранкинг (в порядке применения):

1. **Три `should`-ветки вместо одной** (`def.rs:232-263`): `term name` с boost 12
   (точное имя символа), `match_phrase defs` с boost 8 (список определений файла),
   `multi_match` по взвешенным полям как «recall floor» для обычных слов. Boost’ы
   подобраны, а их обоснование — `Claim`: «94% correct-file-at-rank-1 на 80 задачах
   против 38% для поиска по телу» (`def.rs:223-224`).
2. **Идентификатор → фраза по `code`** (`def.rs:270-274`, boost 4): `def <name>(`
   или `class <name>:` — определение даже при другом регистре.
3. **Coverage-клаузы** (`def.rs:264-269`, ссылка на их #2327): добивают случаи,
   когда слова запроса разбросаны по файлу.
4. **`minimum_should_match: 1` при наличии `filter`** (`def.rs:286-293`): без него
   `--kind`/`--lang` **один** матчил все определения этого kind. Это их же
   исправленный баг — и он того же класса, что наш «0 chunks при reindex».
5. **Ограниченное окно реранка** (`def.rs:308-316`): тянут `k + 40`, но не больше
   `max(k, 200)`, и только потом режут до `k`. Так `pub struct` чуть ниже топ-k
   может обогнать тестовый дубль, а `-k 1000` не тянет весь индекс.
6. **Demoted paths** (`def.rs:361-370`): `tests/`, `examples/`, `fuzz/`, `benches/`
   на любой глубине получают **×0.5 к `_score`**, а не удаляются. Комментарий
   прямо объясняет выбор: файл, который «едва обошёл» реализацию, уезжает назад;
   файл, набравший вдвое больше, остаётся первым — значит, вопрос был про тест.
7. **Реранк по kind и видимости** (`def.rs:440-462`): +20 предпочитаемому kind
   (кроме demoted), +5 публичному объявлению (`pub`/`public`/`export`, разбиение по
   не-буквам, чтобы `publication` не считался).
8. **Demote sparse hits** (`render.rs:292-341`): если в запросе ≥ `MIN_TERMS_FOR_COVERAGE`
   термов и хоть один хит покрывает ≥2 терма, то хиты, чьё имя совпало с **одним**
   термом и чей текст покрывает тоже **один**, уезжают в конец. Ровно то, что у нас
   вылезло в живом прогоне: на «where is build_call_graph defined» в топ попали
   `_v_defined_in` и `test_decorates_skips_undefined_symbol`.

**Берём (по убыванию отношения польза/риск):**

- (a) demote sparse/one-word hits — у нас такой же шум, доказательство в сыром
  ответе (`baseline_raw.txt`, P01: `_v_defined_in` в топ-3). Реализуется без нового
  инструмента, только порядком в существующем мердже.
- (b) demoted-path ×0.5 для `search_code`/`investigate` (не фильтр!), чтобы
  `tests/` не выигрывал у `src/` по совпадению имени.
- (c) bounded rerank window: тянуть `limit+40` из каналов и резать после мерджа.
  Сейчас `limit` применяется **внутри** канала — то есть окно уже, чем нужно.

**Отвергаем:** 50 query types / 63 агрегации (по `PLAN.md` — источник большинства
их свежих багов); Elasticsearch-специфичные mapping/clauses; перенос их движка.

---

## R2. Честный ETA: диапазон + базис вместо одного числа

Прочитано: `xerj-autoindex/src/estimate.rs:1-80, 255-281, 426-470`.

Их правило (`estimate.rs:1-8`): «never state a number we did not measure here»;
результат — **диапазон с указанием базиса, либо ничего и объяснение почему**.

Формула (`estimate.rs:33-43`), классическая оценка makespan (Graham, 1969):

```
low  = max(Σ work_i / W, max work_i)
high = Σ work_i / W + (1 - 1/W) · max work_i
```

где `work_i = bytes_i / rate_family`, а `rate_family` — измеренная на **этом**
прогоне скорость фазы A. Оба конца — арифметика над измеренным, без «коэффициента
на глаз». Поля ответа (`estimate.rs:258-281`): `kind` (константа
`client-side-extraction-floor`), `low_seconds`/`high_seconds` (могут быть `None`),
`basis`, `workers`, `planned_files`, `planned_bytes`, `covered_bytes`, `coverage`,
`unmeasured_families`, `excludes`. Явно сказано, что это **floor**, а не прогноз:
замер на 68 MB дереве дал floor 0.1 s против реальных 8.9 s, ~2% — потому что
доминируют транспорт и сервер, а не клиентский разбор (`estimate.rs:57-62`).

**Наш ETA** (`src/core/eta_predictor.py:71-99`): `base_ms + per_item_ms × items`,
смешанное 30/70 с историей измерений, `confidence: low|medium|high`; одно число,
без диапазона, без `basis`, без покрытия. В телеметрии — `reindex_eta_sec`
(`src/core/intelligence/layer.py:471`), тоже одно число.

**Берём:** не формулу (нам нечего делить по «семействам»), а **форму ответа**:
рядом с `reindex_eta_sec` печатать `basis` и метку `floor`, а при отсутствии
измеренной скорости — `None`, а не `0`. Число без базиса агент читает как обещание.

**Отвергаем сейчас:** сам расчёт диапазона — нужны измеренные скорости по фазам,
а `wait_reason` даёт только текущее звено (`src/core/indexing/wait_state.py`).
Это следующий шаг, не сегодняшний.

---

## R3. «Успех-обманка»: 4 подкласса из их issue + наш ответ

Прочитано (`gh api`, сегодня): #3021, #3005, #3020, #3015.

| # | Подкласс | Что именно | Наш ответ |
|---|---|---|---|
| #3021 (open) | **Health врёт** | `GET /_facts` → 200 при `model.state: "unavailable"`; `llms.txt` велит опрашивать до `loaded`, агент ждёт вечно | `degraded[]` на уровне инструмента (`investigate_tool.py:134,203-205`), `status` в `format_index_status`; «активен» не печатается, когда индекс пуст |
| #3005 (closed) | **Плейсхолдер вместо замера** | `profile: true` отдаёт тайминги 0 или 1 нс на каждом запросе | `latency_ms` считается `perf_counter` (`src/core/error_handler.py:600`); тест «60 ms → ≥50 ms» и «разная стоимость → разные числа» (`tests/test_no_silent_success.py`) |
| #3020 (open) | **Кэш съедает замер** | повторный запрос 0.70 ms вместо 7.80 ms; бенчмарк меряет кэш | кэша ответов у нас нет; но кэши источников (`src/sources/upload/__init__.py:217`, `src/sources/git_url/__init__.py:372`) отдают результат **молча** — латентный риск того же класса, записан в KNOWN_ISSUES |
| #3015 (open) | **«Согласие» вместо проверки** | COUNT теряет «or», отдаёт неверное число с `partner_agreement: true`, потому что обе модели согласны на одной неверной программе | с 2026-11-08 `investigate` печатает `exact: <ident>=N` и предупреждает, что «результаты ниже — соседи, а не совпадения»; согласие двух не-точных каналов доказательством не считается (`tests/test_no_silent_success.py::test_agreement_between_non_exact_channels_is_not_confirmation`) |

Вывод: у нас закрыт класс «молчаливый успех» **на уровне протокола**, но он не был
ни измерен, ни опубликован — до сегодняшнего дня. Теперь есть 8 конформанс-тестов,
из которых 5 падали на коде до правки (проверено `git stash`-прогоном).

---

## R4. Провенанс и согласие в их пакетах

Прочитано: `docs/CORPUS_HUB_V2_IMPLEMENTATION.md:61-124`, `docs/CORPUS_PACKS.md`
(в клоне, до строки 60 и раздел про recipe), `hub/llms.txt` (B4).

Схема (`CORPUS_HUB_V2_IMPLEMENTATION.md:69-124`):

```
LicenceClass      = adapt-with-attribution | approach-only | excluded   (kebab-case)
CatalogueEntry    = slug, domain, topics, ask_for, pin_sha (40-hex), pin_date,
                    refresh_cadence_days, licence_spdx, licence_class,
                    pack_bytes, pack_url, pack_sha256, sig_url, dependency_names,
                    quality_grade (None — «never invent one»), term_sketch
PackManifest      = format_version, slug, pin_sha, pin_date, built_at,
                    builder_version, index_prefix, indices, snapshot_name,
                    licence_spdx, licence_class, sources[], defs_count, files_count
PackSource        = { repo, url, sha, licence }
```

Чего в схеме **нет**: ни `consent.at`, ни `receipt`, ни `scope`, ни `revoke`.
`CORPUS_PACKS.md` прямо говорит: «Licence terms ride along as record data; the tool
does not enforce them — the pack author owns what goes in a pack». Единственный
механизм отзыва — `licence_class = excluded` → пакет не собирается и уходит из
каталога (`:690`), то есть отзыв = пересборка, а не пометка внутри артефакта.
Подпись (`ed25519`) доказывает, **кто собрал**, а не **на каком основании**.

**Берём для наших будущих экспортов (когда появятся):**

- `pin_sha` + `pin_date` обязательны, `licence_spdx` **плюс** текст `LICENSE` в пакете;
- отдельный блок `consent: {at, channel, receipt_ref, scope, revoke_route}` —
  ровно то, чего у них нет; без него «согласие» неотличимо от «промолчал»;
- `quality_grade: None`, если не измерено (их же правило — «never invent one»).

**Отвергаем:** хранить согласие только в переписке (наш нынешний `DECISION.md` —
это решение, а не запись consent для артефакта).

---

## R5. Дыры в нашем покрытии тестами этих классов

Проверено `git grep` по `tests/`:

| Класс | Есть | Нет |
|---|---|---|
| пустая популяция → отказ | `tools/verification/heldout_g5.py:48` (exit 2), `scripts/check_write_bytes.py`, новый `test_empty_population_refuses…` | — |
| недоступная зависимость → `degraded` | `tests/test_context_sections.py`, `test_error_envelope_wiring.py`, `test_health_report.py` | нет теста, что `investigate` **не** печатает «ничего не найдено», когда канал упал (сейчас печатает `degraded` и всё) |
| плейсхолдер вместо замера | новый `test_latency_comes_from_a_clock` | тайминги `wait_reason` (`elapsed_ms`) не проверяются на «не ноль» |
| согласие ≠ доказательство | новый `test_agreement_between_non_exact_channels_is_not_confirmation` | — |
| TOCTOU (stat → hash) | `tests/test_freshness_checker.py` | файл меняется **между** stat и hash — отдельного теста нет |
| две параллельные verify на одном проекте | `tests/test_database_lock*.py`, `test_index_runner_deadlock.py` | именно `verify()` × 2 — нет |

Этот список — вход в I3 (`benchmarks/agent_query/`) и в `KNOWN_ISSUES.md`.
