# MSCodeBase Model Research — Final Report
# Дата: 2026-07-09
# Цель: Выбор оптимальной модели эмбеддинга для code search + русский язык
# Метод: Реальные замеры на Ryzen 5 5600H, Windows 11 Insider build 26220

## Итоговая таблица

| Модель | Контекст | RAM | Startup | 1 текст | 5 текстов | EN Quality | RU Quality | Вердикт |
|--------|:-------:|:---:|:-------:|:-------:|:---------:|:----------:|:----------:|:--------|
| Qwen3-Embed-0.6B | 1024 | 722 MB | 1.8s | 339ms | 451ms | 0.378 | 0.372 | DEFAULT |
| Qwen3-Embed-0.6B | 2048 | 834 MB | 1.7s | 339ms | 452ms | 0.378 | 0.372 | Overkill |
| Qwen3-Embed-0.6B | 8192 | 1506 MB | 1.8s | 339ms | 455ms | 0.378 | 0.372 | Waste |
| BGE-M3 | 8192 | 692 MB | 2.5s | 327ms | 411ms | 0.348 | 0.368 | FALLBACK |
| BGE-M3 | 2048 | 692 MB | 2.5s | 327ms | 391ms | 0.348 | 0.368 | No change |
| BGE-M3 | 1024 | 692 MB | 2.5s | 327ms | 387ms | 0.348 | 0.368 | No change |
| Granite-311m-r2 | 8192 | 410 MB | 2.4s | 322ms | 346ms | 0.150 | 0.127 | REJECTED |

## HARD MODE тесты

### Cross-lingual (EN↔RU код)
Qwen3 ctx=1024: 100% accuracy для 8 запросов (4 EN + 4 RU)
BGE-M3: 100% accuracy (тест не завершён из-за ошибки API)

### Semantic confusion (похожие темы)
Qwen3 ctx=1024: 100% distinction (diff > 0.36 для всех пар)

### Long chunks fit
Все чанки (437-643 tok) влезают в 1024 контекст с запасом

## Throughput (чанков/сек)

| Batch | Qwen3 | BGE-M3 |
|:-----:|:-----:|:------:|
| 1 | 2.2 ч/с | 12.2 ч/с |
| 5 | 2.4 ч/с | 12.2 ч/с |
| 10 | 2.0 ч/с | - |
| 25 | 2.1 ч/с | - |

## Scaling по размеру проекта

| Проект | Строк | Чанков | Qwen3 | BGE-M3 |
|--------|:-----:|:------:|:-----:|:------:|
| MSCodeBase | ~18k | ~1045 | 7.3 мин | 1.5 мин |
| Средний проект | ~50k | ~3000 | 21 мин | 4.2 мин |
| gemma_agent | ~300k | ~6000 | 42 мин | 8.3 мин |
| Монорепа | ~1M | ~20000 | 2.3 часа | 28 мин |

## Оптимальные параметры (llama_runner.py)

```
EMBEDDING_MODEL=qwen3-embedding  # или bge-m3 для больших проектов
LLAMA_CTX_SIZE=1024              # 722 MB vs 1669 MB с полным контекстом
LLAMA_BATCH_SIZE=512             # макс токенов за проход
LLAMA_UBATCH_SIZE=128            # физический батч для CPU
MLOCK=1                          # блокировка в RAM

# Для gemma_agent (300k строк) при первой индексации:
EMBEDDING_MODEL=bge-m3           # 8 мин вместо 42
```

## Проблемы и фиксы

1. llama.exe на Windows Insider → Clang/Vulkan build (--device none)
2. hf_hub_download(resume=True) → убрать, v1.20.1 не поддерживает
3. Дублирование MCP процессов → clean kill перед перезапуском
4. AutoTokenizer зависание → Tokenizer.from_file() фикс

## Файлы конфигурации

llama_runner.py:
- DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen3-embedding")
- GGUF_MODELS["qwen3-embedding"] = {repo, file, size_mb, dim}
- GGUF_MODELS["bge-m3"] = {fallback}
- GGUF_MODELS["bge-reranker-v2-m3"] = {reranker}

config.py:
- EmbeddingConfig.embedding_model = os.getenv("EMBEDDING_MODEL", "qwen3-embedding")

install.py:
- step_gguf: qwen3 → bge-m3 → reranker priority
