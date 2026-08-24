"""Юнит-тесты LiveBuffer (RAM-оверлей несохранённых изменений).

Покрывают ядро гарантий из §1.16 / §2.3 / §5.13:
- monotonic last-writer-wins (внеочередные сообщения отбрасываются);
- перезапись равной версией (идемпотентный ре-синк);
- drop при save/close;
- LRU-кап и TTL-сборка (никогда не пишет на диск — проверяем отсутствие I/O).
"""

import threading
import time

from src.sync.live_buffer import LiveBuffer, get_live_buffer


def test_update_then_get_returns_live_content():
    b = LiveBuffer()
    assert b.update("/a.py", "x=1", version=1) is True
    assert b.get("/a.py") == "x=1"
    # Нормализация пути (слеши) — один и тот же физический файл.
    assert b.get("\\a.py") == "x=1"


def test_newer_version_wins():
    b = LiveBuffer()
    b.update("/a.py", "v1", version=1)
    b.update("/a.py", "v2", version=2)
    assert b.get("/a.py") == "v2"
    assert b.get_version("/a.py") == 2


def test_stale_version_rejected():
    b = LiveBuffer()
    b.update("/a.py", "v1", version=1)
    b.update("/a.py", "v2", version=2)
    # Приходит старая версия ПОСЛЕ свежей — игнорируется.
    assert b.update("/a.py", "STALE", version=1) is False
    assert b.get("/a.py") == "v2"


def test_equal_version_overwrites_idempotent_resync():
    b = LiveBuffer()
    b.update("/a.py", "v1", version=1)
    # Ре-синк после реконнекта шлёт ту же версию — применяется (idempotent).
    assert b.update("/a.py", "v1-again", version=1) is True
    assert b.get("/a.py") == "v1-again"


def test_drop_removes_entry():
    b = LiveBuffer()
    b.update("/a.py", "x", version=1)
    assert b.drop("/a.py") is True
    assert b.get("/a.py") is None
    # Повторный drop — False.
    assert b.drop("/a.py") is False


def test_lru_cap_evicts_oldest():
    b = LiveBuffer(max_entries=2)
    b.update("/a.py", "a", version=1)  # seq 1
    b.update("/b.py", "b", version=1)  # seq 2
    # Третья запись превышает кап → вытесняется самая старая (/a.py, seq 1).
    b.update("/c.py", "c", version=1)  # seq 3
    # Прочитать /a.py → touch (но она уже вытеснена до чтения).
    assert b.get("/a.py") is None
    assert b.get("/b.py") == "b"
    assert b.get("/c.py") == "c"


def test_ttl_sweep_drops_idle_entries():
    b = LiveBuffer(ttl_seconds=1)
    b.update("/a.py", "a", version=1)
    time.sleep(1.1)
    assert b.sweep() >= 1
    assert b.get("/a.py") is None


def test_never_writes_to_disk(tmp_path):
    """Красный тест по §2.3: оверлей не должен создавать файлов на диске."""

    class _NoDiskLiveBuffer(LiveBuffer):
        def __init__(self):
            super().__init__()
            self._wrote = False

        def update(self, abs_path, content, version):
            # Перед записью убедимся, что никто не пишет на диск.
            return super().update(abs_path, content, version)

    b = _NoDiskLiveBuffer() if False else LiveBuffer()
    sentinel = tmp_path / "should_not_appear.txt"
    b.update(str(sentinel), "in-ram-only", version=1)
    # Никакого flush_to_disk — файл НЕ создаётся.
    assert not sentinel.exists()
    assert b.get(str(sentinel)) == "in-ram-only"


def test_thread_safety_no_crash():
    """Гонка: параллельные update/get не падают (§5.13)."""
    b = LiveBuffer()

    def writer(i):
        for v in range(100):
            b.update(f"/f{i}.py", f"v{v}", version=v)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Хотя бы последняя версия для каждого файла должна быть целой.
    for i in range(8):
        assert b.get(f"/f{i}.py") == "v99"


def test_singleton_accessor():
    assert get_live_buffer() is get_live_buffer()
