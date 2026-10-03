# KNOWN_ISSUES 2026-10 (архив)

Перенесено из живого KNOWN_ISSUES.md ротацией 2026-10-03 (лимит 300 строк, §8). Только закрытые записи.

## 2026-10-03 — Аудит репо на чужие данные: исторических утечек нет, риск закрыт гейтом (Closed)

- **Замер (Verified 2026-10-03, 1893 tracked-файлов).** Email-regex дал **767 совпадений, из них
  686 (89%) — ложные**: `модуль@символ.py` в трейсах вызовов (532) + `n@mcp.tool` в сниппетах (154).
  Остаток 81 вхождение / 49 уникальных — легитимное: upstream OSS-мейнтейнеры в метаданных
  зависимостей, `test@test.com`, 2 адреса владельца, 1 вендорский (`billing-support@zed.dev`).
- **Реальных чужих персональных утечек в треке: 0.** Имена 4 комментариев: **0 из 4**.
  Дословных цитат из аудируемых статей: **0**. Крупные tracked-файлы — все свои
  (`multi_rag_ablation_tasks_v3.json`, `trace_gemma.json`, `closure_walk.json`, блог-PNG).
- **Проблема была ровно одна и prospective:** `experiments/audit_devto_judgements/frozen/` —
  1 из 8 `frozen/`-папок содержала чужой сырой дамп. **Устранена:** вынесена в
  `%LOCALAPPDATA%/mscodebase/audit-cache/audit_devto_judgements/` (sha256 сохранён
  `98104210…`), в репо остался только `HANDOFF.md` (наш вывод).
- **Почему это не замечали месяцами:** правило «frozen лежит в репо» было принято один раз,
  молча, и стало фактом. 8 папок так и лежали — ни одна не содержала чужого контента,
  поэтому никто не спросил, а audits — первый случай.
- **Guard:** `scripts/check_third_party_data.py` — 10-й pre-commit гейт. R1 личный email ·
  R2 сигнатура выгруженного профиля (≥3 маркеров) · R3 объёмный дамп (advisory, не блокирует).
  Вендоренные метаданные (`fixtures/`, lock-файлы, `pyproject/package/pom/composer`) — allowlist.
  **Валидация до внедрения:** `--selftest` positive 2/2 + negative 2/2 · FP-замер `--all`
  по 1893 файлам = **0 ложных блокировок** · гейт ловит реальный инцидент (R1+R2+R3) и
  **не флажит наш собственный отчёт** (0 находок). Тесты `tests/test_check_third_party_data.py` 10/10.
  Правила: AGENTS.md §7.1a + `.gitignore` (`*_raw_fetch.*`, `*.raw.*`, `*_page_dump.*`).
- **Статус:** ✅ Closed (2026-10-03). Наследие — глобальные правила §20 в
  `%USERPROFILE%\.config\opencode\AGENTS.md`: 20.1 разделение труда, 20.2 лицензия,
  20.3 FP-ловушка, 20.4 отсутствие≠потеря, 20.5 пересказ снимает калибровки, 20.6 валидация гейта.

# Архив KNOWN_ISSUES — 2026-10

> Вынесено при ротации §4.8 R4: живой файл превысил лимит 300 строк после
> union-merge двух параллельных сессий (ours=289, theirs=249, union=367).
> Перенесены ТОЛЬКО записи без слова Open в собственном заголовке.
> Ни одна Open/P1 не перемещена.

## 2026-10-03 — Гонка между тестами маскировалась как дефект гварда (Fixed)
- **Симптом:** CI (ubuntu + windows) — `NEGATIVE CONTROLS: FAILED (broken=0, unproven=1)`, `dead_guard_classifier` помечен `[UNPROVEN]`. Локально — зелено, включая чистый checkout. Все три `fixture_digest` совпадали при ручной сверке.
- **Root cause:** `tests/test_negative_controls_runner.py` доказывал digest-pinning, **редактируя настоящую фикстуру** `scripts/negative_controls/fixtures/dead_guard.py`, и восстанавливал её в `finally`. Под `pytest -n auto` соседний воркер читал digest этой фикстуры в окне между записью и восстановлением, считал другой хэш и классифицировал здоровый гвард как `UNPROVEN`. Гвард был исправен — гонка была между двумя тестами, а триггером было **число воркеров**, а не содержимое.
- **Почему уцелел:** инцидент проявляется только при достаточном параллелизме. Все ручные проверки (совпадение дайджестов, чистый checkout, одиночный прогон) проходили — потому что проверяли байты, а не параллелизм.
- **Fix:** фикстура копируется в scratch-каталог, создаваемый самим тестом; трекаемый файл не трогается. Добавлен контроль `PROVEN` до мутации.
- **Guard:** `tests/test_no_tracked_file_mutation.py` — запрещает тесту писать через имя, привязанное к `ROOT`. Его первая версия искала `ROOT` в той же строке и **пропустила именно этот баг**; вторая собирала 0 тестов под pytest. Обе правки зафиксированы в selftest этого гварда. Тот же гвард сразу нашёл второй экземпляр: `tests/test_planted_break_gate.py` писал `results.json` из двух воркеров без атомарности → запись стала `temp + os.replace`, артефакт в `.gitignore`.
- **Класс:** P-020 (состояние, переживающее тест: чтение/запись трекаемого файла из параллельного теста).

## 2026-10-03 — Гейт был непригоден вне папки одного разработчика (Fixed)
- **Симптом:** `G5` завершался `POPULATION UNDETERMINABLE` (rc=2) в git-worktree и в чистом клоне — то есть **везде, кроме машины автора**, ради чего он и был закоммичен.
- **Root cause (два независимых):** (1) `REPO = PROJECTS_ROOT / "MSCodeBase"` — зашито **имя папки** вместо `Path(__file__).parents[2]`; (2) популяция выводилась из файловой системы, и отсутствие соседнего MSPortfolio считалось фатальной зависимостью.
- **Fix:** `REPO = ROOT` + объявленные **scope-профили** (`full` / `repo_only`). Гейт выбирает первый профиль, все корни которого существуют, и **печатает** какой и почему остальные пропущены. Покрытие публикуется только для выбранного профиля.
- **Guard:** `heldout_relocation.py` п.3 — неверный `PROJECTS_ROOT` обязан дать `rc=0` **с объявленным** `SCOPE PROFILE: repo_only`; п.3b — при отсутствии самого репозитория `rc=2` и ни одного числа. Тихий зум — хуже падения.
- **Побочно:** два кейса `heldout_g5.py` мутировали `portfolio/*`, которые вне профиля `repo_only` — и **проходили вакуумно** (rc=0 вместо блока). Переведены на `repo/*`.

## 2026-10-03 — Реестр знаний ссылался на пути другой ветки (Fixed)
- **Симптом:** при проверке на ветке `feat/…` — `K2 PATTERNS.md: guard path does not exist: scripts/audit_protocol_guards.py`. Файл существует, но **только на этой ветке**.
- **Root cause:** реестры лежали в `~/.config`, а пути, которые они называли, — в репозитории. Смена ветки обрывала половину ссылок; валидатор проверял границу файла, а не то, что строка несёт утверждение.
- **Fix:** реестры перенесены в `tools/knowledge/` рядом с гейтами и командами; `REPO` выводится из `__file__`. `run_all.py` зовёт уже версию из репозитория.
- **Guard:** сам `check_knowledge.py` (K1/K2) — ссылка вне диапазона и несуществующий guard-путь падают. Плюс: исключения реестра теперь записываются **с обоснованием**, иначе список молча разрастается.
- **Класс:** P-021 (состояние, переживающее контекст: реестр вне дерева, которое он описывает).

## 2026-09-29 — Индекс вычищен от мусора + relang: эффекта языка нет (Fixed/Closed)
- **Purge (Fixed):** 772 файла / 2152 чанка (`experiments/**/results|work`, было 20.3% индекса) удалены one-time скриптом `scripts/purge_experiment_outputs.py` (штатный prune отказал бы: 52.4% файлов > safety-guard 50%). Проверка: 0 осталось. Guard на будущее — PR #62 (`SystemArtifacts.is_experiment_output`).
- **Relang (Closed):** B×5 на чистом стеке — RU 26/80=32.5% vs EN 30/80=37.5%, CI пересекаются → эффекта языка нет. 6/16 запросов флипаются all-or-nothing (язык меняет какие, не сколько). Старый EN-замер на сломанном стеке невалиден. Артефакты: `results/f5relang/`, `f5/RESULTS_RELANG.md`.
- **PR #52 (Closed как superseded):** tier-anchor пропущен (P2 закрыт #54 в той же точке); спасены сигмоида/top-N/holdout-калибровка → PR #63. FTS-hoist+guard → PR #62.
- **Objective (Done 2026-09-29):** перемер на чистом индексе (`results/f5/objective_clean.json`) — A hit@1 4/16, hit@3 5/16, hit@10 6/16 (=), B top-1 4/16. Топ двинут на 1 запрос (шум n=16): purge значимо не повлиял.

## 2026-09-28 — silent_subprocess: STARTUPINFO ctor outside narrowed try (Fixed)
- **Локация:** `src/core/silent_subprocess.py:32-33` (S1), `:51` (S2 — unwrapped `setdefault`).
- **Симптом:** `subprocess.STARTUPINFO()` на L33 вне `try`; на экзотическом win32-билде без `STARTUPINFO` — `AttributeError` из `apply()` на импорте (S2/L51 тот же путь без обёртки; S4/L67 в безопасности — вызов внутри try).
- **Контекст:** на CPython/win32 `STARTUPINFO` всегда есть; все реальные `creationflags=`-вызывающие передают int — практический риск ≈ 0.
- **Guard:** перенести конструирование внутрь try (S1) + обернуть L51 как L67; regression-тест: monkeypatch `subprocess.STARTUPINFO = <missing>` → `apply()` не бросает.
- **Статус:** ✅ Fixed (fix `0b6ca7c4`, merge `e8811af1` = PR #56: ctor inside try + `si = None` init, `:51` wrapped like `:66-69`; `tests/test_silent_subprocess.py` 3/3 green; PR #56 CI all green). Tails (branch `fix/redteam-tails`): модуль был INERT — заведён в entry point (`src/main.py` import + `apply()` at startup, как требует docstring модуля) + TypeError-guard на не-классовый `Popen` (тестовые шимы); liveness доказан `tests/test_silent_subprocess_wired.py` (fresh-процесс: импорт `src.main` → `_APPLIED=True`, на win32 `Popen=_SilentPopen`).

## 2026-09-28 — o1_holdout_gate: hung query hangs whole gate, no timeout (Fixed)
- **Локация:** `scripts/o1_holdout_gate.py:129-156` (`_run_all`), вызов L106.
- **Симптом:** 15 запросов идут последовательно в одном loop без `wait_for`/глобального капа; один зависший `hybrid_search_async` вешает весь гейт навсегда (единственный `timeout=10` — git-rev диагностика, L99-101).
- **Guard:** per-query `asyncio.wait_for(..., timeout=120)` + timeout → fail-row (как `degraded`); regression — фейковый searcher с висящим запросом → гейт падает за ~120с, а не висит.
- **Статус:** ✅ Fixed (fix `0b6ca7c4`, merge `e8811af1` = PR #56: per-query `wait_for(timeout=120)` + `timed_out` fail-row in both gates; `tests/test_holdout_harness_timeout.py` 6/6 green incl. positive controls; PR #56 CI all green).

## 2026-09-28 — Холодный FTS-билд превышал 2s-бюджет и молча выпадал (Fixed) + _get_ext_dir указывал в src/ (Fixed)
- **FTS (c, flaky A/B):** замер — холодный `to_pandas`-билд всего индекса = **2.47s > 2.0s** `wait_for` в `engine.py:671`. Первый поиск в свежем процессе молча терял FTS-тир → пилот 18/20 vs 8/20 на тех же запросах. **Fix:** build вынесен из-под таймаута (идемпотентен, double-checked lock), 2s остались только на сам поиск (~0.05s). Guard `test_fts5_timeout_does_not_break_search` зелёный.
- **llama-пути (b):** `llama_install.py:_get_ext_dir` брал 3 `parent` от `__file__` вместо 4 → указывал в `src/`, ветка «режим разработки» была мёртвой, модели резолвились в пустой `%LOCALAPPDATA%/mscodebase/models`. На вопрос «падает или не успевает»: после простоя restart **пытается** (`idle-unload recovery`), но падал по отсутствию файлов, не по таймингу. **Fix:** off-by-one исправлен + `multilingual-e5-small-Q8_0.gguf` (132MB) докопирован из расширения в `models/` (git-ignored). Live-check `smoke_e2e.py`: **SMOKE E2E PASSED** (embed dim=384, rerank top=1, поиск по индексу).
- **Побочно (Verified, не чинено — решение владельца):** холодный топ захламлён артефактами (`judged_raw*.json`, `work/ctx_*.txt` в выдаче) — живое подтверждение индексного мусора (P2-смежное). Чистка индекса сменит ретрив-базисы.
- **Статус:** ✅ Fixed (пути + FTS-холод).

## 2026-09-27 — Import-time os.environ mutation in scripts breaks xdist workers (Fixed)
- **Симптом:** 6 plugin-тестов (`test_plugins_subprocess/registry`) падали под `-n auto` с `ModuleNotFoundError: No module named 'src'` в runner-subprocess, серийно (`-n0`) — зелёные.
- **Root Cause (Verified, бисекцией до чанка из 24 файлов):** `scripts/f5_judged_run.py` делал `os.environ.setdefault("PYTHONPATH", <EXT>)` на уровне импорта; импорт модуля в `tests/test_f5_judged_verdict.py` загрязнял весь xdist-воркер, и `setdefault(PYTHONPATH)` в `proxy.py` становился no-op с мусорным значением.
- **Fix:** side effects переехали в `_ensure_importable()`, вызываемую только из `if __name__ == "__main__"`. T3: аналогичный паттерн есть в `benchmark_search_stages.py`, `f5_retrieve_arms.py`, `live_search_audit.py` — ни один не импортируется тестами, не трогали.
- **Правило-ловушка:** скрипты с import-time мутацией `os.environ`/`sys.path` нельзя импортировать в тестах — только через `__main__`-guard.
- **Статус:** ✅ Fixed.

## 2026-09-19 тАФ E10 (search quality): full-text-╤Н╨╝╨▒╨╡╨┤╨┤╨╕╨╜╨│ + e5-╨┐╤А╨╡╤Д╨╕╨║╤Б╤Л + ╨┐╤Г╨╗ reranker 50 тЖТ REFUTED (N=10)
- **╨Ш╤Б╤В╨╛╤З╨╜╨╕╨║:** EXPERIMENTS_LOG.md#2026-09-19
- **╨Ю╨┐╨╕╤Б╨░╨╜╨╕╨╡:** ╤В╤А╨╕ ┬л╨▓╤Л╨║╨╗╤О╤З╨░╤В╨╡╨╗╤П┬╗ ╨║╨░╤З╨╡╤Б╤В╨▓╨░ (E10a full-text ╤З╨░╨╜╨║╨░ ╨▓ ╤Н╨╝╨▒╨╡╨┤╨┤╨╕╨╜╨│, e5 `query:`/`passage:`-╨┐╤А╨╡╤Д╨╕╨║╤Б╤Л ╨▓ llama.cpp-╨▓╨╡╤В╨║╨╡ тАФ ONNX/OpenVINO ╤Г╨╢╨╡ ╨╕╨╝╨╡╨╗╨╕ `_ensure_prefix`, E10c ╨┐╤Г╨╗ reranker 30тЖТ50) ╨╜╨╡ ╨┤╨░╨╗╨╕ ╨┐╨╛╨┤╤В╨▓╨╡╤А╨╢╨┤╨░╨╡╨╝╨╛╨│╨╛ ╤Б╨┤╨▓╨╕╨│╨░. ╨з╨╕╤Б╤В╤Л╨╣ ╨┐╤А╨╛╨│╨╛╨╜ (599 ╤Д╨░╨╣╨╗╨╛╨▓ / 9514 ╤З╨░╨╜╨║╨╛╨▓, 799.9s): fast hit@1=0% hit@5=50%; quality hit@1=20% hit@5=40%; baseline ╨░╨▓╤В╨╛╤А╨░ 0/50% ╨╕ 30/30%. ╨Ф╨╡╨╗╤М╤В╨░ тАФ ╨▓ ╨┐╤А╨╡╨┤╨╡╨╗╨░╤Е ╤И╤Г╨╝╨░ N=10.
- **Fix (╨┐╤А╨╡╨┤╨╛╤В╨▓╤А╨░╤Й╨╡╨╜╨╕╨╡):** ╨╕╨╖╨╝╨╡╨╜╤С╨╜╨╜╤Л╨╣ ╨║╨╛╨┤ ╨╛╤В╨║╨░╨╗╨╡╨╜ ╨║ HEAD (╨┐╨╛╨▓╨╡╨┤╨╡╨╜╨╕╨╡ ╨║╨╗╨╕╨╡╨╜╤В╨░ = ╨┐╤А╨╛╨┤); ╨╛╤Б╤В╨░╤В╨╛╨║ тАФ env-╤В╤Г╨╝╨▒╨╗╨╡╤А `MAX_RERANKER_INPUT` ╤Б default=30 (╨╜╨╡╨╣╤В╤А╨░╨╗╨╡╨╜). ╨Я╨╗╨░╤Вo ┬лpure-vector┬╗ ╨┐╨╛╨┤╤В╨▓╨╡╤А╨╢╨┤╨╡╨╜╨╛ ╨┐╨╛╨▓╤В╨╛╤А╨╜╨╛ (╤Б╤А. Exp-29 ceiling ~0.23).
- **╨б╤В╨░╤В╤Г╤Б:** тЭМ REFUTED (╨╖╨░╨║╤А╤Л╤В, ╨╖╨░╨┐╨╕╤Б╨░╨╜ ╨▓ lab exp-43). ╨б╨╗╨╡╨┤╤Г╤О╤Й╨╕╨╣ ╤Е╨╛╨┤ тАФ AST/Graph-hybrid re-ranking, ╨╜╨╡ ╤Н╨╝╨▒╨╡╨┤╨┤╨╕╨╜╨│╨╛╨▓╤Л╨╡ ╤В╨▓╨╕╨║╨╕.
