# Поисковый пайплайн — Полная техническая документация

> **Часть MSCodeBase Intelligence** | v3.0.0

## Обзор

Поисковый пайплайн — ядро MSCodeBase. Он объединяет **4 этапа поиска** для нахождения наиболее релевантного контекста кода.

```mermaid
flowchart TD
    Q[User Query] --> PRE[Preprocessing]
    PRE --> INT{Intent Detection}
    INT -->|code intent| CW[Code-optimized weights]
    INT -->|docs intent| DW[Docs-optimized weights]
    INT -->|auto| BW[Balanced weights]
    
    CW --> PAR[Parallel Search]
    DW --> PAR
    BW --> PAR
    
    subgraph PAR[Parallel Search — 2 channels]
        BM25[BM25 Sparse\nkeyword match]
        DENSE[LanceDB Dense\nsemantic search]
    end
    
    BM25 --> RRF[RRF Fusion\nk=60]
    DENSE --> RRF
    
    RRF --> BUCKET[Multi-Bucket RAG\nsoft weighting]
    BUCKET --> CO[Co-change boost\ngit coupling]
    CO --> GRAPH[Graph expand\ncallees from AST]
    GRAPH --> RERANK[Cross-encoder\nbge-reranker-v2-m3]
    
    RERANK --> CUT[Cut to limit]
    CUT --> FMT[Format response]
    FMT --> RES[Final Results]
```

## Детали этапов

### 1. Расширение запроса (Query Expansion)

```python
_EXPANSION_SYNONYMS = {
    "auth": ["authentication", "login", "authorize"],
    "error": ["exception", "failure", "bug"],
    "create": ["add", "insert", "new"],
    # ... ещё 8 групп
}

def expand_query(query: str, max_expansions: int = 3) -> list[str]:
    """Генерирует варианты с синонимами. Каждый вариант ищется независимо."""
    variants = [query]
    words = query.lower().split()
    for word in words:
        synonyms = _EXPANSION_SYNONYMS.get(word, [])
        for syn in synonyms[:max_expansions - 1]:
            variant = query.replace(word, syn, 1)
            if variant not in variants:
                variants.append(variant)
    return variants
```

### 2. BM25 поиск (разреженный)

- **Назначение:** Точное совпадение по ключевым словам — находит код, содержащий конкретные термины
- **Индекс:** Инкрементальный, строится из чанков LanceDB, хранится как `Dict[doc_id, Dict[term, tf-idf]]`
- **Обновление:** DebounceBatch (500ms) при изменениях файлов, полная перестройка при реиндексации
- **Производительность:** O(log N) на запрос

```mermaid
flowchart LR
    subgraph BM25[BM25 Index Building]
        A[LanceDB chunks] --> B[Tokenize + TF]
        B --> C[Compute IDF]
        C --> D[Score matrix\nterm → doc → tf-idf]
    end
    subgraph BM25Q[BM25 Query]
        Q[Query] --> QT[Tokenize]
        QT --> SC[Sum tf-idf per doc]
        SC --> TOP[Top-k results]
    end
```

### 3. Плотный поиск (векторный, LanceDB)

- **Назначение:** Семантическая близость — находит концептуально связанный код
- **Модель:** `multilingual-e5-base` (intfloat, 768-dim)
- **Провайдер:** ONNX INT8 in-process (primary) / LM Studio (fallback)
- **Индекс:** LanceDB v2 с IVF-PQ квантизацией

```python
async def dense_search(query_vector: list, limit: int) -> list:
    table = await ensure_async_table()
    builder = await table.search(query_vector, vector_column_name="vector")
    df = await builder.limit(limit).to_pandas()
    return [{"text": row["text"], "metadata": {...}} for _, row in df.iterrows()]
```

### 4. RRF Fusion (Reciprocal Rank Fusion)

> ⚠️ **Важно:** Ранги считаются **раздельно** для каждого канала, начиная с 1.
> Объединённый `enumerate(bm25 + dense)` дал бы неверные скоры.

```python
def rrf_fusion(bm25: list, dense: list, k: int = 60) -> list:
    """Слияние результатов BM25 + dense по формуле RRF.
    
    Ранги считаются отдельно для каждого канала (начиная с 1),
    как того требует математически корректная RRF.
    """
    scores = {}
    results_map = {}
    
    # BM25 ранги (отдельный enumerate с start=1)
    for rank, doc in enumerate(bm25, 1):
        key = f"{doc['metadata']['file']}:{doc['metadata']['chunk_index']}"
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        if key not in results_map:
            results_map[key] = {
                **doc,
                "bm25_score": 1.0 / (k + rank),
                "dense_score": 0.0,
            }
        else:
            results_map[key]["bm25_score"] = 1.0 / (k + rank)
    
    # Dense ранги (отдельный enumerate с start=1)
    for rank, doc in enumerate(dense, 1):
        key = f"{doc['metadata']['file']}:{doc['metadata']['chunk_index']}"
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        if key not in results_map:
            results_map[key] = {
                **doc,
                "bm25_score": 0.0,
                "dense_score": 1.0 / (k + rank),
            }
        else:
            results_map[key]["dense_score"] = 1.0 / (k + rank)
    
    for key in results_map:
        results_map[key]["final_score"] = (
            results_map[key]["bm25_score"] + results_map[key]["dense_score"]
        )
    
    return sorted(results_map.values(), key=lambda x: x["final_score"], reverse=True)
```

### 5. Multi-Bucket RAG

```mermaid
flowchart LR
    subgraph Buckets
        CODE[Code Bucket\nweight=1.0]
        DOCS[Docs Bucket\nweight=1.0]
    end
    subgraph Intent
        CODE_HINT[intent_hint=code\ncode*1.2, docs*0.8]
        DOCS_HINT[intent_hint=docs\ncode*0.8, docs*1.2]
        AUTO[intent_hint=auto\nneutral]
    end
    subgraph Extension Detection
        EXT[os.path.splitext\n→ .py, .rs = code\n→ .md, .json = docs]
    end
    RESULTS[Scored results] --> EXT --> |code ext| CODE
    EXT --> |docs ext| DOCS
    CODE --> |multiply by| CODE_HINT
    CODE_HINT --> FINAL[final_score]
    DOCS --> |multiply by| DOCS_HINT
    DOCS_HINT --> FINAL
```

### 6. Co-change Boost

Использует git-историю для повышения файлов, которые исторически изменяются вместе:

```python
def apply_co_change_boost(chunks: list) -> list:
    """Повышает файлы, связанные с топ-3 результатами через git-историю."""
    top_files = {c["metadata"]["file"] for c in chunks[:3]}
    matrix = commit_memory.compute_co_change_matrix()
    
    for chunk in chunks:
        file = chunk["metadata"]["file"]
        partners = matrix.get(file, {})
        if partners and any(tf in partners for tf in top_files):
            best = max(partners.get(tf, 0) for tf in top_files)
            chunk["final_score"] *= (1.0 + best * 0.3)
    return chunks
```

### 7. Кросс-энкодер Reranker

**Модель:** `bge-reranker-v2-m3` (через LM Studio / Ollama)

> **Примечание:** Визуализация реранкера предполагает LM Studio (GPU). При использовании ONNX Runtime (fallback) реранкер использует ту же модель `bge-reranker-v2-m3` через ONNX Runtime (CPU) с пониженной пропускной способностью.

- Оценивает каждую пару (запрос, чанк) независимо — **точнее, чем векторный косинус**
- Реранжит только топ-30 кандидатов (контролируется `MAX_RERANKER_INPUT`)
- Корректно переключается на fallback, если LM Studio недоступна

```python
async def rerank(query: str, candidates: list, top_n: int = 5) -> list:
    """Одноэтапный реранкер: запрос + чанк → оценка релевантности."""
    if not candidates:
        return candidates
    scores = await multi_reranker.rerank(query, candidates)
    for i, chunk in enumerate(candidates):
        chunk["final_score"] = scores[i] if i < len(scores) else 0
    return sorted(candidates, key=lambda x: x["final_score"], reverse=True)[:top_n]
```

## Полная диаграмма последовательности

```mermaid
sequenceDiagram
    participant Agent as AI Agent
    participant MCP as MCP Server
    participant EB as @error_boundary
    participant ST as SearchTool
    participant S as Searcher
    participant E as Embedder
    participant I as Indexer
    participant R as Reranker
    
    Agent->>MCP: search_code(query, mode="quality", intent_hint="code")
    MCP->>EB: wrap(timeout=10000, retries=2)
    EB->>ST: execute()
    
    ST->>S: hybrid_search_async(query, limit=5)
    
    par Разреженный поиск
        S->>I: _bm25_search(query)
        I-->>S: BM25 candidates
    and Плотный поиск
        S->>E: embed_batch_async([query])
        E-->>S: query vector (768-dim)
        S->>I: search_async(vector, limit=30)
        I-->>S: dense candidates
    end
    
    S->>S: RRF fusion (k=60)
    S->>S: Bucket weighting (code intent)
    S->>S: Co-change boost
    
    S->>R: rerank(query, top-15, top_n=5)
    R-->>S: reranked scores
    
    S-->>ST: 5 final results
    ST-->>EB: formatted response
    EB-->>MCP: success + metadata
    MCP-->>Agent: results with file paths
```

## Бенчмарки производительности

| Этап | Время | Накопительно |
|-------|:----:|:----------:|
| Расширение запроса | <1ms | <1ms |
| BM25 поиск | ~150ms | ~150ms |
| Эмбеддинг запроса | ~800ms | ~950ms |
| LanceDB ANN | ~400ms | ~1350ms |
| RRF fusion | <1ms | ~1350ms |
| Bucket weighting | <1ms | ~1350ms |
| Co-change boost | ~50ms | ~1400ms |
| Реранкер (5 кандидатов) | ~1200ms | ~2600ms |
| **Итого (quality mode)** | **~5600ms** | |
| **Итого (fast mode, только BM25)** | **~2300ms** | |
| **Итого (deep mode, рекурсивный)** | **2-5s** | |

> *Замеры с ONNX Runtime (CPU). LM Studio (GPU) может быть в 3-5 раз быстрее.*

## Конфигурация

```ini
# .env настройки поиска
DEFAULT_SEARCH_LIMIT=6
MAX_SEARCH_RESULTS=20
QUERY_SYNONYMS_ENABLED=true
MAX_QUERY_EXPANSIONS=3
OVERFETCH_FACTOR=3
RERANKER_PROVIDERS=ollama,lm_studio

# Веса корзин (1.0 = нейтрально)
CODE_BUCKET_WEIGHT=1.0
DOCS_BUCKET_WEIGHT=1.0
```
