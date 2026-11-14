"""Офлайн-пути установщика: скачивание модели без huggingface_hub и Vulkan-проба.

Оба дефекта — один класс с шагом 7 (`No module named 'httpx'`, 2026-11-14):
установщик работает интерпретатором пользователя, где зависимостей проекта нет.
Здесь проверяется, что «нет пакета» не роняет шаг, а проба железа не запускается
на импорте.
"""

from __future__ import annotations

import hashlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.providers.reranker import llama_install

PAYLOAD = b"GGUF-TEST-PAYLOAD-" * 4096


class _Handler(BaseHTTPRequestHandler):
    payload = PAYLOAD

    def do_GET(self):  # noqa: N802 — контракт http.server
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *_args):  # тишина в выводе тестов
        pass


@pytest.fixture()
def local_hf(monkeypatch):
    """Локальный «Hugging Face»: HF_BASE_URL указывает на него, сеть не нужна."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(llama_install, "HF_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def model_env(tmp_path, monkeypatch):
    """Модель с известным sha256 и каталог моделей во временной папке."""
    monkeypatch.setattr(llama_install, "_get_models_dir", lambda: tmp_path / "models")
    monkeypatch.setitem(
        llama_install.GGUF_MODELS,
        "test-model",
        {
            "repo": "org/repo",
            "file": "test.gguf",
            "size_mb": 1,
            "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
        },
    )
    return tmp_path / "models" / "test.gguf"


def _block_hub(monkeypatch):
    """Имитирует установщик в чистом интерпретаторе: пакета нет."""
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)


def test_gguf_download_works_without_huggingface_hub(local_hf, model_env, monkeypatch):
    _block_hub(monkeypatch)
    assert llama_install.download_gguf_model("test-model") is True
    assert model_env.read_bytes() == PAYLOAD
    assert not model_env.with_suffix(".gguf.part").exists()


def test_gguf_download_rejects_a_checksum_mismatch(local_hf, model_env, monkeypatch):
    _block_hub(monkeypatch)
    monkeypatch.setitem(
        llama_install.GGUF_MODELS, "test-model",
        {**llama_install.GGUF_MODELS["test-model"], "sha256": "0" * 64},
    )
    assert llama_install.download_gguf_model("test-model") is False
    assert not model_env.exists()
    assert not model_env.with_suffix(".gguf.part").exists()


def test_gguf_download_skips_the_network_when_the_file_exists(model_env, monkeypatch):
    model_env.parent.mkdir(parents=True, exist_ok=True)
    model_env.write_bytes(b"already-here")

    def no_network(*_a, **_k):
        raise AssertionError("download must not start for an existing file")

    monkeypatch.setattr(llama_install, "_download_gguf_via_urllib", no_network)
    assert llama_install.download_gguf_model("test-model") is True
    assert model_env.read_bytes() == b"already-here"


def test_vulkan_probe_is_not_started_without_the_vulkan_build(monkeypatch):
    """Нет сборки — нет процесса: импорт установщика не зовёт vulkaninfo."""
    calls: list[object] = []
    monkeypatch.setattr(llama_install.subprocess, "Popen", lambda *a, **k: calls.append(a))
    assert llama_install._detect_vulkan(has_binary=False) is False
    assert calls == []


def test_vulkan_probe_is_not_started_on_other_platforms(monkeypatch):
    monkeypatch.setattr(llama_install.sys, "platform", "linux")
    monkeypatch.setattr(llama_install.subprocess, "Popen", lambda *a, **k: pytest.fail("spawned"))
    assert llama_install._detect_vulkan(has_binary=True) is False


@pytest.mark.skipif(sys.platform != "win32", reason="WinAPI/реестр — только Windows")
def test_cpu_detection_spawns_no_process_of_any_kind(monkeypatch):
    """Ловим любой запуск: Popen/run/check_output/check_call/os.system/os.popen."""
    import os
    import subprocess

    def boom(*_a, **_k):
        raise AssertionError("CPU detection must not spawn processes")

    for name in ("Popen", "run", "check_output", "check_call", "call"):
        monkeypatch.setattr(subprocess, name, boom)
    monkeypatch.setattr(os, "system", boom)
    monkeypatch.setattr(os, "popen", boom)

    info = llama_install._detect_cpu()
    # Контракт, а не железо: реестр/WinAPI бывают недоступны при верном коде.
    assert isinstance(info, dict) and isinstance(info["name"], str)
    assert isinstance(info["ram_gb"], int) and info["ram_gb"] >= 0


def test_ram_falls_back_to_the_documented_default(monkeypatch):
    monkeypatch.setattr(llama_install.sys, "platform", "win32")
    monkeypatch.setattr(llama_install, "_windows_ram_gb", lambda: None)
    monkeypatch.setattr(llama_install, "_windows_cpu_name", lambda: "")
    info = llama_install._detect_cpu()
    assert info["ram_gb"] == 8
    assert info["name"] == "unknown"
