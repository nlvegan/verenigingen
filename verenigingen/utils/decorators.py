# verenigingen/utils/decorators.py — DEPRECATED: decorators moved during 2026-02-27 utils reorg
import warnings

warnings.warn(
    "Import performance_monitor from verenigingen.utils.performance_utils instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.utils.performance_utils import performance_monitor  # noqa: E402,F401
