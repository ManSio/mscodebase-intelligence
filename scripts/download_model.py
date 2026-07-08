"""
Universal ONNX model downloader for MSCodeBase Intelligence.
Supports pre-quantized models (direct download, no export) and
full export pipeline (AutoModel/AutoModelForSequenceClassification).
"""

import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("download_model")

# ─── Model Registry ───────────────────────────────────────
MODEL_REGISTRY = {
    # Embedding models — with pre-quantized ONNX source where available
    "BAAI/bge-m3": {
        "dim": 1024,
        "type": "embedding",
        "size_mb": 570,
        "quality": "best",
        "onnx": "Xenova/bge-m3",
        "onnx_file": "onnx/model_quantized.onnx",
    },
    "BAAI/bge-base-en-v1.5": {
        "dim": 768,
        "type": "embedding",
        "size_mb": 150,
        "quality": "high",
    },
    "BAAI/bge-small-en-v1.5": {
        "dim": 384,
        "type": "embedding",
        "size_mb": 50,
        "quality": "good",
    },
    "intfloat/multilingual-e5-base": {
        "dim": 768,
        "type": "embedding",
        "size_mb": 250,
        "quality": "high",
    },
    "intfloat/multilingual-e5-small": {
        "dim": 384,
        "type": "embedding",
        "size_mb": 100,
        "quality": "good",
    },
    # Reranker models
    "BAAI/bge-reranker-v2-m3": {
        "dim": 1024,
        "type": "reranker",
        "size_mb": 570,
        "quality": "best",
        "onnx": "onnx-community/bge-reranker-v2-m3-ONNX",
        "onnx_file": "onnx/model_quantized.onnx",
    },
    "BAAI/bge-reranker-v2-base": {
        "dim": 768,
        "type": "reranker",
        "size_mb": 500,
        "quality": "high",
    },
}


# ─── Helpers ──────────────────────────────────────────────
def _get_cache_dir() -> Path:
    return Path.home() / ".cache" / "mscodebase" / "hf_models"


def _get_hf_cache_path(model_name: str) -> Path:
    slug = "models--" + model_name.replace("/", "--")
    return _get_cache_dir() / "hub" / slug


def _purge_hf_cache(model_name: str):
    p = _get_hf_cache_path(model_name)
    if p.exists():
        try:
            shutil.rmtree(p, ignore_errors=True)
        except:
            pass


# ─── Pre-quantized download (no torch/transformers needed) ───
def _download_prequantized(model_name: str, model_dir: Path, onnx_path: Path) -> bool:
    info = MODEL_REGISTRY.get(model_name)
    if not info or "onnx" not in info:
        return False

    if onnx_path.exists():
        logger.info(
            f"   ✅ ONNX already exists: {onnx_path.stat().st_size / 1024 / 1024:.0f} MB"
        )
        return True

    onnx_repo, onnx_file = info["onnx"], info["onnx_file"]
    logger.info(f"📥 Downloading pre-quantized ONNX: {onnx_repo}/{onnx_file}")
    model_dir.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import hf_hub_download

        dl = hf_hub_download(
            repo_id=onnx_repo,
            filename=onnx_file,
            local_dir=str(model_dir),
            local_dir_use_symlinks=False,
        )
        final = Path(dl)
        if final.name != "model.onnx":
            final.rename(onnx_path)
        sz = onnx_path.stat().st_size / 1024 / 1024
        logger.info(f"   ✅ Pre-quantized ONNX: {onnx_path} ({sz:.0f} MB)")
        return True
    except Exception as e:
        logger.warning(f"   ⚠️ Pre-quantized download failed: {e}")
        return False


# ─── Full export pipeline (torch + transformers) ───────────
def download_onnx_model(
    model_name: str,
    output_dir: Path,
    force=False,
    purge_cache=False,
    model_type="embedding",
):
    from transformers import (
        AutoModel,
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )

    onnx_dir = output_dir / "onnx"
    slug = model_name.split("/")[-1].replace(".", "-").lower()
    subdir = f"reranker-{slug}" if model_type == "reranker" else slug
    model_dir = onnx_dir / subdir
    onnx_path = onnx_dir / subdir / "model.onnx"

    # Step 1: Try pre-quantized download first
    if not force and _download_prequantized(model_name, model_dir, onnx_path):
        return

    # Step 2: Check existing ONNX
    if onnx_path.exists() and not force:
        logger.info(
            f"✅ ONNX already exists: {onnx_path} ({onnx_path.stat().st_size / 1024 / 1024:.0f} MB)"
        )
        return

    model_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = _get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"📥 Downloading & exporting {model_name} (type={model_type})...")
    if force:
        logger.info("   --force: re-export")

    model_class = (
        AutoModelForSequenceClassification if model_type == "reranker" else AutoModel
    )
    dummy_text = (
        ["тестовый запрос", "тестовый чанк"]
        if model_type == "reranker"
        else ["тестовый запрос"]
    )

    tokenizer = AutoTokenizer.from_pretrained(
        model_name, trust_remote_code=True, cache_dir=str(cache_dir)
    )
    model = model_class.from_pretrained(
        model_name, trust_remote_code=True, cache_dir=str(cache_dir)
    )
    model.eval()
    tokenizer.save_pretrained(str(model_dir))

    # Detect dimension
    hidden_size = getattr(model.config, "hidden_size", None)
    if not hidden_size:
        import torch

        with torch.no_grad():
            dummy = tokenizer(
                dummy_text, return_tensors="pt", padding=True, truncation=True
            )
            out = (
                model(**dummy)
                if model_type == "reranker"
                else model(**dummy).last_hidden_state
            )
            hidden_size = out.shape[-1] if hasattr(out, "shape") else 1024

    # Export to ONNX
    import torch

    dummy_input = tokenizer(
        dummy_text, return_tensors="pt", padding=True, truncation=True, max_length=512
    )
    torch.onnx.export(
        model,
        (dummy_input["input_ids"], dummy_input["attention_mask"]),
        str(onnx_path),
        input_names=["input_ids", "attention_mask"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "last_hidden_state": {0: "batch", 1: "seq"},
        },
        opset_version=14,
    )
    logger.info(
        f"   ✅ ONNX float32: {onnx_path} ({onnx_path.stat().st_size / 1024 / 1024:.0f} MB)"
    )

    # Quantize to int8
    if model_type == "embedding":
        try:
            from onnxruntime.quantization import QuantType, quantize_dynamic

            q_path = str(onnx_path).replace(".onnx", "_int8.onnx")
            quantize_dynamic(
                str(onnx_path),
                q_path,
                weight_type=QuantType.QUInt8,
                op_types_to_quantize=["MatMul", "Add", "Gemm"],
                per_channel=True,
            )
            if onnx_path.with_suffix(".onnx.data").exists():
                os.remove(str(onnx_path.with_suffix(".onnx.data")))
            os.remove(str(onnx_path))
            os.rename(q_path, str(onnx_path))
            q_mb = os.path.getsize(str(onnx_path)) / 1024 / 1024
            logger.info(f"   ✅ ONNX int8: {onnx_path} ({q_mb:.0f} MB)")
        except Exception as qe:
            logger.warning(f"   ⚠️ Quantization failed: {qe}. Keeping float32.")

    # Cleanup
    if purge_cache:
        _purge_hf_cache(model_name)
        if hasattr(Path.home(), ".cache"):
            import glob

            for d in [
                Path.home() / ".cache" / "huggingface" / "hub",
                Path.home() / ".cache" / "torch",
            ]:
                if d.exists():
                    shutil.rmtree(str(d), ignore_errors=True)
        logger.info("   All caches cleaned")
    else:
        logger.info(f"   HF cache kept: {_get_cache_dir()}")

    logger.info(f"✅ Model saved to {model_dir}")
    logger.info(
        f"   ONNX: {onnx_path} ({onnx_path.stat().st_size / 1024 / 1024:.0f} MB, {hidden_size}dim)"
    )


# ─── CLI ──────────────────────────────────────────────────
def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Universal ONNX model downloader")
        print()
        print("Usage:")
        print("  python download_model.py")
        print("  python download_model.py --model BAAI/bge-m3")
        print("  python download_model.py --size light")
        print(
            "  python download_model.py --model BAAI/bge-reranker-v2-m3 --type reranker"
        )
        print("  python download_model.py --force --auto-clean")
        print()
        print("Size presets (for embedding):")
        print("  light    — bge-small-en-v1.5 (384dim, ~50 MB)")
        print("  balanced — bge-base-en-v1.5  (768dim, ~150 MB)  [default]")
        print("  full     — bge-m3             (1024dim, ~570 MB)")
        print()
        print("Available models:")
        for name, info in sorted(MODEL_REGISTRY.items()):
            onnx_src = info.get("onnx", "export")
            print(
                f"  {name:45s} {info['dim']:4d}dim  {info['size_mb']:4d}MB  {onnx_src}"
            )
        return

    model_name, model_type = "BAAI/bge-base-en-v1.5", "embedding"
    force = purge_cache = False
    args, i = sys.argv[1:], 0
    while i < len(args):
        if args[i] == "--model" and i + 1 < len(args):
            model_name = args[i + 1]
            i += 2
        elif args[i] == "--type" and i + 1 < len(args):
            model_type = args[i + 1]
            i += 2
        elif args[i] == "--size" and i + 1 < len(args):
            m = {
                "light": ("BAAI/bge-small-en-v1.5", "embedding"),
                "balanced": ("BAAI/bge-base-en-v1.5", "embedding"),
                "full": ("BAAI/bge-m3", "embedding"),
            }
            model_name, model_type = m.get(args[i + 1], (model_name, model_type))
            i += 2
        elif args[i] == "--force":
            force = True
            i += 1
        elif args[i] in ("--auto-clean", "--purge-cache"):
            purge_cache = True
            i += 1
        else:
            i += 1

    project_root = Path(__file__).resolve().parent.parent
    output_dir = project_root / ".codebase_models"
    download_onnx_model(
        model_name,
        output_dir,
        force=force,
        purge_cache=purge_cache,
        model_type=model_type,
    )


if __name__ == "__main__":
    main()
