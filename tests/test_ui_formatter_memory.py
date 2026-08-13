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


def test_vor_coverage_receipt():
    """Пол Тома: ресипт показывает checked/total — потребитель сам видит, что измерение
    ниже пола (проверено 3 из 100) и не может принять его за полную верификацию."""
    out = format_project_memory(
        _mem(3), stats={"nodes_seen": 100, "checked": 3, "budget_exceeded": False}
    )
    assert "3/100" in out
    assert "VOR coverage" in out


def test_vor_coverage_budget_exceeded_warning():
    """При превышении бюджета ресипт предупреждает: непроверенные узлы несут статус
    прошлых циклов."""
    out = format_project_memory(
        _mem(3), stats={"nodes_seen": 100, "checked": 3, "budget_exceeded": True}
    )
    assert "3/100" in out
    assert "бюджет исчерпан" in out


def test_vor_off_receipt():
    """verify_on_read=False — ресипт честно говорит, что проверки не было."""
    out = format_project_memory(_mem(1), stats={"verify_on_read": False})
    assert "отключён" in out


def test_no_stats_backward_compat():
    """Без stats ресипт не выводится — старый вызов не ломается."""
    out = format_project_memory(_mem(1))
    assert "VOR" not in out


def test_budget_exceeded_node_marker():
    """Непроверенный из-за бюджета узел получает ⚠️-маркер (статус устарел)."""
    mem = _mem(1)
    mem["adrs"][0]["verification"] = "budget_exceeded"
    out = format_project_memory(mem)
    assert "не проверен: бюджет цикла исчерпан" in out


def _audit_mem() -> dict:
    return {
        "adrs": [
            {
                "node_id": "N1",
                "status": "REFUTED",
                "retract_reason": "SILENT_ABSENCE_ON_READ: file:src/x.py",
                "data": {"title": "old-fact"},
            },
            {
                "node_id": "N2",
                "status": "SUPERSEDED",
                "data": {"title": "stale-fact"},
            },
            {
                "node_id": "N3",
                "status": "VERIFIED",
                "data": {"title": "live-fact"},
            },
        ]
    }


def test_audit_mode_shows_statuses_and_reasons():
    """Аудит (include_retracted=True): REFUTED-узлы несут статус и причину отзыва —
    иначе аудит был бы списком заголовков без контекста (ADR-0002: история не стирается)."""
    out = format_project_memory(_audit_mem(), limit=0)
    assert "🔴 [REFUTED: SILENT_ABSENCE_ON_READ: file:src/x.py]" in out
    assert "🔶 [SUPERSEDED]" in out
    assert "✅ [VERIFIED]" in out


def test_normal_view_no_status_tags():
    """Обычный режим (без REFUTED/SUPERSEDED) — статус-теги не выводятся (шум)."""
    out = format_project_memory(_mem(1))
    assert "[VERIFIED]" not in out
    assert "[ACTIVE]" not in out


def test_metrics_line_in_receipt():
    """Снятие метрик: ресипт несёт распределение статусов и false_retraction_rate."""
    out = format_project_memory(
        _mem(1),
        stats={
            "verify_on_read": False,
            "metrics": {
                "total": 43,
                "by_status": {"VERIFIED": 8, "ACTIVE": 28, "REFUTED": 6, "SUPERSEDED": 1},
                "false_retraction_rate": 0.0,
            },
        },
    )
    assert "📊" in out
    assert "VERIFIED 8" in out
    assert "REFUTED 6" in out
    assert "false_retraction: 0.0%" in out


def test_no_metrics_no_line():
    """Без metrics в stats строка метрик не выводится (обратная совместимость)."""
    out = format_project_memory(
        _mem(1), stats={"verify_on_read": False}
    )
    assert "📊" not in out
