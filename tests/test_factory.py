"""Tests for the factory: the gate, the rule brain, the journal, the replay check."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "factory"))

from ops import BY_NAME, OpError, op_grep  # noqa: E402
from plan import flatten, from_dict, resolve, rule_plan, validate  # noqa: E402
from runtime import Budget, Journal, run_plan, verify  # noqa: E402


def test_rule_plan_find_then_test():
    root = rule_plan("найди ActionReceipt затем запусти тесты tests/test_write_tools.py")
    prims = flatten(root)
    assert [n.op for n in prims] == ["grep", "read", "run"]
    assert prims[1].args["path"] == "$t1.hits.0.file"
    assert validate(root) == []


def test_gate_rejects_unknown_operator():
    node = from_dict({"id": "root", "kind": "compound", "children": [
        {"id": "t1", "kind": "primitive", "op": "rm_rf", "args": {}}]})
    assert any("unknown operator" in e for e in validate(node))


def test_gate_rejects_forward_reference():
    node = from_dict({"id": "root", "kind": "compound", "children": [
        {"id": "t1", "kind": "primitive", "op": "read",
         "args": {"path": "$t2.hits.0.file"}},
        {"id": "t2", "kind": "primitive", "op": "grep", "args": {"pattern": "x"}}]})
    assert any("not an earlier node" in e for e in validate(node))


def test_gate_rejects_unknown_arg():
    node = from_dict({"id": "root", "kind": "compound", "children": [
        {"id": "t1", "kind": "primitive", "op": "grep", "args": {"pattern": "x", "nope": 1}}]})
    assert any("unknown args" in e for e in validate(node))


def test_gate_rejects_empty_compound():
    node = from_dict({"id": "root", "kind": "compound", "children": []})
    assert any("without children" in e for e in validate(node))


def test_shell_allowlist_blocks_arbitrary_commands(tmp_path):
    with pytest.raises(OpError):
        BY_NAME["run"].fn(tmp_path, {"cmd": "del /q *"})


def test_write_cannot_escape_repo(tmp_path):
    with pytest.raises(OpError):
        BY_NAME["write"].fn(tmp_path, {"path": "../escaped.txt", "content": "x"})


def test_grep_excludes_build_and_factory(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "copy.py").write_text("TARGET = 1\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text("TARGET = 1\n", encoding="utf-8")
    out = op_grep(tmp_path, {"pattern": "TARGET"})
    assert [h["file"] for h in out["hits"]] == ["src/real.py"]


def test_resolve_dotted_reference():
    results = {"t1": {"hits": [{"file": "a.py", "line": 7}]}}
    assert resolve({"path": "$t1.hits.0.file", "start": "$t1.hits.0.line"}, results) == {
        "path": "a.py", "start": 7}


def test_run_and_verify_pass(tmp_path):
    (tmp_path / "a.py").write_text("VALUE = 42\n", encoding="utf-8")
    root = from_dict({"id": "root", "kind": "compound", "children": [
        {"id": "t1", "kind": "primitive", "op": "grep", "args": {"pattern": "VALUE"}},
        {"id": "t2", "kind": "primitive", "op": "read",
         "args": {"path": "$t1.hits.0.file", "start": "$t1.hits.0.line"}},
    ]})
    journal = tmp_path / "j.jsonl"
    out = run_plan(root, tmp_path, journal, Budget())
    assert out["status"] == "ok" and out["steps"] == 2
    report = verify(journal, tmp_path)
    assert report["verdict"] == "PASS" and report["chain_ok"] is True
    assert all(n["verdict"] == "replayed-match" for n in report["nodes"])


def test_verify_detects_tampering(tmp_path):
    (tmp_path / "a.py").write_text("VALUE = 42\n", encoding="utf-8")
    root = from_dict({"id": "root", "kind": "compound", "children": [
        {"id": "t1", "kind": "primitive", "op": "read", "args": {"path": "a.py"}},
    ]})
    journal = tmp_path / "j.jsonl"
    run_plan(root, tmp_path, journal, Budget())
    lines = journal.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[0])
    rec["args"]["path"] = "b.py"          # tamper after the fact
    journal.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    report = verify(journal, tmp_path)
    assert report["verdict"] == "FAIL" and report["chain_ok"] is False


def test_verify_detects_artifact_change(tmp_path):
    target = tmp_path / "out.txt"
    root = from_dict({"id": "root", "kind": "compound", "children": [
        {"id": "t1", "kind": "primitive", "op": "write", "args": {"path": "out.txt", "content": "hello"}},
    ]})
    journal = tmp_path / "j.jsonl"
    run_plan(root, tmp_path, journal, Budget())
    assert verify(journal, tmp_path)["verdict"] == "PASS"
    target.write_text("changed\n", encoding="utf-8")
    report = verify(journal, tmp_path)
    assert report["verdict"] == "FAIL"
    assert report["nodes"][0]["verdict"] == "artifact-MISMATCH"


def test_budget_stops_the_run(tmp_path):
    (tmp_path / "a.py").write_text("X = 1\n", encoding="utf-8")
    root = from_dict({"id": "root", "kind": "compound", "children": [
        {"id": "t1", "kind": "primitive", "op": "read", "args": {"path": "a.py"}},
        {"id": "t2", "kind": "primitive", "op": "read", "args": {"path": "a.py"}},
    ]})
    out = run_plan(root, tmp_path, tmp_path / "j.jsonl", Budget(max_steps=1))
    assert out["status"] == "budget" and out["steps"] == 1


def test_journal_chain_links(tmp_path):
    journal = Journal(tmp_path / "j.jsonl")
    a = journal.append(node="t1", op="grep", args={"pattern": "x"}, status="ok",
                       result={"hits": []}, error=None, duration_ms=1)
    b = journal.append(node="t2", op="grep", args={"pattern": "y"}, status="ok",
                       result={"hits": []}, error=None, duration_ms=1)
    assert b["prev"] == a["hash"] and b["seq"] == 2

# ---------------------------------------------------------------- ephemeral brain

import json as _json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import brain as brain_mod


class _Stub(BaseHTTPRequestHandler):
    reply = {"args": {"pattern": "ActionReceipt"}}
    last_chars = 0

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = _json.loads(self.rfile.read(length))
        chars = sum(len(m.get("content") or "") for m in body.get("messages", []))
        type(self).last_chars = chars
        payload = _json.dumps({
            "choices": [{"message": {"content": _json.dumps(type(self).reply)}}],
            "usage": {"prompt_tokens": chars // 4, "completion_tokens": 12},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence
        pass


@pytest.fixture()
def stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", _Stub
    server.shutdown()


def test_single_action_prompt_is_small():
    probe = brain_mod.probe_offline(op="grep", goal="найди ActionReceipt")
    assert probe["system_tokens_est"] < 80
    assert probe["total_tokens_est"] < 200


def test_one_call_returns_args(stub):
    endpoint, handler = stub
    args, rec = brain_mod.decide(endpoint=endpoint, model="stub", node_id="t1", op="grep",
                                 goal="найди ActionReceipt", last_digest="")
    assert args == {"pattern": "ActionReceipt"}
    assert rec.error is None
    assert rec.prompt_tokens_est < 200
    assert rec.completion_tokens == 12


def test_one_call_rejects_unknown_args(stub):
    endpoint, handler = stub
    handler.reply = {"args": {"zzz": 1}}
    args, rec = brain_mod.decide(endpoint=endpoint, model="stub", node_id="t1", op="grep",
                                 goal="x", last_digest="")
    assert args == {}
    assert "unknown arguments" in (rec.error or "")
    handler.reply = {"args": {"pattern": "ActionReceipt"}}


def test_run_with_decider_makes_one_call_per_empty_node(tmp_path, stub):
    endpoint, _ = stub
    (tmp_path / "a.py").write_text("ActionReceipt = 1\n", encoding="utf-8")
    root = from_dict({"id": "root", "kind": "compound", "children": [
        {"id": "t1", "kind": "primitive", "op": "grep", "args": {}},
        {"id": "t2", "kind": "primitive", "op": "read",
         "args": {"path": "$t1.hits.0.file", "start": "$t1.hits.0.line"}},
    ]})
    calls = []

    def decider(node, last_digest):
        calls.append(node.id)
        return brain_mod.decide(endpoint=endpoint, model="stub", node_id=node.id, op=node.op,
                                goal="найди ActionReceipt", last_digest=last_digest)

    out = run_plan(root, tmp_path, tmp_path / "j.jsonl", Budget(), decider=decider)
    assert out["status"] == "ok" and out["steps"] == 2
    assert calls == ["t1"]                      # exactly one model call, for the only undecided node
    assert len(out["brain_calls"]) == 1
    assert verify(tmp_path / "j.jsonl", tmp_path)["verdict"] == "PASS"
