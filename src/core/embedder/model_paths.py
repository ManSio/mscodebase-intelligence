"""Где искать каталог ONNX-модели — один список для сервера и клиента.

Зачем отдельный модуль: `onnx_server.load_model` искал модель в трёх местах, а
клиент об этом не знал и запускал процесс, который умирал через 0.1 с; затем
`_wait_for_server` ждал 60 с. Замер 2026-11-17: в worktree без `.codebase_models`
каждый вызов эмбеддинга стоил 60 с ожидания. Общий резолвер позволяет клиенту
отказать сразу и назвать места, где он искал.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

__all__ = ["PROJECT_ROOT", "candidate_dirs", "resolve_model_dir"]

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def candidate_dirs(model_name: str) -> List[Path]:
    """Каталоги модели в порядке приоритета (первый существующий — рабочий)."""
    from src.core.artifact_paths import get_onnx_models_base

    root = PROJECT_ROOT
    return [
        root / ".codebase_models" / "onnx" / model_name,
        root / "models" / model_name,
        get_onnx_models_base() / model_name,
    ]


def resolve_model_dir(model_name: str) -> Optional[Path]:
    """Каталог модели или None. Ничего не создаёт и не бросает."""
    for path in candidate_dirs(model_name):
        try:
            if path.is_dir():
                return path
        except OSError:
            continue
    return None
