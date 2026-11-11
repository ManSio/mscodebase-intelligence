# Где MSCodeBase хранит данные

> Написано 2026-11-12 и сверено с `install.py` v3.2, `src/core/artifact_paths.py`,
> `src/core/artifact_gc.py`, `src/core/log_manager.py`,
> `src/sources/git_url/__init__.py` и живым прогоном `install.py --doctor`.
> Числа измерены, не оценены.

Один вопрос, на который отвечает эта страница: *что установщик и сервер создали на
диске, кому принадлежит каждый путь и как это убрать?*

```bash
python install.py --doctor              # что стоит и сколько весит
python install.py --clean --dry-run     # пути и размеры; ничего не удаляет
python install.py --clean --yes         # удалить все слои ниже
```

## 1. Четыре слоя

| Слой | Путь (по умолчанию) | Кто создаёт | Что это |
|---|---|---|---|
| **Install root** | Windows `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`; macOS `~/Library/Application Support/Zed/extensions/…`; Linux `~/.local/share/zed/extensions/…` | `install.py`: `step_copy`, `step_venv`, `step_pip`, `step_llama`, `step_gguf`, `step_models`, `step_uninst` | Установленная копия: код, `venv/`, опциональные модели, деинсталлятор |
| **Data root** | `%LOCALAPPDATA%\mscodebase` (Win) · `$XDG_CACHE_HOME/mscodebase` или `~/.cache/mscodebase` (POSIX) | `src/core/artifact_paths.py::get_data_root` | Проектные кэши, логи, общие модели, клоны репозиториев |
| **Артефакты проекта** | `<project>/.mscodebase/chunks.db` | сервер (`MSCODEBASE_SQLITE_CHUNKS`) | FTS5 текстовый индекс проекта |
| **Конфиг хоста** | Zed: `%APPDATA%\Zed\settings.json` (`context_servers`) | `install.py` шаг `step_zedcfg` → `adapters/zed/zed_config.py` | Одна запись, по которой хост запускает сервер |

Оба корня переносимы: `MSCODEBASE_INSTALL_ROOT` и `MSCODEBASE_DATA_DIR`
(для второго по-прежнему принимается legacy-алиас `BASE_INDEX_DIR`).

## 2. Install root — что внутри

| Путь | Владелец | Назначение | Размер |
|---|---|---|---|
| `src/`, `scripts/`, `adapters/`, `locales/`, `docs/` | `step_copy` (`_sync_dir`) | Исполняемая копия репозитория (без `experiments/`) | несколько МБ |
| `venv/` | `step_venv`, `step_pip` | Python-окружение с запиненными зависимостями | ~1 ГБ |
| `venv/Scripts/mscodebase-mcp.exe` | entry point из `pyproject.toml [project.scripts]` | Команда stdio, которую запускают хосты | — |
| `.codebase_models/onnx/…` | `step_models` (только с `--with-models`) | ONNX-эмбеддер + реранкер | ~657 МБ |
| `llama_msvc/` | `step_llama` | бинарник llama-server для GGUF-пути | ~200 МБ |
| `models/*.gguf` | `step_gguf` (только с `--with-models`) | GGUF-эмбеддер + реранкер | ~700 МБ |
| `uninstall.bat` / `uninstall.sh` | `step_uninst` (`_build_uninstaller`) | Убивает сервер и удаляет этот каталог | < 1 КБ |
| `__mscodebase_ext__.marker` | `step_copy` | Сообщает `src/main.py`, что код запущен из установленной копии | < 1 КБ |

Замер на машине разработки (2026-11-12, модели установлены):
**3.0 ГБ на 28 429 файлах**, почти всё — `venv/` и модели.

## 3. Data root — что внутри

| Путь | Владелец | Назначение | Политика |
|---|---|---|---|
| `projects/<hash8>/graph.db` | `artifact_paths.get_graph_db_path` | PropertyGraph: файлы, символы, вызовы, импорты | удаляется вместе с папкой проекта |
| `projects/<hash8>/lancedb_v2/` | `get_index_dir`, `get_db_path` | Векторный индекс (только при включённом dense) | то же |
| `projects/<hash8>/intelligence/` | `get_intelligence_dir` | Память проекта: ADR, инциденты, техдолг | то же |
| `projects/<hash8>/metrics/` | `get_metrics_dir` | История задач индексации (ETA-модель) | то же |
| `projects/<hash8>/commit_memory/` | `get_commit_memory_dir` | Семантический кэш коммитов | то же |
| `projects/<hash8>/branches/` | `get_branches_dir` | Состояние индекса по веткам | то же |
| `projects/<hash8>/telemetry/` | `get_telemetry_dir` | Ежедневные JSON-снимки | файлы старше **90 дней** чистятся |
| `projects/<hash8>/summaries_cache/` | `get_summaries_cache_dir` | LLM-описания чанков | как папка проекта |
| `projects/<hash8>/progress.json` | `get_progress_file` | Контракт прогресса индексации | перезаписывается |
| `projects/<hash8>/action_receipts.jsonl` | `src/core/action_receipt.py` | Квитанции write-действий | verified 60 д / inconclusive 7 д (`purge`) |
| `logs/mscodebase-intelligence.log` | `log_manager.get_main_log_path` | Лог сервера | ротация 2 МБ × 3 файла, удаление через **7 дней** |
| `logs/crash.json` | `get_crash_log_path` | Последний краш resource-monitor | перезаписывается |
| `models/.codebase_models/onnx/…` | `get_onnx_models_base` | Общая копия скачанных моделей | только `--clean` |
| `repos/<hash8>/` | `get_repos_cache_dir` | Клоны удалённых репозиториев | LRU(5) + TTL 24 ч (`src/sources/git_url`) |
| `projects/<hash8>/` (целиком) | — | — | неактивные папки старше **30 дней** и пустые папки чистит `artifact_gc.prune_stale_artifacts()` |

Замер на машине разработки (2026-11-12): **302.9 МБ на 2 934 файлах**.
`--doctor` в реальном каталоге проекта, где есть ещё `chunks.db` (78 МБ) и локальная
копия модели (960 МБ), показал **4.3 ГБ на 31 385 файлах** по всем слоям.

## 4. Артефакты проекта

| Путь | Владелец | Назначение |
|---|---|---|
| `<project>/.mscodebase/chunks.db` | хранилище `MSCODEBASE_SQLITE_CHUNKS` | Текстовый индекс (FTS5/BM25) основного пути поиска; `--doctor` показывает число чанков |
| `<project>/.codebase_indices/`, `.codebase/`, `.mscodebase/telemetry/` | legacy | Переносятся в data root при первом открытии проекта (`artifact_paths.migrate_legacy_artifacts`) |
| `<project>/.codebase_models/` | `scripts/download_model.py` (staging) | Временная копия перед установкой модели в install root |

`experiments/**` намеренно исключён из индексации, поэтому индекс от него не растёт.

## 5. Политики

- **Модели — opt-in.** `install.py` по умолчанию text-first: без `--with-models` нет
  ни одного сетевого запроса за модель и ни одного модельного каталога.
  `--skip-models`/`--no-models` по-прежнему принимаются для старых скриптов.
- **Логи** ротируются по размеру (2 МБ, 3 файла) и удаляются через 7 дней
  (`log_manager._MAX_LOG_BYTES`, `_MAX_LOG_FILES`, `_LOG_RETENTION_DAYS`).
- **Телеметрия** — 90 дней; **неактивные папки проектов** — 30 дней
  (`artifact_gc.DEFAULT_*`); пустые папки проектов удаляются сразу.
- **Клоны репозиториев** — LRU из 5 с TTL 24 ч и лимитом 500 МБ после клона
  (`git_url.DEFAULT_MAX_CLONE_BYTES`).
- **Общий кэш моделей** (`data_root/models`) без TTL: удаляется только
  `install.py --clean`.
- **Удаление** — `install.py --clean --yes`: снимает все четыре слоя, кроме записи
  в конфиге хоста (удалите запись `mscodebase` из `settings.json` / `opencode.json` /
  `.mcp.json` сами, либо ставьте с `--no-zed` и не создавайте её).

## 6. Как читать вывод doctor

```
+ install_root              3.0 GB  28429 file(s)  C:\Users\<user>\AppData\Local\Zed\extensions\mscodebase-intelligence
+ data_root               302.9 MB   2934 file(s)  C:\Users\<user>\AppData\Local\mscodebase
+ project_chunks           78.0 MB      4 file(s)  D:\work\repo\.mscodebase
   ...

index           7278 chunk(s)  (D:\work\repo\.mscodebase\chunks.db)
total           4.3 GB over 31385 file(s)
```

`+` — существует, `-` — нет. `index missing` значит, что текстовый индекс для
текущего каталога ещё не построен (его создаст первый вызов
`codebase(action="index")`), а не что поиск сломан. `--json` печатает те же данные
для скриптов.
