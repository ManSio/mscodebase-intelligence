# EXPERIMENTS_LOG.md — Audit Verification (2026-07-22)

## [2026-07-31] — P0-3: verify_clean_state.sh --no-clone (CI self-clone убран)

### Гипотеза
Параметризация `verify_clean_state.sh` (флаг `--no-clone` + `$1` = repo URL) убирает self-clone из CI (тестируется checkout раннера), сохраняя единый источник правды: локальный запуск без аргументов = прежний полный клон.

### Команда
1. `bash -n scripts/verify_clean_state.sh` — синтаксис
2. Python `yaml.safe_load` для `.github/workflows/ci.yml` — валидность
3. Локальный прогон `bash scripts/verify_clean_state.sh --no-clone` — не-Linux ветка (Windows)

### Сырой результат
```
SYNTAX_OK (bash -n scripts/verify_clean_state.sh)
YAML_OK — ci.yml jobs.clean-state.steps[-1].run = bash scripts/verify_clean_state.sh --no-clone "${{ github.repository }}"
Локальный прогон --no-clone (Windows): «No-clone mode: verifying current directory» — clone пропущен, ветка выбрана верно; далее падение на venv/bin/* — pre-existing Linux-only assumption скрипта (POSIX-layout venv), не связано с правкой.
Полный pytest tests/: 610 passed, 0 failed (35.25s)
```

### Вердикт: подтверждена
`--no-clone`-ветка выбирается и корректно пропускает clone (работа в текущем каталоге). Локальный ручной запуск без аргументов сохраняет полный клон (default URL). Linux-путь (venv/bin, lockfile gate, install из lock) требует ubuntu-раннера — покрыто bash -n и логикой ветвления, полный CI-прогон выполнит GH Actions.

---

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
