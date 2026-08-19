# Universal Engine — эксперименты

> Throwaway-зона экспериментов перестройки (план: `docs/{ru,research}/UNIVERSAL_ENGINE_PLAN.md`).
> Сюда — только пробы и замеры (E-03..E-10); реализация — в `src/sources/`,
> `src/mcp/transport/`, `src/plugins/`, `adapters/`.
> Папка уже исключена из pytest-коллекции через `norecursedirs` (pyproject.toml).

| Эксперимент | Статус | Что |
|---|---|---|
| E-01 (плагин RCE) | ✅ прогнано 2026-08-18 | raw output в плане §2 |
| E-02 (git clone/fingerprint) | ✅ прогнано 2026-08-18 | raw output в плане §2 |
| E-03 (clone→index 5-10 репо) | ✅ 4/4 PASSED 2026-08-18 | E03_RESULTS.md: httpx 1812/f1605/rich 2808 чанков; rename-lock → clone-in-place |
| E-05 (Action Receipt) | ⏳ очередь | гейт §11 |
| E-08 (SSRF-сьют) | ⏳ очередь | Фаза 2 |
| E-09 (upload bombs) | ⏳ очередь | Фаза 2 |

## Координация с исследовательским агентом

- **Write-scope:** исследователь — `docs/research/universal-engine-study/**` (+ его
  мелкие `study-detectors/`). Этот каталог (`experiments/universal-engine/`) —
  зона агента-реализатора.
- **Экспериментальные кэши-клоны → системный temp, НЕ в репо** (урок E-03-2026-08-18:
  клонированные доки репо (README/CHANGELOG) ломают stale_detector, а 35k файлов
  клона — health-скан/cap). Мой кэш E-03 — `%TEMP%/mscodebase_e03_clone_cache`.
- **Инцедент 2026-08-18:** `e-s1-polygon/repos/uv` (35 823 файла, не закоммичено)
  лежит в репо и блокирует гейты (health test + stale_detector). ОБЯЗАН переехать
  в temp (владелец известил исследователя).
