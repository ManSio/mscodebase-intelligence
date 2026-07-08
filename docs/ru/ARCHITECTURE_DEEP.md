# MSCodeBase Intelligence — Глубокое Руководство по Архитектуре

[🇬🇧 English](../en/ARCHITECTURE_DEEP.md) • [🇷🇺 Русский](ARCHITECTURE_DEEP.md) • [🇨🇳 中文](../zh/ARCHITECTURE_DEEP.md)

> **Версия:** v2.7.0+ | **Последнее обновление:** 2026-07-07

```mermaid
flowchart TD
    User[Пользователь / AI-Агент] --> MCP[MCP Сервер\n50 инструментов]
    MCP --> DI[DI Контейнер\n15 сервисов]
    DI --> Search[Поисковый Конвейер]
    DI --> Index[Конвейер Индексации]
    DI --> Intel[Интеллектуальный Слой]
    DI --> Health[Здоровье и Диагностика]
    
    Search --> BM25[BM25 Разреженный\nключевой поиск]
    Search --> Dense[LanceDB Плотный\nвекторный поиск]
    Search --> RRF[RRF Фьюжн\nранжирование]
    Search --> Rerank[Кросс-энкодер\nbge-reranker-v2-m3]
    Search --> Bucket[Multi-Bucket RAG\nвзвешивание код/доки]
    Search --> CoChange[Co-change буст\ngit связанность]
    
    Intel --> Topology[Топология кода\nграф вызовов]
    Intel --> Memory[Память проекта\nADR / долг / проблемы]
    Intel --> RCA[Анализ первопричин\nпредсказание ошибок]
    
    Health --> Report[Отчёт здоровья\nполная диагностика]
    Health --> Guard[Страж Индекса\nсамовосстановление]
```

---

## 1. Слои Архитектуры

Система разделена на 10 runtime-слоёв — от инфраструктурного (самый нижний) до пользовательского (самый верхний).

```mermaid
flowchart LR
    subgraph "Слой 10 — MCP Инструменты"
        T1[search_code]
        T2[get_symbol_info]
        T3[impact_analysis]
        T4[intel_*]
    end
    subgraph "Слой 9 — Error Boundary"
        EB[@error_boundary\nтаймаут + retry]
    end
    subgraph "Слой 8 — Интеллект"
        IL[intel_predict_root_cause\nintel_code_topology\nintel_get_project_memory]
    end
    subgraph "Слой 7 — Поиск"
        SH[hybrid_search_async\nRRF + реранкер + корзины]
    end
    subgraph "Слой 6 — Индекс"
        IX[Indexer\nLanceDB + BM25 + SymbolIndex]
    end
    subgraph "Слой 5 — Эмбеддинги"
        EM[RemoteEmbedder\nLM Studio / Ollama / ONNX]
    end
    subgraph "Слой 4 — Парсинг"
        PS[Tree-sitter AST\nParser + SymbolIndex]
    end
    subgraph "Слой 3 — Хранилище"
        ST[LanceDB v2\nизоляция проектов]
    end
    subgraph "Слой 2 — Rate Limiting"
        RL[CircuitBreaker\nDebounceBatch\nSlidingWindow]
    end
    subgraph "Слой 1 — DI Контейнер"
        DI[ServiceCollection\n15 синглтонов + фабрик]
    end
    T1 --> EB --> IL --> SH --> IX --> EM --> PS --> ST --> RL --> DI
```

---

## 2. Поисковый Конвейер — Полный Поток

```mermaid
sequenceDiagram
    participant User as AI-Агент
    participant MCP as MCP Сервер
    participant EB as error_boundary
    participant ST as SearchTool
    participant S as Searcher
    participant I as Indexer
    participant E as Embedder
    participant DB as LanceDB
    participant R as Reranker

    User->>MCP: search_code(query="auth", mode="quality")
    MCP->>EB: @error_boundary(timeout=10000)
    EB->>ST: execute(query, mode, intent_hint)
    
    par BM25 Поиск
        ST->>S: bm25_search_async(query)
        S->>I: table.search().where(...)
        I-->>S: BM25 результаты (разреженные)
    and Плотный Поиск
        ST->>S: эмбеддинг запроса
        S->>E: embed_batch_async([query])
        E-->>S: вектор запроса (1024-dim)
        S->>DB: search(vector, limit=raw_limit)
        DB-->>S: плотные результаты
    end
    
    S->>S: RRF Фьюжн (k=60)
    S->>S: Взвешивание корзин (код/доки)
    S->>S: Co-change Буст (git связанность)
    
    opt реранкер доступен
        S->>R: rerank(query, кандидаты, top_n=5)
        R-->>S: переранжированные оценки
    end
    
    S-->>EB: отсортированные результаты
    EB-->>MCP: форматированный ответ
    MCP-->>User: результаты с путями файлов
```

### Производительность Режимов

| Режим | Конвейер | Задержка | Сценарий |
|-------|----------|---------|----------|
| `fast` | Только BM25 | ~300ms | Поиск символа |
| `quality` | BM25 + Dense + RRF + Реранкер | ~1200ms | Вопросы по архитектуре |
| `deep` | Рекурсивный граф | 2-5s | Сложные расследования |
| `context` | Поиск похожего кода | ~500ms | Найти похожий фрагмент |
| `ask` | Поиск → phi-4 генерация | 5-15s | RAG ответ на вопрос |

---

## 3. Жизненный Цикл Инструмента

```mermaid
flowchart TD
    Start[Агент вызывает инструмент] --> Resolve[DI Контейнер резолвит сервис]
    Resolve --> Guard{RuntimeCoordinator\ncan_execute?}
    Guard -->|заблокирован| Error[Возврат ошибки\nс подсказкой]
    Guard -->|готов| Boundary[error_boundary оборачивает\nс таймаутом + retry]
    
    Boundary --> Execute[Tool.execute параметры]
    Execute --> LMEnd{LM Studio\nдоступен?}
    
    LMEnd -->|да| LM[RemoteEmbedder\nэмбеддинги через LM Studio]
    LMEnd -->|нет| ONNX[RemoteEmbedder\nэмбеддинги через ONNX Runtime]
    
    LM --> Result[Возврат структурированного результата]
    ONNX --> Result
    
    Result --> Telemetry[record_tool_call\nметрики + задержка]
    Telemetry --> Done[Ответ агенту]
    
    Boundary -->|таймаут| Retry{Повторы\nостались?}
    Retry -->|да| Execute
    Retry -->|нет| Timeout[Ошибка таймаута]
```

---

## 4. Модель Данных

```mermaid
erDiagram
    CHUNK ||--o{ METADATA : содержит
    CHUNK {
        string id PK
        vector vector "1024-dim float"
        string text "компактный чанк"
        string text_full "полный код функции"
        string file_path "относительный путь"
        string file_hash "MD5 для инкремента"
        int chunk_index
        string source "lsp_vfs | filesystem"
        string indexed_at ISO8601
        string summary "LLM-описание"
        string callees "JSON массив callee"
        float health_score "1-10"
        string health_band "healthy|warning|alert"
    }
    METADATA {
        string layer "core | mcp | tests"
        string module_name "core.searcher"
        string hierarchy_level "function | class | module"
        bool is_public
        string symbol_type "function_definition"
        string parent_id "хеш для multi-granularity"
    }
    SYMBOL {
        string name
        string file_path
        int line
        string kind
        bool is_definition
    }
    SYMBOL ||--o{ SYMBOL : вызывает
```

---

## 5. Сравнение: MSCodeBase vs Экосистема

| Критерий | **MSCodeBase** | Qartez MCP | CodeGraph | SymDex |
|-----------|:--------------:|:----------:|:---------:|:------:|
| **Язык** | Python + LanceDB (Rust-core) | Rust | TypeScript | - |
| **Поиск** | BM25 + Dense + RRF + Реранкер | Статический анализ | Граф знаний | Поиск символов |
| **Инструментов** | **50** | 30+ | - | - |
| **Тестов** | **396** | - | - | - |
| **Windows** | **Нативно** (UNC, MAX_PATH) | - | - | - |
| **Инкр. индекс** | MD5 + DebounceBatch | - | - | - |
| **Само-восстановление** | IndexGuard | - | - | - |
| **Память проекта** | ADR / долг / проблемы | - | - | - |
| **Реранкер** | bge-reranker-v2-m3 | - | - | - |
| **Co-change** | Матрица git связанности | - | - | - |
| **Здоровье** | Полная диагностика | - | - | - |
| **Документация** | **3 языка** | 1 | 1 | 1 |
| **Лицензия** | MIT | Двойная | MIT | - |

---

## 6. Уровни Деградации

```mermaid
flowchart LR
    L1["Уровень 1: LM Studio\nПолный конвейер\n300ms-5s"] -->|офлайн| L2
    L2["Уровень 2: ONNX Runtime\nТолько эмбеддинги\nCPU, медленнее"] -->|нет модели| L3
    L3["Уровень 3: Только BM25\nКлючевой поиск\nБез семантики"] -->|нет индекса| L4
    L4["Уровень 4: Fallback\nСоздание индекса\nПервый запуск"]
```

**Авто-восстановление:** Система непрерывно сканирует доступность LM Studio/Ollama.
При появлении более высокого уровня — переключается автоматически, без рестарта.

---

## 7. Ключевые Метрики

| Метрика | Значение |
|---------|----------|
| **Режимы поиска** | 6 (fast, quality, deep, context, ask, auto) |
| **MCP инструментов** | 50 (34 core + 14 intel) |
| **Сервисов в DI** | 15 |
| **Тестов** | 396 |
| **Языков** | 3 (EN, RU, ZH) |
| **Полей схемы** | 19 (чанк: 9 + мета: 6 + v3.0: 4) |
| **Размерность эмбеддинга** | 1024 (bge-m3) |
| **Реранкер** | bge-reranker-v2-m3 |
| **LLM** | phi-4-mini-instruct |
| **Векторная БД** | LanceDB v2 |
| **Парсер** | Tree-sitter |
