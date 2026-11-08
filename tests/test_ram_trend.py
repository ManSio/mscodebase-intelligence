"""RAM-trend heuristic: старт процесса не должен выглядеть утечкой (2026-11-07).

До фикса `is_growing` включался уже на 3 сэмплах: при прогреве (загрузка
моделей/индекса) health писал «Возможна утечка памяти» каждые 30 с.
Теперь нужен рост внутри окна (>=5 сэмплов и >50 MB прироста).
"""

from __future__ import annotations

from src.core.indexing.resource_monitor import ResourceMonitor


def _monitor_with(history):
    m = ResourceMonitor()
    m._ram_history = list(history)
    return m


def test_three_warmup_samples_are_not_a_leak():
    m = _monitor_with([(0, 100), (30, 130), (60, 160)])
    trend = m.get_ram_trend()
    assert trend["is_growing"] is False


def test_flat_history_is_not_a_leak():
    m = _monitor_with([(i * 30, 200) for i in range(8)])
    assert m.get_ram_trend()["is_growing"] is False


def test_sustained_growth_is_a_leak():
    # 8 сэмплов, +120 MB за окно — реальный рост
    m = _monitor_with([(i * 30, 100 + i * 17) for i in range(8)])
    trend = m.get_ram_trend()
    assert trend["is_growing"] is True
    assert trend["growth_mb"] > 50


def test_noise_does_not_trigger():
    # Мелкие колебания вокруг 200 MB ±3
    values = [200, 203, 199, 202, 198, 201, 200, 202]
    m = _monitor_with([(i * 30, v) for i, v in enumerate(values)])
    assert m.get_ram_trend()["is_growing"] is False
