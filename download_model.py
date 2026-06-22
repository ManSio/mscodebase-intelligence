"""
Универсальный скрипт для скачивания любой embedding-модели и экспорта в ONNX.
Автоматически пропускает шаги, если ONNX-модель уже существует.
После экспорта чистит временные файлы (safetensors, pytorch_model.bin, HuggingFace кэш).

Использование:
  python download_model.py                                          # BAAI/bge-m3 (рекомендуется)
  python download_model.py --model intfloat/multilingual-e5-small   # Лёгкая (200MB RAM)
  python download_model.py --model intfloat/multilingual-e5-base    # Средняя (350MB RAM)
  python download_model.py --model BAAI/bge-m3                      # Лучшая (800MB RAM)
"""

import json
import logging
import os
import shutil
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("download_model")


def _get_hf_cache_path(model_name: str) -> Path:
    """Возвращает путь к HuggingFace кэшу для указанной модели."""
    cache_home = Path(
        os.environ.get(
            "HF_HOME", os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
        )
    )
    # huggingface_hub кладёт кэш в HF_HOME/hub, а transformers — ещё в HF_HOME
    hub_cache = cache_home / "huggingface" / "hub"
    model_slug = "models--" + model_name.replace("/", "--")
    return hub_cache / model_slug


def cleanup_hf_cache(model_name: str):
    """Удаляет HuggingFace кэш скачанной модели (экономит ~2.5GB)."""
    cache_path = _get_hf_cache_path(model_name)
    if cache_path.exists():
        try:
            shutil.rmtree(cache_path, ignore_errors=True)
            logger.info(f"🧹 Кэш HuggingFace удалён: {cache_path}")
        except Exception as e:
            logger.debug(f"Не удалось удалить кэш HuggingFace: {e}")


def cleanup_source_model(output_dir: Path):
    """Удаляет исходные веса модели из output_dir (safetensors / bin / др.), оставляя только ONNX."""
    for pattern in ["*.safetensors", "*.bin", "*.pt", "*.pth"]:
        for f in output_dir.rglob(pattern):
            try:
                f.unlink()
                logger.debug(f"🧹 Удалён временный файл: {f}")
            except Exception as e:
                logger.debug(f"Не удалось удалить {f}: {e}")


def download_onnx_model(model_name: str, output_dir: Path):
    """Скачивает модель и экспортирует в ONNX.

    Если ONNX-модель уже существует — пропускает все шаги.
    После успешного экспорта удаляет исходные веса и HuggingFace кэш.
    """
    onnx_path = output_dir / "onnx" / "model.onnx"

    # Проверка — уже есть?
    if onnx_path.exists():
        logger.info(f"✅ ONNX-модель уже существует: {onnx_path}")
        logger.info(f"   Размер: {onnx_path.stat().st_size / 1024 / 1024:.1f} MB")
        return

    logger.info(f"📥 Загрузка модели {model_name}...")
    output_dir.mkdir(parents=True, exist_ok=True)

    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModel.from_pretrained(model_name, trust_remote_code=True)
    model.eval()

    # Сохраняем токенизатор и конфиг
    tokenizer.save_pretrained(str(output_dir))

    # Определяем размерность
    hidden_size = getattr(model.config, "hidden_size", None)
    if not hidden_size:
        import torch

        with torch.no_grad():
            dummy = tokenizer(
                ["test"], return_tensors="pt", padding=True, truncation=True
            )
            out = model(**dummy)
            hidden_size = out.last_hidden_state.shape[-1]

    onnx_dir = output_dir / "onnx"
    onnx_dir.mkdir(exist_ok=True)

    # Экспорт в ONNX
    logger.info(f"🔄 Экспорт в ONNX (размерность {hidden_size})...")
    import torch

    dummy_input = tokenizer(
        ["passage: тестовый запрос"],
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=512,
    )

    with torch.no_grad():
        # Используем dynamo=False (стабильный экспортёр) для совместимости с XLM-RoBERTa
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
            opset_version=18,
            dynamo=False,
        )

    # Сохраняем config.json (нужен для transformers AutoTokenizer)
    config_path = output_dir / "config.json"
    if not config_path.exists():
        config = {
            "_name_or_path": model_name,
            "architectures": ["BertModel"],
            "hidden_size": hidden_size,
            "model_type": "bert",
        }
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

    # Чистим временные файлы
    cleanup_source_model(output_dir)
    cleanup_hf_cache(model_name)

    logger.info(f"✅ Модель сохранена в {output_dir}")
    logger.info(
        f"   ONNX: {onnx_path} ({onnx_path.stat().st_size / 1024 / 1024:.1f} MB)"
    )
    logger.info(f"   Размерность: {hidden_size}")
    logger.info(f"   Временные файлы удалены")


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Универсальный загрузчик embedding моделей в ONNX")
        print()
        print("Использование:")
        print("  python download_model.py")
        print("  python download_model.py --model BAAI/bge-m3")
        print("  python download_model.py --model intfloat/multilingual-e5-small")
        print()
        print("Рекомендуемые модели:")
        print(
            "  BAAI/bge-m3                      — лучшая для русский + код (1024, 800MB RAM)"
        )
        print("  intfloat/multilingual-e5-base    — баланс (768, 350MB RAM)")
        print("  intfloat/multilingual-e5-small   — лёгкая (384, 200MB RAM)")
        print("  BAAI/bge-small                   — быстрая (384, 150MB RAM)")
        print("  Alibaba-NLP/gte-Qwen2-1.5B-instruct — мощная (1536, ~3GB RAM)")
        return

    model_name = "BAAI/bge-m3"
    if "--model" in sys.argv:
        idx = sys.argv.index("--model") + 1
        if idx < len(sys.argv):
            model_name = sys.argv[idx]
            # Удаляем, чтобы не мешали парсингу остальных аргументов
            del sys.argv[idx]
            del sys.argv[idx - 1]

    project_path = Path(__file__).parent.resolve()
    output_dir = project_path / ".codebase_models"

    download_onnx_model(model_name, output_dir)


if __name__ == "__main__":
    main()
