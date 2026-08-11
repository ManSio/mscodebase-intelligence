# WISDOM.md — дистиллят фактов (≤50 строк)

> Не архив, не дневник. Каждая строка — проверенный факт, сжатый до одной мысли.
> Полная история — в `AGENT_DIARY.md` / `EXPERIMENTS_LOG.md`.

## Внешний аудит 2026-08-08 (верификация 14/15)
- Indexer всё ещё composition root (12+ подсистем в __init__, indexer.py:34-196);
  кэш-счётчики продублированы в 3 классах (Indexer/db_manager/project_runner).
- Канон доков: 57 base (+1 `execute_script` при env=true → 58) — дрейф закрыт 2026-08-08.
- mcp 2.0.0 уже на PyPI — потолок <2 защищает реально.

## Моки async-методов (2026-08-08)
- `MagicMock(return_value=asyncio.sleep(0, result=X))` — eager-корутина живёт
  в циклах ссылок мока до чужого GC → «coroutine 'sleep' was never awaited».
  Правильно: `AsyncMock(return_value=X)`.
- Мок DI-сервисов НЕ изолирует LSP: WriteTool._get_lsp_client импортирует
  LspClient напрямую → rename-тест поднимал реальный basedpyright и не
  закрывал его (unclosed transport). Фикс: WriteTool.close() + teardown
  фикстуры. Проверять -X dev прогоном, а не which-ом: langserver лежит в
  Zed\languages\...\node_modules, вне PATH.

## CI lint gate (2026-08-08, 18 красных прогонов)
- CI-гейт — `ruff check src/ tests/` ЦЕЛИКОМ, а не per-file: F841/F401/BLE001
  накапливались по коммитам, pytest локально был зелёный, а lint-шаг блокировал
  ВСЕ тесты в CI. Pre-push: полный ruff, не только изменённые файлы.
- F401-автофикс опасен на ФАСАДАХ: src/mcp/server.py реэкспортирует
  resolve_project_root/reset_project_root_cache (импортируются base.py:127 и
  тестами) — автоудаление дало ImportError. Реэкспорт = `# noqa: F401`.
- BLE001: новые файлы обязаны без broad except; sqlite-код → сужение до
  (sqlite3.Error, OSError); integrity-rollback (BL-05) → noqa с причиной.

## Версионная совместимость (2026-08-08, CI matrix 3.10-3.12)
- Локальная проверка ТОЛЬКО на py3.14 слепа: tomllib (3.11+), read_text
  (newline — 3.13+), realpath UNC (3.10-3.12 бросает FileNotFoundError).
  Guard: прогон matrix-команды на py3.10 и py3.11 (есть в py-лаунчере).
- `pip install -e .[dev]` НЕ апгрейдит нарушающие пин пакеты в старом venv
  (язык-pack 0.13.0 остался на 3.11 при пине >=1.14.3) — при версионных
  расхождениях локального окружения обновлять пакет явно, не доверять -e .

## CI платформенные фейлы (2026-08-08)
- Windows-only тесты БЕЗ skipif(win32) валят ubuntu-джобы (normalize_diag_uri
  драйв-букв: на POSIX /d:/... — обычный путь). Guard: проверять ubuntu-джобы
  CI, не только локальный Windows-прогон.
- pip-audit -r lock --no-deps БЕЗ --disable-pip всё равно резолвит через pip
  в temp-venv (requirement.py:161-168: --no-deps лишь разрешает preresolved-путь)
  → pywin32 валит ubuntu, numpy 2.4.6 без колёс для py3.10. На Windows py3.14
  локально маскируется (установка успешна). Guard: --no-deps --disable-pip.
- `gh` CLI авторизован (ManSio) — `gh run view <run> --job <id> --log` даёт
  точные фейлы CI, аннотации GitHub — только «exit code 1».

**Правила:**
- ≤50 строк. Новое входит — вытесненное уходит в `docs/archive/`.
- Пополнение в `[🏁 ИТОГ]` сессии (Триггер 7, §1.19): 1-3 лучших урока, не больше.
- Строка без подтверждения/использования 30+ дней → удалить или архивировать.
- Свежая строка бьёт старую → старую удалить, `CONTRADICTION RESOLVED` в дневнике (§4.9).

## Audit verification deep-research-report.md (2026-08-08)
- Windows mutex-эталон: `CreateMutexW(None, False, ...)` + WaitForSingleObject + парный
  ReleaseMutex (graph.py:74, onnx_client.py:76). llama_runner.py:184 — исправлен на
  `False` 2026-08-08 (был `True` — утечка владения), тест test_llama_mutex Windows.
- CVE-2026-4372 (transformers RCE, обходит trust_remote_code) фиксится в 5.3.0, НЕ 5.0.0 —
  «fixed version» брать из OSV по каждой CVE; lock уже 5.14.1, пин поднят до >=5.3.0.
- LanceDB atomic delete+add: фикс table.version + restore(prev_version) при сбое add
  (db_writer.py) — нативный versioning лучше temp+os.replace.

## Git-мультисессия (2026-08-08)
- `git commit` БЕЗ pathspec коммитит ВЕСЬ индекс — при параллельной сессии
  украдёт её staged-правку (инцидент 568b1f27). Всегда `git commit -m ... -- <paths>`.
  index.lock чужой сессии не удалять — ждать освобождения (кап ~3 мин).
- Локальный ruff-кэш может пропускать BLE001 — перед push `ruff check src/ tests/ --no-cache`.

## Multi-RAG ablation (2026-08-11, Experiment 1 N=30)
- hybrid_search_async engine.py L521-541: на кэш-хите эмбеддинга dense-поиск ПРОПУСКАЕТСЯ
  (all_dense_results пуст) — vector-тир молча исчезает при повторных запросах. НЕ чинить
  без регресс-теста «два подряд одинаковых запроса → оба с dense». Эксперимент обходит
  изоляцией кэша per-arm. Баг доказан абляцией: vector_bm25 == bm25_only 30/30.
- Абляция: recall несут BM25+FTS5 (fts5_only 0.825 — максимум, выше full 0.775),
  vector (llama.cpp e5-small) слабейший (0.167), реранкер = precision (+0.147) ценой
  recall (−0.019); graph-ценность в metadata (callers/callees), не в тексте чанков.

## Tree-sitter грамматики (семена 2026-08-06)
- elixir: шумит макро-токенами → низкое качество индексации, исключить или пометить.
- matlab: расширение `.m` конфликтует с Objective-C → разрешать по содержимому, не по расширению.
- tree-sitter-python 0.25: node-type `async_function_definition` ОТСУТСТВУЕТ →
  сверять паттерны с `node-types.json` установленной версии грамматики.

## Language-pack / платформа (Windows)
- Парсеры language-pack работают вопреки issue #174 → проверка замером (§1.6),
  не issue-трекером. Факт из трекера — гипотеза, факт из прогона — вердикт.

## LSP (basedpyright, Windows, 2026-08-07)
- publishDiagnostics-uri перекодируется (file:///D:/x → file:///d%3A/x):
  нормализуй через unquote+Path.as_uri() до lookup, иначе тихая false-negative.
- _send_text_request оборачивает единичный dict-ответ в список → hover и др.
  методы обязаны обрабатывать wrapped-list, не только dict.

## Multi-window (2026-08-07)
- SQLite scoped_kv_store хранит по-оконные строки (key=window_id), но без
  фильтра по окну это глобальный сигнал → резолв проекта CWD-first:
  Zed ставит CWD = корень окна для каждого MCP-процесса (Verified по 2 окнам).
- PID-lock self-healing (WS9, 2026-08-08): holder классифицируется по цепочке
  родителей (Windows Toolhelp32): живой Zed.exe = HEALTHY (wait ≤8s → мягкий
  LockBusyError), корень мёртв = ORPHAN (TerminateProcess → steal). create_time-
  guard: процесс создан ПОСЛЕ записи lock → PID-reuse → stale. lock пишет
  РЕАЛЬНЫЙ python (не venvlauncher), terminate убивает держателя, обёртка
  умирает сама; после terminate нужен retry-unlink (PermissionError от fd).
- psutil НЕ объявлен/НЕ установлен в venv (WS9): удалён мёртвый _get_process_cpu,
  _find_pid → netstat/ss, _get_parent_pid → Toolhelp32. grep-0.

## Consistency / Trust / Write (2026-08-08)
- Consistency Engine: 6 состояний (CONSISTENT/STALE/UPDATING/PARTIAL/CORRUPTED/
  UNKNOWN), событийная модель, threading.Lock (не asyncio.Lock) — см. src/core/consistency.py.
- Windows: текстовая запись \n→\r\n ломает SHA-256 пост-верификацию →
  _atomic_write пишет с newline="\n" (детерминированно, WS4).
- Late enrichment (флаг MSCODEBASE_LATE_ENRICHMENT): chunk-local поля
  (module/headline/symbol) ~0.7ms на топ-10, +~186 ток/чанк; imports в
  metadata чанков НЕ индексируются — нужен graph-lookup (KNOWN_ISSUES 🟡).

## Security (2026-08-08, WS7)
- Instruction-флаги — адвизорная маркировка на выдаче (role_hijack/imperative/
  shell/secrets), НЕ фильтрация (SoK: filtering не работает) — src/core/instruction_scan.py.
- Trust-стампинг: результаты поиска несут trust-уровень проекта; кросс-репо =
  untrusted по умолчанию (cross-origin poisoning, multi_project_searcher).
- MCPSec/message-auth НЕ применимы: localhost stdio, tools статические
  (guard-тесты test_tool_registration_security). CoREB: короткие запросы
  схлопываются — benchmark2/keywords.jsonl (8 кейсов).
