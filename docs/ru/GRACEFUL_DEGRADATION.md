# Graceful Degradation — Руководство по отказоустойчивости

> **Часть MSCodeBase Intelligence** | v3.0.0

## Обзор

MSCodeBase никогда не падает полностью. Вместо этого он **деградирует graceful-образом** через 5 уровней,
сохраняя базовую функциональность даже при отказе внешних сервисов.

```mermaid
stateDiagram-v2
    [*] --> L1_LLAMA: Все сервисы доступны
    
    state L1_LLAMA[Уровень 1: llama.cpp GGUF (GPU)]
        L1_LLAMA: llama.cpp эмбеддер + реранкер (Vulkan GPU)
        L1_LLAMA: BM25 + Dense + Reranker + Co-change
        L1_LLAMA: ~280ms-3s задержка
    end
    
    L1_LLAMA --> L2_ONNX: llama.cpp недоступен
    
    state L2_ONNX[Уровень 2: ONNX Runtime (CPU)]
        L2_ONNX: Только ONNX эмбеддинги
        L2_ONNX: BM25 + Dense (CPU)
        L2_ONNX: Нет реранкера (только BM25 ранжирование)
        L2_ONNX: ~1-6s задержка
    end
    
    L2_ONNX --> L3_LM: llama.cpp офлайн → LM Studio fallback
    
    state L3_LM[Уровень 3: LM Studio (удалённо)]
        L3_LM: Внешний API (порт 1234)
        L3_LM: BM25 + Dense + Reranker
        L3_LM: ~300ms-5s задержка (сеть)
    end
    
    L3_LM --> L4_BM25: Всё внешнее офлайн
    
    state L4_BM25[Уровень 4: Только BM25]
        L4_BM25: Только ключевой поиск
        L4_BM25: Нет семантического понимания
        L4_BM25: ~50ms-300ms задержка
    end
    
    L4_BM25 --> L5_Fallback: BM25 индекс пуст
    
    state L5_Fallback[Уровень 5: Fallback]
        L5_Fallback: Создание индекса
        L5_Fallback: Первый запуск / после удаления таблицы
        L5_Fallback: Пустые результаты (построение индекса)
    end
    
    L5_Fallback --> L4_BM25: Индекс готов
    L4_BM25 --> L3_LM: LM Studio обнаружен
    L3_LM --> L2_ONNX: ONNX перезагружен
    L2_ONNX --> L1_LLAMA: llama.cpp GGUF доступен
    
    L1_LLAMA --> L2_ONNX: Сбой llama
    L2_ONNX --> L3_LM: Ошибка ONNX → сканирование LM Studio
    L3_LM --> L4_BM25: Сбой LM Studio
    L4_BM25 --> [*]: Катастрофический сбой
```

## Детали уровней

### Уровень 1: Полный конвейер (Production)

| Компонент | Статус |
|-----------|:------:|
| LM Studio | ✅ Онлайн |
| BM25 индекс | ✅ Построен |
| Реранкер | ✅ Доступен |
| mode=ask (phi-4) | ✅ Доступен |
| **Задержка** | **300ms-5s** |
| **Качество** | **Наилучшее** |

**Триггер:** LM Studio отвечает на `127.0.0.1:1234/v1/models`

### Уровень 2: ONNX Runtime (Fallback)

```python
# Автоматический fallback, когда LM Studio недоступен
class RemoteEmbedder:
    def _check_lm_studio(self) -> bool:
        """Маршрутизация через CircuitBreaker для предотвращения каскадных сбоев."""
        if self._breaker is not None:
            return bool(self._breaker.call(self._check_lm_studio_raw, fallback=True))
        return self._check_lm_studio_raw()
    
    def _init_onnx(self):
        """Загрузка ONNX модели из .codebase_models/onnx/bge-m3/"""
        if not self.local_model_dir.exists():
            raise FileNotFoundError("Запустите: python scripts/download_model.py")
        self._onnx_session = ort.InferenceSession(str(self.local_model_dir / "model.onnx"))
```

| Компонент | Статус |
|-----------|:------:|
| LM Studio | ❌ Офлайн |
| ONNX модель | ✅ Доступна (438 МБ) |
| Реранкер | ❌ Недоступен |
| mode=ask | ❌ Недоступен |
| **Задержка** | **1-6s** |
| **Качество** | **Хорошее** (только эмбеддинги, без реранкера) |

### Уровень 3: Только BM25 (Минимальный)

```python
# Graceful degradation в BM25 builder
class Searcher:
    def _build_bm25_index(self) -> None:
        if self.indexer.table is None:
            self._bm25 = {}  # Пустой BM25 = деградированный режим
            return
        try:
            if self.indexer.table.count_rows() == 0:
                self._bm25 = {}
                return
        except Exception:
            self._bm25 = {}  # Таблица повреждена → деградированный режим
            return
```

| Компонент | Статус |
|-----------|:------:|
| LM Studio | ❌ Офлайн |
| ONNX модель | ❌ Отсутствует |
| BM25 индекс | ✅ Доступен |
| Реранкер | ❌ Недоступен |
| mode=ask | ❌ Недоступен |
| **Задержка** | **50ms-300ms** |
| **Качество** | **Базовое** (только ключевые слова) |

### Уровень 4: Fallback (Первый запуск)

```python
# Первый запуск после пересоздания таблицы
class Indexer:
    def _warmup_status(self) -> None:
        count = self.table.count_rows()
        self._cached_total_chunks = count
        if count == 0:
            logger.debug("🔥 Холодный старт — пустая база данных")
```

| Компонент | Статус |
|-----------|:------:|
| LM Studio | ❌ Офлайн |
| ONNX модель | ❌ Недоступна |
| BM25 индекс | ❌ Пуст |
| Реранкер | ❌ Недоступен |
| mode=ask | ❌ Недоступен |
| **Задержка** | N/A |
| **Качество** | **Нет** (ожидание индекса) |

## Автовосстановление

```mermaid
sequenceDiagram
    participant EM as RemoteEmbedder
    participant LM as LM Studio
    participant ONNX as ONNX Runtime
    participant BM25 as BM25 Index
    
    Note over EM: Уровень 2 (ONNX)
    EM->>ONNX: embed query
    ONNX-->>EM: вектор (1024-dim)
    
    par Каждые 30s — цикл сканирования
        EM->>LM: GET /v1/models
        LM-->>EM: 200 OK (bge-m3, phi-4)
        EM->>EM: переключение на LM Studio
        Note over EM: Уровень 1 восстановлен!
    end
    
    EM->>LM: embed query (асинхронно)
    LM-->>EM: вектор (быстрее, GPU)
```

**Ключевые свойства:**
- Сканер запускается каждые 30s в фоновом потоке
- Когда более высокий уровень становится доступен → **автоматическое переключение**
- Перезапуск не требуется
- CircuitBreaker предотвращает быстрое циклическое включение/выключение

## Механизмы защиты

```mermaid
flowchart LR
    subgraph "Уровень защиты"
        CB[CircuitBreaker\n5 сбоев → 30s ожидание]
        DB[DebounceBatch\n500ms окно пакетирования]
        RL[RateLimiter\n10 вызовов/с на инструмент]
        IG[IndexGuard\nсамовосстановление при повреждении]
    end
    
    CB --> |открыт| FALLBACK[Fallback на уровень 2/3]
    DB --> |пакет| BM25[Инкрементальная переиндексация]
    RL --> |ограничен| REQ[Запросы MCP]
    IG --> |восстановлена| TABLE[Таблица LanceDB]
```

| Защита | Механизм | Восстановление |
|-----------|-----------|----------|
| **CircuitBreaker** | 5 сбоев → OPEN (30s) → HALF_OPEN → CLOSED | Автовосстановление после ожидания |
| **DebounceBatch** | 500ms окно, макс 100 файлов | Триггерит перестроение BM25 один раз |
| **RateLimiter** | Скользящее окно, 10 вызовов/с на инструмент | Отбрасывает избыток с RateLimitError |
| **IndexGuard** | Проверка количества + валидация схемы | Пересоздаёт таблицу при повреждении |
