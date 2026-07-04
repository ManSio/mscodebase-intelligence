# MSCodeBase Status — Zed Extension

Нативное расширение для Zed IDE, добавляющее статус-бар, дашборд и интеграцию с MSCodeBase MCP-сервером.

## Сборка

Требуется Rust с таргетом `wasm32-unknown-unknown`:

```bash
rustup target add wasm32-unknown-unknown
cargo build --target wasm32-unknown-unknown --release
```

После сборки скопируйте `.wasm` файл в директорию локальных расширений Zed:
- Windows: `%LOCALAPPDATA%\Zed\extensions\installed\mscodebase-status\`
- macOS: `~/Library/Application Support/Zed/extensions/installed/mscodebase-status/`
- Linux: `~/.local/share/zed/extensions/installed/mscodebase-status/`

## Структура

```
extensions/mscodebase-status/
├── extension.toml      # Манифест расширения
├── Cargo.toml          # Зависимости Rust
└── src/
    └── lib.rs          # Точка входа (статус-бар, команды, JSON-RPC)
```

## Команды

| Команда | Описание |
|---------|----------|
| `MSCodeBase: Trigger Full Reindex` | Принудительная переиндексация |
| `MSCodeBase: Show Architectural Dashboard` | Открыть дашборд |
| `MSCodeBase: Clear Project Memory Cache` | Очистить кэш памяти |

## Push-уведомления от Python-сервера

Расширение обрабатывает 3 типа уведомлений:

| Метод | Что делает |
|-------|------------|
| `mscodebase/indexing_status` | Обновляет статус-бар (прогресс индексации) |
| `mscodebase/system_health` | Показывает состояние LM Studio / CircuitBreaker |
| `mscodebase/diagnostics_update` | Показывает диагностические предупреждения |
