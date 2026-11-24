"""Guard: impact_analysis различает «символ не тот» и «символьный слой пуст».

Замер 2026-11-16: у 4 из 7 реальных проектов `graph.db` пуст (0 узлов) при живых
чанках. Инструмент отвечал «Symbol 'X' not found in index» — пользователь
проверял имя символа, хотя нужно было переиндексировать проект.
"""
from __future__ import annotations

from src.mcp.tools.search_tools import _impact_not_found_payload


def test_empty_symbol_layer_points_to_reindex():
    payload = _impact_not_found_payload("as_dict", 0)

    assert payload["status"] == "warning"
    assert "Symbol layer is empty" in payload["message"]
    assert "as_dict" in payload["message"]
    assert "codebase(action='index'" in payload["next_step"]


def test_known_symbol_layer_points_to_name_lookup():
    payload = _impact_not_found_payload("as_dict", 3018)

    assert "not found in index" in payload["message"]
    assert "search_code" in payload["next_step"]


def test_unknown_symbol_count_does_not_claim_the_layer_is_empty():
    """Если счётчик недоступен (-1), нельзя утверждать, что слой пуст."""
    payload = _impact_not_found_payload("as_dict", -1)
    assert "Symbol layer is empty" not in payload["message"]


def test_new_keys_are_translated_to_every_locale():
    """Любой новый текст под `_()` обязан иметь ключ в каждой локали.

    Иначе англоязычный хост получает русский ответ (дефолтная локаль — en),
    а `scripts/audit_i18n.py` этого не видит: он смотрит только `return "..."`.
    """
    import json
    from pathlib import Path

    locales_dir = Path(__file__).resolve().parent.parent / "locales"
    # "{symbol}" как значение подстановки сохраняет исходный ключ нетронутым:
    # `_()` форматирует один раз, поэтому ключ остаётся с плейсхолдером.
    payloads = [
        _impact_not_found_payload("{symbol}", 0),
        _impact_not_found_payload("{symbol}", 5),
    ]
    keys = {p["message"] for p in payloads}
    keys |= {p["next_step"] for p in payloads}
    assert all("{symbol}" in p["message"] for p in payloads), "ключ должен сохранять плейсхолдер"

    for locale in ("en", "ru", "zh"):
        data = json.loads((locales_dir / f"{locale}.json").read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in data]
        assert not missing, f"{locale}: нет перевода для {missing}"

    assert "Symbol '{symbol}' not found in index" in json.loads(
        (locales_dir / "en.json").read_text(encoding="utf-8")
    )


class _EmptyGraphIndex:
    """Символьный индекс, у которого граф пуст: definition найти нельзя."""

    def __init__(self, symbol_count: int):
        self._count = symbol_count

    def get_symbol_count(self) -> int:
        return self._count

    def get_impact_analysis(self, symbol: str, depth: int = 3) -> dict:
        return {"call_graph": {"definition": []}, "affected_files": []}


class _WiringTool:
    """ImpactAnalysisTool без DI: подменяем только точки входа."""

    async def require_ready_project(self, explicit_project_root=None, timeout=5.0):
        return None

    def __init__(self, symbol_count: int):
        self._symbol_count = symbol_count

    def resolve_symbol_index(self, explicit_project_root=None):
        return _EmptyGraphIndex(self._symbol_count)


def _run_impact(symbol_count: int) -> dict:
    """Проводка execute(): реальный код инструмента, подменён только индекс.

    `error_boundary` отдаёт клиенту JSON-конверт (status=warning внутри), поэтому
    разбираем его и смотрим на текст, который увидит агент.
    """
    import asyncio
    import json

    from src.mcp.tools.search_tools import ImpactAnalysisTool

    tool = _WiringTool(symbol_count)
    raw = asyncio.run(
        ImpactAnalysisTool.execute(tool, symbol="as_dict", project_root="")
    )
    payload = json.loads(raw) if isinstance(raw, str) else raw
    if "error" in payload:
        return {"message": payload["error"].get("message", ""),
                "next_step": (payload["error"].get("details") or {}).get("next_step", "")}
    return payload


def test_tool_reads_symbol_count_to_explain_an_empty_layer():
    payload = _run_impact(0)
    assert "Symbol layer is empty" in payload["message"]


def test_tool_reports_missing_symbol_when_the_layer_has_symbols():
    payload = _run_impact(3018)
    assert "not found in index" in payload["message"]


