# Клиенты и развёртывание

> Перевод: 2026-11-08, источник — docs/en/CLIENTS.md. Английская версия — канон.

> Переписано 2026-11-08. Описывает, как сервер запускается каждым хостом и что
> на самом деле устанавливает `install.py`. Проверено по `install.py`, `extension.toml`,
> `adapters/clients/*`, `.opencode/plugin/` и живому конфигу OpenCode на машине
> разработки.

## 1. Что такое сервер

Python MCP-сервер (`src/main.py`), говорящий по stdio, плюс опциональная точка
входа Streamable-HTTP (`src/remote_main.py`) для docker/удалённого развёртывания.
Сам по себе он не плагин редактора — хост запускает его и общается по MCP.

## 2. OpenCode (основной)

OpenCode запускает сервер как локальный MCP-сервер. На машине разработки запись
выглядит так (пути сокращены):

```jsonc
"mcp": {
  "mscodebase-intelligence": {
    "type": "local",
    "command": [
      "C:\\Users\\<user>\\AppData\\Local\\Zed\\extensions\\mscodebase-intelligence\\venv\\Scripts\\mscodebase-mcp.exe",
      "-u", "-m", "src.main"
    ],
    "environment": {
      "PYTHONPATH": "C:\\Users\\<user>\\AppData\\Local\\Zed\\extensions\\mscodebase-intelligence",
      "PROJECT_PATH": "${workspaceRoot}",
      "PYTHONUTF8": "1"
    }
  }
}
```

Два факта, которые важны:

1. **Установленная копия** живёт в каталоге расширения, а не в git-чекауте.
   Именно `install.py` кладёт туда актуальный код (см. §5).
2. Каталог называется `…\Zed\extensions\…` по историческим причинам. Это обычное
   окружение Python; OpenCode использует его так же, как расширение Zed.

Локальная для проекта конфигурация: `.opencode/plugin/mscodebase_gate.ts` (хуки
коммитов) и `.opencode/command/*.md` (переиспользуемые команды агента). См.
[HOOKS_AND_GATES.md](HOOKS_AND_GATES.md).

## 3. Zed (поддерживается, но не основной)

Расширение Zed (`extension.toml`, `__mscodebase_ext__.marker`) запускает тот же
сервер из того же каталога. Поведение, специфичное для Windows/Zed, описано в
[ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md); относитесь к Zed как к
альтернативному хосту, а не как к эталонной реализации.

## 4. Другие MCP-клиенты

`adapters/clients/` содержит готовые формы для stdio и Streamable-HTTP:

| Файл | Клиент | Секция |
|---|---|---|
| `claude.code.mcp.json` | Claude Code / Desktop | `mcpServers` |
| `vscode.mcp.json` | VS Code (`.vscode/mcp.json`) | `servers` |

Подставьте `<path-to-venv>`, `<path-to-repo>`, `<path-to-project>`. HTTP-вариант
указывает на `http://<host>:8089/mcp` и требует
`Authorization: Bearer <MSCODEBASE_REMOTE_TOKEN>`; удалённый сервер собирается из
`deploy/docker/`.

Для скриптов и CI MCP вообще не нужен:

```bash
python -m src.cli <tool> '<json-args>' [--project <root>]
```

CLI использует тот же DI-контейнер и те же классы инструментов; его диспетчер —
отобранный allowlist (`src/cli.py`), а не вся поверхность из 69 инструментов.

## 5. Установка и цикл обновления

```bash
python install.py            # interactive full install (venv, pip, llama.cpp, models)
python install.py --sync-only  # code only: copy + drop __pycache__, no pip/models
```

`install.py` копирует `src/`, скрипты и вспомогательные файлы в
`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence` (или платформенный
эквивалент) и сохраняет venv расширения. После изменения кода:

```
edit → python install.py --sync-only → restart the host (OpenCode session / Zed window)
```

Без перезапуска старый процесс продолжает отдавать старый код; без синхронизации
нового кода нет на диске в установленном каталоге. Нужны оба шага.

## 6. Удалённо / Docker

`src/remote_main.py` открывает Streamable HTTP с аутентификацией по bearer-токену;
`deploy/docker/Dockerfile` + `docker-compose.yml` собирают образ, а CI гоняет job
`docker-build`. Docker — вариант развёртывания, а не локальное требование.

## 7. Какого клиента указывать в отчёте о баге

Укажите хост (OpenCode / Zed / Claude / VS Code / CLI), профиль
(`core`/`full`) и то, как был запущен сервер. Отчёт без этих трёх пунктов не
позволяет отличить «инструмент скрыт профилем» от «инструмент сломан».
