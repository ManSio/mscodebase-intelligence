"""Парсер [`embed] done/total …` строки из основного лога MCP.

Единый источник правды для подсчёта реальной ETA/скорости индексации.
Вынесен в отдельный нейтральный модуль (2026-09-03): и `layer.py`, и
`tools_reg.py` импортируют его отсюда, что устраняет циклическую
зависимость layer ↔ tools_reg (архитектурный инвариант «нет циклов в core»).
"""

from typing import Any, Dict, Optional


def _embed_progress_from_log(started_at: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Парсит последнюю строку `[embed] done/total …` из основного лога MCP.

    Args:
        started_at: таймстамп старта job (unix). Строки лога старше
            started_at - 2 пропускаются (лог общий, накапливается между сессиями).

    Returns:
        dict {done, total, inst, avg, elapsed, remaining} — или None, если
        строка не найдена (embed ещё не начался / режим non-embed).
    """
    import datetime as _dt
    import re

    from src.core.log_manager import get_main_log_path

    _log_path = get_main_log_path()
    if not _log_path.exists():
        return None
    with open(str(_log_path), "r", encoding="utf-8", errors="replace") as _f:
        for _line in reversed(_f.readlines()):
            try:
                _line_ts = _dt.datetime.strptime(
                    _line[:19], "%Y-%m-%d %H:%M:%S"
                ).timestamp()
                if started_at and _line_ts < started_at - 2:
                    continue
            except (ValueError, IndexError):
                continue
            _m = re.search(r"\[embed\]\s+(\d+)/(\d+)", _line)
            if _m:
                _done, _total = int(_m.group(1)), int(_m.group(2))
                _m_inst = re.search(r"batch=\d+ch/[\d.]+s=(\d+)ch/s", _line)
                _inst = int(_m_inst.group(1)) if _m_inst else 0
                _m_avg = re.search(r"avg=(\d+)ch/s", _line)
                _avg = int(_m_avg.group(1)) if _m_avg else 0
                _m_elapsed = re.search(r"elapsed=(\d+)s", _line)
                _elapsed = int(_m_elapsed.group(1)) if _m_elapsed else 0
                return {
                    "done": _done,
                    "total": _total,
                    "inst": _inst,
                    "avg": _avg,
                    "elapsed": _elapsed,
                    "remaining": _total - _done,
                }
    return None
