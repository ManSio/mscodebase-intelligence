"""Grep fallback — поиск по ключевым словам, когда индекс пуст/битый.

История (ARCH-03, направление core←mcp): функция жила в
src/mcp/tools/search_tools.py как `_grep_fallback`, но её вызывает
src/core/intelligence/layer.py (intel_analyze_incident) — это создавало
запрещённый импорт core→mcp (цикл layer → search_tools → ... → layer).
Перенесена в core 2026-08-17; search_tools.py переэкспортирует как
`_grep_fallback` для обратной совместимости тестов (patch-таргет и
прямые вызовы в test_tool_project_root.py).

INC-MULTI-WINDOW: корень проекта берём из resolve_project_root()
(CWD-first, per-window), а не из __file__ — в installed-режиме __file__
= каталог расширения, и fallback искал бы в чужом каталоге
(аудит Bot_snow #7).
"""

from __future__ import annotations

import pathlib as _pl
from typing import Optional


def grep_fallback(query: str, filter_layer: Optional[str] = None) -> str:
    """Fallback to grep when index is empty/corrupted. Uses keyword-based search.

    Args:
        query: поисковый запрос (разбивается на keywords, OR-матчинг).
        filter_layer: не используется (сохранено для совместимости сигнатуры).

    Returns:
        Markdown-строка с находками (до 20) или "".
    """
    # Ленивый импорт намеренный (как было в search_tools.py):
    # 1) тесты патчат src.core.project_resolution.resolve_project_root
    #    (monkeypatch) — bind-at-import ломает patch (регрессия 2026-08-17,
    #    test_tool_project_root.py);
    # 2) вызов происходит редко (index empty/corrupted) — не нужно тащить
    #    резолвер в import-время модуля.
    from src.core.project_resolution import resolve_project_root

    root = _pl.Path(resolve_project_root())
    results = []

    # Split query into keywords for flexible matching
    keywords = [w.lower() for w in query.split() if len(w) > 2]

    try:
        for ext in ("*.py", "*.md", "*.txt", "*.js", "*.ts"):
            for f in root.rglob(ext):
                # Skip .git, __pycache__, node_modules
                parts = f.parts
                if any(p.startswith(".") or p == "__pycache__" or p == "node_modules" for p in parts):
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(text.split("\n"), 1):
                        line_lower = line.lower()
                        # Match if ANY keyword is found in the line (OR matching)
                        if any(kw in line_lower for kw in keywords):
                            rel = f.relative_to(root)
                            results.append(f"{rel}:{i}: {line.strip()[:80]}")
                            if len(results) >= 20:
                                break
                except Exception:  # noqa: BLE001 — файл может быть бинарным/закрытым, пропускаем
                    continue
                if len(results) >= 20:
                    break
            if len(results) >= 20:
                break

        if results:
            formatted = "\n".join(f"  {r}" for r in results)
            return f"\n🔍 **Grep fallback** (index empty/corrupted, {len(results)} results):\n{formatted}"
        return ""
    except Exception:  # noqa: BLE001 — fallback обязан вернуть "", а не упасть
        return ""
