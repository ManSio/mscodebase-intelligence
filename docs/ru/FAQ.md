# FAQ — MSCodeBase Intelligence

> Перевод: 2026-11-08, источник — docs/en/FAQ.md. Английская версия — канон.

[English](../en/FAQ.md) · [Русский](FAQ.md) · [中文](../zh/FAQ.md)

Ответы сняты с кода в этом репозитории (версия 3.5.0), а не со старых
blog-постов. Цитируемые числа живут в `docs/FACTS.md`.

---

## Нужны ли эмбеддинги для поиска?

Нет, по умолчанию не нужны. Дефолтный runtime — **text-first**:

| Настройка | Значение по умолчанию | Эффект |
|---|---|---|
| `MSCODEBASE_DENSE_OFF` | `true` | dense-уровня нет: запрос никогда не эмбеддится для векторного поиска |
| `MSCODEBASE_SQLITE_CHUNKS` | `true` | чанки лежат текстом в SQLite FTS5, векторы не хранятся |
| `MSCODEBASE_ONDEMAND_RERANK` | `true` | top-N кандидатов эмбеддятся на лету во время запроса, **если** эмбеддер отвечает |

Кандидаты приходят из SQLite FTS5 (ранжирование по BM25) плюс из PropertyGraph.
Индексация тоже пропускает эмбеддинги: `Indexer.index_project()` уходит в
`_index_text_only_project()`, когда `dense_off` истинно.

Если эмбеддер недостижим, on-demand реранк выбрасывает исключение, оно
перехватывается, и объединённый пул возвращается в порядке RRF
(`engine.py::_apply_ondemand_reranker_async`, «Fallback к RRF-порядку»). Поиск
всё равно работает — просто перестаёт переупорядочивать по косинусу.

## Почему результаты выглядят лексическими?

Потому что они лексические. При `dense_off=true` список кандидатов — это BM25 по
FTS5 плюс попадания из графа; ранжирование определяется терминами, поэтому
точный идентификатор обгоняет пересказ. Есть два улучшения, но по умолчанию они
выключены и должны быть сначала измерены на ваших собственных запросах:
`MSCODEBASE_CODE_BM25=true` (разбиение идентификаторов, бусты по полям) и
провайдеры `MSCODEBASE_RERANKER_*`. Цифры качества по режимам — в `docs/FACTS.md`
§5, это снимки, а не гарантии.

## Где живут данные?

Два расположения, разделённые намеренно:

| Что | Путь |
|---|---|
| Текст чанков + индекс FTS5 | `<project>/.mscodebase/chunks.db` (переопределение: `MSCODEBASE_CHUNKS_DB`) |
| Граф, память проекта, телеметрия, LanceDB (только если используется) | `<data_root>/projects/<hash8>/` |

`<data_root>` — это `%LOCALAPPDATA%\mscodebase` на Windows,
`~/Library/Caches/mscodebase` на macOS, `~/.cache/mscodebase` на Linux.
Переопределяется через `MSCODEBASE_DATA_DIR` (`BASE_INDEX_DIR` — устаревший
алиас); папка проекта содержит `graph.db`, `intelligence/project_memory.json`,
`metrics/job_history.json`, `commit_memory/`, `telemetry/YYYY-MM-DD.json`.

Артефакты вынесены из индексируемого проекта намеренно: индексация чужого
репозитория не должна в него писать. `chunks.db` — исключение, и его можно
отключить через `MSCODEBASE_CHUNKS_DB`.

## Как увидеть остальные инструменты?

Регистрация и видимость разделены. **69** инструментов регистрируются всегда
(36 core + 16 intel + 13 inline + 4 dev). Наружу отдаётся профиль:

```bash
# по умолчанию: 17 инструментов, одна запись на намерение
MSCODEBASE_MCP_PROFILE=core

# всё
MSCODEBASE_MCP_PROFILE=full
```

После изменения перезапустите хост — фильтр срабатывает один раз внутри
`create_mcp_server()`. `tool_help()` перечисляет активный профиль, видимые
инструменты и скрытые; в профиле core он виден всегда.
`MSCODEBASE_MCP_TOOLS=a,b,c` — явный allowlist, который перекрывает профиль.
`execute_script` — отдельный опциональный 70-й инструмент за
`MSCODEBASE_EXECUTE_SCRIPT_ENABLED=true`.

## Как сбросить индекс?

Полный профиль: `intel_reset_index()` — закрывает дескрипторы БД, освобождает
PID-lock, удаляет каталог индекса и устаревшие каталоги внутри проекта, затем
запускает фоновую переиндексацию (опрос через `intel_get_job_status(job_id)`).

Профиль core (без `intel_reset_index`): удалить артефакты и форсировать
пересборку.

```powershell
Remove-Item .mscodebase\chunks.db* -Force
Remove-Item "$env:LOCALAPPDATA\mscodebase\projects\<hash8>" -Recurse -Force
```

Затем переиндексируйте через `codebase(action="index", path="project_dir",
project_root=".")` (полный профиль: `intel_trigger_reindex()`), или из шелла:
`python scripts/reindex_text_only.py --project .` (текст + граф, без
эмбеддингов); `python scripts/rebuild_graph.py` пересобирает только граф.

## «Ничего не найдено» против «пустой индекс»

Это разные состояния, и инструменты отвечают по-разному.

- **Пустой индекс** — `codebase(action="index", path="status")` сообщает
  `total_chunks = 0`. Это не «нет совпадений»; ничего не проиндексировано.
  Инструменты, проверяющие готовность, выбрасывают `IndexNotReadyError`, что
  отображается как `🟡 Warning: Index is not ready` с деталью
  `Index is empty for project: … Run index_project_dir() first.`
- **Идёт переиндексация** — синхронный путь поиска
  (`hybrid_search` / `search_with_mode`) немедленно возвращает пустой результат
  вместо ожидания на блокировках БД; асинхронный путь выбрасывает
  «⏳ Индекс перестраивается … повторите поисковый запрос через несколько секунд».
- **Действительно нет совпадения** — `total_chunks > 0`, у запроса просто нет
  лексического попадания. Переформулируйте, используя идентификаторы, которые
  есть в исходниках, или добавьте запрос с намерением `docs/`; статический
  поиск — не движок пересказа.

`investigate` показывает то же различие: он печатает
«Ничего не найдено. Запрос не подтверждён ни одним каналом» только когда все семь
каналов вернулись пустыми, и добавляет `degraded: ...`, если вместо этого канал
ушёл в таймаут.

## Можно ли работать без GPU и без сети?

Да. В дефолтном пути ничего не требует GPU, облачного API или интернета: FTS5,
AST-граф и разбор через tree-sitter — всё локальное. Сеть используется только для
скачивания опциональных моделей (GGUF/ONNX через `install.py`) и опционального
`tree-sitter-language-pack`, чьи парсеры подтягиваются при первом использовании
(`MSCODEBASE_LANGUAGE_PACK=true`). С выключенным флагом каждая грамматика берётся
из закреплённого wheel, и никаких скачиваний не происходит.

Опциональные ускорители, все выключены по умолчанию: LM Studio (`127.0.0.1:1234`),
Ollama (`127.0.0.1:11434`), llama.cpp (`127.0.0.1:8080` эмбеддер / `8081`
реранкер), ONNX-сервер (`127.0.0.1:1235`). См. `LM_STUDIO_SETUP.md` и
`INSTALL_MODELS.md`.

## Хост, логи и что делать после правки сервера

**OpenCode — основной хост**: он запускает
`…\Zed\extensions\mscodebase-intelligence\venv\Scripts\mscodebase-mcp.exe -u -m src.main`
с `PYTHONPATH`, указывающим на этот каталог расширения. Расширение Zed
по-прежнему поддерживается (`extension.toml`, `capabilities = ["context_servers"]`).
Оба запускают скопированный код, поэтому после правки `src/` выполните
`python install.py --sync-only` и перезапустите хост — перезагрузки недостаточно,
процесс держит старые модули.

Логи: `<data_root>/logs/` (падения + ротация), `get_logs()` (недавние
предупреждения/ошибки этого проекта), `debug_runtime_passport()` (полный профиль:
RUN_ID, BUILD_ID, PID, uptime, разрешённый проект — показывает, действительно ли
произошёл перезапуск).

Медленные ответы или один постоянно падающий канал: проверьте
`get_health_report()`, затем `codebase(action="index", path="status")`, затем
`intel_get_runtime_status()` (полный профиль). Один медленный канал деградирует
`investigate`, а не роняет его; что деградирует и что падает — см.
`GRACEFUL_DEGRADATION.md`.

См. также `INSTALL.md`, `ARCHITECTURE.md`, `SEARCH_PIPELINE.md`,
`TELEMETRY.md` и `docs/FACTS.md` — там все цитируемые числа.

**Verified against:** `pyproject.toml`, `src/config/settings.py`,
`src/core/search/engine.py`, `src/core/indexing/indexer.py`,
`src/core/indexing/chunk_store.py`, `src/core/artifact_paths.py`,
`src/core/intelligence/tools_reg.py`, `src/core/error_handler.py`,
`src/mcp/server_tools.py`, `src/mcp/tools/investigate_tool.py`,
`src/mcp/tools/codebase_tool.py`, `install.py`, `extension.toml`,
`scripts/reindex_text_only.py`, `%USERPROFILE%\.config\opencode\opencode.jsonc`.
