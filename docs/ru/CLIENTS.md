# Клиенты и развёртывание

> Перевод: 2026-11-12, источник — docs/en/CLIENTS.md. Английская версия — канон.

> Переписано 2026-11-12. Описывает, как сервер запускается каждым хостом и что
> на самом деле устанавливает `install.py`. Проверено по `install.py`,
> `adapters/clients/snippets.py`, `src/main.py`, `extension.toml`,
> `.opencode/plugin/`, `tests/test_install_cli.py` и
> `scripts/verify_client_snippets.py` (последний запускает сервер из каждого сниппета).

## 1. Что такое сервер

Python MCP-сервер (`src/main.py`, entry point `mscodebase-mcp = src.main:main` в
`pyproject.toml`), говорящий по stdio, плюс опциональная точка входа
Streamable-HTTP (`src/remote_main.py`) для docker/удалённого развёртывания.
Сам по себе он не плагин редактора — хост запускает его и общается по MCP.

С v3.2 установщик **нейтрален к хосту**: на диск кладётся обычное Python-окружение,
и любой MCP-клиент может его запустить. Zed — один из адаптеров, не обязательный шаг.

## 2. Установить сервер один раз

```bash
cd <repo-root>
python install.py                     # venv + зависимости + код (шаги моделей спрашивают)
python install.py --no-zed            # не трогать настройки Zed вообще
python install.py --sync-only         # после правки кода: только копирование кода
```

Куда ставится (по умолчанию исторический путь; к Zed относится только имя):

```
Windows : %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence
macOS   : ~/Library/Application Support/Zed/extensions/mscodebase-intelligence
Linux   : ~/.local/share/zed/extensions/mscodebase-intelligence
```

Перенести в любое место: `MSCODEBASE_INSTALL_ROOT=<path>`. Кэши, логи и артефакты
проектов лежат отдельно (`MSCODEBASE_DATA_DIR`, по умолчанию
`%LOCALAPPDATA%\mscodebase`).

Альтернатива без установщика (любой менеджер, дающий console scripts):

```bash
pipx install .        # или: uv tool install .
mscodebase-mcp        # entry point появляется в PATH
```

## 3. Получить конфиг для своего хоста

Не пишите команду и окружение руками — напечатайте их:

```bash
python install.py --print-config --client generic      # любой mcpServers-хост
python install.py --print-config --client opencode
python install.py --print-config --client zed
python install.py --print-config --client claude-code
python install.py --print-config --client cursor
```

Каждая команда печатает один JSON-объект и ничего больше, поэтому вывод можно
перенаправить: `python install.py --print-config --client cursor > .cursor/mcp.json`.
В сниппете уже разрешённый интерпретатор, `-u -m src.main`, `PYTHONPATH`,
`PROJECT_PATH` и `PYTHONUTF8=1`.

### 3.1 Универсальный MCP-клиент (`mcpServers`)

Файл: там, где хост читает свой MCP-конфиг. `<project>` — рабочее пространство,
которое нужно индексировать (это и есть `PROJECT_PATH`).

```json
{
  "mcpServers": {
    "mscodebase": {
      "command": "<install-root>/venv/Scripts/mscodebase-mcp.exe",
      "args": ["-u", "-m", "src.main"],
      "env": {
        "PYTHONPATH": "<install-root>",
        "PROJECT_PATH": "<project>",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

### 3.2 OpenCode

Файл: `opencode.json(c)` в корне проекта или в `~/.config/opencode/`. OpenCode V2
держит имена серверов под **`mcp.servers`** — плоская V1-форма `mcp.<name>` ещё
принимается для миграции, но в новых конфигах не используется (источник:
<https://opencode.ai/docs/mcp-servers>, «V2 does not place server names directly
under `mcp`»):

```json
{
  "mcp": {
    "servers": {
      "mscodebase": {
        "type": "local",
        "command": ["<install-root>/venv/Scripts/mscodebase-mcp.exe", "-u", "-m", "src.main"],
        "environment": {
          "PYTHONPATH": "<install-root>",
          "PROJECT_PATH": "<project>",
          "PYTHONUTF8": "1"
        }
      }
    }
  }
}
```

Или пусть запишет CLI (сохраняет остальные настройки):

```bash
opencode mcp add mscodebase -- <install-root>/venv/Scripts/mscodebase-mcp.exe -u -m src.main
```

`PROJECT_PATH` можно заменить переменной рабочего пространства, если хост её
раскрывает. Изменения конфига применяются без перезапуска (`/reload` — принудительно).
Проектная автоматика — `.opencode/plugin/mscodebase_gate.ts` и
`.opencode/command/*.md` (см. [HOOKS_AND_GATES.md](HOOKS_AND_GATES.md)).

### 3.3 Zed (поддерживается, но не основной)

Либо установщик патчит `settings.json` (шаг по умолчанию, отключается `--no-zed`),
либо вставьте напечатанный сниппет под `context_servers`:

```json
{
  "context_servers": {
    "mscodebase": {
      "command": "<install-root>/venv/Scripts/mscodebase-mcp.exe",
      "args": ["-u", "-m", "src.main"],
      "env": {
        "PYTHONPATH": "<install-root>",
        "PROJECT_PATH": "$ZED_WORKTREE_ROOT",
        "PYTHONUTF8": "1"
      },
      "enabled": true
    }
  }
}
```

Ключи совпадают с тем, что пишет `adapters/zed/zed_config.py::_make_server_entry`.
Windows/Zed-особенности: [ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md).

### 3.4 Claude Code

Файл `.mcp.json` в корне проекта — та же форма `mcpServers`, что в 3.1.
Эквивалентная CLI-форма:

```bash
claude mcp add-json mscodebase '{"command":"<install-root>/venv/Scripts/mscodebase-mcp.exe","args":["-u","-m","src.main"],"env":{"PYTHONPATH":"<install-root>","PROJECT_PATH":"<project>","PYTHONUTF8":"1"}}'
```

### 3.5 Cursor

Файл: `.cursor/mcp.json` (или `~/.cursor/mcp.json` для всех проектов), форма
`mcpServers` как в 3.1:

```json
{
  "mcpServers": {
    "mscodebase": {
      "command": "<install-root>/venv/Scripts/mscodebase-mcp.exe",
      "args": ["-u", "-m", "src.main"],
      "env": {
        "PYTHONPATH": "<install-root>",
        "PROJECT_PATH": "<project>",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

## 4. Проверить сниппет без GUI

```bash
python scripts/verify_client_snippets.py --install-root <install-root>
```

Скрипт рендерит сниппет каждого клиента ровно так же, как установщик, запускает эту
команду во временном каталоге, делает MCP-хендшейк `initialize` + `tools/list` и
печатает строку на клиента. Ожидаемо (замер 2026-11-12):

```
generic      PASS: server=MSCodebase Intelligence Server tools=17
opencode     PASS: server=MSCodebase Intelligence Server tools=17
zed          PASS: server=MSCodebase Intelligence Server tools=17
claude-code  PASS: server=MSCodebase Intelligence Server tools=17
cursor       PASS: server=MSCodebase Intelligence Server tools=17
```

`tools=17` — профиль `core` по умолчанию (зарегистрировано 69, видно 17); таблица
профилей — в README.

Из панели агента, по порядку:

```
tool_help()                                   # профиль + видимые/скрытые инструменты
get_health_report()                           # индекс, провайдеры, ресурсы
codebase(action="index", path="status")       # chunks > 0?
```

## 5. Цикл обновления

Установленная копия — не git-чекаут:

```
правка src/... -> python install.py --sync-only -> перезапуск хоста (сессия / окно)
```

Без перезапуска старый процесс продолжает отдавать старый код; без sync нового кода
нет в установленном месте. Нужны оба шага. Если сервер запускается прямо из чекаута —
укажите его в `command`/`PYTHONPATH` и sync не нужен.

## 6. Remote / Docker

`src/remote_main.py` отдаёт Streamable HTTP с bearer-токеном;
`deploy/docker/Dockerfile` + `docker-compose.yml` собирают образ, CI гоняет
job `docker-build`. Docker — вариант развёртывания, не локальное требование.

```json
{
  "mcpServers": {
    "mscodebase-remote": {
      "type": "http",
      "url": "http://<host>:8089/mcp",
      "headers": { "Authorization": "Bearer <MSCODEBASE_REMOTE_TOKEN>" }
    }
  }
}
```

## 7. Скрипты и CI (без MCP)

```bash
python -m src.cli <tool> '<json-args>' [--project <root>]
echo '<json>' | python -m src.cli <tool> -
```

CLI использует тот же DI-контейнер и те же классы инструментов; диспетчер — это
отобранный allowlist (`src/cli.py`), а не все 69 инструментов.

## 8. Что указать в баг-репорте

Укажите хост (OpenCode / Zed / Claude Code / Cursor / generic / CLI), профиль
(`core`/`full`) и способ запуска сервера. Отчёт без этих трёх вещей не отличает
«инструмент скрыт профилем» от «инструмент сломан».
