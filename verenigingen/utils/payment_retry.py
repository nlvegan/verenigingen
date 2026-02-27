# verenigingen/utils/payment_retry.py — DEPRECATED: moved to verenigingen_payments/utils/
import warnings

warnings.warn(
    "Import from verenigingen.verenigingen_payments.utils.payment_retry instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.verenigingen_payments.utils.payment_retry import *  # noqa: E402,F401,F403
