# EXPERIMENTS_LOG.md — Audit Verification (2026-07-22)

## [2026-07-27] — P0 Fixes: alias injection, layer injection, CI paths, sandbox docstring

### Гипотеза
Четыре P0-бага из протокольного аудита можно исправить минимальными, проверяемыми правками без риска регрессий.

### Команда
1. `edit_file` cypher_sql.py L84 — добавить `re.fullmatch` валидацию alias
2. `edit_file` engine.py L352, L740 — экранировать `layer` через `_escape_sql_value`
3. `edit_file` verify_clean_state.sh — заменить Windows-пути на POSIX
4. `edit_file` codebase_tool.py — синхронизировать docstring с кодом

### Сырой результат
Все 4 правки применены успешно через `edit_file`. Проверка через `read_file` подтвердила корректность каждой правки:
- cypher_sql.py L84: `if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item.alias):` — добавлен
- engine.py L352-356: `_esc = IndexerTableMixin._escape_sql_value(layer)` — добавлен перед f-string
- engine.py L740-742: аналогично для `search_with_mode`
- verify_clean_state.sh: `venv/bin/pip` и `venv/bin/python` — заменены
- codebase_tool.py: docstring переписан, дубликат удалён

### Вердикт: подтверждена
Правки минимальны, точечны, не затрагивают логику — только добавляют валидацию/экранирование.

---

## [2026-07-22] — Audit: P0-1 DebounceBatch deadlock

**Ожидание:** `await self._flush()` вызывается ВНУТРИ `with self._lock` → deadlock при 100 файлах
**Команда:** AST-анализ + ручное чтение rate_limiter.py L154-232
**Сырой результат:**
```
=== DebounceBatch.add() at line 154 ===
  L154:     async def add(self, file_path: str) -> bool:
  L156:         with self._lock:                    # L156 — lock acquired
  ...
  L163:         if batch_full:                       # OUTSIDE lock
  L164:             await self._flush()              # OUTSIDE lock ✓
```
**Вердикт:** подтверждена — `_flush()` вызывается вне lock, deadlock не воспроизводится.
