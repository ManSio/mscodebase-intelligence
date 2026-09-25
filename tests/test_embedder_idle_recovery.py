"""Регресс-тесты инцидента 2026-09-22: search_code timeout из-за выгруженного embedder.

Цепочка отказа:
1. Watchdog llama_runner по EMBEDDER_IDLE_TIMEOUT=120s сам убивает llama-server
   (`_process=None`) ради RAM.
2. Клиент (RemoteEmbedder.embed_batch) ретраил по логам 3 батча + поштучно, но
   НИКОГДА не поднимал сервер обратно → `WinError 10061` → search_code >15s.
3. Второй дефект: hot-reload (`verify_index_freshness`) ждался синхронно внутри
   search_code → при пачке новых файлов поиск выходил за бюджет.

Покрытие:
A. LlamaRunner.ensure_embedder_started / is_port_up — контракт «поднять при use».
B. RemoteEmbedder._revive_llama_cpp — revive только когда сервер реально мёртв.
C. SearchCodeTool._maybe_hot_reload — фон, дедуп, не блокирует.
"""
import asyncio
from types import SimpleNamespace

from src.mcp.tools.search_tools import SearchCodeTool
from src.providers.embedder.remote_embedder import RemoteEmbedder
from src.providers.reranker.llama_runner import (
    DEFAULT_EMBEDDING_MODEL,
    LlamaRunner,
)

# ── A. LlamaRunner.ensure_embedder_started / is_port_up ──

def test_ensure_embedder_skips_start_when_alive():
    runner = LlamaRunner()
    runner.is_alive = lambda: True
    runner._probe_port_sync = lambda port: False
    started = []
    runner._start_sync = lambda model_key=None: started.append(model_key) or True

    assert runner.ensure_embedder_started() is True
    assert started == [], "живой сервер не должен перезапускаться"


def test_ensure_embedder_skips_start_when_port_up():
    runner = LlamaRunner()
    runner.is_alive = lambda: False
    runner._probe_port_sync = lambda port: True  # чужой процесс держит порт
    started = []
    runner._start_sync = lambda model_key=None: started.append(model_key) or True

    assert runner.ensure_embedder_started() is True
    assert started == [], "порт отвечает — старт не нужен"


def test_ensure_embedder_starts_when_dead_and_port_down():
    runner = LlamaRunner()
    runner.is_alive = lambda: False
    runner._probe_port_sync = lambda port: False
    started = []
    runner._start_sync = lambda model_key=None: started.append(model_key) or True

    assert runner.ensure_embedder_started() is True
    assert len(started) == 1, "мёртвый сервер должен быть перезапущен"
    assert started[0] == DEFAULT_EMBEDDING_MODEL


def test_is_port_up_true_and_false():
    runner = LlamaRunner()
    runner._probe_port_sync = lambda port: True
    assert runner.is_port_up() is True
    runner._probe_port_sync = lambda port: (_ for _ in ()).throw(RuntimeError("boom"))
    assert runner.is_port_up() is False


# ── B. RemoteEmbedder._revive_llama_cpp ──

def _patch_runner(monkeypatch, *, alive, port_up, start_result=True):
    import src.providers.reranker.llama_runner as lr

    calls = {"ensure": 0}
    fake = SimpleNamespace(
        is_alive=lambda: alive,
        is_port_up=lambda: port_up,
        ensure_embedder_started=lambda *a, **k: calls.__setitem__("ensure", calls["ensure"] + 1) or start_result,
    )
    monkeypatch.setattr(lr, "get_global_runner", lambda: fake)
    return calls


def test_revive_returns_false_when_alive(monkeypatch):
    calls = _patch_runner(monkeypatch, alive=True, port_up=False)
    emb = RemoteEmbedder.__new__(RemoteEmbedder)
    assert emb._revive_llama_cpp() is False
    assert calls["ensure"] == 0


def test_revive_returns_false_when_port_up(monkeypatch):
    calls = _patch_runner(monkeypatch, alive=False, port_up=True)
    emb = RemoteEmbedder.__new__(RemoteEmbedder)
    assert emb._revive_llama_cpp() is False
    assert calls["ensure"] == 0


def test_revive_restarts_when_dead(monkeypatch):
    calls = _patch_runner(monkeypatch, alive=False, port_up=False)
    emb = RemoteEmbedder.__new__(RemoteEmbedder)
    assert emb._revive_llama_cpp() is True
    assert calls["ensure"] == 1


def test_revive_handles_exception(monkeypatch):
    import src.providers.reranker.llama_runner as lr

    def _boom():
        raise RuntimeError("no runner")

    monkeypatch.setattr(lr, "get_global_runner", _boom)
    emb = RemoteEmbedder.__new__(RemoteEmbedder)
    assert emb._revive_llama_cpp() is False  # не роняет эмбеддер


# ── C. SearchCodeTool._maybe_hot_reload ──

def _make_search_tool(monkeypatch, verify_calls):
    tool = SearchCodeTool.__new__(SearchCodeTool)
    tool._hot_reload_task = None
    fake_indexer = SimpleNamespace(
        project_path="D:/proj",
        verify_index_freshness=lambda path: verify_calls.append(path) or 3,
    )
    tool.resolve_indexer = lambda explicit_project_root=None: fake_indexer

    import src.config.settings as settings_mod
    monkeypatch.setattr(
        settings_mod,
        "get_config",
        lambda: SimpleNamespace(
            performance=SimpleNamespace(freshness_interval_sec=30)
        ),
    )
    return tool


def test_hot_reload_is_backgrounded_and_deduped(monkeypatch):
    verify_calls = []
    tool = _make_search_tool(monkeypatch, verify_calls)

    async def scenario():
        await tool._maybe_hot_reload()
        assert tool._hot_reload_task is not None, "сверка должна уйти в фон"
        first = tool._hot_reload_task
        assert not first.done(), "search_code не должен ждать hot-reload"

        # повторный вызов при незавершённой задаче — не плодит вторую
        await tool._maybe_hot_reload()
        assert tool._hot_reload_task is first

        await first
        assert verify_calls == ["D:/proj"]

    asyncio.run(scenario())


def test_hot_reload_disabled_when_interval_zero(monkeypatch):
    verify_calls = []
    tool = _make_search_tool(monkeypatch, verify_calls)

    import src.config.settings as settings_mod
    monkeypatch.setattr(
        settings_mod,
        "get_config",
        lambda: SimpleNamespace(
            performance=SimpleNamespace(freshness_interval_sec=0)
        ),
    )

    async def scenario():
        await tool._maybe_hot_reload()
        assert tool._hot_reload_task is None
        assert verify_calls == []

    asyncio.run(scenario())
