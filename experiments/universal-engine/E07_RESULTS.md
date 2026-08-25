# E-07 — эквивалентность транспортов: stdio vs Streamable HTTP

Прогнано: **2026-08-19** (режим `--toy`, live).

Задача (DoD Фазы 3): один и тот же запрос через stdio и HTTP возвращает
идентичный JSON для репрезентативного подмножества тулов.

## Гипотеза / что проверяем

MCP SDK клиент (`ClientSession`) ведёт себя одинаково независимо от транспорта:
один и тот же вызов тула и одна и та же ошибка дают байт-идентичный JSON-RPC
результат/конверт через stdio и через Streamable HTTP.

**Команда:** `python experiments/universal-engine/e07_equiv.py --toy --port 8094`

## Сырой вывод

```
E-07: transport equivalence stdio vs Streamable HTTP (toy FastMCP)
  ✅ bad-args: identical
  ✅ ping-result: identical
E-07 VERDICT: PASSED (2/2)
```

## Разбор

- `ping-result` — вызов `ping(prefix="probe")` через оба транспорта → идентичный
  canonical JSON (правильный вход → правильный выход, §2.3/§5.13).
- `bad-args` — вызов `ping({"bogus": 1})` → идентичный JSON-RPC error-конверт.

## Ограничения / отложенное

- Гарнесс валидирован live на **минимальном FastMCP** (`_e07_toy_server.py`),
  без тяжёлого движка — это безопасно (нет PID-lock/2-го MCP) и доказывает
  корректность сьют-логики.
- Режим **реального движка** (`create_mcp_server`: stdio `python -m src.main` +
  HTTP `uvicorn src.remote_main:app`) — тот же харнесс, пробы `unknown-method` /
  `get_runtime_counters` / `bad-args`. Live-прогон отложен: создаст 2-й MCP и
  будет драться за PID-lock эмбеддера, если основной MCP (расширение) работает
  (прецедент дневник 2026-08-18). Гонять на чистом CI-раннере (Ubuntu) или при
  остановленном основном MCP: `python experiments/universal-engine/e07_equiv.py`.

## Урок

Один и тот же харнесс покрывает и toy и engine через параметр `--toy`; у
`stdlib`-клиента и `streamablehttp`-клиента РАЗНЫЕ сигнатуры распаковки
(2 против 3 значений) — обрабатывается по типу транспорта. Готовность HTTP-сервера
надо проверять не только через `/healthz` (у FastMCP-приложения его нет) — любой
HTTP-ответ означает «слушает».

## Вердикт
✅ подтверждено (toy live; engine-mode требует idle/CI).
