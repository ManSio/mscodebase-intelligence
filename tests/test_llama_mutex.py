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
import sys
import uuid

import pytest

from src.providers.reranker.llama_runner import _InterProcessLock


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
