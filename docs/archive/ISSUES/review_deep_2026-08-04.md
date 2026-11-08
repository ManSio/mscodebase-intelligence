# Глубокий аудит — 2026-08-04 (внешний инструмент, 2-й проход)

> Сохранено по протоколу (не потерять). Верификация по коду — раздел «Вердикты» ниже.
> Триаж: `.agent_task_state.md` (Verification Ledger), критические — `KNOWN_ISSUES.md`.

## Вердикты верификации (проверено по коду 2026-08-04)

| # | Утверждение аудита | Вердикт | Evidence |
|---|--------------------|---------|----------|
| 1 | SQL Injection graph.py x4 | ❌ REFUTED | `placeholders = ",".join("?" ...)` — в SQL только `?`, данные bind-параметрами (см. review_2026-08-04.md) |
| 2 | pickle.load (index_guard.py:367) | ✅ CONFIRMED (P1) | legacy symbol_index.pkl, локальный артефакт-каталог; фикс — restricted unpickler/отказ |
| 3 | time.sleep в async «24 случая» | ⚠️ ЧАСТИЧНО | счёт верен (24 в src/), но НЕ найдено ни одного sleep в event loop: onnx_server.py:285 (idle_killer — фоновый поток), database_lock.py:118,195 (sync файловый лок), lsp_project_bridge.py:242-316 (sync read_active_project), server_factory.py:347 (_recheck — поток), resource_monitor.py:635 — В ФАЙЛЕ НЕТ sleep |
| 4 | create_task без ссылки (server_factory.py:388) | ✅ CONFIRMED (P2) | `asyncio.create_task(_delayed_auto_index(...))` — ссылка не сохраняется; всего ~4 места без ссылки (236, 388, 624, lsp_client:348), остальные 6 сохраняют (self._reindex_task и т.д.) |
| 5 | subprocess без timeout executor.py:398 | ❌ REFUTED | `proc.communicate(timeout=timeout)` присутствует |
| 6 | subprocess без timeout onnx_client.py:129 | ⚠️ N/A | демон-спавн ONNX-сервера (timeout неприменим к серверному процессу); риск — отсутствие health-check таймаута |
| 7 | subprocess без timeout llama_runner.py:103 | ⏳ VERIFY | обёртка `_popen_with_job`; таймаут зависит от call-site (852/978/1065) |
| 8 | subprocess без timeout git_hooks_installer.py:59 | ⏳ VERIFY | Popen без видимого communicate в сниппете |
| 9 | BLE001 664 в ruff.toml | ✅ CONFIRMED (процесс) | «664 legacy нарушений задедклайрены как gradual cleanup» — осознанный долг, не «скрытие ошибок»; новые файлы обязаны быть чистыми |
| 10 | print в onnx_client.py:272-274 | ✅ CONFIRMED (P3) | `print(f"Dim: ...")` — debug-вывод в прод-коде; main.py:139-153 — help (допустимо) |
| 11 | coverage отсутствует | ✅ CONFIRMED | нет coverage в pyproject.toml и ci.yml |
| 12 | порты «разбросаны 20+» | ⚠️ ЧАСТИЧНО | большинство в settings.py (1234/11434/1235 — дефолты config); реальные хардкоды: doc_llm_verifier.py:96-97, layer.py:504 |
| 13 | 27 потоков без синхронизации | ⚠️ ЧАСТИЧНО | потоки есть (remote_embedder 3, llama_runner watchdog, resource_monitor, bridge-recheck), но «без синхронизации» — не проверено; требует отдельного аудита (§5.13) |
| 14 | rate limiting отсутствует | ⏳ VERIFY | есть rate_limiter.py (debounce) — нужен обзор, что покрыто |

## Полный текст отчёта аудита (как получен)

### 1. Проблемы с асинхронностью (251 async функций)
- Fire-and-forget: `asyncio.create_task()` без сохранения ссылки (server_factory.py:388) — потеря задач/ошибок
- Блокирующий sleep: 24 случая time.sleep() вместо asyncio.sleep():
  - server_factory.py:347 (функция обратного вызова)
  - lsp_project_bridge.py:242-316 (polling, 5 случаев)
  - database_lock.py:118-195 (блокировки БД)
  - resource_monitor.py:635 (мониторинг ресурсов)
  - embedder/onnx_server.py:285 (30 секунд блокировки)

### 2. Потоковая безопасность
- 27 потоков без явной синхронизации: remote_embedder.py (3), llama_runner.py (watchdog), resource_monitor.py, bridge-recheck с time.sleep(1.5)

### 3. Subprocess без timeout
- onnx_client.py:129, git_hooks_installer.py:59, executor.py:398, llama_runner.py:103

### 4. Жёстко закодированные значения
- 20+ случаев 127.0.0.1/localhost; порты 8080, 1234, 11434, 1235; таймауты 0.5/1.0/5.0

### 5. Тестирование
- 75 тестовых файлов, нет coverage конфига; нет coverage в CI; @pytest.mark.slow исключаются; нет интеграционных тестов MCP/LSP

### 6. Логирование vs print
- main.py:139-153 (help, допустимо), onnx_client.py:272-274 (убрать), git_hooks_installer.py:54-89 (CLI, допустимо)

### 7. Обработка исключений
- ruff.toml: 664 BLE001 как «gradual cleanup» — скрывает ошибки, мешает отладке

### 8. CI/CD
- checkout@v5 OK; нет кэша pip, нет параллелизации, timeout 10 мин, нет pre-commit stage

### 9. Конфигурация и секреты
- ✅ Нет захардкоженных ключей; ✅ .env.example; ⚠️ нет валидации .env при старте

### 10. Документация кода
- 120+ без docstrings, 134+ без type hints, ~1 TODO

### Безопасность (OWASP Top 10 2024)
- Десериализация pickle (index_guard.py) — табу
- SQL Injection f-строки (graph.py) — см. вердикт ❌
- Нет rate limiting (DoS/квоты LLM)

### AsyncIO anti-patterns
- Блокировка event loop (time.sleep) — см. вердикт ⚠️
- Fire-and-forget задачи — ✅ server_factory.py:388
- Нет backpressure (asyncio.Queue без размера)

### LLM/RAG
- Нет observability (токены/стоимость/латентность промптов)
- Промпты захардкожены (нет Jinja2-шаблонов)
- Нет валидации вывода LLM (pydantic/JSON mode)

### DevOps
- Subprocess без таймаута — ⚠️/⏳ см. вердикты
- 27 глобальных переменных
- print() ломает структурированные логи

### Качество кода
- Магические числа → settings.py через pydantic-settings
- 134+ без аннотаций; mypy --strict
- Нет security/load тестов

### Roadmap аудита
- Hotfix (сегодня): SQL + pickle + time.sleep → asyncio.sleep
- Refactor (неделя 1): параметризация, таймауты subprocess
- Architecture (неделя 2-3): DI, структурированное логирование
- DevOps (неделя 4): CI с типизацией/линтером/security-тестами
