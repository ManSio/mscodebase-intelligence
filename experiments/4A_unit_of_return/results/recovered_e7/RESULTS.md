# 4A — F4 (regression, recovered list) — RESULTS

**Дата:** 2026-09-26. **Вход:** `frozen/e7_HANDOUT_EN.recovered.md` (16 пунктов = 10 симптомов + 6 контролей).
**Изоляция:** пустая папка, MCP off, `--pure`, tools deny. **Сырьё:** `results/recovered_e7/run_*.txt`, `manifest.json`.

## Setup (referent)
- Модели: `opencode-go/longcat-2.0` ×5, `opencode-go/qwen3.7-plus` ×3, `opencode-go/deepseek-v4.1-flash` ×3.
- **variant: default (НЕ пинован `--variant`) — ⚠️ это конфаунд (см. ниже).**
- Контроли: must-hit {1,4,9} = точные записи; must-NONE {3,6,11} = Postgres / GPU / Safari-CSS.
- Промпт фиксирован; handout — вложение.

## Результат

| run | valid | причина |
|---|---|---|
| longcat 2,3,5 | ✅ 6/6 | — |
| longcat 4 | ❌ | `#11 → a-generated-document-is-unverified…` |
| longcat 1 | ⚠️ mangled | файл побит выводом tooling (smoke), исключён |
| qwen 2,3 | ✅ 6/6 | — |
| qwen 1 | ❌ | `#11 → a-generated-document…` |
| deepseek 1,2,3 | ❌ ×3 | `#11 → a-generated-document…` |

**Итог:** valid **5/11**; во **всех 5 валидных `#16 → NONE`** (arrival-симптом недостижим); единственный сбой — один и тот же FP.

## Вердикт

- ✅ **Качественное воспроизведение E7:** controls 6/6 в валидных; `#16 → NONE` везде; единственный режим отказа — тот же известный FP `#11 (Safari/CSS) → generated-document`, концентрированный в deepseek (0/3 valid).
- ⚠️ **НЕ числовое воспроизведение:** valid rate **5/11** здесь против ~10/11 в записи E7. Причины: (1) **variant не пинован** (у E7 был явный reasoning-уровень; здесь — дефолт), (2) один файл побит tooling'ом. Точные проценты **не цитировать** (Coin Flip: смена судьи/бюджета — конфаунд).
- ⚠️ Это **тот же список** → это регрессия, а **НЕ** generalization. Held-out (новые, не пересекающиеся симптомы) — отдельный шаг **F4b**.

## Что это значит
Список восстановлен корректно (структура и поведение совпали с E7), канал воспроизводится. Но прежде чем цитировать частоты — **пин `--variant`** и повтор, иначе валидность «плавает» (как у deepseek в E7).

## Files
- `results/recovered_e7/run_*.txt` — сырые ответы (ANSI снят).
- `results/recovered_e7/manifest.json` — модели/runs/изоляция/контроли.

## Ledger
| # | Утверждение | Источник | Статус |
|---|---|---|---|
| 1 | Список восстановлен верно (структура = E7) | эти прогоны | ✅ |
| 2 | `#16 → NONE` во всех валидных | 5/5 | ✅ |
| 3 | Единственный FP = `#11→generated-document` | все ❌ | ✅ |
| 4 | Числовое воспроизведение E7 | — | ❌ не подтверждено (5/11 vs ~10/11) |
| 5 | Held-out generalization | — | ⏳ F4b |
