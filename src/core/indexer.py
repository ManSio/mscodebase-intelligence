# Backward compatibility shim
import warnings
warnings.warn(
    "src.core.indexer is deprecated, use src.core.indexing.indexer",
    DeprecationWarning, stacklevel=2,
)
from src.core.indexing.indexer import (
    Indexer,  # noqa: F401
    _generate_unique_db_path,  # noqa: F401
)
