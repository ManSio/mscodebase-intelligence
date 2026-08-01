"""Тесты усечения текста до 512 токенов для llama.cpp (фикс HTTP 400).

Фикс: RemoteEmbedder._truncate_for_llama / _load_llama_tokenizer.
HTTP 400 от llama.cpp возникал, когда чанк превышал контекст модели (512 токенов);
эмбеддинг батча падал целиком, после 3 ретраев — нулевой вектор, индексация прерывалась.

Сценарии:
1. Токенизатор загружается из `.codebase_models/onnx/multilingual-e5-small-int8/tokenizer.json`
2. Длинный текст (>512 токенов) усекается — после повторного encode <= 512 токенов
3. Токенизатор отсутствует — текст возвращается без изменений (graceful fallback)
4. Пустой список — возвращается как есть
5. Двойной вызов load — повторная загрузка не создаёт второй экземпляр (double-checked lock)
"""
import threading
from pathlib import Path

import pytest

from src.providers.embedder.remote_embedder import RemoteEmbedder

MAX_TOKENS = 512
TOKENIZER_REL = (
    Path(".codebase_models")
    / "onnx"
    / "multilingual-e5-small-int8"
    / "tokenizer.json"
)
_SRC_TOKENIZER = Path(__file__).resolve().parent.parent / TOKENIZER_REL

requires_tokenizer_file = pytest.mark.skipif(
    not _SRC_TOKENIZER.exists(),
    reason="tokenizer.json недоступен (gitignored, CI без .codebase_models)",
)


def _make_embedder(ext_root: Path) -> RemoteEmbedder:
    """Создаёт RemoteEmbedder без __init__ (который спавнит фоновые потоки)."""
    obj = RemoteEmbedder.__new__(RemoteEmbedder)
    obj.ext_root = ext_root
    obj._llama_tokenizer = None
    obj._llama_tokenizer_lock = threading.Lock()
    return obj


@requires_tokenizer_file
def test_tokenizer_loads_from_ext_root(tmp_path):
    """Токенизатор загружается из ext_root/.codebase_models/.../tokenizer.json."""
    dst = tmp_path / TOKENIZER_REL
    dst.parent.mkdir(parents=True)
    dst.write_bytes(_SRC_TOKENIZER.read_bytes())

    obj = _make_embedder(tmp_path)
    obj._load_llama_tokenizer()

    assert obj._llama_tokenizer is not None, "tokenizer должен загрузиться"


@requires_tokenizer_file
def test_truncates_long_text_to_512_tokens(tmp_path):
    """Текст >512 токенов усекается: повторный encode даёт <= 512 токенов."""
    dst = tmp_path / TOKENIZER_REL
    dst.parent.mkdir(parents=True)
    dst.write_bytes(_SRC_TOKENIZER.read_bytes())

    obj = _make_embedder(tmp_path)
    long_text = " ".join(f"word_{i}" for i in range(900))  # >> 512 токенов

    truncated = obj._truncate_for_llama([long_text])[0]

    enc = obj._llama_tokenizer.encode(truncated, add_special_tokens=True)
    assert len(enc.ids) <= MAX_TOKENS, (
        f"после усечения {len(enc.ids)} токенов > {MAX_TOKENS}"
    )
    assert truncated != long_text, "текст должен был измениться"


@requires_tokenizer_file
def test_truncate_batch_preserves_order_and_count(tmp_path):
    """Батч усекается попарно: длина и порядок сохраняются."""
    dst = tmp_path / TOKENIZER_REL
    dst.parent.mkdir(parents=True)
    dst.write_bytes(_SRC_TOKENIZER.read_bytes())

    obj = _make_embedder(tmp_path)
    short = "короткий текст"
    long_text = " ".join(f"w{i}" for i in range(900))

    result = obj._truncate_for_llama([short, long_text, short])

    assert len(result) == 3
    assert result[0] == short, "короткие тексты не трогаем"
    assert result[1] != long_text, "длинный усекаем"
    assert result[2] == short


def test_missing_tokenizer_is_graceful(tmp_path):
    """Нет tokenizer.json — текст возвращается без изменений, без исключений."""
    obj = _make_embedder(tmp_path)  # пустой ext_root
    texts = ["hello world", "длинный текст " * 100]

    result = obj._truncate_for_llama(texts)

    assert result == texts


def test_empty_input_returns_empty(tmp_path):
    obj = _make_embedder(tmp_path)
    assert obj._truncate_for_llama([]) == []


def test_double_load_is_idempotent(tmp_path):
    """Второй вызов _load_llama_tokenizer не пересоздаёт экземпляр."""
    dst = tmp_path / TOKENIZER_REL
    if _SRC_TOKENIZER.exists():
        dst.parent.mkdir(parents=True)
        dst.write_bytes(_SRC_TOKENIZER.read_bytes())

    obj = _make_embedder(tmp_path)
    obj._load_llama_tokenizer()
    first = obj._llama_tokenizer
    obj._load_llama_tokenizer()

    if _SRC_TOKENIZER.exists():
        assert obj._llama_tokenizer is first, "повторный load не должен создавать новый"
    else:
        assert obj._llama_tokenizer is None
