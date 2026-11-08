# Установка моделей (опционально)

> Перевод: 2026-11-08, источник — docs/en/INSTALL_MODELS.md. Английская версия — канон.

[English](../en/INSTALL_MODELS.md) · [Русский](INSTALL_MODELS.md) · [中文](../zh/INSTALL_MODELS.md)

> Версия 3.5.0. **Для дефолтного runtime никакая модель не требуется.** Text-first
> поиск (`MSCODEBASE_DENSE_OFF=true`) читает чанки из SQLite FTS5 и
> PropertyGraph, поэтому свежая установка работоспособна ещё до появления любой
> модели. Ставьте модели только если вам нужно живое качество
> эмбеддинга/реранка или локальная chat-модель.

---

## 1. Что можно установить и зачем

| Артефакт | Роль | Размер (объявлен в коде) |
|---|---|---|
| `multilingual-e5-small-int8` (ONNX) | in-process эмбеддер, 384-dim | ~113 MB |
| `reranker-bge-reranker-v2-m3` (ONNX) | in-process/HTTP реранкер | ~544 MB |
| `multilingual-e5-small-Q8_0.gguf` | эмбеддер llama.cpp, 384-dim | ~126 MB |
| `bge-reranker-v2-m3` GGUF (`Bge-M3-568M-Q4_K_M`) | реранкер llama.cpp | ~418 MB |
| `llama-server.exe` (сборка llama.cpp `b11476`) | хост для моделей GGUF | зависит от сборки |
| `qwen3-embedding-0.6b-q4_k_m.gguf` (опционально) | альтернативный эмбеддер, 1024-dim | ~379 MB |
| `bge-m3-Q4_K_M.gguf` (опционально) | альтернативный эмбеддер, 1024-dim | ~417 MB |
| `embeddinggemma-2-Q8_0.gguf` (опционально) | альтернативный эмбеддер, 768-dim | ~296 MB |

Таблица GGUF (`GGUF_MODELS` в `src/providers/reranker/llama_install.py`) также
несёт размерность эмбеддинга, которую выдаёт каждая модель — эта размерность
должна совпадать с `EMBEDDING_DIMENSION`, если вы храните векторы. Значения
SHA-256 записаны для части записей (qwen3-embedding, bge-m3, bge-reranker-v2-m3) и
логируются при скачивании; путь скачивания их не сравнивает, поэтому хэш здесь —
справочное значение, а не проверенный пин. (Архив **бинарника** llama.cpp,
наоборот, проверяется по хэшу перед распаковкой.)

## 2. Способ 1 — `install.py` (интерактивный)

```bash
python install.py
```

12 шагов. Сетевые шаги спрашивают перед действием:

- ONNX-модели: *«Download ONNX models (e5-small-int8 ~113 MB + reranker ~544 MB)? (Y/n)»*;
- GGUF + llama.cpp: шаг GGUF скачивает `multilingual-e5-small` и
  `bge-reranker-v2-m3`, а также бинарник llama.cpp для выбранного бэкенда;
- каждый шаг при сбое предлагает `[r]etry / [s]kip / [c]ancel`.

Полезные флаги:

| Флаг | Эффект |
|---|---|
| `--sync-only` / `--sync` | скопировать код в каталог расширения, больше ничего не трогать (используйте после правки `src/`) |
| `--skip-models` / `--no-models` | полностью пропустить шаги с моделями |
| `--yes` / `-y` | отвечать «да» вместо вопроса |
| `--verbose` / `-v` | полный вывод шагов вместо компактного вида |

Установка целенаправленно пишет в каталог расширения
`%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence`:

- ONNX → `<ext>/.codebase_models/onnx/<slug>/model_quantized.onnx`
  (его специализированная подпапка реранкера использует `model.onnx`);
- GGUF → `<ext>/models/<file>.gguf`;
- существующие копии переиспользуются из каталога расширения, затем из
  `~/.cache/mscodebase/models`, затем из корня проекта, и копируются вместо
  повторного скачивания.

После прогона перезапустите хост. Ничего не перезагружается на лету.

## 3. Способ 2 — вручную

Модели — это обычные файлы в известных местах; шага регистрации нет.

```bash
# ONNX (embedder + reranker)
mkdir -p .codebase_models/onnx/multilingual-e5-small-int8
# place model_quantized.onnx there (repo: keisuke-miyako/multilingual-e5-small-onnx-int8)

# GGUF copies are looked up by exact filename
ls models/            # multilingual-e5-small-Q8_0.gguf, Bge-M3-568M-Q4_K_M.gguf
```

Порядок поиска для GGUF — каталог `models/` расширения, затем
`~/.cache/mscodebase/models` (см. `_get_models_dir`). Положите файл в любой из
них; дублирование в каталог расширения избавит от сюрпризов после обновления.

## 4. Порты и процессы

| Процесс | Порт по умолчанию | Env |
|---|---|---|
| эмбеддер llama.cpp (`llama-server.exe`) | `8080` | `LLAMA_CPP_PORT`, `LLAMA_CPP_HOST` |
| реранкер llama.cpp | `8081` | `LLAMA_CPP_RERANK_PORT` |
| ONNX-сервер (подпроцесс) | `1235` | `ONNX_SERVER_PORT`, `ONNX_SERVER_HOST` |
| LM Studio (внешний) | `1234` | `LM_STUDIO_PORT` |
| Ollama (внешний) | `11434` | `OLLAMA_PORT` |

Бэкенд llama.cpp по умолчанию `msvc` (CPU); `LLAMA_BACKEND=vulkan` переключает на
GPU-бинарник и задаёт `-ngl` из `LLAMA_NGL` (по умолчанию 99). Порты проверяются
на попадание в диапазон `8080-8090` перед запуском; порт вне этого диапазона
пропускается с предупреждением.

Два контекста моделей настраиваются отдельно: `LLAMA_EMBED_MAX_TOKENS` (по
умолчанию 480, обрезается клиентом) и `LLAMA_RERANK_MAX_TOKENS` (по умолчанию
1000, пара запрос+пассаж). Физический батч выводится по роли (`resolve_ubatch`):
embed → 512, rerank → 1024.

## 5. Дефолтные имена — реальная несогласованность

В коде существуют два разных значения по умолчанию:

- `src/config/settings.py`: `EMBEDDING_MODEL` по умолчанию `qwen3-embedding`;
- `src/providers/reranker/llama_install.py`: `DEFAULT_EMBEDDING_MODEL` по
  умолчанию `embeddinggemma-2` (env `EMBEDDING_MODEL` его переопределяет).

Шаг GGUF в `install.py` скачивает `multilingual-e5-small` для эмбеддера
независимо от обоих дефолтов. Если выбор для вас важен, закрепите модель явно в
`.env` (`EMBEDDING_MODEL=...`); не полагайтесь на то, что дефолты в разных
модулях совпадают.

## 6. Проверка

```powershell
curl http://127.0.0.1:8080/health     # llama.cpp embedder
curl http://127.0.0.1:8081/health     # llama.cpp reranker
curl http://127.0.0.1:1235/health     # ONNX server
```

Внутри хоста: `intel_get_telemetry()` показывает живые `provider`, `model`,
`ping_ms` и `tokens_per_sec`; `llm.error` означает, что пинг упал, а не был
пропущен. `get_health_report()` включает блок провайдера.

## 7. Удаление моделей

Удалите файлы; никакая запись в реестре их не переживает:

```powershell
Remove-Item .codebase_models\onnx\<slug> -Recurse -Force
Remove-Item models\<file>.gguf -Force
```

Если dense-путь был включён и векторы существуют, дополнительно выполните
`python scripts/reindex_text_only.py --project .` (или `intel_reset_index()`),
иначе сохранённые векторы останутся старой размерности. Каталоги моделей в
git-ignore (`.codebase_models/`, `models/`), поэтому в `git status` ничего не
появится.

---

**Verified against:** `install.py` (`STEPS`, `step_models`, `step_gguf`,
`--sync-only`, `--skip-models`, `--yes`, prompt strings),
`src/providers/reranker/llama_install.py` (`GGUF_MODELS` sizes/dims/SHA-256,
`LLAMA_VERSION`, `LLAMA_PORT`, `DEFAULT_EMBEDDING_MODEL`, `resolve_ubatch`,
`_patch_dll_imports`), `src/providers/reranker/llama_runner.py`
(`RERANK_PORT`, port range check, `LLAMA_BACKEND`/`LLAMA_NGL`),
`src/config/settings.py` (provider ports, `EMBEDDING_MODEL`),
`.env.example`, `.gitignore`.
