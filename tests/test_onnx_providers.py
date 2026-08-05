"""TEST-03 (audit): политика выбора ONNX execution providers (WIN-11).

MSCODEBASE_ONNX_PROVIDER=auto/cpu/dml/cuda — тест на чистую функцию
select_onnx_providers (без реального onnxruntime).
"""

from src.core.embedder.onnx_server import select_onnx_providers

_DML = "DmlExecutionProvider"
_CPU = "CPUExecutionProvider"
_CUDA = "CUDAExecutionProvider"


def test_auto_prefers_dml_when_available():
    assert select_onnx_providers("auto", [_CPU, _DML]) == [_DML, _CPU]


def test_auto_no_dml_cpu_only():
    assert select_onnx_providers("auto", [_CPU]) == [_CPU]


def test_auto_ignores_cuda():
    assert select_onnx_providers("auto", [_CPU, _CUDA]) == [_CPU]


def test_cpu_forced_ignores_accelerators():
    assert select_onnx_providers("cpu", [_CPU, _DML, _CUDA]) == [_CPU]


def test_dml_present_used_first():
    assert select_onnx_providers("dml", [_CPU, _DML]) == [_DML, _CPU]


def test_dml_missing_fallback_cpu():
    assert select_onnx_providers("dml", [_CPU]) == [_CPU]


def test_cuda_present_used_first():
    assert select_onnx_providers("cuda", [_CPU, _CUDA]) == [_CUDA, _CPU]


def test_cuda_missing_fallback_cpu():
    assert select_onnx_providers("cuda", [_CPU]) == [_CPU]


def test_empty_available_returns_cpu():
    assert select_onnx_providers("auto", []) == [_CPU]
