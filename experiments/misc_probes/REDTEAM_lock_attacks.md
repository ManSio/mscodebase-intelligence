# РФД ТИМ AI — DatabaseLock: атаки со всех сторон (2026-08-26)

## Атакованный объект
`src/core/indexing/database_lock.py` (classify_holder → ORPHAN → TerminateProcess любому
живому процессу) + `src/core/indexing/db_manager.py` (жизненный цикл lock'а).

## Методика
- Эмпирика на живых процессах (без Terminate для системных — только classify).
- Unit-анализ кода (db_manager, terminate path, TOCTOU).
- Эксперименты: E1 (4/4 живых MCP → ORPHAN), E2 (holder с мёртвым родителем убит),
  probe3 (поддельный lock → ORPHAN для explorer.exe).

## Результаты атак

### АТАКА 1 [P0] — поддельный lock → произвольный kill системного процесса ✅ ПОДТВЕРЖДЕНО
Любой процесс того же user'а пишет lock-файл с `pid=24744 (explorer.exe)` +
`started=старое` → classify_holder → **ORPHAN** → при `acquire()` сработает
`TerminateProcess(24744)`. Убийство живого системного процесса по поддельному файлу.
Репро: probe3 → `classify_holder -> orphan`.

### АТАКА 2 [P0] — ложный ORPHAN для живого MCP (настоящий инцидент) ✅ ПОДТВЕРЖДЕНО
Живой MCP (venvwlauncher-цепочка: pythonw → pythonw → мёртвый предок) → walk
`parent_chain` обрывается на первом мёртвом звене (L202 `if not alive: break`),
не доходит до живого Zed выше → `chain[-1] dead` + нет `"Zed"` → ORPHAN → терминация.
Репро: E1 — все 4 живых MCP → orphan; E2 — holder pid=1328 убит, lock украден.

### АТАКА 3 [P1] — TOCTOU: PID-reuse между classify и terminate ⚠️ КОД-АНАЛИЗ
`_terminate_holder` (L440-470) не перепроверяет create_time перед TerminateProcess.
Окно: classify(ORPHAN) → holder умирает → PID переиспользован новой программой →
TerminateProcess убивает НЕВИНОВНОГО. Реальных условий kill'а «по наследству».

### АТАКА 4 [P1] — lock держится ВСЮ жизнь менеджера ⚠️ КОД-АНАЛИЗ
`LanceDBManager.__init__` (db_manager.py:83-92) вызывает `_db_lock.acquire()` и
raise при LockBusyError → второе окно Zed на ту же БД **не стартует вообще**
(«Закройте второе окно»), даже для read-only. атака availability multi-window.

### АТАКА 5 [P1] — reacquire после rmtree без fail → два писателя ⚠️ КОД-АНАЛИЗ
`recreate_table_physical` (db_manager.py:490-493): release → rmtree → acquire;
при LockBusyError — только `logger.warning` и ПРОДОЛЖЕНИЕ без lock → два процесса
пишут в БД одновременно (нарушение single-writer).

### АТАКА 6 [P2] — нет hostname в lock ⚠️ КОД-АНАЛИЗ
`_write_owner` пишет только pid/started/role. На сетевом share PID другой машины
непроверяем → чужой host'овый PID выглядит «мёртвым» → steal → два писателя с
двух машин. filelock/QLockFile хранят hostname.

### АТАКА 7 [P3] — нет версии формата lock ⚠️ КОД-АНАЛИЗ
Формат {pid, started, role} без version — миграции невозможны.

## Промежуточный вердикт
Любые варианты «умного kill'а» (A-вариант с эвристиками) не закрывают АТАКИ 1 и 3.
Единственный полный фикс — **радикальный fail-closed: живой PID → HELD (ждать →
LockBusyError), TerminateProcess удалить из acquire полностью** (закрывает 1,2,3),
плюс: hostname в lock (6), version (7), дефолтный lock только на время записи (4),
reacquire-fail → raise (5).

## Вывод
Текущий дизайн «self-healing kill» небезопасен в принципе: он позволяет убивать
произвольные живые процессы (включая системные) через поддельный lock. Индустрия
(PostgreSQL/Qt/filelock) — «break stale lock only on proof of death», т.е. только
мёртвый PID / PID-reuse-токен, никаких TerminateProcess живых.