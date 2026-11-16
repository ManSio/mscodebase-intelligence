"""Guard: при LLAMA_CPP_ENABLED=false старт не трогает ни embedder, ни реранкер.

Замер 2026-11-16: в логе на каждом старте был
`ERROR mscodebase_server.llama_runner: GGUF модель не найдена` — блок реранкера
запускался безусловно, хотя общий тумблер llama.cpp выключен.
"""
from __future__ import annotations

import src.mcp.server_factory as sf
import src.providers.reranker.llama_runner as llama_mod


class _Cfg:
    class embedding:  # noqa: N801 - повторяет форму настроек
        llama_cpp_enabled = False


def test_disabled_toggle_skips_embedder_and_reranker(monkeypatch):
    monkeypatch.setattr("src.config.settings.get_config", lambda: _Cfg())

    called: list[str] = []

    def _boom_start_sync(self, model):  # pragma: no cover - только при регрессе
        called.append("embedder")
        return False

    async def _boom_start_reranker(self):  # pragma: no cover
        called.append("reranker")
        return False

    monkeypatch.setattr(llama_mod.LlamaRunner, "_start_sync", _boom_start_sync)
    monkeypatch.setattr(llama_mod.LlamaRunner, "start_reranker", _boom_start_reranker)

    sf._start_llama_sync()

    assert called == [], f"при выключенном тумблере ничего не запускается, а запущено: {called}"
