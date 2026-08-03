# -*- coding: utf-8 -*-
"""Write audit verdicts into experiments/audit.md (29 items).

Each verdict is inserted as a blockquote line right after the item heading.
Preserves CRLF. Asserts exactly one anchor per item.
Statuses: ✅ ИСПРАВЛЕНО / ⚠️ ЧАСТИЧНО / ❌ НЕ ИСПРАВЛЕНО / 📝 РЕКОМЕНДАЦИЯ / ✅ РЕШЕНО АРХИТЕКТУРНО
"""
import io

P = "experiments/audit.md"
raw = open(P, "rb").read()
text = raw.decode("utf-8")  # keeps \r\n

DATE = "2026-08-03"

ITEMS = [
    ("### 1. **DI-контейнер никогда не вызывает фабрики**",
     f"> **Вердикт ({DATE}):** ✅ ИСПРАВЛЕНО — `src/core/di_container.py:125-131`: `if key in self._factories: instance = self._factories[key](self)` — фабрики реально вызываются (lazy resolve под lock)."),
    ("### 2. **HeartbeatService: некорректная проверка GetLastError**",
     f"> **Вердикт ({DATE}):** ❌ НЕ ИСПРАВЛЕНО — `src/mcp/server_factory.py:57-62`: нет `SetLastError(0)` перед `OpenProcess` (GetLastError может быть stale), fail-open `except Exception: return True`. Претензия аудита валидна; импакт низкий (ложное «родитель жив»)."),
    ("### 3. **asyncio.Lock создаётся вне event loop**",
     f"> **Вердикт ({DATE}):** ⚠️ ЧАСТИЧНО — `src/core/search/engine.py:91`: `asyncio.Lock()` в синхронном `Searcher.__init__` (вызов из `src/core/di_container.py:291`). На Python 3.10+ создание вне loop безопасно, но cross-loop usage (несколько event loop'ов в тестах/перезапусках) — реальный риск. Рекомендация: `threading.Lock` или ленивое создание в loop."),
    ("### 4. **Progress tracking: неверное условие cleanup**",
     f"> **Вердикт ({DATE}):** ⚠️ ЧАСТИЧНО — `src/mcp/server.py:202-206` + `_cleanup_old_progress` (server.py:222-229): cleanup вызывается при `len(_last_progress) > 10`, удаляет записи старше 1ч. Работает, но условие и порог — эвристика, при <10 проектах не сработает."),
    ("### 5. **Resolve project root: дублирование вызовов**",
     f"> **Вердикт ({DATE}):** ✅ ИСПРАВЛЕНО — `src/mcp/server.py:437-447`: единая реализация `resolve_project_root` + SQLite-кэш соединения (TTL 2с, `_get_sqlite_connection`), дубль env-резолва убран."),
    ("### 6. **SearchResultReranker: hardcoded веса**",
     f"> **Вердикт ({DATE}):** ❌ НЕ ИСПРАВЛЕНО — `src/core/search/engine.py:87`: `SearchResultReranker(bm25_weight=0.3, dense_weight=0.7)` захардкожены в коде. Рекомендация: вынести в config (`.env`/config.py) по «Тумблеру» §2.1."),
    ("### 7. **RRF не детерминирован при equal scores**",
     f"> **Вердикт ({DATE}):** ✅ ИСПРАВЛЕНО — `src/core/search/scoring.py:74-75`: `sorted(scores.keys(), key=lambda k: (-scores[k], k))` — детерминированный tie-break по ключу (защита от порядка вставки в dict)."),
    ("### 8. **BM25 reindex callback: синхронный reindex**",
     f"> **Вердикт ({DATE}):** ❌ НЕ ИСПРАВЛЕНО — `src/core/di_container.py:296-300`: `_bm25_reindex_callback` вызывает `captured_indexer.searcher.reindex()` синхронно в DebounceBatch callback (debounce 500ms, batch 100). При тяжёлом BM25-индексе блокирует поток. Рекомендация: асинхронный/фоновый reindex."),
    ("### 9. **Extension handlers: блокировка event loop**",
     f"> **Вердикт ({DATE}):** ✅ РЕШЕНО АРХИТЕКТУРНО — символа `_force_reindex` в `src/mcp/` нет; переиндексация идёт через `intel_trigger_reindex` (fire-and-forget background job), event loop не блокируется."),
    ("### 10. **LanceDB: неверная интерпретация _distance**",
     f"> **Вердикт ({DATE}):** ⚠️ ЧАСТИЧНО — `src/core/search/engine.py:162-172`: явный комментарий «LanceDB _distance = негативная косинусная дистанция (чем больше, тем ближе)» + корректная обработка. НО `src/core/multi_project_searcher.py:161-169` использует raw `_distance` как score без той же семантики — несогласованность осталась."),
    ("### 11. **SQLite schema validation: только таблицы**",
     f"> **Вердикт ({DATE}):** ❌ НЕ ИСПРАВЛЕНО — `src/mcp/server.py:266-276`: `_check_sqlite_schema_health` проверяет только существование таблиц `scoped_kv_store`/`workspaces`, валидации колонок нет. Рекомендация: добавить проверку ключевых колонок."),
    ("### 12. **Encoding: нет PYTHONUTF8=1**",
     f"> **Вердикт ({DATE}):** ❌ НЕ ИСПРАВЛЕНО — в `install.py` нет `PYTHONUTF8=1` (grep по всему файлу: 0 вхождений). Рекомендация: установить env для запускаемых подпроцессов."),
    ("### 13. **install.py: shell=True в subprocess**",
     f"> **Вердикт ({DATE}):** ❌ НЕ ИСПРАВЛЕНО — `install.py:254-259` (`_run`) и `install.py:541-548` (`step_pip`): `shell=True`. Рекомендация: `shell=False` + список аргументов (пути с пробелами/спецсимволами)."),
    ("### 14. **ack_impact: нет проверки TTL на сервере**",
     f"> **Вердикт ({DATE}):** ✅ ИСПРАВЛЕНО — `src/core/modification_guard.py`: `_ACK_TTL=600` (L27-31), `_verify_ack_token`, fingerprint-проверка и инвалидация при изменении файла (L257-267), wrapper проверяет `elapsed < ack_ttl`. ОПРОВЕРГНУТА претензия аудита — TTL-проверка есть."),
    ("### 15. **Cancellation handling: MCP запросы не отменяются**",
     f"> **Вердикт ({DATE}):** 📝 РЕКОМЕНДАЦИЯ — не реализовано (`cancellation_scope`/`cancellation_aware` отсутствуют в src). Новый функционал, не баг."),
    ("### 16. **Tree-sitter: утечка parser instances**",
     f"> **Вердикт ({DATE}):** 📝 РЕКОМЕНДАЦИЯ — `src/core/indexing/parser.py:21`: `CodeParser` не имеет `close()`/`__del__`/`shutdown()` — жизненный цикл tree-sitter parser'ов не закрывается явно. Низкий приоритет (процесс один, утечка ограничена)."),
    ("### 17. **PropertyGraph: нет транзакционности при concurrent operations**",
     f"> **Вердикт ({DATE}):** ⚠️ ЧАСТИЧНО — `move_chunks_metadata` сериализуется через `_table_write_lock` (подтверждено комментарием в `tests/test_move_chunks.py:69-70`), но `_recover_from_wal` отсутствует — recovery из WAL не реализован."),
    ("### 18. **Progress notifications: не используются возможности MCP**",
     f"> **Вердикт ({DATE}):** 📝 РЕКОМЕНДАЦИЯ — `MCPProgressReporter` отсутствует; прогресс хранится в `_last_progress` (server.py) + `logger.info`, MCP `notifications/progress` не шлются."),
    ("### 19. **Rate limiting: только на уровне провайдеров, не на уровне MCP**",
     f"> **Вердикт ({DATE}):** ⚠️ ЧАСТИЧНО — `ToolRateLimiter` отсутствует, но `SlidingWindowRateLimiter` существует (`src/core/rate_limiter.py`, регистрируется в `src/core/di_container.py:316`) — лимитирование на уровне провайдеров есть, на уровне MCP-инструментов нет."),
    ("### 20. **OpenTelemetry: нет distributed tracing**",
     f"> **Вердикт ({DATE}):** 📝 РЕКОМЕНДАЦИЯ — не реализовано (`opentelemetry`/`setup_observability` отсутствуют в src)."),
    ("### 21. **Metrics: нет Prometheus integration**",
     f"> **Вердикт ({DATE}):** 📝 РЕКОМЕНДАЦИЯ — не реализовано (`prometheus` отсутствует в src)."),
    ("### 22. **Hot-reload конфигурации**",
     f"> **Вердикт ({DATE}):** 📝 РЕКОМЕНДАЦИЯ — `ConfigReloader` отсутствует; `SlidingWindowRateLimiter` есть, но без hot-reload конфига."),
    ("### 23. **Chaos-тесты: kill process during indexing**",
     f"> **Вердикт ({DATE}):** 📝 РЕКОМЕНДАЦИЯ — не реализовано (`test_indexing_survives_process_kill`/`test_lsp_crash_recovery` отсутствуют)."),
    ("### 24. **Property-based тесты для scoring**",
     f"> **Вердикт ({DATE}):** 📝 РЕКОМЕНДАЦИЯ — не реализовано (`test_rrf_is_monotonic`/`test_cosine_similarity_symmetric` отсутствуют; есть `tests/test_move_chunks.py` — покрытие meta-patching)."),
    ("### 1. **Self-diagnosis API: исчерпывающий health report**",
     f"> **Вердикт ({DATE}):** ✅ РЕАЛИЗОВАНО — `src/mcp/server_tools.py:700-710`: MCP tool `get_health_report` (индекс, bridge, health, providers)."),
    ("### 2. **Agent-friendly errors: ошибки с подсказками**",
     f"> **Вердикт ({DATE}):** ⚠️ ЧАСТИЧНО — `AgentFriendlyError` отсутствует, но есть `error_boundary` декоратор (`src/mcp/tools/write_tools.py:135`) со структурированными ошибками; `_generate_agent_instructions` не реализован."),
    ("### 3. **Memory-safe: защита от OOM на машине разработчика**",
     f"> **Вердикт ({DATE}):** 📝 РЕКОМЕНДАЦИЯ — `ResourceGuard` отсутствует в src."),
    ("### 4. **One-command ops: install/update/uninstall**",
     f"> **Вердикт ({DATE}):** 📝 РЕКОМЕНДАЦИЯ — `def uninstall` отсутствует в `install.py` (только step-функции установки)."),
    ("### 5. **Hot-reload кода: без перезапуска MCP**",
     f"> **Вердикт ({DATE}):** 📝 РЕКОМЕНДАЦИЯ — `DevModeReloader` отсутствует в src."),
]

for anchor, verdict in ITEMS:
    n = text.count(anchor)
    assert n == 1, f"anchor count = {n} (expected 1): {anchor!r}"
    text = text.replace(anchor, anchor + "\r\n" + verdict)

# Post-conditions
assert text.count("> **Вердикт (" + DATE + "):**") == len(ITEMS), "verdict lines == items"
assert text.count("\r\n") == raw.count(b"\r\n") + len(ITEMS), "CRLF grew by exactly #items"

with io.open(P, "wb") as f:
    f.write(text.encode("utf-8"))

print(f"[OK] {len(ITEMS)} verdicts inserted, CRLF preserved: {raw.count(b'\r\n')} -> {text.count(chr(13)+chr(10))}")
