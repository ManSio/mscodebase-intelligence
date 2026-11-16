"""Guard: без llama.cpp стартовый probe размерности не делается.

Замер 2026-11-16: `create_service_collection` тратил ~3.5 с из ~6 с на
`httpx.post` к `:8080/v1/embeddings`, хотя `LLAMA_CPP_ENABLED=false` — сервера
нет и не будет. Это треть холодного старта MCP.
"""
from __future__ import annotations

import pytest

from src.providers.embedder import remote_embedder as re_mod


@pytest.fixture()
def _no_llama(monkeypatch):
    monkeypatch.setenv("LLAMA_CPP_ENABLED", "false")


def _forbid_probe(monkeypatch):
    def _boom(self):  # pragma: no cover - вызывается только при регрессе
        raise AssertionError("probe не должен выполняться при LLAMA_CPP_ENABLED=false")

    monkeypatch.setattr(re_mod.RemoteEmbedder, "_probe_server_dimension", _boom)


def test_probe_is_skipped_when_llama_is_disabled(monkeypatch, _no_llama):
    _forbid_probe(monkeypatch)
    embedder = re_mod.RemoteEmbedder()
    assert embedder.embedding_dim > 0


def test_probe_runs_when_llama_is_enabled(monkeypatch):
    """Dense-режим + llama.cpp: probe размерности нужен."""
    from src.config.settings import get_config as _real_get_config

    class _Search:
        dense_off = False

    class _Cfg:
        def __init__(self, base):
            self._base = base
            self.search = _Search()

        def __getattr__(self, name):
            return getattr(self._base, name)

    monkeypatch.setenv("LLAMA_CPP_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "")  # иначе probe не нужен
    monkeypatch.setattr(re_mod, "get_config", lambda: _Cfg(_real_get_config()))
    calls: list[int] = []

    def _fake_probe(self):
        calls.append(1)
        return None

    monkeypatch.setattr(re_mod.RemoteEmbedder, "_probe_server_dimension", _fake_probe)
    embedder = re_mod.RemoteEmbedder()
    assert embedder._text_only is False
    assert calls, "при включённом llama.cpp probe обязан вызываться"


def test_onnx_init_is_skipped_in_text_only_mode(monkeypatch):
    """dense_off=true — эмбеддинги не нужны, ONNX-сервер не трогаем вовсе.

    На Windows connect_ex к закрытому loopback-порту ждёт полный таймаут
    (WSAEWOULDBLOCK вместо отказа): 6 проб на старте = ~3 с впустую.
    """
    import src.core.embedder.onnx_client as oc
    from src.config.settings import get_config as _real_get_config

    class _Search:
        dense_off = True

    class _Cfg:
        """Копия конфига с одним изменённым полем (singleton читается из env)."""

        def __init__(self, base):
            self._base = base
            self.search = _Search()

        def __getattr__(self, name):
            return getattr(self._base, name)

    monkeypatch.setattr(re_mod, "get_config", lambda: _Cfg(_real_get_config()))

    def _boom(*args, **kwargs):  # pragma: no cover - только при регрессе
        raise AssertionError("в текстовом режиме ONNX-клиент не должен создаваться")

    monkeypatch.setattr(oc, "get_onnx_client", _boom)

    embedder = re_mod.RemoteEmbedder()
    embedder._init_onnx()
    assert embedder.mode == "text_only"


def test_provider_init_does_not_probe_external_endpoints_in_text_mode(monkeypatch):
    """auto-режим в текстовом режиме не должен щупать LM Studio/ollama."""
    from src.config.settings import get_config as _real_get_config

    class _Search:
        dense_off = True

    class _Cfg:
        def __init__(self, base):
            self._base = base
            self.search = _Search()

        def __getattr__(self, name):
            return getattr(self._base, name)

    monkeypatch.setattr(re_mod, "get_config", lambda: _Cfg(_real_get_config()))

    def _boom(*args, **kwargs):  # pragma: no cover - только при регрессе
        raise AssertionError("в текстовом режиме внешние эндпоинты не опрашиваются")

    monkeypatch.setattr(re_mod.RemoteEmbedder, "_check_lm_studio_raw", _boom)
    monkeypatch.setattr(re_mod.RemoteEmbedder, "_check_ollama", _boom)
    monkeypatch.setattr(re_mod.RemoteEmbedder, "_check_llama_cpp", _boom)

    embedder = re_mod.RemoteEmbedder()
    embedder._init_provider_async()
    assert embedder.mode == "text_only"


def test_probe_is_skipped_in_text_mode_even_with_llama_flag_unset(monkeypatch):
    """dense_off=true по умолчанию: probe не должен зависеть от LLAMA_CPP_ENABLED."""
    from src.config.settings import get_config as _real_get_config

    class _Search:
        dense_off = True

    class _Cfg:
        def __init__(self, base):
            self._base = base
            self.search = _Search()

        def __getattr__(self, name):
            return getattr(self._base, name)

    monkeypatch.delenv("LLAMA_CPP_ENABLED", raising=False)
    monkeypatch.delenv("EMBEDDING_DIMENSION", raising=False)
    monkeypatch.setattr(re_mod, "get_config", lambda: _Cfg(_real_get_config()))

    calls: list[int] = []

    def _spy(self):
        calls.append(1)
        return None

    monkeypatch.setattr(re_mod.RemoteEmbedder, "_probe_server_dimension", _spy)
    embedder = re_mod.RemoteEmbedder()

    assert embedder._text_only is True
    assert not calls, "в текстовом режиме сетевой probe не выполняется"


def test_provider_scanner_is_not_started_in_text_mode(monkeypatch):
    """Фоновый сканер не должен подниматься в текстовом режиме.

    Ревью 2026-11-16: при provider=auto сканер стартовал безусловно и через
    30 с опрашивал LM Studio/ollama, переписывая mode на сетевой провайдер.
    """
    from src.config.settings import get_config as _real_get_config

    class _Search:
        dense_off = True

    class _Cfg:
        def __init__(self, base):
            self._base = base
            self.search = _Search()

        def __getattr__(self, name):
            return getattr(self._base, name)

    monkeypatch.setattr(re_mod, "get_config", lambda: _Cfg(_real_get_config()))

    embedder = re_mod.RemoteEmbedder()

    assert embedder._text_only is True
    assert embedder._scanner_thread is None, "сканер провайдеров не нужен в текстовом режиме"
    assert embedder._preload_thread is None, "предзагрузка ONNX не нужна в текстовом режиме"


def test_scanner_loop_exits_without_network_in_text_mode(monkeypatch):
    """Даже вызванный вручную сканер обязан выйти, не трогая сеть."""
    import threading

    from src.config.settings import get_config as _real_get_config

    class _Search:
        dense_off = True

    class _Cfg:
        def __init__(self, base):
            self._base = base
            self.search = _Search()

        def __getattr__(self, name):
            return getattr(self._base, name)

    monkeypatch.setattr(re_mod, "get_config", lambda: _Cfg(_real_get_config()))
    monkeypatch.setattr(re_mod, "_PROVIDER_SCAN_INTERVAL", 0)

    def _boom(*args, **kwargs):  # pragma: no cover - только при регрессе
        raise AssertionError("в текстовом режиме сканер не должен ходить в сеть")

    monkeypatch.setattr(re_mod.RemoteEmbedder, "_check_lm_studio_raw", _boom)
    monkeypatch.setattr(re_mod.RemoteEmbedder, "_check_ollama", _boom)
    monkeypatch.setattr(re_mod.RemoteEmbedder, "_check_llama_cpp", _boom)

    embedder = re_mod.RemoteEmbedder()
    embedder._text_only = True
    embedder._scanner_stop = threading.Event()
    embedder._provider_scanner_loop()  # не должен зависнуть
    assert embedder.mode == "text_only"
