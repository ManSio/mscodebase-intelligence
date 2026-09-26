# F4b — свежий held-out список (v3, финал кандидата; НЕ заморожено)

Источник: 8 реальных симптомов от **контекстно-чистого субагента** (не читал каталог/использованный список)
из `AGENT_DIARY.md`/`KNOWN_ISSUES.md`/`ISSUE.md`/`EXPERIMENTS_LOG.md`. Формулировки — «как пришло».
Пройдены: G6 token-чекер + **ручной semantic-review** (v1 отклонён: 5/8 reindex-skew + 2 двойника;
v2: #6 заменён — был двойником used #13).

1. Repeated identical queries were answered straight from the cache without ever executing the dense retrieval stage.
2. A sandboxed user script could read the host process's API keys and tokens out of its environment.
3. When two threads resolved the same service concurrently, two independent instances were created (e.g. two graph objects on one database).
4. A tool's own docstring warned that sandboxing was absent, contradicting the strict sandbox the code actually ran, so an admin could wrongly disable it.
5. The clean-state CI job died with exit 127 on the Linux runner because it invoked `.exe` paths that do not exist there.
6. After a timeout, the project's latency metrics showed negative values, corrupting min_ms, avg_ms, P50/P95.
7. A Cypher query asking for paths up to five hops silently returned only the direct neighbours instead of the deeper chain.
8. Running the Zed settings cleanup erased every JSONC comment the user had written in settings.json.

## SOURCES (verbatim)
1 -> EXPERIMENTS_LOG.md: "KI-101 (cache-hit пропускал dense-уровень)"
2 -> ISSUE.md: "F-4: env = os.environ.copy() — ВСЕ секреты родителя доступны sandbox-скрипту."
3 -> ISSUE.md: "Два параллельных resolve создадут два экземпляра (напр., два PropertyGraph на один WAL)."
4 -> ISSUE.md: "Docstring: ⚠️ ВНИМАНИЕ: Изоляция (sandbox) ОТСУТСТВЕТ."
5 -> ISSUE.md: "CI job clean-state на ubuntu-latest → venv/Scripts/pip.exe не существует → exit 127"
6 -> ISSUE.md: "Записывает отрицательную latency в метрики, ломая min_ms, avg_ms, P50/P95."
7 -> ISSUE.md: "Запрос MATCH (n)-[:CALLS*1..5]->(m) возвращает только прямых соседей, не 5 уровней."
8 -> ISSUE.md: "ВСЕ комментарии пользователя в settings.json терялись."

## Semantic review (финал)
| # | Семья | Двойник в used-16? | Вердикт |
|---|---|---|---|
| 1 | retrieval/cache | нет | ✅ |
| 2 | security/secrets | нет | ✅ |
| 3 | concurrency/DI | нет | ✅ |
| 4 | docs/contract | нет | ✅ |
| 5 | CI/portability | used #5/#15 — CI, но иной механизм | ⚠️ помечен |
| 6 | observability/metrics | нет (utils/metrics, не memory) | ✅ |
| 7 | API/query semantics | нет | ✅ |
| 8 | destructive tool | нет | ✅ |

## Следующие шаги (до прогона)
1. Добавить 6 контролей: 3 must-hit-парафразы записей + 3 must-NONE (вне домена; один — соседний домен, per G1).
2. G6 token-чекер на ИТОГОВОМ (8+6) → `OVERLAP: PASS`.
3. Заморозить sha256 ДО прогона; `--variant high` обязателен; прогон сохранить в `results/f4b/`.
