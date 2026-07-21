# Backward compatibility shim
import warnings
warnings.warn(
    "src.core.file_guard is deprecated, use src.core.indexing.file_guard",
    DeprecationWarning, stacklevel=2,
)
from src.core.indexing.file_guard import *  # noqa: F401, F403

