# 🤖 One-Prompt Install Manifest for Zed Agent

> Версия: 3.0.0 | Дата: 2026-07-09
> 
> Скопируй этот текст в чат Агента Zed (`Ctrl+Shift+P` → `Agent Panel: Toggle`)
> и Агент сам выполнит полную установку MSCodeBase под твою систему.

---

## 🎯 Цель

Полностью автоматическая установка MCP-сервера MSCodeBase Intelligence
с авто-детекцией платформы, CPU, и настройкой под пользователя.

```
Ожидаемый результат:
  ✅ Python + venv + pip packages
  ✅ llama.cpp (или ONNX как fallback)
  ✅ GGUF модели bge-m3 + reranker (417+418 MB)
  ✅ MCP сервер настроен в Zed
  ✅ 750 MB–1.9 GB RAM в простое (зависит от провайдера)
  ✅ 50 инструментов доступны Агенту
```

---

## 📋 Чеклист перед началом

- [ ] Установлен Python 3.10–3.14
- [ ] Доступ к GitHub (для скачивания llama.cpp)
- [ ] Доступ к Hugging Face (для скачивания GGUF моделей)
- [ ] ~2 GB свободного места на диске
- [ ] 5-10 минут на выполнение

---

## 🚀 Промпт для Агента

Скопируй **весь блок ниже** и вставь в чат Агента Zed:

```markdown
Ты — эксперт по установке MSCodeBase Intelligence.
Твоя задача — установить и настроить MCP-сервер полностью автоматически,
учитывая все особенности платформы пользователя.

### ПРАВИЛА (прочитай внимательно):

1. **Никогда не активируй виртуальное окружение** через `activate`/`activate.bat`.
   Используй полный путь: `.venv/Scripts/python.exe -m pip ...` (Windows)
   или `.venv/bin/python -m pip ...` (macOS/Linux).

2. **Никогда не используй json.load/json.dump на settings.json Zed.**
   Файл содержит `//` комментарии. Используй текстовую хирургию (поиск/замена подстроки).

3. **Определи платформу первой командой:**
   - `python --version`
   - `uname -m` (macOS/Linux) или `wmic cpu get architecture` (Windows)
   - Проверь поддержку AVX2: на Windows посмотри CPU модель через `wmic cpu get name`
     Если Intel i3-xxx / AMD Ryzen 3/5/7/9 — AVX2 есть.
     Если очень старый Intel (до Sandy Bridge 2011) — AVX нет.

4. **Для llama.cpp скачивай ТОЛЬКО официальные релизы с GitHub:**
   - Windows: `llama-{version}-bin-win-cpu-x64.zip` — содержит все CPU ядра (Haswell, Zen4 и т.д.)
   - macOS Intel: `llama-{version}-bin-macos-x64.tar.gz`
   - macOS ARM: `llama-{version}-bin-macos-arm64.tar.gz`
   - Linux: `llama-{version}-bin-ubuntu-x64.tar.gz`
   - **НЕ ИСПОЛЬЗУЙ** pip install llama-cpp-python — он собран под AVX512 и упадёт на Zen 3.

5. **Если скачивание llama.cpp не удалось** (нет интернета, firewall) — 
   НЕ ПАНИКУЙ. Просто настрой ONNX server. Он медленнее, но работает везде.

6. **Проверь порты** перед запуском серверов:
   - 8080 — llama.cpp
   - 1235 — ONNX server
   - Если заняты — выбери другие через аргументы.

7. **После установки покажи пользователю красивый отчёт.**

### ПОШАГОВЫЙ ПЛАН:

#### Шаг 1. Диагностика окружения
```bash
# Узнаём всё о системе
python --version
uname -a  # macOS/Linux
wmic os get caption  # Windows
wmic cpu get name,architecture  # Windows
```

#### Шаг 2. Клонирование (если не клонировано)
```bash
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence
```

#### Шаг 3. Виртуальное окружение + зависимости
```bash
python -m venv .venv
# Windows:
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install -r requirements.txt
# macOS/Linux:
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

#### Шаг 4. Скачивание llama.cpp (с обработкой ошибок)
```python
# Псевдокод — Агент выполняет в терминале:
версия = "b9940"
архив = получить_архив(платформа)  # win-cpu-x64.zip / macos-arm64.tar.gz / ubuntu-x64.tar.gz
url = f"https://github.com/ggml-org/llama.cpp/releases/download/{версия}/{архив}"

# Скачать
import urllib.request
urllib.request.urlretrieve(url, f".bin/{архив}")

# Распаковать
import zipfile  # или tarfile
# Извлечь только нужные файлы: llama-server*, ggml*.dll
```

#### Шаг 5. Скачивание GGUF моделей
```bash
# Через huggingface_hub (или прямым download)
pip install huggingface_hub -q
python -c "
from huggingface_hub import hf_hub_download
import shutil, os
models = [
    ('lm-kit/bge-m3-gguf', 'bge-m3-Q4_K_M.gguf'),
    ('lm-kit/bge-m3-reranker-v2-gguf', 'Bge-M3-568M-Q4_K_M.gguf'),
]
for repo, file in models:
    path = hf_hub_download(repo_id=repo, filename=file)
    shutil.copy2(path, f'models/{file}')
"
```

#### Шаг 6. Настройка MCP в Zed
```bash
# Прочитать settings.json
# НЕ ИСПОЛЬЗОВАТЬ json.load — удалит // комментарии!
# Вместо этого:
# 1. Прочитай как текст
# 2. Найди последнюю }
# 3. Вставь блок context_servers ПЕРЕД ней
# 4. Сохрани как текст обратно
```

#### Шаг 7. Тестирование
```bash
# Запустить MCP сервер в фоне
.venv/Scripts/python.exe -m src.main &

# Проверить что сервер отвечает
curl -s http://localhost:1235/health  # ONNX server (если есть)
curl -s http://localhost:8080/health  # llama.cpp (если есть)

# Вывести get_index_status через MCP
```

#### Шаг 8. Отчёт пользователю
Выведи красивый отчёт:
```
✅ MSCodeBase Intelligence установлен!
   Система:           ${os} ${arch}
   RAM:               ${total_ram} GB
   Провайдер:         ${provider} (${provider_ram} MB)
   MCP статус:        ${status}
   Команда:           ${python} -u -m src.main
   
   После перезапуска Zed:
   - Открой Agent Panel
   - Выполни: get_index_status()
```

### ОБРАБОТКА ОШИБОК:

| Ошибка | Действие |
|--------|----------|
| Python < 3.10 | Скажи пользователю обновить Python |
| Нет места на диске | Предупреди, нужно ~2 GB |
| Не удалось скачать llama.cpp | Переключись на ONNX, продолжи |
| Не удалось скачать GGUF | Скачай ONNX модели (bge-m3 ONNX) |
| settings.json не найден | Создай новый с минимальной конфигурацией |
| Порт 8080 занят | Используй 8081, 8082... |
| Порт 1235 занят | Используй 1236, 1237... |
| Все порты заняты | Скажи пользователю освободить порты |
| Connection refused | Подожди 5 сек, повтори |
| Любая другая ошибка | Лог + продолжай со следующим шагом |

Начинай установку. Не задавай вопросов — действуй.
```

---

## 🧠 Что этот промпт покрывает

| Сценарий | Как обрабатывается |
|---|---|
| Windows без AVX (очень старый CPU) | `win-cpu-x64.zip` содержит `ggml-cpu-sandybridge.dll` (SSE4.2) |
| Windows с AVX2 (обычный) | `win-cpu-x64.zip` → `ggml-cpu-haswell.dll` (AVX2) |
| Windows с AVX512 (Zen 4+) | `win-cpu-x64.zip` → `ggml-cpu-zen4.dll` (AVX512) |
| macOS Apple Silicon (M1-M4) | `macos-arm64.tar.gz` → Metal GPU ускорение |
| macOS Intel | `macos-x64.tar.gz` |
| Linux x64 | `ubuntu-x64.tar.gz` |
| Нет интернета | Fallback на ONNX (без скачиваний) |
| Hugging Face заблокирован | Fallback на ONNX модели (другие источники) |
| GitHub заблокирован | Fallback на ONNX server (без llama.cpp) |
| Мало RAM (< 4 GB) | Используй Q4_K_M квантование (523 MB вместо 1.7 GB) |
| Мало места (< 2 GB) | Предупреждение перед началом |
| PowerShell Execution Policy | Не activate, прямой путь к python.exe |
| settings.json с // комментариями | Текстовая хирургия, не JSON парсинг |
| Уже установлено | Проверка и пропуск |

---

## 📂 Файлы для установки

После успешной установки структура проекта:

```
mscodebase-intelligence/
├── .venv/                    # Виртуальное окружение
├── .bin/
│   └── llama.cpp/            # llama-server.exe + DLL
├── models/
│   ├── bge-m3-Q4_K_M.gguf    # Embedder (417 MB)
│   └── Bge-M3-568M-Q4_K_M.gguf # Reranker (418 MB)
├── src/                      # Исходный код MCP
├── install.py                # Установщик (повторный запуск безопасен)
└── requirements.txt          # Python зависимости
```

---

## 🔄 Roadmap: что ещё можно добавить

- [ ] **GPU детекция**: если есть NVIDIA GPU → скачать CUDA-версию llama.cpp
- [ ] **Docker support**: fallback через Docker если Python не установлен
- [ ] **Auto-update**: проверка новой версии при каждом запуске
- [ ] **Telemetry**: анонимный отчёт об успешности установки
- [ ] **Multi-model**: поддержка нескольких моделей одновременно (embedder + reranker в одном процессе)
