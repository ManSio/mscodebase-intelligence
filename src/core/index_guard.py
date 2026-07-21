# Backward compatibility shim
import warnings
warnings.warn(
    "src.core.index_guard is deprecated, use src.core.indexing.index_guard",
    DeprecationWarning, stacklevel=2,
)
from src.core.indexing.index_guard import *  # noqa: F401, F403

