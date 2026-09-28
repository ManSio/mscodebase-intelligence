# Jev System One — Эксперименты с TypeSafe AI

## Цель
Проверить реальные возможности Jev (System One model от TypeSafe AI) для интеграции в MSCodeBase:
- Производительность (latency, throughput, RAM)
- Точность на реальных кейсах
- Скрытые возможности и нетрадиционное использование
- Интеграция с AST-графом, маршрутизацией MCP, guardrail-функциями

## Требования
- `TYPESAFE_API_KEY` в окружении или `.env`
- Python 3.10+
- `typesafe-sdk` (`pip install typesafe-sdk`)

## Структура экспериментов

| Скрипт | Что тестирует | Статус |
|--------|---------------|--------|
| `bench_latency.py` | Задержка на разных типах вопросов | готов к запуску |
| `bench_accuracy.py` | Точность на реальных кейсах MSCodeBase | готов к запуску |
| `bench_ram.py` | Потребление RAM | готов к запуску |
| `test_ast_integration.py` | Интеграция с AST-графом | готов к запуску |
| `test_mcp_routing.py` | Маршрутизация MCP-инструментов | готов к запуску |
| `test_guardrail.py` | Guardrail-функции для кода | готов к запуску |
| `test_hidden_capabilities.py` | Нетрадиционное использование | готов к запуску |

## Запуск

```bash
# Установка зависимостей
pip install typesafe-sdk

# Бенчмарк задержки
python experiments/jev_systemone/bench_latency.py

# Тест точности
python experiments/jev_systemone/bench_accuracy.py

# Тест RAM
python experiments/jev_systemone/bench_ram.py

# Интеграция с AST
python experiments/jev_systemone/test_ast_integration.py

# Маршрутизация MCP
python experiments/jev_systemone/test_mcp_routing.py

# Guardrail
python experiments/jev_systemone/test_guardrail.py

# Скрытые возможности
python experiments/jev_systemone/test_hidden_capabilities.py
```

## Что мы уже знаем (из документации и исследований)

### Заявленные метрики
| Метрика | Значение |
|---------|----------|
| Задержка | 70-500ms (средняя ~100ms) |
| Цена input | $0.042/MTok |
| Цена output | Free |
| Точность на System One tasks | Сопоставима с LLM |
| Галлюцинации | 0% (type-safe по архитектуре) |

### Ограничения (из исследований)
1. **"Routing Plateau"** (arXiv:2606.07587): все роутеры сходятся к ~77-80% точности
2. **"Unsolvability Ceiling"** (arXiv:2605.07395): при сильном majority-class роутер коллапсирует
3. **"RAG Makes Guardrails Unsafe"** (arXiv:2510.05310): RAG-контекст делает guardrails небезопасными
4. **"Guardrail Robustness"** (EMNLP 2025): уязвимость к mutations и veiled expressions

### Архитектура Jev
- **Не генерирует текст** — возвращает типизированные решения
- **Три примитива**: `Choice`, `Score`, `Noul`
- **Параллельная обработка**: несколько вопросов к одному состоянию за один проход
- **Обучение**: RLCD (Reinforcement Learning for Calibrated Decisions)

## План экспериментов

### Фаза 1: Базовое тестирование
1. Задержка на разных типах вопросов
2. Потребление RAM
3. Точность на простых кейсах

### Фаза 2: Интеграция с MSCodeBase
1. Классификация интентов
2. Оценка релевантности кода
3. Маршрутизация MCP-инструментов

### Фаза 3: Guardrail
1. Обнаружение опасного кода
2. Проверка синтаксических ошибок
3. Adversarial attacks

### Фаза 4: Скрытые возможности
1. Нетрадиционные применения
2. Комбинирование примитивов
3. Параллельная обработка

## Источники
- [TypeSafe AI Docs](https://docs.typesafe.ai/)
- [Jev API Reference](https://docs.typesafe.ai/api)
- [Cookbooks](https://docs.typesafe.ai/cookbooks)
- [Research: Routing Plateau](https://arxiv.org/abs/2606.07587)
- [Research: Guardrails under RAG](https://arxiv.org/abs/2510.05310)
