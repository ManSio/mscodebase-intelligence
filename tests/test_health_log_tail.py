"""Guard: get_health_report читает хвост лога и не объявляет critical за чужой лог.

Замер 2026-11-16 (установленный сервер, 7 реальных проектов): `get_health_report`
p50 ~1.1–2.9 с и вердикт `overall_health: critical` из-за «13 ошибок в последнем
логе». Лог общий на все проекты (`mcp_global.log`), читался целиком на каждый
вызов, а сама диагностика писала ~20 WARNING в него же.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.core.intelligence.health import (
    HealthReport,
    _count_log_levels,
    _read_log_tail,
)


def _write_log(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_tail_read_stops_at_cap(tmp_path):
    log = tmp_path / "big.log"
    # 3 МБ одинаковых строк — больше лимита чтения (2 МБ).
    line = "2026-11-16 10:00:00 [WARNING] шум " + "x" * 90
    with open(log, "w", encoding="utf-8") as f:
        for _ in range(30_000):
            f.write(line + "\n")

    tail = _read_log_tail(log, cap=64 * 1024)

    assert len(tail.encode("utf-8")) <= 64 * 1024
    assert tail.startswith("2026-11-16 10:00:00"), "первая строка не должна быть обрезана"


def test_small_log_is_read_fully(tmp_path):
    log = tmp_path / "small.log"
    _write_log(log, ["2026-11-16 10:00:00 [ERROR] boom"])

    assert _read_log_tail(log).strip() == "2026-11-16 10:00:00 [ERROR] boom"


def test_old_errors_are_outside_the_window():
    old = "2026-11-10 10:00:00 [ERROR] ancient"
    fresh = "2026-11-16 10:00:00 [ERROR] today"
    errors, warnings = _count_log_levels(
        f"{old}\n{fresh}", datetime(2026, 11, 16, 12, 0, 0)
    )
    assert (errors, warnings) == (1, 0)


def test_many_log_errors_degrade_instead_of_critical(tmp_path, monkeypatch):
    """Ошибки общего лога — degraded (warning), не critical (issue)."""
    import src.core.log_manager as log_manager

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_log(
        logs_dir / "mcp_global.log",
        [f"{now} [ERROR] чужая ошибка #{i}" for i in range(15)],
    )
    monkeypatch.setattr(log_manager, "get_log_dir", lambda _p: logs_dir)

    report = HealthReport(project_path=tmp_path).run_full_diagnostic()

    assert report["metrics"]["latest_log_errors"] >= 15
    assert report["overall_health"] != "critical", report["issues"]
    assert any(w["component"] == "logs" for w in report["warnings"])


def test_check_logs_uses_the_tail_reader(tmp_path, monkeypatch):
    """Проводка: _check_logs обязан идти через _read_log_tail, а не читать файл целиком."""
    import src.core.intelligence.health as health_mod
    import src.core.log_manager as log_manager

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    _write_log(logs_dir / "mcp_global.log", ["2026-11-16 10:00:00 [INFO] ok"])
    monkeypatch.setattr(log_manager, "get_log_dir", lambda _p: logs_dir)

    calls: list[str] = []
    real = health_mod._read_log_tail

    def _spy(path, cap=health_mod._LOG_TAIL_BYTES):
        calls.append(str(path))
        return real(path, cap)

    monkeypatch.setattr(health_mod, "_read_log_tail", _spy)

    HealthReport(project_path=tmp_path)._check_logs()

    assert calls, "чтение лога должно идти через _read_log_tail (хвост, а не весь файл)"


def test_global_log_is_named_as_shared_project_log_is_not(tmp_path, monkeypatch):
    """«Общий на все проекты» — только про `*global*.log`, а не про любой файл."""
    import src.core.log_manager as log_manager

    def _logs_warnings(log_file_name: str, sub: str) -> list[str]:
        logs_dir = tmp_path / sub
        logs_dir.mkdir()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _write_log(
            logs_dir / log_file_name,
            [f"{now} [ERROR] чужая ошибка #{i}" for i in range(15)],
        )
        monkeypatch.setattr(log_manager, "get_log_dir", lambda _p, d=logs_dir: d)
        report = HealthReport(project_path=tmp_path).run_full_diagnostic()
        return [w["message"] for w in report["warnings"] if w["component"] == "logs"]

    shared = _logs_warnings("mcp_global.log", "a")
    assert shared and "общий на все проекты" in shared[0]

    own = _logs_warnings("project.log", "b")
    assert own and "общий на все проекты" not in own[0]


def test_text_only_embedder_is_not_reported_as_available(tmp_path):
    """Текстовый режим — не «embedder доступен» и не warning (ревью 2026-11-16)."""

    class _Embedder:
        mode = "text_only"

    report = HealthReport(project_path=tmp_path, embedder=_Embedder()).run_full_diagnostic()

    assert report["metrics"]["embedder_status"] == "text_only"
    assert report["metrics"]["embedder_available"] is False
    assert not [w for w in report["warnings"] if w["component"] == "embedder"]


def test_diagnostic_does_not_log_warnings_into_the_counted_log(monkeypatch, caplog):
    """Диагностика не должна сама добавлять WARNING в лог (самозагрязнение)."""
    import logging

    with caplog.at_level(logging.WARNING, logger="mscodebase_server"):
        HealthReport(project_path=Path(".")).run_full_diagnostic()

    own = [r for r in caplog.records if "[diag]" in r.getMessage()]
    assert not [r for r in own if r.levelno >= logging.WARNING]
