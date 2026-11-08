# Полный аудит — 2026-08-04 (инженер-экспериментатор v3.3.11, 3-й проход)

> Сохранено по протоколу. Верификация по коду — «Вердикты» ниже.
> Полный Ledger: `.agent_task_state.md`; критические — `KNOWN_ISSUES.md`.

## Вердикты верификации (2026-08-04)

| # | Утверждение | Вердикт | Evidence |
|---|-------------|---------|----------|
| 1 | SQL injection graph.py (6 мест: 573, 623, 1030, 1039, 1085, 1330) | ❌ REFUTED | тот же безопасный IN-паттерн: `placeholders = ",".join("?" ...)`, данные только bind-параметрами (см. review_2026-08-04.md, rows 1-5 Ledger) |
| 2 | pickle (index_guard.py:367) | ✅ CONFIRMED (P1) | legacy-миграция; фикс запланирован |
| 3 | subprocess без timeout «14 случаев», включая graph.py | ❌ REFUTED (для graph.py) | graph.py:1426 и 1464 — оба `subprocess.run(..., timeout=60)` (B2/B3); executor.py:398 — communicate(timeout=) есть; onnx_client:129 — демон-спавн |
| 4 | time.sleep в async «18 случаев» | ⚠️ PARTIAL | 24 sleep всего; 0 подтверждённых в event loop (см. review_deep_2026-08-04.md) |
| 5 | global (30) | ⚠️ PARTIAL | фактически 27 global; дефер |
| 6 | мёртвый `_BATCH_SIZE = 4` в indexer.py | ❌ REFUTED | удалён 08-03 (AGENT_DIARY#CONTRADICTION-2026-08-03); остался `index_batch_size` (settings.py:174, dead-config — уже в KNOWN_ISSUES) |
| 7 | ONNX_BATCH_SIZE/ONNX_MAX_LENGTH «в docs не существуют» | ❌ REFUTED | docs/ARCHITECTURE.md:313-314 уже помечают их как «Удалено» |
| 8 | composition_adapter.py, graph_rag_adapter.py «0 импортов» | ❌ REFUTED | файлы не существуют (удалены ранее) |
| 9 | эксперименты в проде (run_experiment_v*, mmr_prototype, pagerank) | ✅ CONFIRMED (по дизайну) | файлы есть; experiments/ канонична (§0.6 AGENTS.md), артефакты gitignored |
| 10 | метрики: 251 async / 626 except / 24 sleep / 27 global / 21 print | ✅ CONFIRMED | подсчёты точны (grep 2026-08-04) |
| 11 | ruff.toml «88 файлов BLE001» | ✅ CONFIRMED | 88 строк BLE001 в per-file-ignores; gradual cleanup |
| 12 | 5 DI-ключей без резолва | ⏳ VERIFY | не проверено в этой сессии |
| 13 | coverage / CI улучшения / security scan | ✅ CONFIRMED (отсутствуют) | нет coverage в pyproject/ci.yml; bandit нет |

## Полный текст отчёта (как получен)

### 🔴 Критические (заявлены)
1. SQL Injection в Property Graph (4-6 мест) — graph.py:573, 623, 1030, 1039, 1085, 1330 → ❌ REFUTED
2. Pickle Deserialization — index_guard.py:367 → ✅ P1 (фикс запланирован)
3. Subprocess без timeout (14 случаев) — graph.py, lsp_project_bridge.py, onnx_client.py, sandbox/executor.py → ❌ для graph.py (timeout=60 есть), ⏳ остальное

### 🟡 Архитектурные
4. Async/Sync Mixing — 18 time.sleep в async → ⚠️ 0 подтверждённых в event loop
5. Глобальное состояние — 30 global → фактически 27
6. Hardcoded значения — 20+ → ⚠️ частично (в settings.py, хардкоды doc_llm_verifier/layer.py)

### 🟢 Качество кода
7. Обработка исключений — 626 except Exception; ruff.toml 88 файлов BLE001 → ✅ gradual cleanup
8. Типизация — 334 (27%) без аннотаций; docstrings <1%
9. Print в production — 8

### 🔬 Эксперименты и техдолг
10. Мёртвый код: _BATCH_SIZE=4 (❌ удалён), ONNX_BATCH_SIZE/MAX_LENGTH (❌ docs помечены), DI-ключи (⏳), adapters (❌ не существуют)
11. Эксперименты в проде: /experiments 20 файлов, run_experiment_v*, mmr_prototype, pagerank, embed_bench_local → ✅ по дизайну

### 📊 CI/CD и тесты
12. Покрытие: 75 файлов, 761 passed; нет coverage % в CI; slow исключены; нет интеграционных
13. CI: нет кэша, параллелизации, pre-commit, coverage, security scan

### 🛡️ Безопасность (ruff S*) — список в оригинале потерян (пустой код-блок)

### 📈 Метрики (подтверждены)
Python файлов 131 | Тестов 75 | Экспериментов 20 | Async 251 | Except 626 | Global 27 | Sleep 24 | Subprocess без timeout 0 подтверждённых | Print 8-21 | TODO 1 | Без типов 334 (27%) | Без docstring ~1200 (95%)

### 🎯 Планы аудита
- P0 (1 нед): SQL, pickle, subprocess timeout, async sleep
- P1 (2 нед): global state → DI, hardcoded → config, exceptions
- P2 (1 мес): типизация, docstrings, print → logging
- P3 (2 мес): CI, security scan, pre-commit

### ✅ Что хорошо (подтверждено)
- Структура src/tests/experiments; DI-контейнер; 761 тест; KNOWN_ISSUES/AGENT_DIARY актуальны; ruff gradual cleanup честно задекларирован; нет eval/exec; tree-sitter 23 языка
