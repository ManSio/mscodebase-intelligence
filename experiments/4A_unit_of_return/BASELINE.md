# 4A — BASELINE (freeze template + system snapshot)

> **Правило:** НИ ОДИН прогон 4A не запускается без заполненного раздела **Freeze** ниже.
> «После» — только **дописывается** (`## Run N`), никогда не перезаписывается (Tom: удаление =
> тюнинг под уже увиденное). Каждое число в отчёте несёт referent (популяция / corpus / candidate
> set / n / judge / noise).
>
> **Frozen inputs живут ТОЛЬКО в репо:** `experiments/4A_unit_of_return/frozen/` (git-tracked).
> Хранить замороженный список в `%TEMP%`/`/tmp` **запрещено** — прецедент 2026-09-26: список E7/E11
> лежал в `%TEMP%/opencode/e11` и был удалён, verbatim-регрессия стала невозможной. Guard:
> `tests/test_frozen_inputs_tracked.py`.

## System baseline — 2026-09-26 (MSCodeBase)

| Поле | Значение |
|---|---|
| Branch | `chore/privacy-paths` (PR #49) → база для эксперимента — до мерджа ветвиться от неё |
| HEAD | `5f158ece` (после PR #49) |
| MCP RUN_ID | `45b0a471f48e` (PID 15624, state READY) |
| Index | **10 106 chunks / 716 files / 14 099 symbols** |
| Embedder / Reranker | llama.cpp 🟢 / BGE-M3 🟢 |
| Tests | `pytest tests/`: **1866 passed, 5 skipped, 0 failed** (313s) |
| Privacy guard | `tests/test_no_personal_paths.py` ✅ |

## Freeze (заполнить ДО прогона, hash-фиксация)

| Поле | Значение |
|---|---|
| Experiment | 4A unit-of-return |
| git HEAD | `<sha>` |
| Index stats до | `chunks=___ files=___ symbols=___` |
| queries file | `<path>` sha256=`<hash>` |
| populations file | `<path>` sha256=`<hash>` |
| retriever / top-k | `<заморожено>` |
| judge model + budget | `<модель> / <reasoning>` |
| n per arm | `___` |
| noise floor | измеренный повторным прогоном: `___` |
| **Prediction (Tom):** | проза: whole-doc ≤ closed book; код: нет. Если обе популяции движутся одинаково → двухпопуляционная история неверна на нашем индексе. |

## Run 1 — `<дата>` (append, не редактировать прошлое)

| Arm | reader gets | hit@1 | hit@3 | top-1-doc-is-gold | context tokens | referent |
|---|---|---|---|---|---|---|
| A | top-k chunks | | | | | |
| B | top-1 whole document | | | | | |
| C | oracle file (chunked) | | | | | |
| D | nothing (closed book) | | | | | |

- Controls passed: `__/__`
- Verdict: `<…>` (raw output referenced)
- Index stats after: `chunks=___ files=___ symbols=___` (must equal "до", иначе прогон невалиден)
