import warnings
warnings.warn(
    "src.core.chunk_summarizer is deprecated, use src.core.indexing.chunk_summarizer",
    DeprecationWarning, stacklevel=2,
)
from src.core.indexing.chunk_summarizer import *  # noqa: F403, F405

