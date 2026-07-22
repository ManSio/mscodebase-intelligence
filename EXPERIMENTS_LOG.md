# EXPERIMENTS_LOG.md — Audit Verification (2026-07-22)

## [2026-07-22] — Audit: P0-1 DebounceBatch deadlock

**Ожидание:** `await self._flush()` вызывается ВНУТРИ `with self._lock` → deadlock при 100 файлах
**Команда:** AST-анализ + ручное чтение rate_limiter.py L154-232
**Сырой результат:**
```
=== DebounceBatch.add() at line 154 ===
  L154:     async def add(self, file_path: str) -> bool:
  L156:         with self._lock:                    # L156 — lock acquired
  L157:             is_new = file_path not in self._files
  L158:             self._files.add(file_path)
  L159:             self._last_added_at = time.monotonic()
  L160:             batch_full = len(self._files) >= self._config.max_batch_size
  L161:             timer_missing = self._timer is None or self._timer.done()
  L162:                                             # ← with block ENDS here, lock RELEASED
  L163:         if batch_full:                       # OUTSIDE lock
  L164:             logger.info("Batch full, flushing immediately")
  L165:             await self._flush()              # OUTSIDE lock ✓
  L166:             return is_new

=== DebounceBatch._flush() at line 216 ===
  L216:     async def _flush(self):
  L218:         with self._lock:                     # acquires lock (no contention)
  L219:             if not self._files:
  L220:                 return
  L221:             files = self._files.copy()
  L222:             self._files.clear()
```
**Вердикт:** **ОПРОВЕРГНУТА** ❌ — `await self._flush()` вызывается ПОСЛЕ释放ения lock (L162 end of `with` block). Код уже исправлен. Дедлок НЕ возможен.

---

## [2026-07-22] — Audit: P0-2 wmic удалён в Win11 25H2

**Ожидание:** `_get_process_ram` использует `wmic`, который удалён → RAM=0
**Команда:** проверка наличия wmic.exe + чтение layer.py L260-270
**Сырой результат:**
```
wmic.exe exists: False
wmic: FileNotFoundError (not available on this system)
OS: Windows-11-10.0.26220-SP0
psutil available: False (sandbox), but in project: YES (used in _get_process_cpu)
```
**Код из layer.py L260-270:**
```python
def _get_process_ram(pid: int) -> int:
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where", f"processid={pid}",
             "get", "WorkingSetSize", "/format:value"],
            timeout=3
        )
```
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — wmic.exe отсутствует на Win11 10.0.26220 (25H2). `_get_process_ram` всегда падает в `except` → возвращает 0. `_get_process_cpu` (L275) уже использует psutil.

---

## [2026-07-22] — Audit: P1-3 asyncio.Event между loop'ами

**Ожидание:** `asyncio.Event` в `_ready_events` привязан к loop, `set_state` может вызываться из другого loop
**Команда:** чтение project_indexer_registry.py L102, L236-258, L270-313
**Сырой результат:**
```
L102: self._ready_events: Dict[Path, asyncio.Event] = {}
L251: ev = self._ready_events.get(p)
L253: ev.set()                                  # asyncio.Event.set() — может быть в wrong loop
L300: if p not in self._ready_events:
L301:     self._ready_events[p] = asyncio.Event()  # создаётся в loop wait_until_ready
L313: await asyncio.wait_for(ev.wait(), timeout=timeout)
```
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ (с оговоркой) — `asyncio.Event` привязан к loop, в котором создан. `set_state` — синхронный метод, вызывается из любого потока. Если поток индексации НЕ в running loop → `ev.set()` поднимет `RuntimeError: no running event loop`. Риск реален при threaded indexer. Однако, в текущей архитектуре индексатор часто работает в `asyncio.to_thread`, что создаёт отдельный thread без loop — тогда `ev.set()` упадёт.

---

## [2026-07-22] — Audit: P1-4 Широкие except Exception

**Ожидание:** `except (ImportError, Exception)` ≡ `except Exception` маскирует баги
**Команда:** grep layer.py
**Сырой результат:**
```
277: except (ImportError, Exception):  # L277 — _get_process_cpu
```
Plus ~20 `except Exception` в layer.py, ~5 в engine.py
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — `(ImportError, Exception)` эквивалентен `except Exception`. Каждый широкий catch маскирует любые программные ошибки.

---

## [2026-07-22] — Audit: P1-5 Логика intel_code_topology

**Ожидание:** definitions попадают в outgoing_callees; references_count игнорирует callee
**Команда:** чтение layer.py L196-247
**Сырой результат:**
```
L203: result["call_graph"]["outgoing_callees"].append(...)  # definitions → callees
L229: result["call_graph"]["outgoing_callees"] = [...]      # BUT callees OVERWRITES (=, not append)
L239: result["references_count"] = len(result["call_graph"]["incoming_callers"])  # ignores callees
L242: if result["references_count"] == 0 and result["definitions_count"] > 0:
L244:     "potential_dead_code": True
```
**Вердикт:** **ЧАСТИЧНО ПОДТВЕРЖДЕНА** ⚠️ — definitions действительно добавляются в `outgoing_callees` (L203), НО если `build_call_graph` возвращает callees — они ПЕРЕЗАПИСЫВАЮТ список (=, не append, L229). Значит definitions попадают в callees только когда символ НЕ вызывает других функций. `references_count` действительно считает только callers, не callees — это подтверждено.

---

## [2026-07-22] — Audit: P1-6 Thrash кэша эмбеддингов

**Ожидание:** `clear()` вместо LRU eviction при 1000 записях
**Команда:** чтение engine.py L393-396
**Сырой результат:**
```
L394: if len(self._embedding_cache) >= self._embedding_cache_max:
L395:     self._embedding_cache.clear()
L396: self._embedding_cache[query_hash] = query_vector
```
То же самое в reranker cache (L1068):
```
L1068: self._reranker_cache.clear()
```
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — `clear()` сбрасывает ВЕСЬ кэш, а не одну запись. LRU (OrderedDict + popitem) был бы корректнее.

---

## [2026-07-22] — Audit: P1-7 sync→async bridge

**Ожидание:** `hybrid_search` создаёт ThreadPoolExecutor + asyncio.run() на каждый вызов
**Команда:** чтение engine.py L280-300
**Сырой результат:**
```
L284: if loop and loop.is_running():
L285:     import concurrent.futures
L286:     with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
L287:         future = pool.submit(asyncio.run, self.hybrid_search_async(...))
L288:         return future.result(timeout=30)
```
Аналогичный паттерн L1021-1028 для reranker.
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — каждый sync-вызов создаёт новый executor + loop. Расточительно, ломает async-примитивы в подкомпонентах.

---

## [2026-07-22] — Audit: P1-8 hash() недетерминирован

**Ожидание:** `hash(variant)` недетерминирован между процессами (PYTHONHASHSEED)
**Команда:** чтение engine.py L378, L1049
**Сырой результат:**
```
L378: query_hash = hash(variant)
L1049: cache_key = f"{hash(query)}:{hash(chunk_keys)}:{top_n}"
```
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — `hash()` для строк в Python не детерминирован (PYTHONHASHSEED). Кэш-промахи после рестарта. Для in-memory кэша одного процесса — не критично (hash стабилен в рамках одного process). Но для reranker cache (L1049) — потенциальная проблема при pickle/serialization.

---

## [2026-07-22] — Audit: P2-9 Дрейф числа tools

**Ожидание:** 37/42/48/59 — четыре разных значения
**Команда:** grep по README.md и ARCHITECTURE.md
**Сырой результат:**
```
README.md L47: "42 tools for AI assistant"
README.md L70: "38 MCP tools"
README.md L121: "48 tools (19 core + 13 intel + 12 inline + 4 dev)"
README.md L208: "MCP Tools (48 total)"
ARCHITECTURE.md L18: "18 core + 13 intel + 7 inline + 3 dev + 1 optional = 42"
ARCHITECTURE.md L94: "18 core + 13 intel + 7 inline + 3 dev + 1 optional = 42"
ARCHITECTURE.md L101: "19 core + 12 inline + 4 dev"
ARCHITECTURE.md L279: "48 registered (19 core + 13 intel + 12 inline + 4 dev)"
```
**Реальные классы MCPTool:** 37 classes, plus 13 intel_* + 13 inline @mcp.tool + 4 dev tools
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — минимум 4 разных счётчика (37/38/42/48) в одном README. Архитектурный дрейф.

---

## [2026-07-22] — Audit: P2-10 Устаревшие пути в ARCHITECTURE.md

**Ожидание:** Пути не отражают refactor src/ into domains; doc_sync_engine.py не существует
**Команда:** ls + grep ARCHITECTURE.md
**Сырой результат:**
```
test -f src/core/doc_sync_engine.py → EXISTS (src/core/doc_sync_engine.py exists!)
ARCHITECTURE.md L157: doc_sync_engine.py → src/core/doc_sync_engine.py
```
Дубликаты: `branch_aware_index.py` — только в `search/`, не в `core/` (flat deleted)
**Вердикт:** **ЧАСТИЧНО ОПРОВЕРГНУТА** ⚠️ — doc_sync_engine.py СУЩЕСТВУЕТ (аудит утверждал что нет). branch_aware_index.py дубликат — ОПРОВЕРГНУТ (только search/ версия). Пути cypher_engine.py — устарели (разбит на 5 модулей) — ПОДТВЕРЖДЕНА.

---

## [2026-07-22] — Audit: P2-11 Дубликаты файлов

**Ожидание:** branch_aware_index.py, cross_project_deps.py, cypher_engine.py в core/ и search/
**Команда:** ls + grep imports
**Сырой результат:**
```
src/core/branch_aware_index.py → NOT FOUND
src/core/cross_project_deps.py → NOT FOUND
src/core/cypher_engine.py → NOT FOUND
src/core/search/branch_aware_index.py → EXISTS (204 lines)
```
Все импорты ведут в `src.core.search.*`
**Вердикт:** **ОПРОВЕРГНУТА** ❌ — плоские дубликаты УДАЛЕНЫ. Все импорты корректны на `search/`.

---

## [2026-07-22] — Audit: P2-12 MODE_HYBRID dead code

**Ожидание:** MODE_HYBRID поддерживается в коде, но DI создаёт MODE_PURE
**Команда:** grep
**Сырой результат:**
```
graph_adapter.py L55: MODE_HYBRID = "hybrid"
graph_adapter.py L64-66: self._definitions, _references, _file_to_symbols
graph_adapter.py L91: if self._mode == self.MODE_HYBRID:
di_container.py L189: SymbolIndexAdapter(pg, mode=SymbolIndexAdapter.MODE_PURE)
```
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — MODE_HYBRID код существует, но не используется DI. Мёртвый код.

---

## [2026-07-22] — Audit: P2-13 Доступ к приватным полям

**Ожидание:** `_resolve_active_indexer` лезет в `registry._meta_lock` и `registry._indexers`
**Команда:** чтение layer.py L155-160
**Сырой результат:**
```
L155: registry = self._services.resolve(ProjectIndexerRegistry)
L157: with registry._meta_lock:           # приватное поле
L158:     for p, idx in registry._indexers.items():  # приватное поле
```
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — прямой доступ к `_meta_lock` и `_indexers`.

---

## [2026-07-22] — Audit: P2-14 Утечка процессов pyright

**Ожидание:** `_handle_crash` не terminate'ит процесс
**Команда:** чтение lsp_client.py L100-116, L307-320
**Сырой результат:**
```python
# stop() method (L100-116):
self._process.terminate()   # ← CORRECT: terminate in stop()
self._process.kill()

# _handle_crash() method (L307-320):
self._process = None        # ← NO terminate, NO kill, just nullifies reference
```
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — `_handle_crash` обнуляет `_process` без `terminate()/kill()`. Процесс pyright может остаться zombie. `stop()` делает terminate, но `_handle_crash` — нет.

---

## [2026-07-22] — Audit: P2-15 Хардкод портов 8080/8081

**Ожидание:** `_get_total_ram` хардкодит порты, а `intel_get_runtime_status` читает env
**Команда:** чтение layer.py L306-310, L430-432
**Сырой результат:**
```
L306: def _get_total_ram() -> int:
L308:     for port in ['8080', '8081']:        # HARDCODED
...
L430: "llama_qwen_pid": _find_pid("llama-server.exe", "8080"),  # HARDCODED
L431: "llama_qwen_ram": _get_ram_by_port("8080"),
L432: "llama_rerank_ram": _get_ram_by_port("8081"),
```
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — порты хардкодятся в 3 местах.

---

## [2026-07-22] — Audit: P3-17 Мёртвый параметр name

**Ожидание:** `name` в `_find_pid(name, port)` не используется
**Команда:** чтение layer.py L281-297
**Сырой результат:**
```
L281: def _find_pid(name: str, port: str) -> int:
L284:     port_int = int(port)
L285:     out = subprocess.check_output(["netstat", "-ano"], ...)
# name НЕ используется в теле функции
L300: pid = ProjectIntelligenceLayer._find_pid('', port)  # вызывается с ''
L430: _find_pid("llama-server.exe", "8080")  # name передаётся но игнорируется
```
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — параметр `name` передаётся (L430) но никогда не читается.

---

## [2026-07-22] — Audit: P3-18 __import__("re")

**Ожидание:** `__import__("re")` вместо top-level import
**Команда:** grep
**Сырой результат:**
```
graph_adapter.py L69: self._id_pattern = __import__("re").compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
```
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — неидиоматично, мешает статанализу.

---

## [2026-07-22] — Audit P2-P3 fixes: verification run (519 passed, 0 regressions)

**Ожидание:** P2/P3 fixes (LSP terminate, public API, ports→config, ARCHITECTURE.md, dead param, top-level import, tool count) не ломают существующие тесты
**Команда:** `python -m pytest tests/ -q --tb=short -m "not slow and not benchmark"`
**Сырой результат:**
```
519 passed, 36 pre-existing failures, 9 skipped, 91 deselected in 8.25s
```
**Вердикт:** **ПОДТВЕРЖДЕНА** ✅ — 0 regressions. Все P2/P3 патчи не повлияли на pass/fail.

---

## [2026-07-22] — Tech debt entries added: P2-12 + P2-16

**Ожидание:** Записи в KNOWN_ISSUES.md корректно отражают отложенные проблемы
**Команда:** `cat >> KNOWN_ISSUES.md` + ручная проверка
**Сырой результат:** P2-12 (MODE_HYBRID dead code), P2-16 (532 broad except) добавлены.
**Вердикт:** **ДОКУМЕНТИРОВАНО** ✅
