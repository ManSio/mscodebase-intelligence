# Системные требования

> Перевод: 2026-11-08, источник — docs/en/SYSTEM_REQUIREMENTS.md. Английская версия — канон.

[English](../en/SYSTEM_REQUIREMENTS.md) · [Русский](SYSTEM_REQUIREMENTS.md) · [中文](../zh/SYSTEM_REQUIREMENTS.md)

> Версия 3.5.0. Измеренные значения ниже указывают машину и дату. Там, где
> ничего не измерялось, это сказано прямо. Цифры по чанкам/файлам/таймингам
> здесь не повторяются — они живут в `docs/FACTS.md`, где также указана команда,
> которая их пересоздаёт.

---

## 1. Обязательное

| Компонент | Требование | Источник истины |
|---|---|---|
| Python | **3.14 или новее** | `requires-python = ">=3.14"` в `pyproject.toml` |
| ОС | Windows (проверено) или Linux (тестируется в CI); macOS не тестировался | матрица `.github/workflows/ci.yml`: `ubuntu-latest` + `windows-latest` |
| Интерпретатор | только CPython | wheel закреплены через `==` в `pyproject.toml` |
| Диск | свободное место для хранилища чанков + data root | см. §3 |
| Хост | OpenCode (основной) или расширение Zed | `install.py`, `extension.toml` |

Python 3.10–3.13 **не** поддерживаются, хотя старые классификаторы в
`pyproject.toml` всё ещё перечисляют 3.10–3.12. CI ставит только 3.14.

Для дефолтного text-first runtime не нужны ни GPU, ни Docker, ни WSL, ни доступ в
сеть. Docker-образы собираются в CI (задача `docker-build`) из `deploy/docker/`;
запускать их локально необязательно и к обычной настройке MCP это отношения не
имеет.

## 2. Хост

OpenCode запускает MCP-сервер напрямую:

```
%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\venv\Scripts\mscodebase-mcp.exe -u -m src.main
```

с `PYTHONPATH`, указывающим на каталог расширения, и `PROJECT_PATH`, указывающим
на рабочую область. На Windows `mscodebase-mcp.exe` — это NTFS hardlink на
`pythonw.exe` (создаётся один раз через `install.py`), поэтому консольное окно не
появляется. Расширение Zed (`extension.toml`,
`capabilities = ["context_servers"]`) использует
`venv\Scripts\pythonw.exe -u -m src.main` с `PYTHONUTF8=1`.

Следствие: оба хоста запускают **скопированный** код из
`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`, а не этот checkout.
После правки `src/` выполните `python install.py --sync-only` и перезапустите
хост.

## 3. Диск (измерено на этом репозитории, 2026-11-08)

| Артефакт | Размер | Примечание |
|---|---:|---|
| `<project>/.mscodebase/chunks.db` | **77.9 MiB** | текст + индекс FTS5 для этого репо; число чанков в `docs/FACTS.md` |
| `<data_root>/` (11 папок проектов) | **74.3 MiB** | граф, память, телеметрия, кеш коммитов, остаточные таблицы LanceDB |
| `.codebase_models/` (опционально) | **960.1 MiB** | файлы моделей ONNX + GGUF, присутствующие на этой машине |
| `models/` (опционально) | **839.4 MiB** | модели GGUF, скопированные для расширения |

Практическое правило: текстовый индекс пропорционален индексируемому корпусу и
примерно на порядок меньше векторного индекса по тому же корпусу. Опциональные
каталоги моделей доминируют, когда они есть, и отсутствуют в остальных случаях.
`install.py` скачивает модели только с `--with-models` (`models_enabled()` в
`install.py`); дефолт — text-first без вопросов и без загрузки, поэтому установка
только с текстом занимает размер кода плюс хранилище чанков.

`artifact_paths.check_disk_space()` предупреждает, когда на data root остаётся
меньше **500 MB** (`MIN_FREE_DISK_MB`); гейт в CI падает ниже 1 GB.
`artifact_gc` вычищает неактивные папки проектов, телеметрию старше 90 дней и
старые логи в фоновом потоке через 3 s после старта.

## 4. Память

**В этом проходе не измерялась.** Здесь не приводится цифра RSS, потому что в этой
сессии на контролируемой конфигурации замер не делался; старые числа в истории
этого файла (сотни MB для серверов llama.cpp, гигабайты для in-process ONNX)
описывали другой стек провайдеров и не должны переиспользоваться.

Что можно утверждать по коду: дефолтный text-first путь не загружает модель в
MCP-процесс. Память растёт вместе с page cache SQLite, буферами разобранных
чанков во время переиндексации и соединением PropertyGraph. Если вы включаете
опциональный провайдер, процесс модели отдельный (`llama-server.exe` для GGUF,
`onnx_server.py` для ONNX или внешний экземпляр LM Studio/Ollama), поэтому его
след — это не след MCP-процесса.

Чтобы измерить на своей машине:

```powershell
Get-Process | Where-Object { $_.ProcessName -in @('mscodebase-mcp','python','pythonw') } |
  Select-Object ProcessName, Id, @{n='RSS_MB';e={[math]::Round($_.WorkingSet64/1MB,1)}}
```

Если публикуете число, записывайте команду и вывод.

## 5. CPU

x86_64 — единственная архитектура, задействованная в измеренных прогонах здесь.
ARM64 не тестировался. Требования к возможностям CPU у закреплённого wheel
`onnxruntime==1.27.0` (AVX2 и подобные) на этом проекте **не проверялись**,
поэтому такое требование не заявляется.

Грамматики Tree-sitter поставляются как `abi3` wheel, поэтому у разбора нет
требований к возможностям CPU сверх обычной сборки CPython.

## 6. Опциональные провайдеры и их значения по умолчанию

Все loopback, все опциональные, все выключены, пока вы их не включите:

| Провайдер | Эндпоинт | Env |
|---|---|---|
| LM Studio | `http://127.0.0.1:1234` | `LM_STUDIO_HOST`, `LM_STUDIO_PORT` |
| Ollama | `http://127.0.0.1:11434` | `OLLAMA_HOST`, `OLLAMA_PORT` |
| эмбеддер llama.cpp | `127.0.0.1:8080` | `LLAMA_CPP_PORT` |
| реранкер llama.cpp | `127.0.0.1:8081` | `LLAMA_CPP_RERANK_PORT` |
| ONNX-сервер | `127.0.0.1:1235` | `ONNX_SERVER_PORT` |

GPU имеет значение только для Vulkan-бэкенда llama.cpp (`LLAMA_BACKEND=vulkan`;
дефолт в коде — `msvc`, то есть CPU, и Vulkan используется только при явной
установке) или для execution providers ONNX DirectML/CUDA
(`MSCODEBASE_ONNX_PROVIDER`). Дефолтный путь никогда его не требует.

`basedpyright` нужен только для шести инструментов `lsp_*` и для
`check_types=True` на операциях записи. Без `basedpyright-langserver` в `PATH`
эти инструменты возвращают понятное сообщение
«LSP недоступен (basedpyright не найден)», и остальной сервер не затронут.

## 7. Сеть

По умолчанию офлайн. Сеть используется только для (a) скачиваний моделей/бинарников
через `install.py`, которые вы одобрили, (b) `pip install`, (c) опционального
`tree-sitter-language-pack` (`MSCODEBASE_LANGUAGE_PACK=true`), чьи дополнительные
парсеры подтягиваются при первом использовании, и (d) случая, когда вы сами
направили провайдера на удалённый эндпоинт. С выключенным флагом 31 грамматика
берётся из закреплённых wheel.

## 8. Быстрый preflight

```powershell
python --version                     # must print 3.14.x
python -c "import src.main"          # dependencies importable
python -m pytest tests/ -q           # default selection (slow/benchmark excluded)
```

Затем внутри хоста: `tool_help()` для видимой поверхности и
`get_health_report()` для индекса, провайдеров и диска.

---

**Verified against:** `pyproject.toml`, `.github/workflows/ci.yml`,
`src/core/artifact_paths.py` (`MIN_FREE_DISK_MB`, data-root layout),
`src/core/artifact_gc.py` (retention defaults), `src/config/settings.py`
(provider hosts and ports), `extension.toml`, `install.py`,
`src/providers/reranker/llama_runner.py` (`RERANK_PORT`), `docs/FACTS.md`,
`AGENTS.md` §0.5. Disk sizes measured with `Get-Item` / `Get-ChildItem` on this
checkout, 2026-11-08. RAM: not measured.
