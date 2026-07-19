"""SARIF output tool for dead code detection.

GitHub Code Scanning compatible output.
"""

import json
from pathlib import Path
from typing import Optional


def get_dead_code_sarif(project_root: Optional[str] = None) -> dict:
    """SARIF output для dead code (GitHub Code Scanning compatible).

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
        dead_nodes = graph.detect_dead_code()

        results = []
        for node in dead_nodes:
            results.append({
                "ruleId": "dead-code",
                "level": "warning",
                "message": {
                    "text": f"Function '{node.name}' has no incoming calls (dead code)"
                },
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": node.file_path or "unknown.py"},
                        "region": {
                            "startLine": node.properties.get("start_line", 1) if node.properties else 1,
                        }
                    }
                }],
            })

        return {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "mscodebase-deadcode", "version": "1.0.0"}},
                "results": results,
            }]
        }
    except Exception as e:
        return {"error": str(e)}