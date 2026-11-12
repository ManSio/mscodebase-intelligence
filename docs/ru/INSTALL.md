# Установка MSCodebase Intelligence

> Перевод: 2026-11-12, источник — docs/en/INSTALL.md. Английская версия — канон.

<p align="center">
  <img src="../../logo/baner.png" alt="MSCodeBase Banner" width="100%"/>
</p>

[🇬🇧 English](../en/INSTALL.md) • [🇷🇺 Русский](INSTALL.md) • [🇨🇳 中文](../zh/INSTALL.md)

> Переписано 2026-11-12 по `install.py` v3.2. Сервер — локальный MCP-сервер, а
> установщик **нейтрален к хосту**: он создаёт обычное Python-окружение, и любой
> MCP-хост его запускает. Zed — опциональный адаптер. Дефолтная установка
> **text-first**: без эмбеддингов, GPU, сети и без загрузки моделей, если их не
> попросили явно.

---

## 1. Требования

| Компонент | Требование |
|---|---|
| ОС | Windows 10+ (проверенная платформа), Linux (CI), macOS |
| Python | **3.14+** (тестируется только 3.14) |
| RAM | 4 ГБ; 8 ГБ+ при включении локальных моделей |
| Диск | ~1.5 ГБ без моделей (основное — venv); +~650 МБ с `--with-models` |
| Хост | OpenCode, Zed, Claude Code, Cursor или любой MCP-клиент |
| Опционально | LM Studio / Ollama / llama.cpp для реранка и legacy dense-пути |

Docker и WSL на машине разработчика не нужны. Сборка контейнера — вариант
развёртывания (`deploy/docker/`).

## 2. Установка

```bash
cd <repo-root>
python install.py                     # venv + зависимости + код; text-first
python install.py --with-models       # то же + ONNX/GGUF модели (~657 МБ, сеть)
python install.py --no-zed            # вообще не трогать настройки Zed
python install.py --yes               # без вопросов: принимать каждый шаг
```

В Windows также есть `install.bat`; в Linux/macOS — `install.sh`. Установщик:

1. останавливает старые процессы MCP/llama, чтобы работал именно новый код;
2. создаёт/обновляет виртуальное окружение и ставит запиненные зависимости;
3. копирует код в каталог установки (`--sync-only` пропускает 1–2 и делает только это);
4. опционально (адаптер Zed) пишет запись `context_servers` в `settings.json`;
5. пишет `uninstall.bat` / `uninstall.sh` в каталог установки.

Каталог установки по умолчанию (имя историческое, к Zed относится только оно):

```
Windows : %LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence
macOS   : ~/Library/Application Support/Zed/extensions/mscodebase-intelligence
Linux   : ~/.local/share/zed/extensions/mscodebase-intelligence
```

Перенос: `MSCODEBASE_INSTALL_ROOT=<path>`; кэши/логи/артефакты — в
`MSCODEBASE_DATA_DIR` (по умолчанию `%LOCALAPPDATA%\mscodebase`). Что куда пишется и
сколько весит (с замерами): [DATA_MAP.md](DATA_MAP.md).

Без установщика (любой менеджер, дающий console scripts, entry point
`mscodebase-mcp = src.main:main`):

```bash
pipx install .      # или: uv tool install .
```

## 3. Цикл обновления (часть, которую обычно путают)

Установленная копия живёт вне репозитория:

```bash
python install.py --sync-only    # копирует код, чистит __pycache__, без pip/моделей
# затем перезапуск хоста: сессия OpenCode, окно Zed, процесс CLI
```

`--sync-only` (алиас `--sync`) — быстрый путь после каждого изменения исходников.
Пропуск перезапуска оставляет работать старый процесс; пропуск синхронизации
оставляет в установленном каталоге старый код. Нужно и то, и другое.

## 4. Подключение хоста

Не пишите команду руками — напечатайте её и вставьте в конфиг хоста.

```bash
python install.py --print-config --client generic      # хосты формы mcpServers
python install.py --print-config --client opencode
python install.py --print-config --client zed
python install.py --print-config --client claude-code
python install.py --print-config --client cursor
```

Имена файлов, готовый JSON для копипаста и проверка запуска
(`python scripts/verify_client_snippets.py`) — в [CLIENTS.md](CLIENTS.md).

## 5. Проверка

Из панели агента, в этом порядке:

```
tool_help()                                   # профиль + видимые/скрытые инструменты
get_health_report()                           # индекс, провайдеры, ресурсы
codebase(action="index", path="status")       # chunks > 0?
```

Если текстовый индекс отсутствует или устарел:

```bash
python scripts/reindex_text_only.py --project .   # чанки + граф, без эмбеддингов
python scripts/rebuild_graph.py                   # только граф
```

Затем перезапустите сервер, чтобы новый процесс открыл пересобранные хранилища.
Замеренные числа для этого репозитория — в [FACTS.md](../FACTS.md).

## 6. Что на диске и как это убрать

```bash
python install.py --doctor            # версии, пути, размеры, состояние индекса (--json)
python install.py --clean --dry-run   # каждый артефакт с размером; ничего не удаляет
python install.py --clean             # спрашивает подтверждение, затем удаляет
python install.py --clean --yes       # без вопросов (скрипты)
```

`--clean` удаляет каталог установки (код + venv + модели + деинсталлятор), data root
(`projects/`, `logs/`, `models/`, `repos/`) и в текущем проекте `.mscodebase`,
`.codebase_indices`, `.codebase`, `.codebase_models`. Он отказывается удалять путь,
который является исходным чекаутом, корнем файловой системы или домашним каталогом,
и сообщает об остатке (заблокированные файлы работающим хостом) с ненулевым кодом
возврата. Политики кэшей (ротация логов, чистка 7/30/90 дней, LRU(5)+24 ч для клонов)
— в [DATA_MAP.md](DATA_MAP.md).

## 7. Удаление

```bash
python install.py --clean --yes       # все слои, проверено: 0 байт остатка
./uninstall.bat                       # Windows: генерируется шагом step_uninst
```

Сгенерированный деинсталлятор убивает процессы сервера и удаляет только каталог
установки. `--clean` — полная версия. Ни то, ни другое не трогает конфиг хоста:
удалите запись `mscodebase` из `settings.json` (Zed), `opencode.json` (OpenCode) или
`.mcp.json` / `.cursor/mcp.json` сами.

## 8. Опциональные провайдеры

| Провайдер | Зачем | Где |
|---|---|---|
| llama.cpp (GGUF) | реранк по запросу, legacy dense-путь | `LLAMA_CPP_PORT` (8080), реранкер 8081 |
| LM Studio | эмбеддинги/реранк по HTTP | `LM_STUDIO_HOST:1234` |
| Ollama | эмбеддинги/реранк по HTTP | `OLLAMA_HOST:11434` |
| basedpyright | шесть инструментов `lsp_*` | PATH или venv расширения |

Ни один из них не нужен для дефолтного text-first ответа. Настройки провайдеров:
[CONFIGURATION.md](CONFIGURATION.md).

## 9. Диагностика проблем

| Симптом | Вероятная причина |
|---|---|
| Ожидаемого инструмента нет | профиль `core` — выполните `tool_help()`, переключитесь на `full` |
| «Ничего не найдено» на любой запрос | пустой индекс — проверьте `codebase(action="index", path="status")` |
| Новый код не даёт эффекта | нет `--sync-only` и/или перезапуска хоста |
| Сервер стартует, инструменты уходят в таймаут | завис провайдер или LSP — см. [GRACEFUL_DEGRADATION.md](GRACEFUL_DEGRADATION.md) |
| Мигают консольные окна в Windows | подпроцесс без `CREATE_NO_WINDOW` — см. [ZED_WINDOWS_QUIRKS.md](ZED_WINDOWS_QUIRKS.md) |
| `--clean` оставил файлы | их держит запущенный хост (блокировки) — остановите хост и повторите |
