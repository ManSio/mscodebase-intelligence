"""Тесты OnnxEmbedderClient: discover-or-launch + reload после idle-timeout.

Заменяет stub (B11, KNOWN_ISSUES.md): вместо `assert True` — реальные
проверки `src/core/embedder/onnx_client.py`.

Реальный ONNX-сервер не поднимается (нужны модели, долгий старт) —
_launch_server/_health_check мокаются; тестируется именно логика
координации: health-check, double-check под локом, мутекс, reload.
"""

import threading
from unittest.mock import patch

from src.core.embedder.onnx_client import OnnxEmbedderClient


def _client():
    # Свободный порт: реальный health-check обязан вернуть False
    return OnnxEmbedderClient(port=19999, model_name="test-model")


def test_server_not_running_on_free_port():
    """TCP-проверка на свободном порту → сервер не запущен."""
    c = _client()
    assert c._is_server_running() is False


def test_health_check_fails_when_no_server():
    """HTTP health-check без сервера → False (не exception)."""
    c = _client()
    assert c._health_check() is False


def test_ensure_server_running_skips_launch_when_alive():
    """Сервер уже жив → launch не вызывается."""
    c = _client()
    with patch.object(c, "_health_check", return_value=True) as hc, patch.object(
        c, "_launch_server"
    ) as launch:
        assert c.ensure_server_running() is True
        hc.assert_called_once()
        launch.assert_not_called()


def test_ensure_server_running_launches_when_dead():
    """Сервер мёртв → захват мутекса, launch, ожидание готовности."""
    c = _client()
    with (
        patch.object(c, "_health_check", return_value=False),
        patch.object(c, "_acquire_launch_mutex", return_value=True),
        patch.object(c, "_launch_server", return_value=True) as launch,
        patch.object(c, "_wait_for_server", return_value=True) as wait,
        patch.object(c, "_release_launch_mutex"),
    ):
        assert c.ensure_server_running() is True
        launch.assert_called_once()
        wait.assert_called_once()


def test_ensure_server_running_waits_for_other_process():
    """Мутекс занят другим процессом → ждём готовности, не запускаем."""
    c = _client()
    with (
        patch.object(c, "_health_check", return_value=False),
        patch.object(c, "_acquire_launch_mutex", return_value=False),
        patch.object(c, "_launch_server") as launch,
        patch.object(c, "_wait_for_server", return_value=True) as wait,
    ):
        assert c.ensure_server_running() is True
        launch.assert_not_called()
        wait.assert_called_once()


def test_ensure_server_running_fails_when_launch_fails():
    """Не удалось запустить сервер → False (без исключения)."""
    c = _client()
    with (
        patch.object(c, "_health_check", return_value=False),
        patch.object(c, "_acquire_launch_mutex", return_value=True),
        patch.object(c, "_launch_server", return_value=False),
        patch.object(c, "_wait_for_server", return_value=False),
        patch.object(c, "_release_launch_mutex"),
    ):
        assert c.ensure_server_running() is False


def test_reload_after_idle_timeout():
    """Idle-reload: сервер был жив → умер (idle timeout) → повторный вызов перезапускает."""
    c = _client()
    # Фаза 1: сервер жив
    with patch.object(c, "_health_check", return_value=True), patch.object(
        c, "_launch_server"
    ) as launch:
        assert c.ensure_server_running() is True
        launch.assert_not_called()

    # Фаза 2: сервер умер → discover-or-launch заново
    with (
        patch.object(c, "_health_check", return_value=False),
        patch.object(c, "_acquire_launch_mutex", return_value=True),
        patch.object(c, "_launch_server", return_value=True) as launch2,
        patch.object(c, "_wait_for_server", return_value=True),
        patch.object(c, "_release_launch_mutex"),
    ):
        assert c.ensure_server_running() is True
        launch2.assert_called_once()


def test_ensure_server_running_concurrent_single_launch():
    """8 потоков при мёртвом сервере → launch ровно 1 раз (lock + мутекс)."""
    c = _client()
    mutex_results = iter([True] + [False] * 7)

    with (
        patch.object(c, "_health_check", return_value=False),
        patch.object(c, "_acquire_launch_mutex", side_effect=lambda: next(mutex_results)),
        patch.object(c, "_launch_server", return_value=True) as launch,
        patch.object(c, "_wait_for_server", return_value=True),
        patch.object(c, "_release_launch_mutex"),
    ):
        results = []
        errors = []

        def worker():
            try:
                results.append(c.ensure_server_running())
            except Exception as exc:  # noqa: BLE001 - собираем любую ошибку потока для диагностики гонки
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert launch.call_count == 1, "Сервер должен запускаться ровно один раз"
        assert all(results), "Все потоки должны получить успех"
