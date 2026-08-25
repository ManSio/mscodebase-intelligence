# .locks — файловые лока параллельных агентов (git-based, §10 skill multi-agent-coordination)

Когда несколько агентов могут одновременно править один ресурс, единственная
корректная блокировка — **отдельный закоммиченный файл** `.locks/<resource_id>.lock`
(не общая markdown-таблица — у той гонка TOCTOU). Атомарность гарантирует git:
два параллельных push на один путь невозможны без предварительного pull —
гонка становится видимой и отклоняемой на уровне git.

## Формат файла

```json
{
  "resource": "src/core/search/engine.py",
  "agent": "Agent A",
  "acquired_at": "2026-08-24T14:00:00Z",
  "purpose": "FTS5 integration — hybrid_search_async, reindex, close",
  "estimated_duration_min": 30
}
```

## Правила

1. **Перед любой правкой файла** (`edit_file`/`write_file`): `git fetch origin main`,
   затем если чужого лока на ресурс нет — `python scripts/lock_guard.py acquire <ресурс> "<цель>"`.
   (По умолчанию — только если в проекте активен >1 агент/окно; в одиночной
   сессии лок не обязателен.)
2. **Не редактировать** файл с чужим активным локом.
3. **Освободить сразу** по завершении: `python scripts/lock_guard.py release <ресурс>`.
4. **Stale-лок** (владелец пропал >2ч): снять С ЯВНОЙ причиной в сообщении
   (`unlock: ... (stale, no activity for 2h+)`), никогда не молча.
5. Статус фиксируется **коммитами**, а не общей таблицей: `git --no-pager log --oneline --all -20`.
6. Архитектурные решения между агентами — **ADR**, не handoff-файл.

## Быстрый статус

```bash
python scripts/lock_guard.py status
```