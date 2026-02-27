# verenigingen/utils/webhook_rate_limiter.py — DEPRECATED: moved to verenigingen_payments/utils/
import warnings

warnings.warn(
    "Import from verenigingen.verenigingen_payments.utils.webhook_rate_limiter instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.verenigingen_payments.utils.webhook_rate_limiter import *  # noqa: E402,F401,F403
