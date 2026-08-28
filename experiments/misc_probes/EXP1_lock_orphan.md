# EXPERIMENT 1 — [2026-08-26] Гипотеза: DatabaseLock классифицирует ЖИВОЙ MCP как ORPHAN

**Ожидание:** parent_chain для честного holder'а (venvwlauncher-цепочка) содержит
мёртвого предка ВЫШЕ живого Zed → classify_holder вернёт ORPHAN (ложный позитив).

**Команда:**
```bash
venv/Scripts/python.exe experiments/misc_probes/probe_lock_classify.py 11832 8260 21924 22112
```

**Сырой результат:**
```
PID     alive  decision  parent-chain
11832   True   orphan    11832:pythonw.exe[alive] <- 22112:pythonw.exe[alive] <- 21296:?[dead]
  ^^^ WOULD BE TERMINATED by DatabaseLock (TerminateProcess)
8260    True   orphan    8260:pythonw.exe[alive] <- 21924:pythonw.exe[alive] <- 23988:?[dead]
  ^^^ WOULD BE TERMINATED by DatabaseLock (TerminateProcess)
21924   True   orphan    21924:pythonw.exe[alive] <- 23988:?[dead]
  ^^^ WOULD BE TERMINATED by DatabaseLock (TerminateProcess)
22112   True   orphan    22112:pythonw.exe[alive] <- 21296:?[dead]
  ^^^ WOULD BE TERMINATED by DatabaseLock (TerminateProcess)
```

**Вердикт:** ПОДТВЕРЖДЕНА. Все 4 живых MCP-процесса → ORPHAN.
Корень: `parent_chain()` останавливается на первом мёртвом предке
(завершившаяся venv-обёртка/прослойка), не доходя до живого Zed.exe выше.
Ветка `chain[-1] dead & no Zed → ORPHAN → TerminateProcess` убивает живой MCP.

**Урок:** эвристика «живой Zed в цепочке» ненадёжна, когда между holder'ом и Zed
есть завершившиеся промежуточные процессы (venvwlauncher → dead). Требуются:
(а) проверка command line holder'а (наш venv + src.main → HEALTHY), или
(б) никогда не убивать живые процессы из «нашего» окружения, или
(в) kill только по явному критерию (lock возраст + PID мёртв).

Связь: EXPERIMENTS_LOG — этот жечас. Воспроизводит инцидент 2026-08-26 (PID 20052 killed by 12524).