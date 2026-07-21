# Backward compatibility shim
import warnings
warnings.warn(
    "src.core.searcher is deprecated, use src.core.search.engine",
    DeprecationWarning, stacklevel=2,
)
from src.core.search.engine import *  # noqa: F401, F403
from src.core.search.engine import _expand_query, _filter_by_time  # noqa: F401
from src.core.search.utils import _parse_iso_datetime, _tokenize  # noqa: F401
