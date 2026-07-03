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
):
    """
    Скачивает модель и экспортирует в ONNX.

    Аргументы:
        model_name: Имя модели на HuggingFace (напр. "BAAI/bge-m3")
        output_dir: Куда сохранить ONNX
        force: Принудительный ре-экспорт (даже если ONNX уже есть)
        purge_cache: Удалить HF кэш после экспорта (экономит ~2GB)
    """
    onnx_path = output_dir / "onnx" / "model.onnx"

    # ── Шаг 1: Проверяем ONNX (быстрый skip) ──
    if onnx_path.exists() and not force:
        logger.info(f"✅ ONNX-модель уже существует: {onnx_path}")
        logger.info(f"   Размер: {onnx_path.stat().st_size / 1024 / 1024:.1f} MB")
        return

    # ── Шаг 2: Убеждаемся что директории существуют ──
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = _get_persistent_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"📥 Загрузка модели {model_name}...")
    if force:
        logger.info("   Режим --force: принудительный ре-экспорт")
    logger.info(f"   HF cache_dir: {cache_dir} (сохраняется между сессиями)")

    from transformers import AutoModel, AutoTokenizer

    # cache_dir указывает на персистентную папку — если модель уже скачана,
    # from_pretrained() НЕ качает заново
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True,
        cache_dir=str(cache_dir),
    )
    model = AutoModel.from_pretrained(
        model_name,
        trust_remote_code=True,
        cache_dir=str(cache_dir),
    )
    model.eval()

    # ── Шаг 3: Сохраняем токенизатор и конфиг ──
    tokenizer.save_pretrained(str(output_dir))

    # ── Шаг 4: Определяем размерность эмбеддингов ──
    hidden_size = getattr(model.config, "hidden_size", None)
    if not hidden_size:
        import torch

        with torch.no_grad():
            dummy = tokenizer(
                ["test"], return_tensors="pt", padding=True, truncation=True
            )
            out = model(**dummy)
            hidden_size = out.last_hidden_state.shape[-1]

    # ── Шаг 5: Экспорт в ONNX ──
    onnx_dir = output_dir / "onnx"
    onnx_dir.mkdir(exist_ok=True)

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
        # dynamo=False — классический экспортёр (стабильный), без torch.compile
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

    # ── Шаг 6: Сохраняем config.json (нужен для AutoTokenizer) ──
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

    # ── Шаг 7: Чистка ──
    # Удаляем исходные safetensors/bin из output_dir (они уже в cache_dir)
    _cleanup_source_weights(output_dir)

    # HF кэш удаляем ТОЛЬКО по явному флагу
    if purge_cache:
        _purge_hf_cache(model_name)
        logger.info("   HF кэш удалён (--purge-cache)")
    else:
        logger.info(f"   HF кэш сохранён: {_get_persistent_cache_dir()}")
        logger.info("   Для удаления используйте --purge-cache")

    logger.info(f"✅ Модель сохранена в {output_dir}")
    logger.info(
        f"   ONNX: {onnx_path} ({onnx_path.stat().st_size / 1024 / 1024:.1f} MB)"
    )
    logger.info(f"   Размерность: {hidden_size}")


# ──────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Универсальный загрузчик embedding моделей в ONNX")
        print()
        print("Использование:")
        print("  python download_model.py")
        print("  python download_model.py --model BAAI/bge-m3")
        print("  python download_model.py --model intfloat/multilingual-e5-small")
        print("  python download_model.py --force")
        print("  python download_model.py --purge-cache")
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
    force = False
    purge_cache = False

    # Ручной парсинг argv без зависимостей
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--model" and i + 1 < len(args):
            model_name = args[i + 1]
            i += 2
        elif args[i] == "--force":
            force = True
            i += 1
        elif args[i] == "--purge-cache":
            purge_cache = True
            i += 1
        else:
            i += 1

    project_path = Path(__file__).parent.resolve()
    output_dir = project_path / ".codebase_models"

    download_onnx_model(model_name, output_dir, force=force, purge_cache=purge_cache)


if __name__ == "__main__":
    main()
