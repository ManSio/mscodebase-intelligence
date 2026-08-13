"""Тесты Windows Named Mutex в llama_runner._InterProcessLock.

Регрессия deep-research-report.md P1: CreateMutexW(None, True, ...) +
WaitForSingleObject = двойной захват (recursion 2), один ReleaseMutex
(в _release) → мутекс остаётся owned после выхода из with (утечка владения
до смерти потока) → повторный запуск llama-server другим MCP-процессом не
может захватить лок (10s timeout → RuntimeError).

Фикс: bInitialOwner=False — владение только через WaitForSingleObject
(эталон: src/core/graph.py:74 _CrossProcessMutex, src/core/embedder/onnx_client.py:76).

Запуск: pytest tests/test_llama_mutex.py -v
"""

import ctypes
import os
import subprocess
import sys
import time
import uuid

import pytest

from src.providers.reranker.llama_runner import _InterProcessLock

_WIN32 = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows Named Mutex / PID-проверка только на Windows"
)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Named Mutex только на Windows")
def test_interprocess_lock_release_does_not_leak_ownership():
    """После выхода из with мутекс обязан быть свободен (WaitForSingleObject, 0ms).

    С багом (initialOwner=True): при выходе ReleaseMutex снимает только ОДИН
    из двух захватов → WaitForSingleObject(h, 0) вернёт WAIT_TIMEOUT (258).
    С фиксом (initialOwner=False): count 1 → Release → 0 → WAIT_OBJECT_0 (0).
    """
    name = f"mscodebase_test_{uuid.uuid4().hex[:8]}"
    lock = _InterProcessLock(name)
    with lock:
        pass  # acquire + release

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    # Открываем существующий мутекс и пробуем захватить без ожидания
    h = kernel32.CreateMutexW(None, False, lock._name)
    assert h, "CreateMutexW failed"
    result = kernel32.WaitForSingleObject(h, 0)
    try:
        assert result == 0, (
            f"Мutex остался owned после release (WaitForSingleObject={result}, "
            f"ожидался 0=WAIT_OBJECT_0) — утечка владения"
        )
    finally:
        kernel32.ReleaseMutex(h)
        kernel32.CloseHandle(h)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PID-проверка")
def test_is_pid_alive_dead_process_returns_false():
    """Завершённый процесс не считается живым (инцидент 2026-08-13: stale PID
    reranker'а блокировал запуск весь день).

    До фикса OpenProcess(SYNCHRONIZE) возвращал handle для завершённого
    процесса (объект жив, пока у родителя handle) → ложный True.
    """
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    proc.communicate()
    # Даём ОС время убрать объект процесса
    time.sleep(0.2)

    assert _InterProcessLock._is_pid_alive(proc.pid) is False, (
        f"PID {proc.pid} завершён, но _is_pid_alive вернул True — "
        f"OpenProcess(SYNCHRONIZE) видит объект процесса без exit-code проверки"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PID-проверка")
def test_is_pid_alive_nonexistent_pid_returns_false():
    """Несуществующий PID → False (OpenProcess вернёт NULL)."""
    # 2^28 — заведомо вне диапазона типовых PID (макс ~4e6 на Windows)
    assert _InterProcessLock._is_pid_alive(2**28) is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PID-проверка")
def test_is_pid_alive_non_llama_process_returns_false():
    """Живой процесс, НЕ llama-server.exe → False (PID-reuse guard).

    Если мёртвый PID переиспользован другим процессом — мы не должны
    считать, что llama-server уже запущен.
    """
    assert _InterProcessLock._is_pid_alive(os.getpid()) is False


@_WIN32
def test_start_sync_spawns_embedder_once_under_concurrency():
    """Дедупликация embedder при 2 окнах (инцидент 2026-08-13: 2×8080).

    Windows-only: на Linux _InterProcessLock не использует Named Mutex
    (только PID-файл, гонка между потоками) — проверяем именно Windows-путь
    (прод-платформа: 2 окна Zed).

    Два конкурирующих вызова _start_sync (по одному на MCP-окно):
    lock держится ДО готовности порта, поэтому второй вызов видит
    «порт занят» и НЕ спавнит второго llama-server (spawn_count == 1).
    """
    import threading

    from src.providers.reranker.llama_runner import LlamaRunner

    runner = LlamaRunner.__new__(LlamaRunner)
    runner._host = "127.0.0.1"
    runner._port = 8199  # тестовый порт (8080-8090 диапазон не обязателен для спавна)
    runner._model_key = None
    runner._reranker_process = None

    state = {"spawned": 0, "ready": False, "lock": threading.Lock()}

    def fake_spawn(_model_key: str) -> bool:
        with state["lock"]:
            state["spawned"] += 1
        # Симулируем задержку запуска llama-server (Popen → bind порта)
        time.sleep(0.2)
        with state["lock"]:
            state["ready"] = True
        return True

    def fake_probe(_port: int) -> bool:
        with state["lock"]:
            return state["ready"]

    runner.is_alive = lambda: False
    runner._spawn_embedder = fake_spawn
    runner._probe_port_sync = fake_probe

    results = []
    errors = []

    def worker():
        try:
            results.append(runner._start_sync("test-model"))
        except Exception as e:  # noqa: BLE001 — тест должен увидеть любую ошибку
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"unexpected errors: {errors}"
    assert state["spawned"] == 1, (
        f"embedder спавнился {state['spawned']} раз — гонка двух окон не закрыта"
    )
    assert all(results), f"_start_sync вернул False: {results}"
