# Особенности Windows (и ситуация с хостами)

> Перевод: 2026-11-08, источник — docs/en/ZED_WINDOWS_QUIRKS.md. Английская версия — канон.

[English](../en/ZED_WINDOWS_QUIRKS.md) · [Русский](ZED_WINDOWS_QUIRKS.md) · [中文](../zh/ZED_WINDOWS_QUIRKS.md)

> Версия 3.5.0. Имя файла сохранено ради стабильности ссылок. **OpenCode теперь
> основной хост; расширение Zed по-прежнему поддерживается.** Инциденты,
> касающиеся только Zed, помечены в конце как история и не описывают текущее
> поведение.

## 1. Хосты

| Хост | Команда запуска | Статус |
|---|---|---|
| OpenCode | `…\Zed\extensions\mscodebase-intelligence\venv\Scripts\mscodebase-mcp.exe -u -m src.main`, `PYTHONPATH` = каталог расширения | основной |
| Расширение Zed | `extension.toml` → `venv\Scripts\pythonw.exe -u -m src.main`, `PROJECT_PATH = $ZED_WORKTREE_ROOT`, `PYTHONUTF8=1` | поддерживается |

Оба запускают код, скопированный в
`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`. Правка `src/` ничего не
меняет, пока не выполнены `python install.py --sync-only` и перезапуск хоста. Это
самая частая причина «мой фикс не применился».

## 2. Без консольных окон: `CREATE_NO_WINDOW` везде

Windows создаёт консоль для каждого дочернего процесса консольной подсистемы.
Сервер запускает их много (`git`, `llama-server.exe`, `basedpyright`, idle-пробы),
поэтому флаг применяется на двух уровнях:

1. **Глобально** — `src/core/silent_subprocess.py`, импортируемый первым в
   `src/main.py`, патчит `subprocess.Popen/run/check_output/check_call` на win32,
   добавляя через OR `CREATE_NO_WINDOW` и выставляя
   `STARTUPINFO(wShowWindow=SW_HIDE)`. Любая библиотека, которая вызывает шелл,
   покрыта, даже не зная об этом.
2. **Локально** — десятки мест вызова передают
   `creationflags=CREATE_NO_WINDOW` явно (`git_tools`, `commit_memory`,
   `execution_contract`, `resource_monitor`, `verify_on_read`, `graph`,
   `sandbox/executor`, …). Флаг добавляется через OR и никогда не переписывает
   уже установленный набор.

Долгоживущие серверы моделей добавляют `DETACHED_PROCESS | CREATE_NO_WINDOW`
(`llama_runner._popen_with_job`), поэтому они переживают родителя и не мигают
окном при каждом перезапуске. Это не косметика: консоль, мигающая примерно каждые
~30 s (idle-проба), была зафиксированным инцидентом, который пользователи читали
как вредоносное ПО.

## 3. `pythonw.exe` против `python.exe`, и имена процессов

`pythonw.exe` — интерпретатор GUI-подсистемы: консоли нет, но stdio всё равно
работает через pipe'ы, которые даёт хост. Поэтому `install.py` использует
`venv\Scripts\pythonw.exe` как `MCP_PYTHON` и создаёт одноразовый NTFS hardlink
`mscodebase-mcp.exe → pythonw.exe` (`process_titles.ensure_mcp_hardlink`),
откатываясь к обычному `pythonw.exe`, если линковка не удалась.

Hardlink существует потому, что у `pythonw.exe` нет консоли и он не может задать
заголовок окна — Task Manager показал бы просто `python.exe`. С ним процесс
опознаваем. `apply_mcp_process_title()` собирает
`mscodebase-mcp:<project>-<hash8>`; `start_server.bat` запускает `python.exe` с
`PYTHONUTF8=1` и задаёт заголовок из bat-файла. Потомки `llama-server` получают
hardlink'и `llama-embed.exe` / `llama-rerank.exe` по той же причине.

## 4. `Popen` + `communicate`, никогда `capture_output`

`capture_output=True` и `check_output()` запрещены внутри MCP-процесса: когда
stdout уже перенаправлен в pipe (как под MCP-хостом), они могут заклинить pipe в
рабочем потоке, и вызов никогда не вернётся. Домашний паттерн:

```python
proc = subprocess.Popen([...], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace",
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
try:
    out, _ = proc.communicate(timeout=...)
except subprocess.TimeoutExpired:
    proc.kill()
    proc.communicate()   # reap; never leave a zombie
```

`stdin=DEVNULL` не даёт потомку, читающему stdin, блокироваться навсегда.
`.githooks/pre-commit` использует тот же паттерн и трактует таймаут как вердикт
(«гейт не ответил»), а не как падение.

## 5. Кодировка

- `PYTHONUTF8=1` задан в обеих конфигурациях хостов (`extension.toml`,
  MCP-блок OpenCode), поэтому интерпретатор не откатывается к OEM-кодовой странице.
- Скрипты, печатающие эмодзи, перенастраивают stdout
  (`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`); иначе консоль
  cp1251/cp866 бросает `UnicodeEncodeError`, и гейт падает по неверной причине.
- В PowerShell задайте это на сессию перед чтением логов:
  `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`.
- Никогда не вызывайте `print()` в stdout из библиотечного кода — stdout это канал
  JSON-RPC. Диагностика идёт в логгер, который пишет в `<data_root>/logs/`.

## 6. Пути

- Аргументы MCP принимают нативные пути Windows (`C:\work\app\src\main.py`);
  для `notify_change` используйте относительные пути от корня проекта, для
  `project_root` — абсолютные.
- Внутренние ключи сравнения — канонические POSIX
  (`Path.resolve().as_posix()`), приведённые к нижнему регистру на `win32`,
  потому что файловая система регистронезависима
  (`modification_guard._normalize_path`).
- Пути длиннее `MAX_PATH` проходят через `to_win_long_path()` (префикс `\\?\`;
  на POSIX — no-op).
- Сравнение вывода `git worktree list` с путями `pathlib` без нормализации
  разделителей заставляет гейт видеть собственное дерево как чужое — отсюда
  выделенный нормализатор в `scripts/check_parallel_sessions.py`.

## 7. Git, локи и Insider-сборки

Git может заблокироваться на графическом Credential Manager из процесса без окна,
поэтому каждый вызов использует `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=echo`,
`GIT_PAGER=cat`, плюс `CREATE_NO_WINDOW` и таймаут (`git_tools._git_run`, 15 s).

Windows держит memory-mapped файлы БД заблокированными, пока открыт дескриптор.
Поэтому `intel_reset_index()` закрывает дескриптор, освобождает PID-lock, удаляет
и заново захватывает — `rmtree` поверх удерживаемого лока раньше оставлял
полуудалённый индекс. Если удаление всё же упирается в `PermissionError`,
менеджер переключается на свежий путь БД, а `artifact_gc` пропускает
заблокированные файлы и сообщает о них вместо принудительного удаления. Папка,
которая отказывается удаляться, обычно означает, что её всё ещё держит другой
процесс MCP.

На Insider-сборках Windows DLL'ы UCRT API-set (`api-ms-win-crt-*`) отсутствуют, и
апстримный `llama-server.exe` не загружается; `_patch_dll_imports` переписывает
эти импорты на `ucrtbase.dll` перед первым запуском. Обход уровня машины, а не
требование.

## 8. История (только для контекста)

- **LSP-сервер для Zed** — отдельный процесс `mscodebase-lsp` был удалён (Zed
  требует Rust/WASM-адаптер для кастомных языковых серверов). Внутренний LSP
  *клиент* (basedpyright) выжил; мост LSP→MCP был удалён 2026-07-20, и
  инструментам `lsp_*` мост не нужен.
- **«MCP не перезапускается»** — в Zed не было авто-перезапуска для context
  servers, поэтому каждое изменение кода требовало полного выхода. Под OpenCode
  эквивалент — перезапуск сессии; правило (процесс держит старые модули) не
  изменилось.
- **Restricted Mode / доверие рабочей области** — диалог первого открытия в Zed.
  Не свойство этого сервера и не проверяется по коду (поведение хоста).
- **Разрешение проекта** — состояние SQLite в Zed всё ещё опрашивается, но уже не
  первым: явный аргумент → CWD → `PROJECT_PATH` → SQLite с несколькими рабочими
  областями → БД `workspaces` Zed → `ZED_WORKTREE_ROOT` → корень расширения
  (`project_resolution.resolve_project_root`). CWD идёт раньше баз данных,
  потому что это единственный сигнал уровня процесса при нескольких открытых
  окнах; см. `investigations/ACTIVE_WORKSPACE_RESOLUTION.md`.
- **Мигание консоли** — исправлено §2; оставлено здесь, потому что объясняет,
  зачем существует глобальный патч.

---

**Verified against:** `src/main.py` (silent_subprocess import, console title),
`src/core/silent_subprocess.py`, `src/core/process_titles.py`,
`src/providers/reranker/llama_runner.py` (`_popen_with_job`, DETACHED_PROCESS),
`src/mcp/tools/git_tools.py` (`GIT_TERMINAL_PROMPT`/`GIT_ASKPASS`/`GIT_PAGER`),
`src/core/modification_guard.py` (`_normalize_path`),
`src/sources/local_fs/windows.py` (`to_win_long_path`),
`src/core/sandbox/executor.py` (Popen + communicate), `src/core/artifact_gc.py`,
`src/core/intelligence/tools_reg.py` (`intel_reset_index`), `install.py`
(`MCP_EXE`, `_ensure_mcp_hardlink`), `start_server.bat`, `extension.toml`,
`.githooks/pre-commit`, `src/providers/reranker/llama_install.py`
(`_patch_dll_imports`), `src/core/project_resolution.py`,
`src/core/lsp_client.py`, `src/mcp/tools/lsp_tools.py`.
