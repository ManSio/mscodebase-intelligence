# MSCodeBase Intelligence — Проектная документация

## 📋 Содержание

### 🏗️ Архитектура
- [Техническая архитектура](ARCHITECTURE.md) — модули, потоки данных, storage

### 📖 Пользовательская документация
- [README.md](README.md) — установка, запуск, использование
- [AI_PROMPT.md](AI_PROMPT.md) — инструкция для AI-ассистента

### 🛠️ Разработка
- [TESTING.md](TESTING.md) — QA-сценарии
- [CHANGELOG.md](CHANGELOG.md) — история изменений
- [SECURITY.md](SECURITY.md) — политика безопасности

---

## 📊 Текущий статус

**Версия:** 1.1.0
**Статус:** ✅ Production Ready
**Последнее обновление:** 2026-06-27

## 🎯 Ключевые возможности

| Возможность | Статус |
|-------------|--------|
| Гибридный поиск (vector + BM25) | ✅ |
| Семантический чанкинг (Tree-sitter) | ✅ |
| Call Graph анализ | ✅ |
| Архитектурный дифф | ✅ |
| LSP автоиндексация | ✅ |
| Fallback режим (без LM Studio) | ✅ |
| Windows path normalization | ✅ |
| LanceDB v2 хранилище | ✅ |

## 🔧 Компоненты

| Компонент | Файл | Описание |
|-----------|------|----------|
| MCP Server | `src/mcp/server.py` | Инструменты и промпты для AI |
| LSP Server | `src/lsp_main.py` | Индексация при сохранении |
| Indexer | `src/core/indexer.py` | Сканирование + LanceDB |
| Searcher | `src/core/searcher.py` | Гибридный поиск |
| SymbolIndex | `src/core/symbol_index.py` | Tree-sitter + Call Graph |
| ContextEngine | `src/core/context_engine.py` | Сжатый контекст |
| RemoteEmbedder | `src/core/remote_embedder.py` | LM Studio / Ollama / ONNX |
| Installer | `install.py` | Деплой + настройка Zed |

## 📈 Метрики

| Метрика | Значение |
|---------|----------|
| Фрагментов в базе | 458 |
| Уникальных файлов | 51 |
| Структурных символов | 255 |
| Режим эмбеддера | LM Studio |

## 🔒 Безопасность

- Локальное хранение (без внешних API кроме LM Studio)
- Path hashing для изоляции проектов
- .gitignore фильтрация
- Без Docker, без WSL

---

*Документация обновлена: 2026-06-27*
