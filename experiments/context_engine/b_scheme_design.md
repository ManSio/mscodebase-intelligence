# B-scheme Design: GetContextTool Extension

## Intent → Sections Mapping (from experiment D v3)

| Intent | Required Sections | Optional Sections |
|--------|------------------|-------------------|
| explain | source, symbols | git |
| modify | source, symbols, git, memory | fallback |
| debug | source, symbols | git |
| test | source, symbols, memory, git | fallback |
| git_history | git | — |
| find_caller_callee | symbols | — |
| prepare_change | source, symbols, git, memory | fallback |
| verify_change | source, git | memory |

## Section Definitions

### source
- **Что**: исходный код функции/класса вокруг определения (±40 строк)
- **Источник**: чтение файла с диска (pathlib), поиск def/class по имени символа
- **Токены**: up to 1200 (hard limit)
- **Fallback**: если символ не найден в файле → пусто

### symbols
- **Что**: GetSymbolInfoTool результат (definition, callers, callees, impact)
- **Источник**: GetSymbolInfoTool.execute(symbol) + fallback search_code при not-found
- **Токены**: up to 800
- **Dedup**: уже внутри адаптера (_pick_best_node, _candidate_starts, _is_one_off_script)

### git
- **Что**: `git log --oneline -6 -- <file>` (последние 6 коммитов)
- **Источник**: subprocess git (тот же паттерн, что в эксперименте)
- **Токены**: up to 300

### memory
- **Что**: IntelligenceStore.load_memory() — project memory (ADR, known_issues, incidents)
- **Источник**: IntelligenceStore(self.project_root).load_memory()
- **Токены**: up to 400 (топ-8 узлов по секциям)

### fallback
- **Что**: search_code(mode="fast", limit=3) для символов вне графа (inline @mcp.tool, приватные)
- **Источник**: SearchCodeTool.execute(query=symbol, mode="fast", limit=3)
- **Токены**: up to 200

## Token Budget Algorithm

```python
TOKEN_LIMIT = 2000
SECTION_BUDGETS = {
    "source": 1200,
    "symbols": 800,
    "git": 300,
    "memory": 400,
    "fallback": 200,
}

def truncate_to_budget(text: str, budget: int) -> str:
    """Обрезает текст до бюджета токенов (chars/4)."""
    max_chars = budget * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"
```

## Dedup Strategy

1. Собираем все секции в список `(section_name, text)`
2. Для каждой секции вычисляем "signature" = (file_path, symbol_name) если применимо
3. Удаляем дубликаты по signature, оставляя секцию с наивысшим приоритетом:
   source > symbols > git > memory > fallback
4. Общий токен-бюджет: если сумма > TOKEN_LIMIT, пропорционально урезаем от низкоприоритетных секций

## API Design (Backward Compatible)

```python
async def execute(
    self,
    targets: Optional[List[str]] = None,
    intent: str = "explain",           # NEW: intent-параметр
    kwargs: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    targets: список символов (backward compat)
    intent: explain|modify|debug|test|git_history|find_caller_callee|prepare_change|verify_change
    kwargs: legacy targets через kwargs.get("targets")
    """
```

## Implementation Plan

1. **src/mcp/tools/context_tool.py** — расширить GetContextTool:
   - Добавить intent-параметр
   - Добавить секции source/git/memory/fallback
   - Токен-бюджет + dedup
   - Backward compat: targets без intent → explain

2. **src/mcp/tools/search_tools.py** — добавить helper:
   - `_read_source_around_symbol(file_path, symbol)` → source text
   - `_get_git_history(file_path)` → git log
   - `_get_project_memory()` → memory

3. **src/mcp/server_tools.py** — регистрация без изменений (тот же класс)

4. **tests/test_context_tool.py** — тесты:
   - intent=explain → source+symbols
   - intent=modify → source+symbols+git+memory
   - intent=test → source+symbols+memory+git
   - token budget enforcement
   - dedup работает
   - fallback для not-found символов