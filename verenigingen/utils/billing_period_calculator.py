# vereinigingen/utils/billing_period_calculator.py — DEPRECATED: moved to services/billing/
import warnings

warnings.warn(
    "Import from verenigingen.services.billing.billing_period_calculator instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.billing.billing_period_calculator import *  # noqa: E402,F401,F403
