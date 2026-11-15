"""ONNX server pads per batch, not to a fixed 512 (dense-build perf, 2026-11-12).

Measured before the fix: every 32-text batch took 6-8 s whether texts were 30
or 2000 chars, because the tokenizer padded all of them to 512 tokens. The
indexer sorts chunks by length, so a per-batch maximum is nearly the exact
length and removes the waste.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from src.core.embedder.onnx_server import OnnxHandler


class _FakeSession:
    def __init__(self):
        self.seen_seq_len = None
        self.seen_batch = None

    def run(self, _outputs, inputs):
        self.seen_batch, self.seen_seq_len = inputs["input_ids"].shape
        return [np.zeros((self.seen_batch, self.seen_seq_len, 384), dtype=np.float32)]


def _handler(ids_list):
    handler = OnnxHandler.__new__(OnnxHandler)
    encodings = [
        SimpleNamespace(ids=ids, attention_mask=[1] * len(ids)) for ids in ids_list
    ]
    handler.server = SimpleNamespace(
        session=_FakeSession(),
        tokenizer=SimpleNamespace(encode_batch=lambda _texts, add_special_tokens: encodings),
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        max_length=512,
    )
    return handler


def test_batch_pads_to_the_longest_text_not_to_512():
    handler = _handler([[1, 2, 3], [4] * 40, [5] * 7])
    handler._embed_batch(["a", "b", "c"])
    assert handler.server.session.seen_seq_len == 40, (
        "batch must be padded to its own maximum length, not 512"
    )
    assert handler.server.session.seen_batch == 3


def test_batch_truncates_at_max_length():
    handler = _handler([[1] * 900])
    handler._embed_batch(["long"])
    assert handler.server.session.seen_seq_len == 512


def test_fixed_padding_toggle_restores_legacy_width(monkeypatch):
    monkeypatch.setenv("ONNX_FIXED_PADDING", "512")
    handler = _handler([[1, 2, 3], [4] * 40])
    handler._embed_batch(["a", "b"])
    assert handler.server.session.seen_seq_len == 512, (
        "ONNX_FIXED_PADDING=512 must restore the old 512-wide inputs"
    )
