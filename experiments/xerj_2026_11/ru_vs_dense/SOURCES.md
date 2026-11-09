# Внешние источники (не наши замеры)

Все числа ниже — утверждения источников, на нашем железе не воспроизводились.
Наши собственные замеры — в `../RESEARCH_DENSE_COST.md` §2 и в `frozen/`.

## Скорость и стоимость эмбеддингов

**GigaGPU, «Embedding Speed: GPU vs CPU Benchmark», 2026-04**
https://gigagpu.com/embedding-speed-gpu-vs-cpu/

- BGE-Large 335M, Xeon 8480+ (32 ядра), ONNX Runtime, вход 512 токенов:
  batch 1 → 55 текстов/с; batch 512 → 220 текстов/с.
- RTX 5090: 330/с (batch 1) → 3 200/с (batch 512); RTX 6000 Pro: 500 → 4 500/с.
- 1 млн чанков: 75 мин на CPU против 5.5 мин на RTX 6000 Pro (13x).
- Единичный запрос: 17–32 мс на CPU, 2–5 мс на GPU.

**Runpod, «Which GPU should you actually use for embedding workloads?», 2026-09**
https://www.runpod.io/blog/gpu-embedding-workloads-benchmark

- bge-m3 (568M, 1024d), пассажи 512 токенов, TEI:
  RTX A5000 ~190 текстов/с; RTX 6000 Ada ~275; H100 SXM ~1 240; H200 ~1 345.
- Стоимость: 0.78 USD (A5000) … 2.75 USD (B200) за 1 млрд входных токенов.
- Одиночный запрос: p50 3–16 мс на GPU.
- Выбор движка меняет пропускную способность до 11x на той же карте.

## Качество/скорость альтернатив

**Hugging Face, «Train 400x faster Static Embedding Models», 2025-01**
https://huggingface.co/blog/static-embeddings

- Static-эмбеддинги: 87.4% качества all-mpnet-base-v2, 397x быстрее на CPU,
  24x быстрее на GPU.
- Мультиязычная static-модель теряет ~8% против multilingual-e5-small, но заявлена
  для **similarity**, а не retrieval.

**MTEB-сводки (агрегаторы, не первоисточник)**
https://supermemory.ai/blog/best-open-source-embedding-models-benchmarked-and-ranked/
https://www.tigerdata.com/blog/finding-the-best-open-source-embedding-model-for-rag

- EmbeddingGemma-300m: MTEB Multilingual v2 retrieval 62.49, 768d.
- BGE-M3: MTEB Multilingual 59.56, 1024d, 568M.
- Qwen3-Embedding-8B: 70.58 (лидер на момент публикации).

## Перевод запроса как метод (наш вопрос)

**Saleh & Pecina, ACL 2020, «Document Translation vs. Query Translation for
Cross-Lingual Information Retrieval in the Medical Domain»**
https://aclanthology.org/2020.acl-main.613/

Вывод: перевод запроса (QT) статистически превосходит перевод документов (DT) для
всех языков коллекции; NMT улучшает оба подхода, но QT остаётся лучше. Это ровно
наша стратегия: переводить короткий запрос, а не индексировать корпус в другом
языковом пространстве.

**Microsoft Azure AI Foundry, «query rewriting and new semantic ranker»**
https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/raising-the-bar-for-rag-excellence-query-rewriting-and-new-semantic-ranker/4302729

- Generative Query Rewriting: +4 пункта NDCG@3 на term-based индексах, особенно
  когда recall низкий.

**Elastic, «Query rewriting strategies for LLMs & search engines»**
https://www.elastic.co/search-labs/blog/query-rewriting-llm-search-improve

- NDCG@10: исходный запрос 0.346 → 0.364 (Sonnet) / 0.368 (Haiku) при лексическом
  обогащении запроса.

**Ограничение этих источников:** CLIR-работа — медицинский домен и SMT/NMT, не код;
Microsoft/Elastic — веб-поиск, не код. Перенос на поиск по коду проверяется только
нашим прогоном.
