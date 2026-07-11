# 🤖 One-Prompt Install Manifest for Zed Agent

> Версия: 3.1.0 | Дата: 2026-07-11
>
> Скопируй этот текст в чат Агента Zed (`Ctrl+Shift+P` → `Agent Panel: Toggle`)
> и Агент сам выполнит установку, настройку и проверку MSCodeBase Intelligence.

---

## 🎯 Цель

Полностью автоматическая установка MCP-сервера MSCodeBase Intelligence
с авто-детекцией платформы, CPU, GPU (Vulkan), и настройкой под пользователя.

```
Ожидаемый результат:
  ✅ Python + venv + pip packages (в расширении Zed)
  ✅ llama.cpp embedder + reranker (Vulkan GPU / CPU)
  ✅ GGUF модели bge-m3 Q4_K_M + bge-reranker-v2-m3 (417+418 MB)
  ✅ MCP сервер настроен в Zed
  ✅ ~1.0 GB RAM в простое (llama.cpp GGUF)
  ✅ 56 инструментов доступны Агенту (39 core + 14 intel + 3 diagnostic)
```

---

## 📋 Чеклист перед началом

- [ ] Установлен Python 3.10–3.14
- [ ] Доступ к GitHub (для скачивания llama.cpp через install.py)
- [ ] Доступ к Hugging Face (для скачивания GGUF моделей через install.py)
- [ ] ~2 GB свободного места на диске
- [ ] 5-10 минут на выполнение
- [ ] Расширение `mscodebase-intelligence` установлено в Zed

---

## 🚀 Промпт для Агента

Скопируй **весь блок ниже** и вставь в чат Агента Zed:

```markdown
Ты — эксперт по установке MSCodeBase Intelligence.
Твоя задача — установить, настроить и ПРОВЕРИТЬ MCP-сервер полностью автоматически.

### ВАЖНО: архитектура проекта

- **Source code:** `D:\Project\MSCodeBase` — здесь ты редактируешь код
- **Extension dir:** `%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence` — откуда MCP реально запускается
- **Venv:** `{EXT}\venv\Scripts\python.exe`
- **llama binary:** `{EXT}\llama_msvc\` (CPU) или `{EXT}\llama_vulkan\` (GPU)
- **Models:** `{EXT}\models\` — GGUF файлы
- **install.py** (из исходников) копирует файлы в расширение

### ПРАВИЛА:

1. **Никогда не активируй виртуальное окружение** — используй полный путь
2. **Не используй json.load/json.dump на settings.json Zed** — он содержит // комментарии
3. **Перед install.py — убей процессы:** `taskkill //F //IM "llama-server.exe"` и `python.exe`
4. **После install.py — перезагрузи Zed**, если не делаешь тест напрямую
5. **Все пути в терминале — POSIX** (`src/core/...`), в MCP — Windows (`src\\core\\...`)

### ПОШАГОВЫЙ ПЛАН:

#### Шаг 1. Диагностика окружения
```bash
python --version
wmic os get caption  # Windows
wmic cpu get name,architecture  # Windows
wmic memorychip get capacity  # RAM
```

#### Шаг 2. Убить старые процессы
```bash
taskkill //F //IM "llama-server.exe" 2>&1
taskkill //F //FI "WINDOWTITLE eq mscodebase*" //IM python.exe 2>&1
```

#### Шаг 3. Запустить install.py
```bash
cd /d/Project/MSCodeBase
printf 's\nn\n' | python install.py
```

install.py сделает всё сам:
1. Скопирует 39+ файлов исходников в расширение
2. Установит/обновит Python пакеты
3. Скачает llama-server.exe (под твою платформу, с CRT патчем для Insider)
4. Скачает GGUF модели (bge-m3 + reranker)
5. Настроит MCP в settings.json Zed

#### Шаг 4. ПРОВЕРКА — запустить MCP напрямую из расширения
```bash
cd "/c/Users/misha/AppData/Local/Zed/extensions/mscodebase-intelligence"
nohup venv/Scripts/python.exe -m src.main > /tmp/mcp_test.log 2>&1 &
sleep 10
```

#### Шаг 5. Проверить что процессы поднялись
```bash
# Должны быть 2 процесса llama-server.exe
tasklist //FI "IMAGENAME eq llama-server.exe" //NH 2>&1

# Должны слушаться порты 8080 (embed) + 8081 (rerank)
/c/Windows/System32/netstat.exe -ano 2>&1 | grep -E ":8080 |:8081 "
```

#### Шаг 6. Проверить embed API
```bash
python -c "
import httpx
r = httpx.post('http://127.0.0.1:8080/v1/embeddings',
    json={'input': ['тестовый запрос']}, timeout=15)
print('Embed:', r.status_code, 'dim=', len(r.json()['data'][0]['embedding']))
"
# Ожидается: Embed: 200 dim=1024
```

#### Шаг 7. Проверить rerank API
```bash
python -c "
import httpx
r = httpx.post('http://127.0.0.1:8081/rerank',
    json={'query': 'тест', 'texts': ['документ а', 'документ б']}, timeout=15)
print('Rerank:', r.status_code, r.json())
"
# Ожидается: Rerank: 200 [{'index': ..., 'score': ...}]
```

#### Шаг 8. Убить тестовые процессы
```bash
taskkill //F //IM "llama-server.exe" 2>&1
taskkill //F //FI "WINDOWTITLE eq mscodebase*" //IM python.exe 2>&1
```

#### Шаг 9. Отчёт пользователю
```markdown
✅ MSCodeBase Intelligence установлен и проверен!
   Система:           ${os} ${arch}
   RAM:               ${total_ram} GB
   Провайдер:         llama.cpp GGUF (${gpu})
   MCP:               ${python} -u -m src.main
   Embed:             8080 ✅ (1024 dim)
   Reranker:          8081 ✅
   Инструменты:       50 (33 core + 14 intel + 3 diagnostic)
   
   Действие: Перезагрузи Zed (File → Quit → reopen)
   После перезапуска проверь: intel_get_runtime_status()
```

### ОБРАБОТКА ОШИБОК:

| Ошибка | Действие |
|--------|----------|
| Python < 3.10 | Скажи пользователю обновить Python |
| install.py упал | Проверь логи, покажи ошибку |
| Нет места на диске | Нужно ~2 GB |
| Не удалось скачать llama.cpp | install.py сам скачает; если firewall — ONNX fallback |
| Не удалось скачать GGUF | install.py сам скачает; если нет — ONNX fallback |
| Порт 8080 занят | Убей процесс: `taskkill //F //PID <pid>` |
| Connection refused | Подожди ещё 10 сек, llama грузит модель |
| Только 1 llama-server | Жди ещё 15 сек — reranker стартует после embed |
| Любая другая ошибка | Лог + продолжай со следующим шагом |
``` 

---

## 🧠 Что покрывает install.py (а не этот промпт)

install.py делает ВСЮ тяжёлую работу. Этот промпт только координирует.

| Что делает install.py | Детали |
|---|---|
| **Копирование исходников** | 39+ файлов из `D:\Project\MSCodeBase\src\` в расширение |
| **Venv + пакеты** | 33 Python пакета (httpx, lancedb, pyarrow и т.д.) |
| **llama.cpp бинарник** | `b9940` — MSVC (CPU) + Clang (Vulkan GPU) |
| **CRT патч для Insider** | Авто-патч PE импортов `api-ms-win-crt-*` → `ucrtbase.dll` |
| **GGUF модели** | bge-m3 Q4_K_M (417 MB) + bge-reranker-v2-m3 (418 MB) |
| **Qwen3 (альтернатива)** | qwen3-embedding-0.6b-q4_k_m.gguf (346 MB RAM) |
| **ONNX fallback** | bge-m3 ONNX (543 MB) + reranker ONNX (544 MB) |
| **MCP настройка Zed** | `patch_zed_settings()` — текстовая хирургия settings.json |
| **Vulkan детекция** | Если GPU с Vulkan → использует Vulkan, иначе CPU |

---

## 📂 Структура после установки

```
%LOCALAPPDATA%\Zed\extensions\mscodebase-intelligence\
├── venv\                        # Виртуальное окружение Python
├── llama_msvc\                  # llama.cpp MSVC сборка (CPU)
│   ├── llama-server.exe
│   └── ggml-cpu-haswell.dll     # + sandybridge, zen4 DLL
├── llama_vulkan\                # llama.cpp Clang сборка (GPU)
│   ├── llama-server.exe
│   ├── ggml-cpu-haswell.dll     # CPU fallback DLL
│   └── ggml-vulkan.dll          # Vulkan backend
├── models\
│   ├── bge-m3-Q4_K_M.gguf       # Embedder (417 MB)
│   ├── Bge-M3-568M-Q4_K_M.gguf  # Reranker (418 MB)
│   └── qwen3-embedding-0.6b-... # Альтернатива (346 MB RAM)
├── src\                         # Исходный код MCP (скопирован install.py)
│   ├── core\
│   ├── mcp\
│   └── utils\
└── .zed\settings.json           # MCP настроен (PYTHONPATH, PROJECT_PATH)
```

---

## 🔄 Стандартный цикл разработки (для разработчиков)

Когда нужно изменить код и проверить:

```
ШАГ 1 — Правим код в исходниках (D:\Project\MSCodeBase\src\)
ШАГ 2 — Убиваем старые процессы
ШАГ 3 — install.py (синхронизация в расширение)
ШАГ 4 — Запуск MCP напрямую из расширения
ШАГ 5 — Тестируем (embed, rerank, search_code)
ШАГ 6 — Убиваем тестовые процессы
ШАГ 7 — Говорим пользователю: «Перезагрузи Zed»
```

Подробнее: `AGENTS.md` → раздел `0.5. WORKFLOW: ИСХОДНИКИ → РАСШИРЕНИЕ ZED`
