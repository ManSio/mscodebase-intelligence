# PENDING_LEDGER — предложения в реестры, которыми владеет другая сессия

**Почему этот файл существует (§21.3).** `KNOWN_ISSUES.md` и `docs/archive/KNOWN_ISSUES_2026_09.md`,
`docs/archive/KNOWN_ISSUES_2026_10.md` содержат **незакоммиченные правки, сделанные другой сессией**
(проверено `git status` на 2026-10-06). Реестр принадлежит той сессие. Молчаливый двойной дневник хуже
отсутствия записи, поэтому здесь — предложение, а не правка.

Источник: `experiments/publication_audit_2026-10-06/RESULTS.md`, ветка `fix/audit-number-corrections`.

## Предложение 1 — P1, «сырьё LLM-плеча не восстановимо, числа fail-closed не перевыводимы»

**Температура:** 🟡 watching → 🔴 при попытке цитировать. **Дедлайн:** до отправки PR в портфолио.

Проблема: числа `FA` / `recall` LLM-руки (1-L live arm, август) не имеют сырья. Per-item вердикты лежали в
`<DATA_DIR>/projects/bfe9644b/experiments/live_arm_1L_progress_*.json`; каталог существует и **пуст**,
в git эти файлы **никогда не попадали** (`git log --all --diff-filter=A` по ним пуст). Уцелели: id
false-positive по моделям в `experiments/1L_live_arm/report.md` §6.2 и 833 КБ телеметрии вызовов
(`openrouter_activity_2026-08-15.csv`, 4,087 генераций — без вердиктов).

Предлагаемая формулировка записи: **числа LLM-руки fail-closed публикуются только как
`measured on <sha>, raw not retained`, либо снимаются совсем.** Детерминированная 1-V лестница
(1.0 / 0.12 / 0.16 / 0.24) перевыводится из репозитория и остаётся.

Побочно: каталог `bfe9644b/experiments/` пуст — это «мёртвый путь», и `scripts/summarize_1L_categories.py:58`
упирается в него, выходя с кодом 2. Проверено: громкий отказ, не тихий ноль. Поведение правильное,
запись нужна, чтобы никто не «оживил» его повторным запуском.

## Предложение 2 — P2, «результаты экспериментов вне контура frozen/»

**Температура:** 🟢 stable.

`tests/test_frozen_inputs_tracked.py` требует git-tracked для `experiments/**/frozen/**`, но **не**
покрывает `<DATA_DIR>/experiments/` — то есть ровно то место, где дважды терялись сырьевые прогоны
(список E7 2026-09-22, лаб E11 2026-09-22). Предложение: либо расширить контур, либо зафиксировать
правило «сырьё любого прогона коммитится в `experiments/**/frozen/` до старта».

## Предложение 3 — P2, «внутренние ссылки на несуществующие пути в реестрах»

Проверка выборочной ссылки (13+ случаев) нашла в `EXPERIMENTS_LOG.md` / `AGENT_DIARY.md` ссылки на
файлы, которых нет ни на диске, ни в истории: `experiments/context_engine/memory_contamination.py`
(переехал в `1V_memory_contamination/`), `experiments/exp2_symbols.py` и ещё 4 (в истории нет ни разу),
`experiments/bench_embed_batch.py` (переехал), `experiments/bootstrap/dynamic_trace_plugin.py`
(переехал в `src/core/`), `src/utils/paths.py` (расщеплён на `artifact_paths.py` +
`extension_paths.py`), `experiments/openrouter_activity_2026-08-15.csv` (правильный путь с `1L_live_arm/`),
`experiments/token_reduction_v3_lancedb/run_experiment_hybrid.py`, и др. Часть помечена как «удалено по
дизайну», часть — нет.

Это класс §19.11 «число/факт без воспроизводимого referent'а». Предложение: один проход по реестрам с
заменой битых ссылок на `файл @ sha` либо на `SUPERSEDED (путь удалён, <sha>)`.

## Что НЕ предлагается

Правки в `KNOWN_ISSUES.md` не вносились, `docs/archive/*` не тронуты, `ISSUE.md` и `WISDOM.md` не
трогались. Ветка `fix/audit-number-corrections` ждёт решения владельца: слить с той сессией или
закоммитить отдельно.
