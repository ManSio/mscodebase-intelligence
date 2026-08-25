"""predict_tools.py — predict_change: предсказание исхода правки до коммита.

Два режима:
  static — blast radius без прогона (изменённые файлы → affected-тесты +
           гейты + риск) — быстро;
  full   — полный превью-прогон в изолированном git worktree (affected-тесты
           + гейты реально гоняются) → вердикт VERIFIED/REFUTED/INCONCLUSIVE.

Логика — в src/core/change_preview.py (Тумблер: core = логика, инструмент =
тонкая обёртка; та же трёхзначная модель вердиктов, что в action_receipt).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.core.di_container import ServiceCollection
from src.core.error_handler import error_boundary
from src.mcp.tools.base import MCPTool

logger = logging.getLogger(__name__)


class PredictChangeTool(MCPTool):
    """predict_change — «внести изменение и точно знать, что будет».

    Аргументы:
      mode: "static" (по умолчанию) | "full"
          static — только карта влияния (affected-тесты + гейты + риск);
          full   — прогон affected-тестов и гейтов в изолированном worktree
                   (вердикт PASS/FAIL ДО коммита).
      base: база диффа (по умолчанию "HEAD").
      timeout: кап на прогон (сек, по умолчанию 300).

    Возвращает: VERDICT: VERIFIED|REFUTED|INCONCLUSIVE + детали.
    """

    def __init__(self, services: ServiceCollection):
        super().__init__(services, tool_name="predict_change")

    @error_boundary("predict_change", timeout_ms=60000)
    async def execute(
        self,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        from src.core.change_preview import ChangePreview, static_predict
        from src.core.project_resolution import resolve_project_root

        kwargs = kwargs or {}
        mode = str(kwargs.get("mode", "static")).strip().lower() or "static"
        base = str(kwargs.get("base", "HEAD")).strip() or "HEAD"
        try:
            timeout = int(kwargs.get("timeout", 300) or 300)
        except (TypeError, ValueError):
            timeout = 300

        repo = resolve_project_root()
        if mode == "full":
            verdict, message = ChangePreview(repo, base, timeout=timeout).run()
            return f"VERDICT: {verdict}\n{message}"

        info = static_predict(repo, base)
        if not info["changed"]:
            return f"VERDICT: INCONCLUSIVE\n{info['note']}"
        lines = [
            "VERDICT: STATIC (без прогона — mode='full' для вердикта)",
            f"Changed files ({len(info['changed'])}): " + ", ".join(info["changed"]),
            f"Risk: {info['risk']}",
            f"Affected tests ({len(info['affected_tests'])}): "
            + (", ".join(info["affected_tests"]) or "—"),
            f"Gates: {', '.join(info['gates']) or '—'}",
            "",
            "Для вердикта PASS/FAIL выполните mode='full'.",
        ]
        return "\n".join(lines)
