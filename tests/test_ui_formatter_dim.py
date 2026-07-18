"""
Test: ui_formatter.format_runtime_status must show real embedding dimension
from model_info (top-level in data), not default 768.

Regression test for bug (2026-07-18): intel_get_runtime_status showed
ONNX (768dim) instead of multilingual-e5-small-int8 (384dim) because
ui_formatter looked for model_info inside provider_status.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.ui_formatter import format_runtime_status


def test_format_runtime_status_shows_real_dimension():
    """format_runtime_status must use dimension from model_info (top-level)."""
    data = {
        "embedding_provider": "onnx",
        "provider_status": {
            "onnx_local_engine": "loaded_and_ready",
            "lm_studio_at_1234": "offline",
            "ollama_at_11434": "offline",
        },
        # model_info is at TOP level (not inside provider_status)
        "model_info": {
            "provider": "onnx",
            "model": "multilingual-e5-small-int8",
            "dimension": 384,
        },
        "index_telemetry": {
            "total_chunks": 3765,
            "unique_files": 256,
            "symbol_index_count": 4799,
        },
    }
    result = format_runtime_status(data)
    # Must show 384dim, NOT 768dim
    assert "384dim" in result, f"Expected 384dim in output, got:\n{result}"
    assert "768dim" not in result, f"Found wrong 768dim in output:\n{result}"
    assert "multilingual-e5-small-int8" in result


def test_format_runtime_status_fallback_to_768_when_no_model_info():
    """If model_info missing, fallback to 768 (legacy behavior)."""
    data = {
        "embedding_provider": "onnx",
        "provider_status": {
            "onnx_local_engine": "loaded_and_ready",
        },
        "index_telemetry": {
            "total_chunks": 100,
            "unique_files": 10,
        },
    }
    result = format_runtime_status(data)
    assert "768dim" in result, f"Expected fallback 768dim, got:\n{result}"


if __name__ == "__main__":
    test_format_runtime_status_shows_real_dimension()
    test_format_runtime_status_fallback_to_768_when_no_model_info()
    print("All tests passed")
