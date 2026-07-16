"""
Code Health Score — детерминированная оценка здоровья файлов (v3.0).

6 маркеров на основе repowise (ROC AUC 0.74) + code-review-graph:
- churn_risk: частота изменений за 90 дней
- complexity: цикломатическая сложность (McCabe)
- nested_depth: максимальная глубина вложенности
- co_change_scatter: количество совместно изменяемых файлов
- file_size: размер файла в строках
- error_handling: пустые except/pass блоки

Score: 1-10, где 10 = здоровый, 1 = критический.
Все вычисления детерминированные, без LLM, без внешних API.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

__all__ = [
    "score_file",
]
logger = logging.getLogger("code_health")


def score_file(
    file_path: str,
    project_path: Path,
    churn_data: Optional[Dict[str, int]] = None,
    co_change_matrix: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Вычисляет health score для одного файла (1-10).

    Args:
        file_path: относительный путь к файлу
        project_path: корень проекта
        churn_data: {file: commit_count} (опционально)
        co_change_matrix: {file: {partner: coupling}} (опционально)

    Returns:
        {
            "score": 7.5,
            "band": "warning",
            "markers": {"churn_risk": 8, "complexity": 5, ...},
        }
    """
    full_path = project_path / file_path
    score = 10.0
    markers: Dict[str, float] = {}

    # Marker 1: File size (lines) — cap -1.5
    lines = _count_lines(full_path)
    if lines > 500:
        ded = min(1.5, (lines - 500) / 1000 * 1.5)
        score -= ded
        markers["file_size"] = round(max(1.0, 10.0 - ded), 1)
    else:
        markers["file_size"] = 10.0

    # Marker 2: Complexity (McCabe) — cap -1.5
    cc = _count_cyclomatic_complexity(full_path)
    if cc > 15:
        ded = min(1.5, (cc - 15) / 30 * 1.5)
        score -= ded
        markers["complexity"] = round(max(1.0, 10.0 - ded), 1)
    else:
        markers["complexity"] = 10.0

    # Marker 3: Nested depth — cap -1.5
    nd = _max_nesting_depth(full_path)
    if nd >= 4:
        ded = min(1.5, (nd - 3) * 0.5)
        score -= ded
        markers["nested_depth"] = round(max(1.0, 10.0 - ded), 1)
    else:
        markers["nested_depth"] = 10.0

    # Marker 4: Churn risk — cap -2.0
    if churn_data and file_path in churn_data:
        churn = churn_data[file_path]
        if churn >= 5:
            ded = min(2.0, churn / 20 * 2.0)
            score -= ded
            markers["churn_risk"] = round(max(1.0, 10.0 - ded), 1)
        else:
            markers["churn_risk"] = 10.0
    else:
        markers["churn_risk"] = 10.0

    # Marker 5: Co-change scatter — cap -2.0
    if co_change_matrix and file_path in co_change_matrix:
        partners = len(co_change_matrix[file_path])
        if partners >= 5:
            ded = min(2.0, partners / 15 * 2.0)
            score -= ded
            markers["co_change_scatter"] = round(max(1.0, 10.0 - ded), 1)
        else:
            markers["co_change_scatter"] = 10.0
    else:
        markers["co_change_scatter"] = 10.0

    # Marker 6: Error handling — cap -0.5
    eh = _count_bare_excepts(full_path)
    if eh > 0:
        ded = min(0.5, eh * 0.1)
        score -= ded
        markers["error_handling"] = round(max(5.0, 10.0 - ded), 1)
    else:
        markers["error_handling"] = 10.0

    final_score = round(max(1.0, min(10.0, score)), 1)

    if final_score >= 8.0:
        band = "healthy"
    elif final_score >= 4.0:
        band = "warning"
    else:
        band = "alert"

    return {
        "score": final_score,
        "band": band,
        "markers": markers,
    }


def _count_lines(file_path: Path) -> int:
    try:
        if not file_path.exists():
            return 0
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _max_nesting_depth(file_path: Path) -> int:
    """Оценивает максимальную глубину вложенности по отступам."""
    max_depth = 0
    try:
        if not file_path.exists():
            return 0
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                stripped = line.lstrip()
                if stripped and not stripped.startswith(
                    ("#", "//", "/*", "*", "'''", '"""')
                ):
                    indent = len(line) - len(line.lstrip())
                    depth = indent // 4  # 4 пробела = 1 уровень
                    max_depth = max(max_depth, depth)
    except Exception as _e:
        logger.warning("exception", exc_info=True)
        pass
    return max_depth


def _count_cyclomatic_complexity(file_path: Path) -> int:
    """Оценивает цикломатическую сложность по ключевым словам."""
    cc = 1  # базовая сложность
    keywords = [
        b"if ",
        b"elif ",
        b"else:",
        b"for ",
        b"while ",
        b"and ",
        b"or ",
        b"except",
        b"finally:",
        b"with ",
        b"assert ",
        b"case ",
        b"match ",
    ]
    try:
        if not file_path.exists():
            return cc
        data = file_path.read_bytes()
        for kw in keywords:
            cc += data.count(kw)
    except Exception as _e:
        logger.warning("exception", exc_info=True)
        pass
    return cc


def _count_bare_excepts(file_path: Path) -> int:
    """Считает пустые except/pass блоки."""
    count = 0
    try:
        if not file_path.exists():
            return 0
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        import re

        count += len(re.findall(r"except\s*:\s*\n\s*(pass|\.\.\.|#.*\n\s*$)", content))
        count += len(
            re.findall(r"except\s+Exception\s*:\s*\n\s*(pass|\.\.\.)", content)
        )
    except Exception as _e:
        logger.warning("exception", exc_info=True)
        pass
    return count
