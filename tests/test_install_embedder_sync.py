"""
CI test: install.py model slug must be consistent with what
remote_embedder._detect_model_dir() looks for (INT8 models).

Prevents regression of INC-INSTALL (2026-07-18): install.py was
downloading e5-base-v2-int8 while runtime expected multilingual-e5-small-int8.
"""

import pytest


class TestInstallEmbedderSync:
    """Verify install.py and remote_embedder.py agree on the embedder model."""

    def test_install_has_int8_embedder_slug(self):
        """install.py step_models must define at least one INT8 embedder slug."""
        import importlib
        import sys

        # Import install.py as a module
        spec = importlib.util.spec_from_file_location(
            "install_module", "install.py"
        )
        install = importlib.util.module_from_spec(spec)
        # Prevent install.py from running main() on import
        sys.argv = ["install.py", "--skip-models"]
        spec.loader.exec_module(install)

        # Find the models dict in step_models
        # It maps slug -> (hf_repo, type, size_mb)
        # We need to check that at least one embedding slug contains "int8"
        # This is a structural check — if someone changes the model,
        # they must keep the int8 convention.
        # We can't easily extract the dict without running step_models,
        # so we check the source text instead.
        import inspect
        source = inspect.getsource(install)

        # The models dict in step_models should have an int8 slug
        assert "int8" in source, (
            "install.py must have at least one INT8 embedder slug "
            "in step_models models dict"
        )

    def test_install_slug_matches_known_model(self):
        """install.py embedder slug must be 'multilingual-e5-small-int8'."""
        with open("install.py", encoding="utf-8") as f:
            source = f.read()

        # The current active model slug
        assert "multilingual-e5-small-int8" in source, (
            "install.py must reference 'multilingual-e5-small-int8' "
            "as the embedder model slug"
        )

        # The HF repo for the active model
        assert "keisuke-miyako/multilingual-e5-small-onnx-int8" in source, (
            "install.py must reference the correct HF repo "
            "'keisuke-miyako/multilingual-e5-small-onnx-int8'"
        )

    def test_remote_embedder_prefers_int8(self):
        """remote_embedder._detect_model_dir() must prefer INT8 models."""
        with open("src/providers/embedder/remote_embedder.py", encoding="utf-8") as f:
            source = f.read()

        # _detect_model_dir sorts with INT8 first
        assert "'-int8'" in source or '"-int8"' in source, (
            "remote_embedder._detect_model_dir() must sort INT8 models first"
        )

        # Must look for model_quantized.onnx (INT8 filename)
        assert "model_quantized.onnx" in source, (
            "remote_embedder must look for model_quantized.onnx (INT8)"
        )
