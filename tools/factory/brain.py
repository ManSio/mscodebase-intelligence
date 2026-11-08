"""Ephemeral single-action worker: one call, one action, the call dies.

There is no agent loop here. For one primitive node we make exactly one HTTP
call to an OpenAI-compatible endpoint, carrying:

  * a system prompt of ~50-70 tokens: which one operator, which parameter
    names, "JSON only";
  * a bounded brief: the goal, the last observation digest, the allowed paths.

The model returns arguments for that one operator. The call is not resumable,
holds no history, and is thrown away. The harness executes the operator and
moves on — so the cost per action is (system + brief), not a growing transcript.

Budgets are enforced before the call: if the brief would exceed `max_prompt_chars`
it is shrunk; if the operator is unknown the call is not made at all.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from ops import BY_NAME

SYSTEM_TMPL = (
    "You are one action. Operator: {name}. Parameters: {params}. "
    "Return JSON only: {{\"args\": {{{arg_keys}}}}}. No prose, no markdown."
)


class BrainError(RuntimeError):
    pass


@dataclass
class CallRecord:
    node: str
    op: str
    prompt_chars: int
    prompt_tokens_est: int
    completion_tokens: int | None
    latency_s: float
    args: dict | None
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "node": self.node,
            "op": self.op,
            "prompt_chars": self.prompt_chars,
            "prompt_tokens_est": self.prompt_tokens_est,
            "completion_tokens": self.completion_tokens,
            "latency_s": round(self.latency_s, 2),
            "args": self.args,
            "error": self.error,
        }


def system_prompt(op_name: str) -> str:
    spec = BY_NAME[op_name]
    return SYSTEM_TMPL.format(name=op_name, params=", ".join(spec.params),
                              arg_keys=", ".join(f'"{p}": ...' for p in spec.params))


def user_brief(goal: str, last_digest: str, max_chars: int = 600) -> str:
    text = f"goal: {goal}\nlast: {last_digest}".strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


def _post(endpoint: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise BrainError(f"no JSON in the answer: {text[:120]!r}")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise BrainError(f"bad JSON: {exc}") from exc
    if isinstance(data, dict) and "args" in data:
        return dict(data["args"] or {})
    if isinstance(data, dict):
        return data
    raise BrainError("the answer is not an object")


def decide(*, endpoint: str, model: str, node_id: str, op: str, goal: str,
           last_digest: str, timeout: int = 180, max_tokens: int = 160,
           max_prompt_chars: int = 1000) -> tuple[dict, CallRecord]:
    """Exactly one stateless call. Returns (args, record)."""
    import time

    if op not in BY_NAME:
        raise BrainError(f"unknown operator: {op}")
    system = system_prompt(op)
    user = user_brief(goal, last_digest, max_prompt_chars - len(system))
    prompt_chars = len(system) + len(user)

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }

    t0 = time.time()
    try:
        resp = _post(endpoint, payload, timeout)
    except Exception as exc:  # noqa: BLE001
        record = CallRecord(node_id, op, prompt_chars, prompt_chars // 4, None,
                            time.time() - t0, None, f"{type(exc).__name__}: {exc}")
        return {}, record

    usage = resp.get("usage") or {}
    message = (resp.get("choices") or [{}])[0].get("message") or {}
    raw = message.get("content") or ""
    try:
        args = _extract_json(raw)
        spec = BY_NAME[op]
        unknown = set(args) - set(spec.params)
        if unknown:
            raise BrainError(f"unknown arguments {sorted(unknown)} for {op}")
    except BrainError as exc:
        record = CallRecord(node_id, op, prompt_chars, prompt_chars // 4,
                            usage.get("completion_tokens"), time.time() - t0, None, str(exc))
        return {}, record

    record = CallRecord(node_id, op, prompt_chars, prompt_chars // 4,
                        usage.get("completion_tokens"), time.time() - t0, args, None)
    return args, record


def probe_offline(node_id: str = "t1", op: str = "grep", goal: str = "найди ActionReceipt") -> dict:
    """Show the exact prompt and its size without any network call."""
    system = system_prompt(op)
    user = user_brief(goal, "(no previous observation)")
    return {
        "operator": op,
        "system": system,
        "system_tokens_est": len(system) // 4,
        "user": user,
        "user_tokens_est": len(user) // 4,
        "total_tokens_est": (len(system) + len(user)) // 4,
        "max_tokens_out": 160,
    }
