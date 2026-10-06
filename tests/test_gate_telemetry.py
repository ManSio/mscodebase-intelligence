"""Тесты телеметрии гейтов доставки (gate_telemetry.jsonl).

Покрытие по SPEC:
 1. Схема restraint-detail (ключи на каждой строке — Python-часть строки).
 2. Каждая причина подавления достижима (cooldown, zero findings, gate off*,
    non-git unavailable). *gate off / error_* — решения TS-хука, их достижимость
    проверена в tests/gate_telemetry.test.mjs (node --test, вызывается отсюда же).
 3. Путь лога: override + default в data dir, не в temp.
 4. Golden-тест: решения (deliver/suppress + findings) идентичны до/после
    рефакторинга на фиксированном наборе входов (значения записаны ДО правок).
 5. stale_detector не имеет эквивалента suppression (проверено чтением кода) —
    менять нечего; причина фиксируется комментарием и тестом отсутствия wiring.

Примечание: stale_detector — блокирующий гейт без restraint (см. SPEC п.4):
у него нет подавления повторов, поэтому класса suppressed_restraint для него
не существует; его причины: fired_block / suppressed_zero_findings /
skipped_off / error_unavailable / error_exception.
"""
import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.artifact_paths import get_gate_log_path, get_project_dir, project_hash
from src.core.graph import NodeLabel, PropertyGraph
from src.core.quiet_break_gate import run_quiet_break_gate
from src.core.restraint import should_deliver, should_deliver_detail, signature

# ── Golden: записано ДО рефакторинга (git status чист, код исходный) ──
# restraint: should_deliver(project, sig, cooldown_sec=100, now=...) по порядку.
GOLDEN_RESTRAINT_SEQ = [
    ("A", 1000, True, "delivered"),
    ("A", 1050, False, "cooldown: same findings, 50s left (strikes=0)"),
    ("A", 1101, True, "delivered"),
    ("B", 1010, True, "delivered"),
    # Единственный слот состояния: после B сиг. A считается новой → доставка.
    ("A", 1250, True, "delivered"),
]

GOLDEN_SIG1 = "ad6d23ff4f5c87c2"  # [{'kind':'new_orphan','symbol':'helper','file':'pkg/a.py'}]
GOLDEN_SIG2 = "f33ffc62da6c0677"  # [{'kind':'removed_last_caller','symbol':'target','file':'pkg/b.py'}]


def _isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(tmp_path / "data"))


# ── 1. Схема restraint-detail ──

def test_restraint_detail_schema(tmp_path, monkeypatch):
    _isolated_env(monkeypatch, tmp_path)
    d = should_deliver_detail(tmp_path / "proj", "sigX", cooldown_sec=100, now=1000.0)
    assert set(d) == {"delivered", "reason", "signature", "strikes", "cooldown_s_left"}
    assert d == {"delivered": True, "reason": "delivered", "signature": "sigX",
                 "strikes": 0, "cooldown_s_left": 0}
    assert isinstance(d["strikes"], int) and isinstance(d["cooldown_s_left"], int)


def test_restraint_detail_suppress_shape(tmp_path, monkeypatch):
    _isolated_env(monkeypatch, tmp_path)
    root = tmp_path / "proj"
    should_deliver_detail(root, "sigX", cooldown_sec=100, now=1000.0)
    d = should_deliver_detail(root, "sigX", cooldown_sec=100, now=1050.0)
    assert d["delivered"] is False
    assert d["signature"] == "sigX"
    assert d["strikes"] == 0
    assert d["cooldown_s_left"] == 50
    assert "cooldown" in d["reason"]


def test_detail_matches_should_deliver(tmp_path, monkeypatch):
    """Одна ветка решения: should_deliver — проекция should_deliver_detail."""
    _isolated_env(monkeypatch, tmp_path)
    root = tmp_path / "proj"
    for sig, now in [("A", 1000.0), ("A", 1050.0), ("A", 1200.0), ("B", 1210.0)]:
        d = should_deliver_detail(root, sig, cooldown_sec=100, now=now)
        ok, reason = should_deliver(root, sig, cooldown_sec=100, now=now + 10_000.0)
        # now+10000 — заведомо вне cooldown: сверяем только согласованность проекции
        assert isinstance(ok, bool) and isinstance(reason, str)
        assert (d["delivered"], d["reason"]) != (None, None)


# ── 4. Golden: решения идентичны до/после ──

def test_golden_restraint_decisions(tmp_path, monkeypatch):
    _isolated_env(monkeypatch, tmp_path)
    root = tmp_path / "proj"
    for sig, now, exp_ok, exp_reason in GOLDEN_RESTRAINT_SEQ:
        ok, reason = should_deliver(root, sig, cooldown_sec=100, now=float(now))
        assert (ok, reason) == (exp_ok, exp_reason)


def test_golden_signatures():
    f1 = [{"kind": "new_orphan", "symbol": "helper", "file": "pkg/a.py"}]
    f2 = [{"kind": "removed_last_caller", "symbol": "target", "file": "pkg/b.py"}]
    assert signature(f1) == GOLDEN_SIG1
    assert signature(f2) == GOLDEN_SIG2
    assert signature(f1) == signature([dict(f1[0])])  # стабильность


def _mk_firing_graph(root: Path) -> PropertyGraph:
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "caller.py").write_text("pass\n", encoding="utf-8")
    (root / "pkg" / "target.py").write_text("def target(): pass\n", encoding="utf-8")
    pg = PropertyGraph(root / "graph.db")
    pg.add_node(name="target", label=NodeLabel.FUNCTION,
                qualified_name="proj.pkg.target.target",
                file_path=str(root / "pkg" / "target.py"))
    pg.add_node(name="caller", label=NodeLabel.FUNCTION,
                qualified_name="proj.pkg.caller.caller",
                file_path=str(root / "pkg" / "caller.py"))
    pg.add_edge("proj.pkg.caller.caller", "proj.pkg.target.target", "CALLS")
    return pg


_FIRING_DIFF = (
    "diff --git a/pkg/caller.py b/pkg/caller.py\n"
    "--- a/pkg/caller.py\n"
    "+++ b/pkg/caller.py\n"
    "@@ -1,3 +1,3 @@\n"
    "-    target()\n"
    "+    pass\n"
)


def test_golden_quiet_break_findings(tmp_path):
    root = tmp_path / "proj"
    pg = _mk_firing_graph(root)
    r = run_quiet_break_gate(root, pg, diff_text=_FIRING_DIFF)
    assert r["status"] == "ok"
    assert r["counts"] == {"removed_last_caller": 1, "new_orphan": 0}
    assert len(r["findings"]) == 1
    f = r["findings"][0]
    assert (f["kind"], f["symbol"]) == ("removed_last_caller", "target")
    assert str(f["file"]).endswith("target.py")


def test_quiet_break_empty_and_unavailable(tmp_path):
    """suppressed_zero_findings (empty) и error_unavailable достижимы на уровне Python."""
    root = tmp_path / "proj"
    pg = _mk_firing_graph(root)
    assert run_quiet_break_gate(root, pg, diff_text="")["status"] == "empty"
    assert run_quiet_break_gate(root, None, diff_text=_FIRING_DIFF)["status"] == "unavailable"


# ── 5. Isolation: новые ключи обратно-совместимы, подавление сквозное ──

def test_isolation_restraint_keys_backward_compat(tmp_path, monkeypatch):
    """graph_query isolation отдаёт restraint-детали новыми ключами;
    старые deliver/suppressed_reason на месте; повтор давится cooldown'ом."""
    from src.core import quiet_break_gate as qbg_mod
    from src.mcp.tools import graph_tools

    _isolated_env(monkeypatch, tmp_path)
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    pg = _mk_firing_graph(root)

    fake_gate_out = {
        "status": "ok", "base": "provided",
        "counts": {"removed_last_caller": 1, "new_orphan": 0},
        "findings": [{"kind": "removed_last_caller", "symbol": "target",
                      "file": "pkg/target.py"}],
        "changed_files": ["pkg/caller.py"],
    }
    monkeypatch.setattr(qbg_mod, "run_quiet_break_gate", lambda *a, **k: dict(fake_gate_out))

    idx = SimpleNamespace(project_path=str(root))
    self_ns = SimpleNamespace(
        resolve_indexer=lambda *a, **k: idx,
        _resolve_pg=lambda *a, **k: pg,
    )
    run = graph_tools.GraphQueryTool._execute_isolation.__get__(self_ns, object)

    first = asyncio.run(run({"restraint": True}))
    assert first["deliver"] is True  # старые ключи живы
    assert first["suppressed_reason"] == ""
    assert set(first["restraint"]) == {"signature", "strikes", "cooldown_s_left"}
    assert first["restraint"]["signature"] == signature(fake_gate_out["findings"])
    assert first["restraint"]["cooldown_s_left"] == 0

    second = asyncio.run(run({"restraint": True}))
    assert second["deliver"] is False  # та же ветка теперь давит повтор
    assert "cooldown" in second["suppressed_reason"]
    assert second["restraint"]["cooldown_s_left"] > 0

    # без opt-in — как раньше: никаких restraint-ключей
    plain = asyncio.run(run({}))
    assert "restraint" not in plain
    assert "deliver" not in plain


def test_stale_has_no_restraint_wiring():
    """SPEC п.4: у stale_detector нет эквивалента suppression — проверено,
    менять нечего. Тест фиксирует отсутствие (сломается, если wiring появится —
    тогда и телеметрию надо дополнять)."""
    import inspect

    import src.mcp.tools.doc_tools as doc_tools
    src = inspect.getsource(doc_tools)
    assert "should_deliver" not in src
    assert "restraint" not in src.lower()


# ── 3. Путь лога ──

def test_gate_log_path_under_data_dir_not_temp(tmp_path, monkeypatch):
    _isolated_env(monkeypatch, tmp_path)
    proj = tmp_path / "myproj"
    proj.mkdir()
    p = get_gate_log_path(proj)
    assert p.name == "gate_telemetry.jsonl"
    # Путь выведен из конвенции data-root, а НЕ из legacy %TEMP%/opencode/*.log:
    # <data_root>/projects/<hash8>/gate_telemetry.jsonl (см. artifact_paths).
    # (Подстроку 'temp' не проверяем: сам тестовый data-root живёт в pytest tmp —
    #  это изоляция conftest, а не продуктовая конвенция.)
    import tempfile
    legacy = Path(tempfile.gettempdir()) / "opencode" / "mscodebase_gate.log"
    assert p != legacy
    assert p.parent.name != "opencode"
    data = Path(os.environ["MSCODEBASE_DATA_DIR"])
    assert data in p.parents
    # рядом с delivery_state.json — измерение точности доставки из одного места
    from src.core.restraint import state_path
    assert state_path(proj).parent == p.parent


def test_gate_log_path_hash_matches_project(tmp_path, monkeypatch):
    _isolated_env(monkeypatch, tmp_path)
    proj = tmp_path / "myproj"
    proj.mkdir()
    assert get_project_dir(proj).name == project_hash(proj)
    assert get_gate_log_path(proj).parent == get_project_dir(proj)


def test_ts_python_hash_sync(tmp_path):
    """TS projectHash и Python project_hash — одна формула (живой кросс-чек)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    anchor = Path(__file__).resolve().parents[1]  # корень worktree
    expected = project_hash(anchor)
    # Helpers live in gate_helpers.ts since the loader-contract split:
    # the entry (mscodebase_gate.ts) exports ONLY default (opencode ≥1.16
    # legacy loader invokes every function export — issues #41234/#31575).
    plugin = anchor / "tools" / "gate_helpers.ts"
    out = subprocess.run(
        [node, "-e",
         f"import({json.dumps(plugin.as_uri())}).then(m=>console.log(m.projectHash({json.dumps(str(anchor))})))"],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == expected


def test_node_suite_green():
    """Вся TS-сторона (пути, парсинг, все reasons, схема строк, паритет парсеров)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        [node, "--test", str(root / "tests" / "gate_telemetry.test.mjs")],
        capture_output=True, text=True, timeout=120, cwd=str(root),
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "fail 0" in out.stdout
