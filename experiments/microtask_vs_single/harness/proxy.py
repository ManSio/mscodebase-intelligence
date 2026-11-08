"""Transparent proxy in front of the Tīrtha API.

Two jobs:
1. ENFORCEMENT — the Tīrtha extensions `tirtha.mode=low` and
   `tirtha.no_cache=true` are written into every request body, so the
   treatment does not depend on whether OpenCode propagates model options.
2. MEASUREMENT — per request it records the response metadata that OpenCode
   hides: `tirtha.served_by`, `checked`, `checked_by`, `escalated`, `mode`,
   and the token usage.

It never stores credentials or prompt content: only metadata, usage, and a
hash of the request body. The upstream key lives in memory only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_UPSTREAM = "https://api.tirtha.ai"
KEY_RE = re.compile(r'"apiKey"\s*:\s*"([^"]+)"')


def read_tirtha_key() -> str:
    import os

    env_key = os.environ.get("TIRTHA_API_KEY")
    if env_key:
        return env_key
    config = Path.home() / ".config" / "opencode" / "opencode.jsonc"
    if not config.is_file():
        raise RuntimeError("TIRTHA_API_KEY is not set and the global config was not found")
    match = KEY_RE.search(config.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError("no apiKey found in the global opencode config")
    return match.group(1)


class Recorder:
    def __init__(self) -> None:
        self.records: list[dict] = []
        self._lock = threading.Lock()
        self.usd = 0.0

    def add(self, record: dict) -> None:
        cost = float((record.get("tirtha") or {}).get("cheap_cost_usd") or 0.0) + float(
            (record.get("tirtha") or {}).get("value_cost_measured_usd") or 0.0
        )
        with self._lock:
            self.records.append(record)
            self.usd += cost

    def dump(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for record in self.records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")


class BudgetExceeded(Exception):
    pass


def enforce(body: dict) -> dict:
    """Write the treatment into the request body."""
    body = dict(body)
    tirtha = dict(body.get("tirtha") or {})
    tirtha["mode"] = "low"
    tirtha["no_cache"] = True
    body["tirtha"] = tirtha
    return body


def _usage_from_sse(raw: bytes) -> dict:
    usage: dict = {}
    for line in raw.split(b"\n"):
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if payload == b"[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("usage"), dict):
            usage = obj["usage"]
    return usage


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "microtask-proxy/0.1"

    def log_message(self, *args) -> None:  # silence stderr noise
        return

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001
        """Client-side disconnects are normal here (streamed answers)."""
        return

    def do_GET(self) -> None:
        self._forward(b"")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        self._forward(raw)

    def _forward(self, raw: bytes) -> None:
        started = time.monotonic()
        upstream = self.server.upstream  # type: ignore[attr-defined]
        key = self.server.api_key  # type: ignore[attr-defined]
        recorder = self.server.recorder  # type: ignore[attr-defined]
        path = self.path

        # COST GUARD: one runaway session once cost $3.05 and 30M tokens.
        # The guard answers 429 before the request is forwarded, so the run
        # ends instead of draining the credit balance.
        max_requests = self.server.max_requests  # type: ignore[attr-defined]
        budget_usd = self.server.budget_usd  # type: ignore[attr-defined]
        if max_requests and len(recorder.records) >= max_requests:
            self._refuse("request_budget_exceeded", f"{len(recorder.records)} requests")
            return
        if budget_usd and recorder.usd >= budget_usd:
            self._refuse("cost_budget_exceeded", f"${recorder.usd:.4f} spent")
            return


        request_body: dict = {}
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
                if isinstance(parsed, dict):
                    request_body = parsed
            except (json.JSONDecodeError, UnicodeDecodeError):
                request_body = {}

        body_hash = hashlib.sha256(raw).hexdigest() if raw else ""
        enforced = False
        if request_body:
            request_body = enforce(request_body)
            raw = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
            enforced = True

        url = upstream.rstrip("/") + path
        headers = {
            key_name: value
            for key_name, value in self.headers.items()
            if key_name.lower() not in {"host", "content-length", "authorization", "accept-encoding"}
        }
        headers["Authorization"] = f"Bearer {key}"
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(raw))

        record: dict = {
            "t_start": started,
            "path": path,
            "method": self.command,
            "model": request_body.get("model"),
            "stream": bool(request_body.get("stream")),
            "tools_count": len(request_body.get("tools") or []),
            "messages_count": len(request_body.get("messages") or []),
            "enforced": enforced,
            "tirtha_sent": (request_body.get("tirtha") if enforced else None),
            "body_sha256": body_hash,
        }

        request = urllib.request.Request(url, data=raw or None, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                content_type = response.headers.get("Content-Type", "")
                status = response.status
                if "text/event-stream" in content_type:
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    collected = bytearray()
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        collected.extend(chunk)
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                        self.wfile.flush()
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                    usage = _usage_from_sse(bytes(collected))
                    meta = self._tirtha_meta_from_sse(bytes(collected))
                else:
                    payload = response.read()
                    self.send_response(status)
                    self.send_header("Content-Type", content_type or "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    usage = {}
                    meta = {}
                    try:
                        parsed = json.loads(payload.decode("utf-8"))
                        if isinstance(parsed, dict):
                            usage = parsed.get("usage") or {}
                            meta = parsed.get("tirtha") or {}
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            record.update({"status": exc.code, "error": payload[:400].decode("utf-8", "replace")})
            record["duration_s"] = round(time.monotonic() - started, 3)
            recorder.add(record)
            return
        except Exception as exc:  # noqa: BLE001 - the proxy must report, not die
            record.update({"status": 0, "error": f"{type(exc).__name__}: {exc}"})
            record["duration_s"] = round(time.monotonic() - started, 3)
            recorder.add(record)
            self.send_response(502)
            payload = json.dumps({"error": {"type": "proxy_error", "message": str(exc)}}).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        record.update(
            {
                "status": status,
                "usage": usage,
                "tirtha": meta,
                "duration_s": round(time.monotonic() - started, 3),
            }
        )
        recorder.add(record)

    def _refuse(self, kind: str, detail: str) -> None:
        payload = json.dumps(
            {"error": {"type": kind, "message": f"harness budget guard: {detail}"}}
        ).encode("utf-8")
        self.send_response(429)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    @staticmethod
    def _tirtha_meta_from_sse(raw: bytes) -> dict:
        meta: dict = {}
        for line in raw.split(b"\n"):
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("tirtha"), dict):
                meta = obj["tirtha"]
        return meta


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001
        """Client disconnects are normal (streamed answers); stay quiet."""
        return


class Proxy:
    def __init__(
        self,
        upstream: str,
        api_key: str,
        budget_usd: float | None = None,
        max_requests: int | None = None,
    ) -> None:
        self.recorder = Recorder()
        self.server = ProxyServer(("127.0.0.1", 0), ProxyHandler)
        self.server.upstream = upstream  # type: ignore[attr-defined]
        self.server.api_key = api_key  # type: ignore[attr-defined]
        self.server.recorder = self.recorder  # type: ignore[attr-defined]
        self.server.budget_usd = budget_usd  # type: ignore[attr-defined]
        self.server.max_requests = max_requests  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "Proxy":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()

    def dump(self, path: Path) -> None:
        self.recorder.dump(path)


def selftest() -> int:
    """Fake upstream: proves enforcement and capture without network or model."""
    from http.server import BaseHTTPRequestHandler

    seen: list[dict] = []

    class Fake(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            seen.append(json.loads(raw.decode("utf-8")))
            payload = json.dumps(
                {
                    "id": "chatcmpl-fake",
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
                    "tirtha": {
                        "served_by": "deepinfra",
                        "checked": True,
                        "checked_by": "schema",
                        "escalated": False,
                        "mode": "low",
                    },
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    fake_base = f"http://127.0.0.1:{fake.server_address[1]}"

    with Proxy(fake_base, "fake-key") as proxy:
        body = json.dumps({"model": "tirtha/auto", "messages": [{"role": "user", "content": "hi"}]})
        request = urllib.request.Request(
            proxy.base_url + "/v1/chat/completions",
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
        records = proxy.recorder.records

    if not seen:
        print("SELFTEST FAIL: fake upstream saw no request")
        return 1
    sent = seen[0]
    if sent.get("tirtha", {}).get("mode") != "low":
        print(f"SELFTEST FAIL: mode not enforced: {sent.get('tirtha')}")
        return 1
    if sent.get("tirtha", {}).get("no_cache") is not True:
        print(f"SELFTEST FAIL: no_cache not enforced: {sent.get('tirtha')}")
        return 1
    if not records:
        print("SELFTEST FAIL: no records captured")
        return 1
    record = records[0]
    if record.get("usage", {}).get("total_tokens") != 14:
        print(f"SELFTEST FAIL: usage not captured: {record.get('usage')}")
        return 1
    if record.get("tirtha", {}).get("served_by") != "deepinfra":
        print(f"SELSTEST FAIL: tirtha metadata not captured: {record.get('tirtha')}")
        return 1
    if "hi" in json.dumps(record):
        print("SELFTEST FAIL: prompt content leaked into the record")
        return 1

    # cost/request guard: after the cap the proxy refuses instead of spending
    with Proxy(fake_base, "fake-key", max_requests=1) as guarded:
        body = json.dumps({"model": "tirtha/auto", "messages": [{"role": "user", "content": "hi"}]})
        for attempt, expect in ((0, 200), (1, 429)):
            request = urllib.request.Request(
                guarded.base_url + "/v1/chat/completions",
                data=body.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    response.read()
                code = 200
            except urllib.error.HTTPError as exc:
                code = exc.code
            if code != expect:
                print(f"SELFTEST FAIL: guard attempt {attempt} answered {code}, expected {expect}")
                return 1

    fake.shutdown()
    fake.server_close()

    print(
        "SELFTEST: PASS (mode=low and no_cache enforced; usage and tirtha metadata captured; "
        "no prompt content stored; the request guard refuses at the cap)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--dump")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    with Proxy(DEFAULT_UPSTREAM, read_tirtha_key()) as proxy:
        print(f"proxy listening on {proxy.base_url} -> {DEFAULT_UPSTREAM}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        if args.dump:
            proxy.dump(Path(args.dump))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

