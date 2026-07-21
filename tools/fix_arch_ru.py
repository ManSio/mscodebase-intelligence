"""Fix remaining Russian text in docs/en/ARCHITECTURE.md"""
import re
from pathlib import Path

text = Path("docs/en/ARCHITECTURE.md").read_text(encoding="utf-8")

fixes = {
    "# asyncio.Lock для thread safety": "# asyncio.Lock for thread safety",
    "# Только core-слой": "# Only core layer", 
    "# Только tests": "# Only tests",
    "# Без фильтра (все слои, как раньше)": "# No filter (all layers, as before)",
    "Фильтрация работает на уровне LanceDB `.where(prefilter=True)` — векторный\nпоиск идёт только по чанкам нужного слоя. BM25 пост-фильтруется по layer\nиз metadata.": "Layer filtering works at LanceDB level via `.where(prefilter=True)` — vector search only searches chunks of the specified layer. BM25 post-filters by layer from metadata.",
    
    "v2.3+ поддерживает **несколько открытых проектов в Zed одновременно**.": "v2.3+ supports **multiple open projects in Zed simultaneously**.",
    "Раньше DI хранил singleton `Indexer` — при переключении окон state ломался": "Previously DI held a singleton `Indexer` — when switching windows, state would break",
    "(один `file_guard`, один `db_path`, общий `SymbolIndex`).": "(one `file_guard`, one `db_path`, shared `SymbolIndex`).",
    
    "`src/core/project_indexer_registry.py` — потокобезопасный реестр `Indexer`-ов:": "`src/core/indexing/project_indexer_registry.py` — thread-safe registry of `Indexer` objects:",
    "max_cached=5,                      # LRU лимит (5 проектов = 1-2.5GB RAM)": "max_cached=5,                      # LRU limit (5 projects = 1-2.5GB RAM)",
    "# Per-project lazy создание через factory:": "# Per-project lazy creation via factory:",
    "symbol_index=SymbolIndex(),  # изолирован": "symbol_index=SymbolIndex(),  # isolated",
    
    "Гарантии:": "Guarantees:",
    "- **Изоляция:** каждое окно получает свой `FileGuard`/`SymbolIndex`/`db_path`.": "- **Isolation:** each window gets its own `FileGuard`/`SymbolIndex`/`db_path`.",
    "- **LRU:** при открытии 6-го проекта самый старый `Indexer` вытесняется.": "- **LRU:** when the 6th project opens, the oldest `Indexer` is evicted.",
    "- **Pressure-evict:** при RAM > 1GB или CPU > 85% — принудительный evict": "- **Pressure-evict:** when RAM > 1GB or CPU > 85% — forced evict",
    "перед созданием нового `Indexer` (предотвращает OOM).": "before creating a new `Indexer` (prevents OOM).",
    "- **Cleanup:** `_safe_close()` обнуляет LanceDB connection + `gc.collect()`": "- **Cleanup:** `_safe_close()` resets LanceDB connection + `gc.collect()`",
    "(для Windows mmap handles).": "(for Windows mmap handles).",
    
    "Пороги:": "Thresholds:",
    "- Soft: 768MB / 75% CPU → throttle индексации (0.1s задержка между файлами)": "- Soft: 768MB / 75% CPU → throttle indexing (0.1s delay between files)",
    "- Hard: 1024MB / 85% CPU → pressure-evict + 0.5-2s задержка": "- Hard: 1024MB / 85% CPU → pressure-evict + 0.5-2s delay",
    
    "time.sleep(delay)  # в Indexer.index_project между файлами": "time.sleep(delay)  # in Indexer.index_project between files",
    
    "`src/lsp_main.py` хранит **per-workspace** DI-контейнеры:": "`src/lsp_main.py` stores **per-workspace** DI containers:",
    "# → создаёт изолированный DI-контейнер для ОКНА": "# → creates isolated DI container for a WINDOW",
    
    "`src/mcp/tools/base.py` — единая точка получения per-project Indexer:": "`src/mcp/tools/base.py` — single entry point for per-project Indexer:",
    "Все MCP-инструменты должны использовать `self.resolve_indexer(...)`": "**All MCP tools** must use `self.resolve_indexer(...)`",
    "вместо `self._services.resolve(Indexer)` — последний больше не работает": "instead of `self._services.resolve(Indexer)` — the latter no longer works",
    "(Indexer не singleton).": "(Indexer is not a singleton).",
    
    "`src/core/health_report.py` — добавлен метод:": "`src/core/code_health.py` — added method:",
    
    "Эти правила НЕ должны нарушаться ни одним новым PR.": "These rules must NOT be violated by any new PR.",
    "1. Tool не обращается к Registry напрямую.": "1. Tool does not access Registry directly.",
    "2. Tool не читает Bridge напрямую.": "2. Tool does not read Bridge directly.",
    "3. Tool работает только через RuntimeCoordinator.": "3. Tool works only through RuntimeCoordinator.",
    "4. RuntimeCoordinator не знает про Search / Indexer / Memory.": "4. RuntimeCoordinator does not know about Search / Indexer / Memory.",
    "5. ProjectContext — immutable snapshot (не запускает операций).": "5. ProjectContext is an immutable snapshot (does not start operations).",
    "6. Все системные файлы определяются только через SystemArtifacts.": "6. All system files are defined only through SystemArtifacts.",
    "7. Индексатор никогда не индексирует системные артефакты.": "7. The indexer never indexes system artifacts.",
    "8. Любой путь проекта проходит через единый resolver (resolve_project_root).": "8. Any project path goes through the single resolver (resolve_project_root).",
    "9. Все Intel-инструменты используют ProjectContext (не низкоуровневые API).": "9. All Intel tools use ProjectContext (not low-level APIs).",
    "10. Любой новый runtime-компонент обязан иметь одну ответственность.": "10. Any new runtime component must have a single responsibility.",
    "11. Слой Core не имеет MCP-импортов.": "11. Core layer has no MCP imports.",
    "12. Инструменты не создают зависимости — всё через DI.": "12. Tools do not create dependencies — everything through DI.",
    "13. server.py регистрирует — не содержит бизнес-логики.": "13. server.py registers — does not contain business logic.",
    
    "Проверка при code review: любой PR должен отвечать на вопрос": "Code review check: every PR must answer the question",
    '"Какой существующий слой расширяется?". Если ответ "никакой, я сделал': '"Which existing layer does this extend?". If the answer is "none, I created',
    "новый Manager/Services/Provider\" — это повод остановиться.": "a new Manager/Services/Provider\" — this is a reason to stop and reconsider.",
}

for old, new in fixes.items():
    if old in text:
        text = text.replace(old, new)
        print(f"  OK: {old[:50]}...")
    else:
        print(f"  MISS: {old[:50]}...")

Path("docs/en/ARCHITECTURE.md").write_text(text, encoding="utf-8")

remaining = len(re.findall(r"[а-яА-ЯёЁ]", text))
total = len(text)
print(f"\nCyrillic remaining: {remaining} / {total} = {remaining/total*100:.1f}%")
