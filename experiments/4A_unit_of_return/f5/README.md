# F5 — 4-arm unit-of-return (на НАШЕМ индексе)

**Статус:** 🟡 дизайн заморожен (README §1), harness готов, **fresh-набор заморожен (G6 PASS)**,
**objective-половина прогнана** (`RESULTS.md`). Judged-плечо (читатель+судья) — не начато.

## Цель

Единственная переменная — **единица возврата**: A top-k чанков (baseline) / B top-1 целого документа
(гипотеза) / C oracle-файл, нарезанный на чанки (потолок) / D ничего (closed book, контроль).
Ретривер, режим, limit, набор запросов — фиксированы.

## Phase Zero

- **Known (verified 2026-09-26):** MCP жив (PID 15624, embedder+reranker 🟢); индекс 10106 chunks /
  716 files / 14099 symbols; in-process `Searcher.search_with_mode` отдаёт `text` + `metadata.file/chunk_index`;
  доступ read-only (PID-lock MCP держится, наш процесс только читает).
- **Assumed:** gold = файл, в котором обязан быть ответ; релевантность измеряется по попаданию gold-файла.
- **Suspected:** whole-doc B даёт топ-1 не чаще A (у Tom whole-doc не сдвинул низ), но больше токенов.
- **Must verify:** (1) fresh-набор (G6) — не пересекается с benchmark2/35-panel и F4b; (2) судья слепой,
  reference одинаков; (3) index-статистика заморожена (BASELINE.md) до прогона.
- **Worst case (blast radius):** чужой MCP/llama на :8080/:8081 убьёт ретрив mid-run; прогон пишет в
  чужой индекс. Митигация: read-only, MCP off в шардах, :8080/:8081 проверены до/после, индекс не пишем.

## Harness

`scripts/f5_retrieve_arms.py` — плечи A/B/C/D, objective-метрики (hit@1/@3/@10, top-1-doc-is-gold,
context-chars) + контекст-бандлы для будущего judged-плеча.

## Пилот (in-sample, ⚠️ не результат F5)

Вход: `f5/pilot_benchmark2.jsonl` = 12 задач benchmark2 (gold = первый `evidence`-файл). **Этот набор
уже виден** → только калибровка harness, не генерализация. Индекс — не заморожен.

| метрика | rate |
|---|---|
| A hit@1 | 0.083 (1/12) |
| A hit@3 | 0.417 (5/12) |
| A hit@10 | 0.417 (5/12) |
| B top-1-doc-is-gold | 0.083 (1/12) |
| C oracle | 1.0 (by construction) |
| D closed book | 0.0 |

`avg context chars`: A≈4 947 · B≈135 738 (×27 к A) · C≈35 196 · D=0.
Сырьё: `f5/pilot_results.json`. Команда: `python scripts/f5_retrieve_arms.py --queries
experiments/4A_unit_of_return/f5/pilot_benchmark2.jsonl --out experiments/4A_unit_of_return/f5/pilot_results.json`.

**Наблюдение пилота (не вывод):** B не обогнал A по top-1 (оба 1/12) при ×27 контекста; ретрив по
gold-файлу слабый (hit@1 8%). Говорит о калибровке, не о гипотезе: judged-плечо ещё не поставлено.

## Что осталось до F5 (гейты)

1. **Fresh-набор (G6):** автор — context-clean субагент (не видел каталог/F4b), прогон через
   `frozen_overlap_check.py` v2 → `OVERLAP: PASS`; sha256 до прогона.
2. **Judged-плечо:** генераторы/судья — разные шарды, opaque-токены, reference одинаков, 10–20 trials
   majority + κ/flip-rate (Coin Flip Judge, arXiv:2606.13685).
3. **Freeze:** `queries.json`/`populations.json`/`manifest.json` (retriever/mode/limit/model/budget/n/seed).
4. **Полоса шума** повторным прогоном (Tom floor 2 пункта на n=14).
