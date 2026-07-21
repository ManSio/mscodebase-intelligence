import warnings
warnings.warn(
    "src.core.remote_embedder is deprecated, use src.providers.embedder.remote_embedder",
    DeprecationWarning, stacklevel=2,
)
from src.providers.embedder.remote_embedder import *  # noqa: F403, F405

