"""UI-форматтер project memory: сводка, limit (полный список), ❓-маркер INCONCLUSIVE."""

from src.utils.ui_formatter import format_project_memory


def _mem(n: int, with_flag: bool = False) -> dict:
    """Секция adrs из n узлов; первый узел может нести no_anchors-флаг."""
    return {
        "adrs": [
            {
                "node_id": f"N{i}",
                "status": "ACTIVE",
                "data": {"title": f"title-{i}"},
                **({"verification": "no_anchors"} if with_flag and i == 0 else {}),
            }
            for i in range(n)
        ]
    }


def test_default_limit_three():
    """По умолчанию — сводка: N entries, топ-3, «and N-3 more» (токен-бюджет)."""
    out = format_project_memory(_mem(10))
    assert "**Adrs:** 10 entries" in out
    assert "title-0" in out and "title-1" in out and "title-2" in out
    assert "title-3" not in out
    assert "and 7 more" in out


def test_limit_zero_shows_all():
    """limit=0 — полный список: все узлы, без «and more» (аудит)."""
    out = format_project_memory(_mem(10), limit=0)
    assert "title-9" in out
    assert "more" not in out


def test_limit_above_len_shows_all():
    """limit >= len(items) — все узлы, «and more» не выводится."""
    out = format_project_memory(_mem(3), limit=10)
    assert "title-2" in out
    assert "more" not in out


def test_inconclusive_marker():
    """no_anchors-узел получает ❓ [неверифицируемо по коду] (ADR-0003 предохранитель)."""
    out = format_project_memory(_mem(2, with_flag=True))
    assert "неверифицируемо по коду" in out
