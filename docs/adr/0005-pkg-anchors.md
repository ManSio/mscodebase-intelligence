# ADR-0005: `pkg:` Anchors — closed-world проверка зависимостей через манифест

**Status:** ✅ Accepted (2026-08-14, по итогам обсуждения dev.to комментария Skillselion)
**Дата:** 2026-08-14
**Автор:** агент (по итогам верификации поста «The Mechanical vs. The Semantic» и комментария про manifest-based anchoring)

## Context

ADR-0003 (Verify-On-Read) проверяет узлы памяти по якорям трёх видов: `file:`/`import:`/`env:`.
Эксперименты 1-R/1-V выявили два остаточных зазора, а обсуждение поста (комментарий
Skillselion) предложило закрыть их манифест-анкорами:

1. **SILENT-fact trap.** Утверждение «We use Celery» без ключевого слова `import` не даёт
   `import:`-якоря → INCONCLUSIVE → факт остаётся в памяти. Grep по 50K LOC даёт «тишину».
2. **Anchor typing (dist name ≠ import path).** `from mcp.server.fastmcp import ...` —
   в src-импортах `fastmcp` нет (есть `mcp`) → ложный `REFUTED` истинного факта
   (7 артефактов маппинга в Experiment 1-V: G07/G11/G18/G21/G23/G24/G25).
3. **Present-trap (частично).** `sqlite3` импортирован «по другой причине» → ложный `VERIFIED`.
   Для stdlib манифест-анкор просто выпадает из скоупа (нет записи в манифесте) — не VERIFIED.

Ключевой инсайт Skillselion: **манифест — закрытый мир**. Отсутствие зависимости в
`pyproject.toml`/lock-файле — это *доказательство*, а не тишина. Grep по исходникам
отвечает «не знаю»; манифест отвечает «нет».

## Decision

Добавить четвёртый тип якоря `pkg:` (closed-world):

1. **`_Fingerprint.packages`** — множество нормализованных имён пакетов (PEP 503:
   lowercase, `-_.` → `-`), собранных из `pyproject.toml` (`project.dependencies`,
   `project.optional-dependencies.*`, `project.dev-dependencies`,
   `dependency-groups.*`) и `requirements.txt`/`requirements-lock.txt`.
   Парсинг: `tomllib` (3.11+) / `tomli` (3.10, уже в dev-deps), fallback — строковый
   разбор. Кэш отпечатка (verify_cache.json) получает поле `packages`; устаревший
   кэш без поля пересобирается (schema guard) — иначе пустой `packages` ложно
   REFUTED'ил бы все `pkg:`-якоря.
2. **Синтаксис `pkg:X`** в тексте claim (аналог `file:path`) — создаёт `pkg:`-якорь
   на обоих путях (read/write).
3. **Write-path capture:** при `project_root` слова прозы, нормализованное имя которых
   присутствует в манифесте, становятся `pkg:`-якорями. Fail-closed: слово НЕ в
   манифесте → якорь не создаётся (нет ложного REFUTED для «мы перешли с Redis»).
   Read-path: только явный `pkg:` синтаксис (консервативно, без present-trap).
4. **Проверка:** `_check_anchor(pkg)` = нормализованное значение ∈ `fp.packages`.
   Семантика closed-world: явный `pkg:`-якорь + отсутствие в манифесте → `REFUTED`
   (`SILENT_ABSENCE_ON_READ`), теперь с реальным доказательством, а не тишиной.
5. **Семантика AND не меняется:** все якоря узла должны пройти (консистентно с file/import/env).
6. **Stdlib вне скоупа:** `sqlite3` и т.п. нет в манифесте → write-path не создаёт
   `pkg:`-якорь → INCONCLUSIVE вместо ложного VERIFIED (Skillselion: «stdlib imports
   simply fall out of scope»). Present-trap для `import:`-якорей остаётся известным
   ограничением (честный агент читает контекст).

## Consequences

- **Плюс:** fastmcp-класс false-REFUTED закрывается (dist name = имя в манифесте);
  зависимостные SILENT-claims получают проверяемый канал; closed-world отсутствие —
  доказательство.
- **Минус:** dist-name ≠ import-name остаётся для обратного направления (claim «uses
  mcp» vs dist `mcp` — ок; claim «uses fastmcp» при dist `mcp` → INCONCLUSIVE, не
  REFUTED). Это честный INCONCLUSIVE, не ложный вердикт.
- **Temporal:** при смене HEAD fingerprint пересобирается → `pkg:`-вердикты актуальны;
  устаревший кэш без `packages` пересобирается guard'ом.
- **Guard:** tests/test_verify_on_read.py — новые тесты (парсинг манифеста, found/absent,
  explicit pkg:, write-path capture, stdlib-out-of-scope, cache schema guard).

## Guard (2026-08-14): проза-«import X» — C-гибрид

Инцидент NODE-cc88d2: фраза «dist name ≠ import path» в прозе узла дала
ложный якорь `import:path` → ложный REFUTED (SILENT_ABSENCE). Live-smoke поймал,
узел восстановлен (false_retraction 0→0.125%).

Правило (оба пути, только проза): `import:`-якорь из `\bimport\s+X` /
`from X import` отбрасывается, **если** X ∈ `_COMMON_WORDS` (частые англ. слова:
path/time/data/...) **и** X отсутствует в src-импортах проекта.
- Редкие слова (grafana/celery/fastmcp) сохраняются даже без src — SILENT-детекция
  и smoke-негативный контроль (grafana → REFUTED) живы.
- Частотное слово, реально импортированное (time/os/json), сохраняется — VERIFIED не теряется.
- Явные `data.anchors` (намеренные якоря автора) не фильтруются.
- read-path: `run()` передаёт `fp.imports` (свежий на HEAD); write-path: кэш `_fingerprint_for`.
- Fail-open bias: дроп = INCONCLUSIVE (false negative дешевле false positive — вывод поста).

Тесты: +6 (tests/test_verify_on_read.py, 37 всего): drop both paths, e2e node not refuted,
keep common-in-src, keep rare-not-in-src, explicit anchors unguarded.

## Impact

| Файл | Изменение |
|---|---|
| `src/core/intelligence/verify_on_read.py` | `pkg:`-якорь: regex, `_load_manifest_packages`, `_Fingerprint.packages`, `_check_anchor`, schema guard кэша |
| `src/core/intelligence/layer.py` | docstring-обновления (file/import/env → +pkg) — код не меняется (capture уже идёт через `extract_anchors(project_root=...)`) |
| `tests/test_verify_on_read.py` | +7 тестов |
| `KNOWN_ISSUES.md` | запись о footgun'е `experiments/1V_memory_contamination/memory_contamination_verify.py` + этот ADR |
