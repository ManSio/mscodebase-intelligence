# Конфигурация

> Перевод: 2026-11-08, источник — docs/en/CONFIGURATION.md. Английская версия — канон.

> Переписано 2026-11-08 по `src/config/settings.py`, `.env.example` и живому
> дампу `get_config()`. Показанные значения по умолчанию — то, что возвращает код,
> **когда ничего не задано**. Числа, меняющиеся от репозитория к репозиторию (размер
> индекса, тайминги), живут в [FACTS.md](../FACTS.md), а не здесь.

## 1. Откуда берутся настройки

1. Значения читаются из переменных окружения в момент построения объекта конфигурации
   (`src/config/settings.py`, `get_config()`), поэтому изменение требует
   **перезапуска процесса**.
2. `.env` в корне проекта загружается через `python-dotenv`; это предназначенное место
   для локальных значений. `.env.example` документирует поддерживаемую поверхность.
3. Приоритет: окружение процесса > `.env` > встроенное значение по умолчанию.
4. Ничего из этого списка не читается из YAML/JSON-файла конфигурации — второго
   формата конфигурации нет.

Группы ниже повторяют dataclass'ы: `server`, `search`, `embedding`, `index`,
`performance`, `security`, `memory`.

## 2. Сервер, профиль и хранилище

| Переменная | По умолчанию | Эффект |
|---|---|---|
| `MSCODEBASE_MCP_PROFILE` | `core` | Поверхность инструментов: `core` = 17 инструментов, `full` = все 69 |
| `MSCODEBASE_MCP_TOOLS` | — | Явный allowlist через запятую; перекрывает профиль |
| `MSCODEBASE_EXECUTE_SCRIPT_ENABLED` | `false` | Регистрирует `execute_script` (RCE на хосте, по умолчанию выключено) |
| `MSCODEBASE_DATA_DIR` | `%LOCALAPPDATA%/mscodebase` (Windows) или `~/.cache/mscodebase` | Корень для графа, памяти, jobs, телеметрии, памяти коммитов |
| `MSCODEBASE_PROJECT_PATH` / `MSCODEBASE_PROJECT_ROOT` | не задано | Зафиксировать проект, когда хост не передаёт корень воркспейса |
| `MSCODEBASE_CHUNKS_DB` | `<project>/.mscodebase/chunks.db` | Переопределить расположение чанк-хранилища SQLite |
| `MSCODEBASE_LOG_DIR` | `<data_root>/logs` | Каталог логов сервера |
| `MSCODEBASE_LOCALE` | system / `en` | Язык строк интерфейса (`en`, `ru`) |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8765` | Слушатель Streamable-HTTP (stdio его игнорирует) |
| `LSP_HOST` / `MSCODEBASE_LSP_START_TIMEOUT` | `127.0.0.1` / — | Клиент LSP basedpyright |

Каталог на проект — `<data_root>/projects/<md5(project_path)[:8]>/`
(`src/core/artifact_paths.py`): `graph.db`, `intelligence/`, `commit_memory/`,
`telemetry/`. Внутри проекта лежат только `chunks.db` и `.mscodebase/`, и оба
в gitignore.

## 3. Retrieval (умолчания, которые важны)

| Переменная | По умолчанию | Эффект |
|---|---|---|
| `MSCODEBASE_DENSE_OFF` | `true` | Полностью пропускать dense/vector retrieval; только FTS5 + граф |
| `MSCODEBASE_SQLITE_CHUNKS` | `true` | Использовать чанк-хранилище SQLite/FTS5 для кандидатов |
| `MSCODEBASE_ONDEMAND_RERANK` | `false` | Переоценивать верхних кандидатов живыми эмбеддингами, когда есть провайдер; на один вызов: `investigate(rerank=true)` |
| `MSCODEBASE_ONDEMAND_RERANK_TOP_N` | `10` | Сколько кандидатов попадает в пул реранка |
| `MSCODEBASE_ONDEMAND_RERANK_MAX_CHARS` | `1600` | Обрезка текста перед эмбеддингом |
| `MSCODEBASE_DOCS_MARGIN` | `4.0` | Канал документов побеждает, когда `docs_score − code_score > margin` |
| `MSCODEBASE_AUGMENT_CHUNKS` | `true` | Дописывать `FILE:` / `SYMBOLS:` / `DOC:` в начало текста чанка |
| `MSCODEBASE_CODE_BM25` (+`_K1`, `_B`, `_STOPWORDS`) | `false` / `1.2` / `0.45` / `true` | BM25-оценка с учётом идентификаторов |
| `MSCODEBASE_RU_SYNONYMS` | `false` | Расширение русских терминов в английские термины кода |
| `MSCODEBASE_DEMOTE_NON_CODE` / `_DEMOTE_INTENT_AWARE` | `false` | Понижать вес документов/тестов для вопросов о коде |
| `MSCODEBASE_P3_ANCHOR` | `false` | Якорь пула по заголовкам модулей |
| `MSCODEBASE_TESTS_SIGNAL` | `false` | Добавлять покрывающие тесты к результатам по символам |
| `MSCODEBASE_LATE_ENRICHMENT` | `false` | Отложить обогащение графом до конца ранжирования |

`EXPERIMENTS/**` исключён из индексации через `FileGuard` независимо от этих флагов:
замороженные панели не должны никогда попадать в результаты поиска.

## 4. Индексация и производительность

| Переменная | По умолчанию | Эффект |
|---|---|---|
| `BASE_INDEX_DIR` | `.codebase_indices` | Имя каталога legacy-индекса |
| `LANCEDB_VERSION` | `v2` | Раскладка векторного хранилища (используется только при включённом dense) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `512` / `100` | Резервное разбиение на чанки по строкам |
| `INDEX_BATCH_SIZE` | `100` | Файлов на пакет индексации |
| `MSCODEBASE_PARSE_TIMEOUT_SEC` | — | Бюджет разбора на файл |
| `MSCODEBASE_LINK_TIMEOUT_SEC` | — | Бюджет прохода связывания графа |
| `MSCODEBASE_REINDEX_STALL_SEC` | — | Watchdog зависаний для долгих переиндексаций |
| `MSCODEBASE_IVF_MAX_ABANDONS` | — | Автоотключение IVF после N неудачных optimize/create |
| `MSCODEBASE_MAX_FILE_SIZE_MB` (security) | `10` | Файлы больше этого пропускаются |

## 5. Провайдеры (все опциональны)

Text-first поиску не нужен ни один из них; они используются для реранка, legacy
dense-пути и LSP.

| Переменная | По умолчанию | Эффект |
|---|---|---|
| `LLAMA_CPP_ENABLED` | включено, если не `false` | Локальный сервер llama.cpp для эмбеддингов/реранка |
| `LLAMA_CPP_PORT` / `RERANKER_PORT` | `8080` / `8081` | Эндпоинты llama.cpp и BGE-M3 |
| `LM_STUDIO_HOST` / `LM_STUDIO_PORT` | `127.0.0.1` / `1234` | Провайдер LM Studio |
| `OLLAMA_HOST` / `OLLAMA_PORT` | `127.0.0.1` / `11434` | Провайдер Ollama |
| `EMBEDDING_MODEL` / `MODEL_NAME` / `EMBEDDING_DIMENSION` | `qwen3-embedding` / `multilingual-e5-small-int8` / `384` | Выбор модели провайдера |
| `MSCODEBASE_ONNX_PROVIDER` | — | Принудительно задать конкретный execution provider ONNX |
| `MSCODEBASE_REMOTE_TOKEN` / `_REMOTE_RATE_LIMIT_RPS` | — | Аутентификация и лимит частоты для удалённого провайдера |
| `MSCODEBASE_LANGUAGE_PACK` | `false` | Включить tree-sitter-language-pack (скачивает парсеры при первом использовании) |

## 6. Безопасность и доверие

| Переменная | По умолчанию | Эффект |
|---|---|---|
| `MSCODEBASE_TRUSTED_ROOTS` | корень проекта | Пути, которые инструменты могут читать/писать |
| `MSCODEBASE_RESTRICTED_READ` | выкл. | Ограничить чтение доверенными корнями |
| `MSCODEBASE_SANDBOX_MODE` | выкл. | Дополнительные ограничения записи |
| `MSCODEBASE_ALLOW_SELF_INDEX` | выкл. | Разрешить индексировать собственный чекаут сервера (только CI) |
| `MSCODEBASE_ACK_SECRET` | вычисляется | HMAC-секрет для токенов `ack_impact` |

Детали безопасности и модель угроз: [SECURITY.md](SECURITY.md).

## 7. Хуки и гейты

| Переменная | По умолчанию | Эффект |
|---|---|---|
| `MSCODEBASE_STALE_GATE` | `block` | `block` / `off` для гейта дрейфа документации в плагине OpenCode |
| `MSCODEBASE_ISOLATION_GATE` | `advisory` | `advisory` / `block` / `off` для изоляции графа |
| `MSCODEBASE_GATE_LOG` | `%TEMP%/opencode/mscodebase_gate.log` | Путь лога плагина |
| `MSCODEBASE_PY` | `<repo>/venv/Scripts/python.exe` | Интерпретатор, который вызывает плагин |
| `MSCODEBASE_AUTODOC_LEDGERS` | выкл. | Разрешить AutoDocUpdater переписывать реестры, принадлежащие агенту |
| `MSCB_PRECOMMIT_FAST` / `MSCB_PRECOMMIT_GATE_TIMEOUT` | — / `900` | Ускорение pre-commit и бюджет |

Что проверяет каждый гейт — см. [HOOKS_AND_GATES.md](HOOKS_AND_GATES.md).

## 8. Как проверить изменение

```bash
python -c "from src.config.settings import get_config; c=get_config(); print(c.search.dense_off, c.search.docs_margin)"
```

Конфигурация строится один раз на процесс: перезапустите MCP-хост после правки
`.env`, затем `get_health_report()` должен показать новые значения (или хотя бы
не старое состояние провайдера).
