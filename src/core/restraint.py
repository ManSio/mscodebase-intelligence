"""restraint.py — сдержанность доставки (anti-numbing): не повторять одну и ту же заметку.

Зачем: заметка, которая приходит снова и снова, притупляет читателя (Tom Jones, «the evening the
agent went numb to its own alerts»; наш E3/E4 — та же опасность). Ограничиваем ПОВТОР одной и той же
advisory-заметки: сигнатура findings + cooldown, с растущим backoff по «страйкам».

Только для ADVISORY (speak). Блокирующие гейты сдержанность НЕ применяют: заблокированный коммит —
жёсткий стоп, а не нытьё (Red Team п.3). Вызов opt-in (`restraint: true`).

Состояние — один маленький JSON на проект в data_root (перезаписывается, не растёт).
⛔ Не граница безопасности; best-effort, при сбое чтения/записи — доставляем (fail-open).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("mscodebase_server.restraint")

__all__ = ["signature", "should_deliver", "state_path"]

DEFAULT_COOLDOWN_SEC = 600.0
DEFAULT_MAX_STRIKES = 3


def signature(findings: List[Dict[str, Any]]) -> str:
    """Стабильная сигнатура набора findings: изменение kind/symbol/file → новая сигнатура."""
    keys = sorted(
        f"{f.get('kind', '')}:{f.get('symbol', '')}:{f.get('file', '')}" for f in findings
    )
    return hashlib.sha1("|".join(keys).encode("utf-8")).hexdigest()[:16]


def state_path(project_root: Path) -> Path:
    from src.core.artifact_paths import get_graph_db_path

    return get_graph_db_path(Path(project_root).resolve()).parent / "delivery_state.json"


def _read_state(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, state: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("restraint: state write failed: %s", exc)


def should_deliver(
    project_root: Path,
    sig: str,
    cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
    max_strikes: int = DEFAULT_MAX_STRIKES,
    now: Optional[float] = None,
) -> Tuple[bool, str]:
    """True — доставить (обновляет состояние); False — подавить повтор.

    Backoff растёт с числом повторных доставок той же сигнатуры: window = cooldown * 2^min(strikes, max).
    """
    path = state_path(project_root)
    now = time.time() if now is None else now
    state = _read_state(path)

    same = state.get("sig") == sig
    strikes = int(state.get("strikes", 0)) if same else 0
    last = float(state.get("last_ts", 0.0)) if same else 0.0
    window = cooldown_sec * (2 ** min(strikes, max_strikes))

    if same and (now - last) < window:
        left = int(window - (now - last))
        return False, f"cooldown: same findings, {left}s left (strikes={strikes})"

    _write_state(path, {"sig": sig, "last_ts": now, "strikes": strikes + 1 if same else 0})
    return True, "delivered"
