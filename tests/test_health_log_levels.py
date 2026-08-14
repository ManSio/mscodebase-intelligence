"""_count_log_levels — счёт по level-маркерам, не по подстроке.

Регрессия 2026-08-14: health._check_logs считал content.lower().count("error")
→ 99 «ошибок» при 20 реальных [ERROR]-строках (подстроки в 'ValueError',
'latest_log_errors' и т.п.). Плюс окно 24ч: исторические ошибки (7 дней назад)
не должны держать health в critical.
"""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.intelligence.health import _count_log_levels  # noqa: E402

NOW = datetime(2026, 8, 14, 12, 0, 0)


def test_counts_level_markers_not_substrings():
    """'error' как подстрока (ValueError, latest_log_errors) не считается."""
    content = (
        "2026-08-14 09:00:00 [ERROR] [mcp_global] real error line\n"
        "2026-08-14 09:00:01 [WARNING] [mcp_global] real warning\n"
        "2026-08-14 09:00:02 [INFO] latest_log_errors=99 ValueError TypeError\n"
    )
    errors, warns = _count_log_levels(content, NOW)
    assert errors == 1
    assert warns == 1


def test_window_excludes_old_errors():
    """Ошибки старше окна не считаются (health не держим в critical историей)."""
    content = (
        "2026-08-13 09:00:00 [ERROR] [mcp_global] old outside window\n"
        "2026-08-14 09:00:00 [ERROR] [mcp_global] recent\n"
    )
    errors, _ = _count_log_levels(content, NOW, window_hours=24)
    assert errors == 1


def test_unparseable_lines_skipped():
    """Строки без timestamp (traceback-продолжения) не считаются."""
    content = "no timestamp here [ERROR]\n"
    errors, warns = _count_log_levels(content, NOW)
    assert errors == 0
    assert warns == 0
