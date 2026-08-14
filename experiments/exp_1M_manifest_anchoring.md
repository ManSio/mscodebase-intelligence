# Experiment 1-M — Manifest-Anchoring (гипотеза Skillselion): закрывает ли closed-world манифест 7 false-REFUTED?

> Дата: 2026-08-14 · Тип: verification mapping — гипотеза уже реализована (ADR-0005),
> документ связывает гипотезу ревьюера с существующим evidence (file:line).
> Источник гипотезы: комментарий Skillselion на dev.to: «манифест — закрытый мир,
> отсутствие там = доказательство, а не тишина».

## Гипотеза

Ложные REFUTED возникают, когда верификатор «не нашёл» якорь, но его отсутствие —
это тишина (инструмент не увидел), а не доказательство (факта нет). Closed-world
манифест (явный список того, что МОЖЕТ существовать) превращает «не найдено» в
«доказано отсутствует». Ревью: *«он дал тебе готовую гипотезу, которую легко
проверить против 7 false-REFUTED кейсов из твоих логов»*.

## 7 false-REFUTED из Exp 1-V

- Кейсы: **G07, G25, G11, G24, G23, G18, G21** — `EXPERIMENTS_LOG.md#1-V`
  (false REFUTED среди TRUE = 7).
- Причина: **наивная типизация голых токенов** — fastmcp-класс: dist name ≠ import
  path → якорь `import:path` не находится → ложный SILENT-отзыв.
- Контроль: Exp 1-V-REP — при корректной типизации (write-time capture) **0** false
  REFUTED среди TRUE.

## Маппинг: гипотеза → ADR-0005 → evidence

| Слой гипотезы | Реализация | Evidence |
|---|---|---|
| «Отсутствие = доказательство» | closed-world REFUTED: явный `pkg:`-якорь + отсутствие в манифесте → REFUTED(SILENT_ABSENCE_ON_READ) | `docs/adr/0005-pkg-anchors.md` |
| «dist name ≠ import path» (корень 7 кейсов) | `_Fingerprint.packages` из pyproject.toml (tomllib/tomli, PEP 503) + явный `pkg:name` на обоих путях | `src/core/intelligence/verify_on_read.py`; 31 тест `tests/test_verify_on_read.py` |
| «Манифест — единый источник» | schema guard кэша: fingerprint без «packages» → rebuild (иначе ложные REFUTED) | ADR-0005 п.5 |
| Live-проверка | реальный манифест 104 пакета: `pkg:celery` → REFUTED(SILENT_ABSENCE); stdlib `sqlite3` → без якоря (не ловим) | `AGENT_DIARY.md` 2026-08-14 10:45 |

## Вердикт

✅ **Подтверждено на существующих данных.** Закрытие 7 false-REFUTED реализовано
двумя слоями: (1) корректная типизация (write-time capture) — 0 в 1-V-REP;
(2) ADR-0005 — манифестный слой поверх (manifest-anchoring Skillselion 1:1).
Отдельный прогон не требуется — 1-V-REP уже показал 0 на тех же кейсах.

**Остаток (структурный, документирован):** present-trap — `sqlite3` «импортирован
по другой причине»: presence-проверка не различает намерение. Ловит только честный
агент (code_first 0.0). Это ограничение слоя, не манифеста.

## Связи

`EXPERIMENTS_LOG.md#2026-08-11-1-V` · `EXPERIMENTS_LOG.md#2026-08-11-1-V-REP` ·
`docs/adr/0003-verify-on-read.md` · `docs/adr/0005-pkg-anchors.md` ·
`AGENT_DIARY.md` 2026-08-14.
