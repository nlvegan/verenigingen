# verenigingen/utils/webhook_security.py — DEPRECATED: moved to verenigingen_payments/utils/
import warnings

warnings.warn(
    "Import from verenigingen.verenigingen_payments.utils.webhook_security instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.verenigingen_payments.utils.webhook_security import *  # noqa: E402,F401,F403
