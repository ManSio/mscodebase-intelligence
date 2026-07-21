"""Unit-тесты для ResourceMonitor (multi-window, INC-6BCB)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.core.indexing.resource_monitor import (
    ResourceMonitor,
    ResourceSnapshot,
    get_global_resource_monitor,
    reset_global_resource_monitor,
)


class TestResourceMonitor:
    """ResourceMonitor: stdlib-only мониторинг RAM/CPU."""

    def test_sample_returns_snapshot(self):
        m = ResourceMonitor()
        s = m.sample(force=True)
        assert isinstance(s, ResourceSnapshot)
        assert s.rss_mb >= 0
        assert s.num_threads >= 1
        assert s.timestamp > 0

    def test_sample_throttles(self):
        m = ResourceMonitor(min_sample_interval_sec=10.0)
        s1 = m.sample(force=True)
        # Второй sample без force возвращает кэшированный snapshot.
        s2 = m.sample(force=False)
        assert s2 is s1, "Должен вернуть кэш при interval < min_sample_interval"

    def test_pressure_thresholds(self):
        # С заведомо большими порогами — давления нет.
        m = ResourceMonitor(ram_soft_mb=99999, ram_hard_mb=99999)
        assert not m.is_under_pressure()
        assert not m.is_under_pressure(hard=True)

        # С заведомо маленькими — давление есть.
        m_low = ResourceMonitor(ram_soft_mb=1, ram_hard_mb=2)
        assert m_low.is_under_pressure()
        assert m_low.is_under_pressure(hard=True)

    def test_throttle_delay_scaling(self):
        ResourceMonitor(
            ram_soft_mb=100,
            ram_hard_mb=200,
            cpu_soft_percent=50.0,
            cpu_hard_percent=80.0,
        )
        # Под нормальной нагрузкой delay = 0.
        m_low_thresh = ResourceMonitor(ram_soft_mb=99999, ram_hard_mb=99999)
        assert m_low_thresh.suggest_throttle_delay_sec() == 0.0

        # Под high pressure — delay > 0.
        m_high = ResourceMonitor(ram_soft_mb=1, ram_hard_mb=1)
        delay = m_high.suggest_throttle_delay_sec()
        assert delay > 0.0, f"Должен быть delay > 0 под pressure, got {delay}"

    def test_summary_structure(self):
        m = ResourceMonitor()
        summary = m.get_summary()
        required_keys = {
            "rss_mb", "cpu_percent", "num_threads", "timestamp",
            "ram_soft_mb", "ram_hard_mb", "cpu_soft_percent", "cpu_hard_percent",
            "num_cpus", "under_soft_pressure", "under_hard_pressure",
            "suggested_throttle_sec",
        }
        assert required_keys.issubset(summary.keys()), \
            f"Missing keys: {required_keys - summary.keys()}"

    def test_singleton(self):
        reset_global_resource_monitor()
        m1 = get_global_resource_monitor()
        m2 = get_global_resource_monitor()
        assert m1 is m2
        reset_global_resource_monitor()
        m3 = get_global_resource_monitor()
        assert m3 is not m1
        reset_global_resource_monitor()


class TestProjectIndexerRegistry:
    """ProjectIndexerRegistry: per-project cache с LRU + ResourceMonitor."""

    def test_singleton_per_path(self):
        from src.core.indexing.project_indexer_registry import (
            ProjectIndexerRegistry,
            reset_global_registry,
        )
        reset_global_registry()

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "P1"
            proj.mkdir()

            reg = ProjectIndexerRegistry(max_cached=5)
            i1 = reg.get_indexer(proj, factory=lambda p: object())
            i2 = reg.get_indexer(proj, factory=lambda p: object())
            assert i1 is i2, "Должен вернуть тот же Indexer (singleton per path)"

    def test_lru_eviction(self):
        from src.core.indexing.project_indexer_registry import ProjectIndexerRegistry

        with tempfile.TemporaryDirectory() as tmp:
            projects = [Path(tmp) / f"P{i}" for i in range(3)]
            for p in projects:
                p.mkdir()

            reg = ProjectIndexerRegistry(max_cached=2)
            for p in projects:
                reg.get_indexer(p, factory=lambda x: object())

            stats = reg.get_stats()
            # После 3-х get_indexer с max_cached=2 должно остаться 2.
            assert stats["cached_projects"] == 2, \
                f"LRU eviction должен сработать, cached={stats['cached_projects']}"
            assert stats["evictions"] == 1, \
                f"Должна быть 1 eviction, got {stats['evictions']}"

    def test_pressure_eviction(self):
        from src.core.indexing.project_indexer_registry import ProjectIndexerRegistry

        # Monitor с заведомо маленьким порогом → всегда pressure.
        monitor = ResourceMonitor(ram_soft_mb=1, ram_hard_mb=1)

        with tempfile.TemporaryDirectory() as tmp:
            projects = [Path(tmp) / f"P{i}" for i in range(3)]
            for p in projects:
                p.mkdir()

            reg = ProjectIndexerRegistry(max_cached=10, resource_monitor=monitor)
            for p in projects:
                reg.get_indexer(p, factory=lambda x: object())

            stats = reg.get_stats()
            # pressure_evicts должны сработать.
            assert stats["evictions_for_pressure"] >= 1, \
                f"Должен быть pressure-evict, got {stats['evictions_for_pressure']}"

    def test_evict_explicit(self):
        from src.core.indexing.project_indexer_registry import ProjectIndexerRegistry

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "P1"
            proj.mkdir()

            reg = ProjectIndexerRegistry(max_cached=5)
            reg.get_indexer(proj, factory=lambda p: object())
            assert reg.evict(proj) is True
            assert reg.evict(proj) is False  # уже удалён
            assert len(reg.get_all_paths()) == 0

    def test_stats_track_hits_misses(self):
        from src.core.indexing.project_indexer_registry import ProjectIndexerRegistry

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "P1"
            proj.mkdir()

            reg = ProjectIndexerRegistry(max_cached=5)
            reg.get_indexer(proj, factory=lambda p: object())  # miss
            reg.get_indexer(proj, factory=lambda p: object())  # hit
            reg.get_indexer(proj, factory=lambda p: object())  # hit

            stats = reg.get_stats()
            assert stats["cache_misses"] == 1
            assert stats["cache_hits"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
