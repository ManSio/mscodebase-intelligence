# Vision & Roadmap

> MSCodebase Intelligence — гибридная LSP+MCP система семантического поиска кода для Zed IDE.

**Текущий уровень зрелости: 90–95%** от состояния лучших GraphRAG Code Memory систем 2026 года.

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
| LLM-описания чанков | ✅ | `generate_chunk_summaries` |
| RepoRank | ✅ | `get_repo_map` |
| Branch-aware индекс | ✅ | `get_branch_info` |
| Cross-project dependency graph | ✅ | `cross_project_deps` |
| Time-aware search | ✅ | `search_code` (since/before) |
| Index timeline | ✅ | `get_index_timeline` |

### Архитектурные преимущества

1. **MCP-first** — спроектирован вокруг MCP с нуля, а не через адаптер
2. **Гибридный LSP+MCP** — один процесс, общая память, нет race condition
3. **Multi-provider reranking** — Ollama → LM Studio → RRF fallback
4. **Инкрементальная индексация** — не перестроение всего индекса при изменении файла

---

## Конкурентный ландшафт (2026)

| Проект | Семантика | AST | Граф вызовов | MCP | Инкремент. | Repo Map | GraphRAG | Branch-aware | Cross-project | Time-aware |
|--------|-----------|-----|--------------|-----|-----------|----------|----------|--------------|---------------|------------|
| Aider Repo Map | ❌ | ✅ | частично | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| opencode-codebase-index | ✅ | ✅ | ✅ | ✅ | ✅ | частично | ❌ | ❌ | ❌ | ❌ |
| Semble | ✅ | частично | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Octocode | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Codebase-Memory (research) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **MSCodebase** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## Roadmap до 90%+

### Phase 1: Enhanced Graph (目标: 85%) — ✅ COMPLETE

- [x] **Impact Analysis** — `impact_analysis` MCP tool: risk score, affected files, risk level
- [x] **Полный граф зависимостей** — function, class, module, API route, event как узлы
- [x] **Graph query API** — MCP tool `query_graph(query)`

### Phase 2: Semantic Enhancement (目标: 88%) — ✅ COMPLETE

- [x] **LLM-описания чанков** — генерация контекстных описаний для функций (`generate_chunk_summaries`)
- [x] **RepoRank** — PageRank на графе вызовов для приоритизации (`get_repo_map`)
- [x] **Branch-aware индекс** — разные индексы для разных веток (`get_branch_info`)

### Phase 3: Code Memory (目标: 92%) — ✅ COMPLETE

- [x] **Semantic commit memory** — история изменений с контекстом (Phase 2.4)
- [x] **Bug correlation** — какие файлы чаще участвуют в багах
- [x] **Auto relation extraction** — cochange + bug + call relations → knowledge graph
- [x] **GraphRAG query engine** — навигация по графу знаний (impact, feature, deps, tests)

### Phase 4: Full GraphRAG (目标: 95%) — ✅ COMPLETE

- [x] **Autonomous Fix Loop** — автоматическое исправление ошибок с rollback
- [x] **Health Check** — полная диагностика проекта
- [x] **GraphRAG query engine** — навигация по графу знаний (impact, feature, deps, tests)
- [x] **Cross-project dependency graph** — граф зависимостей между проектами (`cross_project_deps`)
- [x] **Time-aware search** — фильтрация по времени (`search_code` since/before)
- [x] **Index timeline** — история изменений индекса (`get_index_timeline`)

---

## Приоритизация

```
Сейчас (90–95%) — ВСЕ ФАЗЫ ЗАВЕРШЕНЫ ✅
    │
    ▼
Phase 1: Enhanced Graph ──────────────────────► 85% ✅
    │  - Impact Analysis
    │  - Graph query API
    │
    ▼
Phase 2: Semantic Enhancement ───────────────► 88% ✅
    │  - LLM chunk descriptions (+40-50% качество поиска)
    │  - RepoRank
    │  - Branch-aware индекс
    │
    ▼
Phase 3: Code Memory ────────────────────────► 92% ✅
    │  - Commit memory
    │  - Bug correlation
    │  - GraphRAG query engine
    │
    ▼
Phase 4: Full GraphRAG ──────────────────────► 95% ✅
       - Knowledge graph navigation
       - Cross-project dependency graph
       - Time-aware search
       - Index timeline
```

---

## Как внести вклад
## Приоритизация

Все основные фазы завершены. Приоритетные направления для контрибьюторов:

1. **Расширение моделей** — поддержка новых embedding/reranking провайдеров
2. **Оптимизация производительности** — ускорение индексации больших проектов
3. **Документация** — примеры использования, туториалы

См. [CONTRIBUTING.md](CONTRIBUTING.md) для деталей.

---

*Последнее обновление: 2026-06-30*
