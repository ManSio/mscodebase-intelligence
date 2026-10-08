# E25 MANIFEST — воспроизводимость

candidates: search_with_mode quality, прод-индекс (та же таблица), :8080 УБИТ
  (проверка refused), :8081 УБИТ (rerank пропускается по is_available),
  DISABLE_ONNX_FALLBACK=true; top-10 fused-порядка на запрос; тексты кандидатов —
  как вернул движок (поле text/snippet результата; если пусто — сегмент файла
  по metadata file:chunk, та же нарезка 1/3 как в bench_e18).
rerank: gemma2-Q4 UD-Q4_K_XL (176MB, unsloth) + llama-server b11476
  (commit 98819068; -c 2048 --ubatch-size 512 --threads 10 --pooling mean),
  ОДИН запрос /v1/embeddings на 11 текстов (1 query + 10 docs), L2+cosine.
  raw: тексты как есть. coderet: query `task: code retrieval | query: {q}`,
  doc `title: {file} | text: {chunk}` (формат вендора, E18).
  B-e5: те же 11 текстов через прод :8080 (e5-small-Q8, один батч).
latency: wall-clock на запрос (embed + cosine), p50 по 10 запросам.
verdict: только из results/*.json этой сессии.
