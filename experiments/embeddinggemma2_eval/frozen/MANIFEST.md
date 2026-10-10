# E18 MANIFEST — параметры воспроизводимости (единый чек-лист, §18)

reasoning: ручной прогон агентом, без LLM-судей (все метрики детерминированы кодом)
variant: bench_e18.py (форк bench.py E14, diff минимален: +пресеты gemma2, +префиксы CodeRetrieval, +контроли, +T10-guard)
temperature: N/A (эмбеддинги детерминированы, pooling mean)
seed: N/A (порядок файлов/запросов сортирован)
code_version: записать git-sha bench_e18.py в results/*.json (поле env.git_sha)
isolation: отдельный порт на пресет (8093+), сервер старт/стоп внутри прогона, prod :8080/:8081 не трогаем
env: Win11 x64, CPU threads=10, llama-server b9940 (прод-бинарник, первая проба); при unsupported-arch → свежий релиз llama.cpp только в experiments/, прод не меняем
server_flags: -c 2048 --batch-size 2048 --ubatch-size {512|2048} --threads 10 --cache-type-k q4_0 --cache-type-v q4_0 --no-webui -ngl 0 --embedding --pooling mean
client: POST /v1/embeddings raw text (parity) ИЛИ CodeRetrieval-префиксы (vendor), L2-нормализация
models: ggml-org/embeddinggemma-2-GGUF (Q8_0 ~310MB, BF16 ~558MB) + prod multilingual-e5-small-Q8_0 (тот же сеанс, контроль)
scope: ТОЛЬКО текст. image/audio/video через llama-server --embedding не поддерживаются (mmproj — для генеративных VLM, не для embedding-endpoint) — зафиксировано как граница, не пропуск
verdict_rule: число публикуется только из results/*.json текущей сессии; чужой вердикт (MTEB 78.68) — не наш, цитируем отдельно
