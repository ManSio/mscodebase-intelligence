"""
Универсальный скрипт для скачивания любой embedding-модели и экспорта в ONNX.

АРХИТЕКТУРА КЭШИРОВАНИЯ (фикс циклической перекачки):
- Исходные веса HF сохраняются в ПЕРСИСТЕНТНЫЙ кэш (~/.cache/mscodebase/hf_models/)
- Этот кэш НЕ удаляется между сессиями
- ONNX экспорт сохраняется в .codebase_models/onnx/
- Проверка ONNX делается первой (мгновенный skip при повторном запуске)
- Если ONNX удалён — модель НЕ перекачивается, а берётся из персистентного кэша
- HF кэш удаляется ТОЛЬКО при --purge-cache (опционально)

Использование:
  python download_model.py                                          # BAAI/bge-m3 (рекомендуется)
  python download_model.py --model intfloat/multilingual-e5-small   # Лёгкая (200MB RAM)
  python download_model.py --model intfloat/multilingual-e5-base    # Средняя (350MB RAM)
  python download_model.py --model BAAI/bge-m3                      # Лучшая (800MB RAM)
  python download_model.py --force                                   # Принудительный ре-экспорт
  python download_model.py --purge-cache                             # Удалить HF кэш после экспорта
"""

import json
import logging
import shutil
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("download_model")


# ──────────────────────────────────────────────────
# Персистентный cache_dir (~/.cache/mscodebase/hf_models/)
# НЕ в проекте, НЕ удаляется между сессиями
# ──────────────────────────────────────────────────


def _get_persistent_cache_dir() -> Path:
    """Персистентный HF cache_dir — сохраняется между сессиями."""
    return Path.home() / ".cache" / "mscodebase" / "hf_models"


def _get_hf_cache_path(model_name: str) -> Path:
    """Путь к HF кэшу в персистентной директории."""
    model_slug = "models--" + model_name.replace("/", "--")
    return _get_persistent_cache_dir() / "hub" / model_slug


def _purge_hf_cache(model_name: str):
    """Удаляет HF кэш. Только с флагом --purge-cache."""
    cache_path = _get_hf_cache_path(model_name)
    if cache_path.exists():
        try:
            shutil.rmtree(cache_path, ignore_errors=True)
            logger.info(f"🧹 Кэш HuggingFace удалён: {cache_path}")
        except Exception as e:
            logger.debug(f"Не удалось удалить кэш HuggingFace: {e}")


def _cleanup_source_weights(output_dir: Path):
    """Удаляет исходные веса ИЗ output_dir, оставляя только ONNX."""
    for pattern in ["*.safetensors", "*.bin", "*.pt", "*.pth"]:
        for f in output_dir.rglob(pattern):
            try:
                f.unlink()
                logger.debug(f"🧹 Удалён временный файл: {f}")
            except Exception as e:
                logger.debug(f"Не удалось удалить {f}: {e}")


# ──────────────────────────────────────────────────
# Основная функция
# ──────────────────────────────────────────────────


def download_onnx_model(
    model_name: str,
    output_dir: Path,
    force: bool = False,
    purge_cache: bool = False,
    model_type: str = "embedding",
):
    """
    Скачивает модель и экспортирует в ONNX.

    Args:
        model_name: Имя модели на HuggingFace (напр. "BAAI/bge-m3")
        output_dir: Куда сохранить ONNX
        force: Принудительный ре-экспорт
        purge_cache: Удалить HF кэш после экспорта
        model_type: "embedding" (AutoModel) или "reranker" (AutoModelForSequenceClassification)
    """
    from transformers import (
        AutoModel,
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )

    onnx_dir = output_dir / "onnx"
    model_subdir = "bge-m3" if model_type == "embedding" else "bge-reranker"
    onnx_path = onnx_dir / model_subdir / "model.onnx"

    # ── Шаг 1: Проверяем ONNX (быстрый skip) ──
    if onnx_path.exists() and not force:
        logger.info(f"✅ ONNX уже существует: {onnx_path}")
        logger.info(f"   Размер: {onnx_path.stat().st_size / 1024 / 1024:.1f} MB")
        return

    # ── Шаг 2: Убеждаемся что директории существуют ──
    model_dir = onnx_dir / model_subdir
    model_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = _get_persistent_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"📥 Загрузка {model_name} (type={model_type})...")
    if force:
        logger.info("   Режим --force: принудительный ре-экспорт")

    # Выбираем класс модели
    if model_type == "reranker":
        model_class = AutoModelForSequenceClassification
        dummy_text = ["тестовый запрос", "тестовый чанк"]
    else:
        model_class = AutoModel
        dummy_text = ["тестовый запрос"]

    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True,
        cache_dir=str(cache_dir),
    )
    model = model_class.from_pretrained(
        model_name,
        trust_remote_code=True,
        cache_dir=str(cache_dir),
    )
    model.eval()

    # ── Шаг 3: Сохраняем токенизатор ──
    tokenizer.save_pretrained(str(model_dir))

    # ── Шаг 4: Определяем размерность ──
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

    # ── Шаг 5: Экспорт в ONNX ──
    logger.info(f"🔄 Экспорт в ONNX (размерность {hidden_size})...")
    import torch

    dummy_input = tokenizer(
        dummy_text,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=512,
    )

    # Экport с dynamo=False
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
    logger.info(f"   ONNX сохранён: {onnx_path}")

    # ── Шаг 6: Чистка ──
    _cleanup_source_weights(model_dir)
    if purge_cache:
        _purge_hf_cache(model_name)
        logger.info("   HF кэш удалён (--purge-cache)")
    else:
        logger.info(f"   HF кэш сохранён: {_get_persistent_cache_dir()}")

    logger.info(f"✅ Модель сохранена в {model_dir}")
    logger.info(
        f"   ONNX: {onnx_path} ({onnx_path.stat().st_size / 1024 / 1024:.1f} MB)"
    )
    logger.info(f"   Размерность: {hidden_size}")


# ──────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Универсальный загрузчик моделей в ONNX")
        print()
        print("Использование:")
        print("  python download_model.py")
        print("  python download_model.py --model BAAI/bge-m3")
        print(
            "  python download_model.py --model BAAI/bge-reranker-v2-m3 --type reranker"
        )
        print("  python download_model.py --force")
        print("  python download_model.py --purge-cache")
        print()
        print("Типы:")
        print(
            "  --type embedding  (по умолчанию) AutoModel → .codebase_models/onnx/bge-m3/"
        )
        print(
            "  --type reranker   AutoModelForSequenceClassification → .codebase_models/onnx/bge-reranker/"
        )
        print()
        print("Рекомендуемые модели:")
        print("  BAAI/bge-m3                  — embedding (1024, ~438 MB ONNX)")
        print("  BAAI/bge-reranker-v2-m3       — reranker (~636 MB ONNX)")
        print("  intfloat/multilingual-e5-base  — баланс (768, ~350 MB)")
        return

    model_name = "BAAI/bge-m3"
    model_type = "embedding"
    force = False
    purge_cache = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--model" and i + 1 < len(args):
            model_name = args[i + 1]
            i += 2
        elif args[i] == "--type" and i + 1 < len(args):
            model_type = args[i + 1]
            i += 2
        elif args[i] == "--force":
            force = True
            i += 1
        elif args[i] == "--purge-cache":
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
