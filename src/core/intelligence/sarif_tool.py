"""SARIF output tool for dead code detection.

GitHub Code Scanning compatible output.
"""

import json
from pathlib import Path
from typing import Optional


def get_dead_code_sarif(project_root: Optional[str] = None) -> dict:
    """SARIF output для dead code (GitHub Code Scanning compatible).

    Поддерживает suppression markers:
    - # mscodebase-ignore-next-line (Python)
    - // mscodebase-ignore-next-line (JS/TS, C/C++, Java, C#)

    Args:
        project_root: Путь к проекту (по умолчанию текущая директория)

    Returns:
        SARIF-совместимый dict с results для CI-гейта.
    """
    if project_root:
        root = Path(project_root)
    else:
        root = Path.cwd()

    try:
        from src.core.graph import PropertyGraph

        graph = PropertyGraph(root / ".codebase" / "graph.db")
        return graph.detect_dead_code_sarif()
    except Exception as e:
        return {"error": str(e)}