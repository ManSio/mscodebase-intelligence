# E-05 — ActionReceipt `reproducible_by` (ТЗ §11.5 этап 3 / §12.3 gate)

**Дата:** 2026-08-19
**Команда:** `python experiments/universal-engine/e05_action_receipt.py`
**Статус:** ✅ PASSED (4/4)

## Гипотеза (ТЗ §12.3)
> «reproducible_by воспроизводится 1:1? Или, как с temporal-git-provenance, окажется,
> что "очевидно полезное" поле на практике не работает так, как задумано»

## Метод
Реальные действия (не mock), чистое temp-окружение:
- `file_write` — запись реального файла (before/after SHA-256 реальные)
- `git_commit` — реальный git commit в чистом temp-репо
- `git_push` — реальный `git status -sb` (состояние «не опережает remote»)
- `index_sync` — INCONCLUSIVE по дизайну (verify_index_sync не выполняет реальной проверки)

Для каждого: build_receipt → ActionReceiptStore.record → store.get → выполнить
`reproducible_by` в подпроцессе → сравнить вердикт с receipt.

## Сырой вывод (хвост)
```
action       verdict      repro_verdict  result
file_write   VERIFIED     VERIFIED       PASS
git_commit   VERIFIED     VERIFIED       PASS
git_push     VERIFIED     VERIFIED       PASS
index_sync   INCONCLUSIVE INCONCLUSIVE   PASS
Store round-trip (E05-git1): PASS
E-05: 4 cases — 4 PASSED, 0 FAILED
SMOKE E-05: PASSED
```

## Находка (первый прогон: 2/4 — git_commit/git_push REFUTED)
`verify_git_commit`/`verify_git_push` хардкодили **cwd процесса** — `git log` шёл в
MSCodeBase (находил коммит 381e41bd), а не в тестовом `<repo>`. `reproducible_by`
выполнялся в другом cwd → предсказуемый mismatch вердиктов. **Root cause:** verify и
reproducible_by были рассинхронизированы по рабочей директории.

## Фикс
- `execution_contract.py`: `verify_git_commit(..., cwd=...)` + `verify_git_push(cwd=...)`
  (backwards-compatible, default None = cwd процесса).
- `action_receipt.py`: `reproducible_command(.., workdir)` кодирует `git -C "<dir>"`;
  `ActionReceipt.workdir` + `build_receipt(.., workdir)`.
- `lifecycle_tools.py`: `verify_action` резолвит project_root и передаёт в verify + build_receipt.

## Вердикт
**Гипотеза §12.3 подтверждена с оговоркой:** reproducible_by воспроизводится 1:1
(после фикса — 4/4), НО **требует явного workdir** для git-типов. Поле стало
самодостаточным (кодирует cwd). Без workdir — недетерминировано (как и подозревал §12.3).
Это подтверждает ценность E-05 как gate перед встраиванием §11 в default.

## Урок (см. AGENTS.md, раздел про Урок в EXPERIMENTS_LOG)
- Не-идеальное поле из «очевидно полезного» может молча не работать: verify в одном
  cwd, reproduce в другом — оба «выглядят правильно», но вердикты расходятся.
- E-05 с реальными действиями = единственный способ это поймать (unit-тест cwd
  процесса = текущий каталог прогона — не различает).
- Связь: KI-2026-08-11 present-trap / «очевидно полезное не обязано работать».
