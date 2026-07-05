#!/usr/bin/env python3
"""Fill ru.json and zh.json with translations from en.json keys."""

import json
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

locales_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales"
)

# Russian translations
ru = {
    "   • ...and {more} more\\n": "   • ...и ещё {more}\\n",
    "  • Architectural diff:": "  • Архитектурные изменения:",
    "  • Cache hits: {hits}": "  • Попаданий в кэш: {hits}",
    "  • Elapsed: {time}s": "  • Прошло: {time}с",
    "  • Embedder: {mode}": "  • Эмбеддер: {mode}",
    "  • Files updated: {count}": "  • Файлов обновлено: {count}",
    "  • LLM calls: {calls}": "  • Вызовов LLM: {calls}",
    "**{key}:**\\n": "**{key}:**\\n",
    "*...and {more} more*\\n": "*...и ещё {more}*\\n",
    "All chunks already have summaries": "Все чанки уже имеют summaries",
    "Call graph is empty": "Граф вызовов пуст",
    "Database is empty": "База данных пуста",
    "Found {count} files": "Найдено файлов: {count}",
    "Incident {incident_id} stored.": "Инцидент {incident_id} сохранён.",
    "JSON parse error: {error}": "Ошибка парсинга JSON: {error}",
    "LanceDB table not initialized": "Таблица LanceDB не инициализирована",
    "No data yet": "Нет данных",
    "Path does not exist: {path}": "Путь не существует: {path}",
    "Symbol '{symbol}' not found in index": "Символ '{symbol}' не найден в индексе",
    "Symbol index is not available": "Индекс символов недоступен",
    "Symbol index not available": "Индекс символов недоступен",
    "\\n⬆️ **Called from:**\\n": "\\n⬆️ **Вызывается из:**\\n",
    "\\n⬇️ **Calls:**\\n": "\\n⬇️ **Вызывает:**\\n",
    "\\n📁 **Другие проекты:**\\n": "\\n📁 **Другие проекты:**\\n",
    "\\n📅 **История (снэпшоты):**\\n": "\\n📅 **История (снэпшоты):**\\n",
    "\\n📊 **Инструменты:**\\n": "\\n📊 **Инструменты:**\\n",
    "\\n📎 **Usages:**\\n": "\\n📎 **Использования:**\\n",
    "\\n🔬 Layer filter: {layer}": "\\n🔬 Фильтр слоя: {layer}",
    "threading": "threading",
    "{icon} **MSCodeBase** — {status}\\n": "{icon} **MSCodeBase** — {status}\\n",
    "ℹ️ **Job {job_id}** not found\\n": "ℹ️ **Job {job_id}** — не найдена\\n",
    "ℹ️ **{name}** — {reason}\\n": "ℹ️ **{name}** — {reason}\\n",
    "ℹ️ **{query}** — not found\\n": "ℹ️ **{query}** — не найден\\n",
    "ℹ️ *No data*\\n": "ℹ️ *Нет данных*\\n",
    "ℹ️ *Nothing found*\\n": "ℹ️ *Ничего не найдено*\\n",
    "⚙️ **PID:** {pid}\\n": "⚙️ **PID:** {pid}\\n",
    "✅ Scan complete: {name}": "✅ Сканирование завершено: {name}",
    "✅ Summaries generated: {count} chunks": "✅ Сгенерировано summaries: {count} чанков",
    "❌ Code search error: {error}": "❌ Ошибка поиска по коду: {error}",
    "❌ Deep search error: {error}": "❌ Ошибка глубокого поиска: {error}",
    "❌ Embedder unavailable. Cannot vectorize code.": "❌ Эмбеддер недоступен. Невозможно векторизовать код.",
    "❌ Embedder unavailable. Cannot vectorize query.": "❌ Эмбеддер недоступен. Невозможно векторизовать запрос.",
    "❌ Empty code fragment for search.": "❌ Пустой фрагмент кода для поиска.",
    "❌ Empty search query.": "❌ Пустой поисковый запрос.",
    "❌ Query is empty": "❌ Пустой запрос",
    "❌ Search engine error: {error}": "❌ Ошибка поискового движка: {error}",
    "🏆 **Symbol Ranking** ({time}ms)\\n\\n": "🏆 **Рейтинг символов** ({time}ms)\\n\\n",
    "💡 *Do not rerun for the next 5 minutes.*": "💡 *Не запускай повторно следующие 5 минут.*",
    "💡 *Next scan: no earlier than 2 minutes.*": "💡 *Следующее сканирование: не ранее чем через 2 минуты.*",
    "📄 **Definitions:**\\n": "📄 **Определения:**\\n",
    "📊 **Tool Health**": "📊 **Здоровье инструментов**",
    "📋 **Execution Timeline**": "📋 **Лента вызовов**",
    "📋 Logs clean — no errors or warnings found.": "📋 Логи чисты — ошибок и предупреждений не обнаружено.",
    "📋 Recent {count} errors/warnings:\\n": "📋 Последние {count} ошибок/предупреждений:\\n",
    "📦 Chunks: {count} | Files: {count}": "📦 Чанков: {count} | Файлов: {count}",
    "🔍 **{title}**\\n\\n": "🔍 **{title}**\\n\\n",
    "🔍 Exact matches found, but no unique similar fragments.": "🔍 Точные совпадения найдены, но уникальных похожих фрагментов нет.",
    "🔍 Similar code not found.": "🔍 Похожий код не найден.",
    "🔥 **Top Risks**\\n\\n": "🔥 **Топ рисков**\\n\\n",
    "🧠 **Embedder:** {embedder}\\n": "🧠 **Эмбеддер:** {embedder}\\n",
    "🧠 **Project Memory**\\n\\n": "🧠 **Project Memory**\\n\\n",
}

# Chinese translations
zh = {
    "   • ...and {more} more\\n": "   • ...还有{more}个\\n",
    "  • Architectural diff:": "  • 架构差异:",
    "  • Cache hits: {hits}": "  • 缓存命中: {hits}",
    "  • Elapsed: {time}s": "  • 已用: {time}秒",
    "  • Embedder: {mode}": "  • 嵌入器: {mode}",
    "  • Files updated: {count}": "  • 文件已更新: {count}",
    "  • LLM calls: {calls}": "  • LLM 调用: {calls}",
    "**{key}:**\\n": "**{key}:**\\n",
    "*...and {more} more*\\n": "*...还有{more}个*\\n",
    "All chunks already have summaries": "所有块已有摘要",
    "Call graph is empty": "调用图为空",
    "Database is empty": "数据库为空",
    "Found {count} files": "找到{count}个文件",
    "Incident {incident_id} stored.": "事件 {incident_id} 已存储。",
    "JSON parse error: {error}": "JSON 解析错误: {error}",
    "LanceDB table not initialized": "LanceDB 表未初始化",
    "No data yet": "暂无数据",
    "Path does not exist: {path}": "路径不存在: {path}",
    "Symbol '{symbol}' not found in index": "符号 '{symbol}' 在索引中未找到",
    "Symbol index is not available": "符号索引不可用",
    "Symbol index not available": "符号索引不可用",
    "\\n⬆️ **Called from:**\\n": "\\n⬆️ **调用自:**\\n",
    "\\n⬇️ **Calls:**\\n": "\\n⬇️ **调用:**\\n",
    "\\n📁 **Другие проекты:**\\n": "\\n📁 **其他项目:**\\n",
    "\\n📅 **История (снэпшоты):**\\n": "\\n📅 **历史 (快照):**\\n",
    "\\n📊 **Инструменты:**\\n": "\\n📊 **工具:**\\n",
    "\\n📎 **Usages:**\\n": "\\n📎 **用法:**\\n",
    "\\n🔬 Layer filter: {layer}": "\\n🔬 层过滤器: {layer}",
    "threading": "threading",
    "{icon} **MSCodeBase** — {status}\\n": "{icon} **MSCodeBase** — {status}\\n",
    "ℹ️ **Job {job_id}** not found\\n": "ℹ️ **Job {job_id}** 未找到\\n",
    "ℹ️ **{name}** — {reason}\\n": "ℹ️ **{name}** — {reason}\\n",
    "ℹ️ **{query}** — not found\\n": "ℹ️ **{query}** — 未找到\\n",
    "ℹ️ *No data*\\n": "ℹ️ *无数据*\\n",
    "ℹ️ *Nothing found*\\n": "ℹ️ *未找到*\\n",
    "⚙️ **PID:** {pid}\\n": "⚙️ **PID:** {pid}\\n",
    "✅ Scan complete: {name}": "✅ 扫描完成: {name}",
    "✅ Summaries generated: {count} chunks": "✅ 摘要生成: {count} 块",
    "❌ Code search error: {error}": "❌ 代码搜索错误: {error}",
    "❌ Deep search error: {error}": "❌ 深度搜索错误: {error}",
    "❌ Embedder unavailable. Cannot vectorize code.": "❌ Embedder 不可用。无法向量化代码。",
    "❌ Embedder unavailable. Cannot vectorize query.": "❌ Embedder 不可用。无法向量化查询。",
    "❌ Empty code fragment for search.": "❌ 空的代码片段用于搜索。",
    "❌ Empty search query.": "❌ 空的搜索查询。",
    "❌ Query is empty": "❌ 查询为空",
    "❌ Search engine error: {error}": "❌ 搜索引擎错误: {error}",
    "🏆 **Symbol Ranking** ({time}ms)\\n\\n": "🏆 **符号排名** ({time}毫秒)\\n\\n",
    "💡 *Do not rerun for the next 5 minutes.*": "💡 *5分钟内请勿重复运行。*",
    "💡 *Next scan: no earlier than 2 minutes.*": "💡 *下次扫描: 至少2分钟后。*",
    "📄 **Definitions:**\\n": "📄 **定义:**\\n",
    "📊 **Tool Health**": "📊 **工具健康**",
    "📋 **Execution Timeline**": "📋 **执行时间线**",
    "📋 Logs clean — no errors or warnings found.": "📋 日志干净 — 未发现错误和警告。",
    "📋 Recent {count} errors/warnings:\\n": "📋 最近{count}条错误/警告:\\n",
    "📦 Chunks: {count} | Files: {count}": "📦 块数: {count} | 文件数: {count}",
    "🔍 **{title}**\\n\\n": "🔍 **{title}**\\n\\n",
    "🔍 Exact matches found, but no unique similar fragments.": "🔍 找到精确匹配，但没有唯一的相似片段。",
    "🔍 Similar code not found.": "🔍 未找到相似代码。",
    "🔥 **Top Risks**\\n\\n": "🔥 **主要风险**\\n\\n",
    "🧠 **Embedder:** {embedder}\\n": "🧠 **嵌入器:** {embedder}\\n",
    "🧠 **Project Memory**\\n\\n": "🧠 **项目记忆**\\n\\n",
}

# Apply ru
path_ru = os.path.join(locales_dir, "ru.json")
with open(path_ru, "r", encoding="utf-8") as f:
    data_ru = json.load(f)
for k, v in ru.items():
    data_ru[k] = v
with open(path_ru, "w", encoding="utf-8") as f:
    json.dump(data_ru, f, ensure_ascii=False, indent=2)

# Apply zh
path_zh = os.path.join(locales_dir, "zh.json")
with open(path_zh, "r", encoding="utf-8") as f:
    data_zh = json.load(f)
for k, v in zh.items():
    data_zh[k] = v
with open(path_zh, "w", encoding="utf-8") as f:
    json.dump(data_zh, f, ensure_ascii=False, indent=2)

# Verify
for lang in ["en", "ru", "zh"]:
    path = os.path.join(locales_dir, f"{lang}.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    empty = sum(1 for v in data.values() if not v)
    print(f"{lang}.json: {len(data)} keys, {empty} empty")

print("\nDone.")
