# MSCodeBase Intelligence — Руководство по глубокой архитектуре

[🇬🇧 English](../en/ARCHITECTURE_DEEP.md) • [🇷🇺 Русский](ARCHITECTURE_DEEP.md) • [🇨🇳 中文](../zh/ARCHITECTURE_DEEP.md)

> **Версия:** v3.0.0 | **Последнее обновление:** 2026-07-11

> **Примечание:** Полный перевод architecture diagrams на русский язык
> требует обновления mermaid-диаграмм. См. английскую версию для актуальных схем.

```mermaid
flowchart TD
    User[User / AI Agent] --> MCP[MCP Server\n57 tools]
    MCP --> DI[DI Container\n18 services]
    DI --> Search[Search Pipeline]
    DI --> Index[Indexing Pipeline]
    DI --> Intel[Intelligence Layer]
    DI --> Health[Health & Diagnostics]
    
    Search --> BM25[BM25 Sparse\nkeyword search]
    Search --> Dense[LanceDB Dense\nvector search]
    Search --> RRF[RRF Fusion\nreciprocal rank fusion]
    Search --> Rerank[Cross-encoder\nbge-reranker-v2-m3]
    Search --> Bucket[Multi-Bucket RAG\ncode/docs weighting]
    Search --> CoChange[Co-change boost\ngit coupling]
    
    Intel --> Topology[Code Topology\ncall graph]
    Intel --> Memory[Project Memory\nADR / debt / issues]
    Intel --> RCA[Root Cause Analysis\nerror prediction]
    
    Health --> Report[Health Report\nfull diagnostics]
    Health --> Guard[Index Guard\nself-recovery]
```

---

## 1. Архитектурные слои

Система разделена на 10 runtime-слоёв, от нижнего (инфраструктура) до верхнего (пользовательские инструменты).

```mermaid
flowchart LR
    subgraph "Layer 10 — MCP Tools"
        T1[search_code]
        T2[get_symbol_info]
        T3[impact_analysis]
        T4[intel_*]
    end
    subgraph "Layer 9 — Error Boundary"
        EB[@error_boundary\ntimeout + retry]
    end
    subgraph "Layer 8 — Intelligence"
        IL[intel_predict_root_cause\nintel_code_topology\nintel_get_project_memory]
    end
    subgraph "Layer 7 — Search"
        SH[hybrid_search_async\nRRF + reranker + buckets]
    end
    subgraph "Layer 6 — Index"
        IX[Indexer\nLanceDB + BM25 + SymbolIndex]
    end
    subgraph "Layer 5 — Embeddings"
        EM[RemoteEmbedder\nllama.cpp GGUF / LM Studio / ONNX]
    end
    subgraph "Layer 4 — Parsing"
        PS[Tree-sitter AST\nParser + SymbolIndex]
    end
    subgraph "Layer 3 — Storage"
        ST[LanceDB v2\nper-project isolation]
    end
    subgraph "Layer 2 — Rate Limiting"
        RL[CircuitBreaker\nDebounceBatch\nSlidingWindow]
    end
    subgraph "Layer 1 — DI Container"
        DI[ServiceCollection\n15 singletons + factories]
    end
    T1 --> EB --> IL --> SH --> IX --> EM --> PS --> ST --> RL --> DI
```

---

## 2. Поисковый пайплайн — полный поток

```mermaid
sequenceDiagram
    participant User as AI Agent
    participant MCP as MCP Server
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
    
    par BM25 Search
        ST->>S: bm25_search_async(query)
        S->>I: table.search().where(...)
        I-->>S: BM25 results (sparse)
    and Dense Search
        ST->>S: embed query vector
        S->>E: embed_batch_async([query])
        E-->>S: query vector (1024-dim)
        S->>DB: search(vector, limit=raw_limit)
        DB-->>S: dense results
    end
    
    S->>S: RRF Fusion (k=60)
    S->>S: Bucket Weighting (code/docs)
    S->>S: Co-change Boost (git coupling)
    
    opt reranker available
        S->>R: rerank(query, candidates, top_n=5)
        R-->>S: reranked scores
    end
    
    S-->>EB: sorted results
    EB-->>MCP: formatted response
    MCP-->>User: search results with file paths
```

### Производительность режимов

| Режим | Пайплайн | Задержка | Сценарий использования |
|-------|----------|----------|----------------------|
| `fast` | Только BM25 | ~300ms | Поиск точного символа |
| `quality` | BM25 + Dense + RRF + Reranker | ~1200ms | Архитектурные вопросы |
| `deep` | Рекурсивное расширение графа | 2-5s | Сложные расследования |
| `context` | Поиск похожего кода по фрагменту | ~500ms | Найти похожий код |
| `ask` | Поиск → генерация phi-4 | 5-15s | RAG ответы на вопросы |

---

## 3. Жизненный цикл инструмента

```mermaid
flowchart TD
    Start[Agent вызывает инструмент] --> Resolve[DI Container разрешает сервис]
    Resolve --> Guard{RuntimeCoordinator\ncan_execute?}
    Guard -->|blocked| Error[Возврат ошибки\nс подсказкой по восстановлению]
    Guard -->|ready| Boundary[error_boundary оборачивает вызов\nс timeout + retry]
    
    Boundary --> Execute[Tool.execute params]
    Execute --> LMEnd{llama.cpp / LM Studio\nдоступен?}
    
    LMEnd -->|yes| LLAMA[RemoteEmbedder\nllama.cpp GGUF (GPU)]
    LMEnd -->|no| LM[RemoteEmbedder\nэмбеддинги через LM Studio]
    LMEnd -->|no| ONNX[RemoteEmbedder\nэмбеддинги через ONNX Runtime]
    
    LM --> Result[Возврат структурированного результата]
    LLAMA --> Result
    ONNX --> Result
    
    Result --> Telemetry[record_tool_call\nметрики + задержка]
    Telemetry --> Done[Ответ агенту]
    
    Boundary -->|timeout| Retry{Остались\nповторы?}
    Retry -->|yes| Execute
    Retry -->|no| Timeout[Ошибка таймаута]
```

---

## 4. Взаимодействие компонентов — поток запуска

```mermaid
sequenceDiagram
    participant Zed as Zed IDE
    participant MCP as MCP Server
    participant DI as DI Container
    participant IX as Indexer
    participant EM as Embedder
    participant LM as LM Studio
    participant DB as LanceDB

    Zed->>MCP: Запуск context server
    MCP->>DI: create_service_collection()
    DI->>DI: Регистрация 15 сервисов
    
    par Последовательность запуска
        DI->>IX: Создание Indexer
        IX->>DB: open_table / create_table
        DB-->>IX: table handle
        IX->>IX: _warmup_status()
        IX-->>DI: Indexer готов
    and
        DI->>EM: Создание RemoteEmbedder
        EM->>EM: _init_provider_async() [фон]
        EM->>LM: проверка /v1/models
        LM-->>EM: доступен (bge-m3, phi-4)
        EM-->>DI: Embedder готов
    end
    
    DI-->>MCP: Контейнер готов
    MCP->>MCP: Регистрация 56 инструментов
    MCP-->>Zed: Сервер готов (PID объявлен)
    
    Note over Zed,DB: Общий запуск: ~2-5s (асинхронная инициализация embedder)
```

---

## 5. Архитектура Intelligence Layer

```mermaid
flowchart LR
    subgraph "Intel Tools"
        RTS[intel_get_runtime_status]
        CT[intel_code_topology]
        PM[intel_get_project_memory]
        RCA[intel_predict_root_cause]
        AI[intel_analyze_incident]
        TL[intel_get_telemetry]
        HOT[intel_get_hotspots]
    end
    
    subgraph "Сервисы поддержки"
        SI[SymbolIndex]
        IDX[Статус Indexer]
        ERR[История ошибок]
        TEL[Метрики телеметрии]
    end
    
    RTS --> IDX
    CT --> SI
    PM --> PMDB[(Project Memory\nJSON store)]
    RCA --> ERR
    RCA --> SI
    AI --> ERR
    TL --> TEL
    HOT --> SI
    HOT --> IDX
```

---

## 6. Модель данных

```mermaid
erDiagram
    CHUNK ||--o{ METADATA : contains
    CHUNK {
        string id PK
        vector vector "1024-dim float"
        string text "compact chunk"
        string text_full "полный текст функции"
        string file_path "относительный путь"
        string file_hash "MD5 для инкрементального"
        int chunk_index
        string source "lsp_vfs | filesystem"
        string indexed_at ISO8601
        string summary "LLM-сгенерированное"
        string callees "JSON-массив имён callee"
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
    SYMBOL ||--o{ SYMBOL : calls
```

---

## 7. Сравнение: MSCodeBase vs Экосистема

| Критерий | **MSCodeBase** | Qartez MCP | CodeGraph | SymDex |
|----------|:--------------:|:----------:|:---------:|:------:|
| **Язык** | Python + LanceDB (Rust-core) | Rust | TypeScript | - |
| **Поиск** | BM25 + Dense + RRF + Reranker | Static analysis | Knowledge Graph | Symbol lookup |
| **Инструменты** | **43** | 30+ | - | - |
| **Тесты** | **396** | - | - | - |
| **Windows** | **Нативный** (UNC, MAX_PATH) | - | - | - |
| **Инкрементальный индекс** | MD5 + DebounceBatch | - | - | - |
| **Самовосстановление** | IndexGuard | - | - | - |
| **Проектная память** | ADR / debt / issues | - | - | - |
| **Реренкер** | bge-reranker-v2-m3 | - | - | - |
| **Co-change** | Матрица git coupling | - | - | - |
| **Здоровье** | Полная диагностика | - | - | - |
| **Документация** | **3 языка** | 1 | 1 | 1 |
| **Лицензия** | MIT | Dual | MIT | - |

---

## 8. Сравнение системных профилей

| Функция | `light` profile | `server` profile |
|---------|:---------------:|:----------------:|
| `mode=ask` (phi-4) | ❌ Заблокирован | ✅ Доступен |
| Асинхронный поиск | ✅ | ✅ |
| Реренкер | ✅ | ✅ |
| Использование RAM | ~150 MB | ~300 MB (с phi-4) |
| Время запуска | ~1s | ~3s |
| Сценарий | Ежедневная разработка | Глубокий анализ |

---

## 9. Уровни отказоустойчивости (graceful degradation)

```mermaid
flowchart LR
    L1["Уровень 1: llama.cpp GGUF\nGPU эмбеддинги + reranker\n280ms-3s"] -->|offline| L2
    L2["Уровень 2: ONNX Runtime\nТолько CPU эмбеддинги\nМедленнее"] -->|missing| L3
    L3["Уровень 3: LM Studio\nВнешний API\n300ms-5s"] -->|offline| L4
    L4["Уровень 4: Только BM25\nКлючевой поиск\nБез семантики"] -->|index missing| L5
    L5["Уровень 5: Fallback\nСоздание индекса\nПервый запуск"]
```

**Автовосстановление:** Система непрерывно сканирует llama.cpp GGUF, затем LM Studio/Ollama.
Когда более высокий уровень становится доступен, переключение происходит автоматически — без перезапуска.

---

## 10. Ключевые метрики

| Метрика | Значение |
|---------|---------|
| **Режимы поиска** | 6 (fast, quality, deep, context, ask, auto) |
| **MCP инструменты** | 50 (34 core + 14 intel + 2 diagnostic) |
| **Сервисы в DI** | 15 |
| **Тесты** | 396 |
| **Языки** | 3 (EN, RU, ZH) |
| **Поля схемы** | 19 (chunk: 9 + metadata: 6 + v3.0: 4) |
| **Размерность эмбеддинга** | 1024 (bge-m3) |
| **Реренкер** | bge-reranker-v2-m3 |
| **LLM** | phi-4-mini-instruct |
| **Векторная БД** | LanceDB v2 |
| **Парсер** | Tree-sitter |
