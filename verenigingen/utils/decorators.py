# verenigingen/utils/decorators.py — DEPRECATED: decorators moved during 2026-02-27 utils reorg
import warnings

warnings.warn(
    "Import rate_limit from verenigingen.utils.validation.api_validators and "
    "performance_monitor from verenigingen.utils.performance_utils instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.utils.performance_utils import performance_monitor  # noqa: E402,F401
from verenigingen.utils.validation.api_validators import rate_limit  # noqa: E402,F401
