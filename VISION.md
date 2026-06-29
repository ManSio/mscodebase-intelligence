# Vision & Roadmap

> MSCodebase Intelligence — гибридная LSP+MCP система семантического поиска кода для Zed IDE.

**Текущий уровень зрелости: 75–82%** от состояния лучших GraphRAG Code Memory систем 2026 года.

---

## Где мы сейчас

### Что уже реализовано

| Фича | Статус | MCP Tool |
|------|--------|----------|
| Семантический поиск (vector) | ✅ | `search_code` |
| Лексический поиск (BM25) | ✅ | `search_code` |
| Гибридный поиск (RRF fusion) | ✅ | `search_code` |
| LLM-реранкинг (Qwen 2.5 / Ollama) | ✅ | `search_code` |
| Инкрементальная индексация | ✅ | `scan_changes` |
| Call Graph (symbol → callers) | ✅ | `get_symbol_info` |
| AST-структурный поиск | ✅ | `structural_search` |
| Кросс-репо поиск | ✅ | `cross_repo_search` |
| Итеративный deep search | ✅ | `deep_search` |
| Поиск похожего кода | ✅ | `context_search` |
| Repo Map | ✅ | `get_repo_map` |
| Прогресс индексации | ✅ | `get_index_progress` |
| Валидация схемы БД | ✅ | `index_project_dir` |
| Логирование | ✅ | `get_logs` |

### Архитектурные преимущества

1. **MCP-first** — спроектирован вокруг MCP с нуля, а не через адаптер
2. **Гибридный LSP+MCP** — один процесс, общая память, нет race condition
3. **Multi-provider reranking** — Ollama → LM Studio → RRF fallback
4. **Инкрементальная индексация** — не перестроение всего индекса при изменении файла

---

## Конкурентный ландшафт (2026)

| Проект | Семантика | AST | Граф вызовов | MCP | Инкремент. | Repo Map | GraphRAG |
|--------|-----------|-----|--------------|-----|-----------|----------|----------|
| Aider Repo Map | ❌ | ✅ | частично | ❌ | ❌ | ✅ | ❌ |
| opencode-codebase-index | ✅ | ✅ | ✅ | ✅ | ✅ | частично | ❌ |
| Semble | ✅ | частично | ❌ | ✅ | ✅ | ❌ | ❌ |
| Octocode | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Codebase-Memory (research) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **MSCodebase** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | частично |

---

## Roadmap до 90%+

### Phase 1: Enhanced Graph (目标: 85%) — IN PROGRESS

- [x] **Impact Analysis** — `impact_analysis` MCP tool: risk score, affected files, risk level
- [ ] **Полный граф зависимостей** — function, class, module, API route, event как узлы
- [ ] **Graph query API** — MCP tool `query_graph(query)`

### Phase 2: Semantic Enhancement (目标: 88%)

- [ ] **LLM-описания чанков** — генерация контекстных описаний для функций
- [ ] **RepoRank** — PageRank на графе вызовов для приоритизации
- [ ] **Branch-aware индекс** — разные индексы для разных веток

### Phase 3: Code Memory (目标: 92%) — IN PROGRESS

- [x] **Semantic commit memory** — история изменений с контекстом (Phase 2.4)
- [x] **Bug correlation** — какие файлы чаще участвуют в багах
- [x] **Auto relation extraction** — cochange + bug + call relations → knowledge graph
- [ ] **GraphRAG query engine** — навигация по графу знаний

### Phase 4: Full GraphRAG (目标: 95%) — IN PROGRESS

- [x] **Autonomous Fix Loop** — автоматическое исправление ошибок с rollback
- [x] **Health Check** — полная диагностика проекта
- [ ] **GraphRAG query engine** — навигация по графу знаний
- [ ] **Cross-project dependency graph** — граф зависимостей между проектами

---

## Приоритизация

```
Сейчас (82%)
    │
    ▼
Phase 1: Enhanced Graph ──────────────────────► 85%
    │  - Impact Analysis (высокая ценность)
    │  - Graph query API
    │
    ▼
Phase 2: Semantic Enhancement ───────────────► 88%
    │  - LLM chunk descriptions (+40-50% качество поиска)
    │  - RepoRank
    │
    ▼
Phase 3: Code Memory ────────────────────────► 92%
    │  - Commit memory
    │  - Bug correlation
    │
    ▼
Phase 4: Full GraphRAG ──────────────────────► 95%
       - Knowledge graph navigation
       - Auto relation extraction
```

---

## Как внести вклад

Приоритетные направления для контрибьюторов:

1. **Impact Analysis** — самая высокая ценность для пользователей
2. **LLM chunk descriptions** — наибольший прирост качества поиска
3. **RepoRank** — улучшение релевантности без изменения архитектуры

См. [CONTRIBUTING.md](CONTRIBUTING.md) для деталей.

---

*Последнее обновление: 2026-06-28*
