"""Embedding dimension contract: provider declares, schema follows, mismatch is loud.

Why (G4, night 12->13.11.2026): this project's LanceDB table was declared as
`vector fixed_size_list<float>[384]` with **zero rows**, while the active
embedder returned 768. The old detection read the width from a data row, found
none, and let the write fail deep inside LanceDB:

    ValueError: lance error: Cannot cast to FixedSizeList(384):
    value at index 0 has length 768

Silent padding/truncation is worse than the crash: it would store 768-d answers
under a 384-d promise and make similarity meaningless. The rule here is one
line: before any write, provider width == schema width. A mismatch is a fast
refusal that names the provider and both numbers.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")


class EmbeddingDimMismatch(RuntimeError):
    """Provider and vector schema disagree about the width."""


class EmbedderUnavailable(RuntimeError):
    """The embedder did not answer after the bounded attempts."""


def provider_label(embedder: Any) -> str:
    """Human name of the active provider, for error messages and the diary.

    Looks at an explicit `provider_name` first (RemoteEmbedder exposes one),
    then falls back to `mode` + model, then to the class name. Never returns an
    empty string: an unnamed provider in a mismatch message is useless.
    """
    if embedder is None:
        return "no-embedder"

    name = getattr(embedder, "provider_name", None)
    if callable(name):
        try:
            name = name()
        except Exception:  # noqa: BLE001 — a broken label must not hide the error
            name = None
    if not isinstance(name, str) or not name:
        mode = getattr(embedder, "mode", None) or getattr(embedder, "provider", None)
        model = getattr(embedder, "model_name", None) or getattr(
            embedder, "_model_name", None
        )
        name = ":".join(
            str(part)
            for part in (mode, model)
            if isinstance(part, str) and part
        )
    if not name:
        name = type(embedder).__name__
    return str(name)


def provider_dim(embedder: Any) -> Optional[int]:
    """Width the provider promises to return, or None when it does not say."""
    if embedder is None:
        return None
    dim = getattr(embedder, "embedding_dim", None)
    if dim is None:
        getter = getattr(embedder, "get_embedding_dim", None)
        if callable(getter):
            try:
                dim = getter()
            except Exception:  # noqa: BLE001 — unknown is not an error here
                dim = None
    # Only a real number is a declaration; a Mock/attribute of another type is
    # "unknown", not a width of 1.
    if isinstance(dim, bool) or not isinstance(dim, (int, float)):
        return None
    return int(dim) if dim else None


def schema_vector_dim(schema: Any) -> Optional[int]:
    """Width of the `vector` field of an existing LanceDB/pyarrow schema.

    Reads the schema, not a sample row: an empty table has no rows to sample,
    which is exactly how G4's 384-vs-768 mismatch slipped through.
    """
    if schema is None:
        return None
    fields = getattr(schema, "names", None)
    if fields is None:
        return None
    if "vector" not in fields:
        return None
    try:
        field = schema.field("vector")
    except Exception:  # noqa: BLE001 — old pyarrow without field()
        field = next((f for f in schema if getattr(f, "name", "") == "vector"), None)
    if field is None:
        return None
    value_type = getattr(field, "type", None)
    size = getattr(value_type, "list_size", None)
    if size:
        return int(size)
    value_type = getattr(value_type, "value_type", None)
    size = getattr(value_type, "list_size", None)
    return int(size) if size else None


def require_dim_match(
    *,
    provider: str,
    provider_dim: Optional[int],
    schema_dim: Optional[int],
    where: str,
) -> None:
    """Raise `EmbeddingDimMismatch` unless both widths are known and equal."""
    if provider_dim is None or schema_dim is None:
        raise EmbeddingDimMismatch(
            f"{where}: cannot verify the vector width — provider '{provider}' "
            f"declares {provider_dim}, schema declares {schema_dim}. "
            "Refusing to write an unverified vector."
        )
    if provider_dim != schema_dim:
        raise EmbeddingDimMismatch(
            f"{where}: provider '{provider}' returns {provider_dim}-d vectors, "
            f"but the vector schema is {schema_dim}-d. Refusing to resize "
            "silently. Rebuild the index at the provider's width, or start a "
            f"{schema_dim}-d provider."
        )


def bounded_attempts(
    step: Callable[[int], T],
    *,
    attempts: int,
    provider: str,
    label: str,
    backoff: tuple[float, ...] = (),
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run `step` at most `attempts` times, then raise `EmbedderUnavailable`.

    The night incident was an open-ended loop: embed error -> idle-unload ->
    restart -> embed error. A retry policy must end in a named BLOCKED answer,
    not in a spinner. `step` receives the zero-based attempt number.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last: Optional[BaseException] = None
    for attempt in range(attempts):
        try:
            return step(attempt)
        except Exception as exc:  # noqa: BLE001 — re-raised below with context
            last = exc
            if attempt + 1 < attempts:
                delay = backoff[min(attempt, len(backoff) - 1)] if backoff else 0.0
                if delay:
                    sleep(delay)
    raise EmbedderUnavailable(
        f"{label}: provider '{provider}' failed after {attempts} attempt(s): {last}"
    ) from last
