# vereinigingen/utils/billing_constants.py — DEPRECATED: moved to services/billing/
import warnings

warnings.warn(
    "Import from verenigingen.services.billing.billing_constants instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.billing.billing_constants import *  # noqa: E402,F401,F403
