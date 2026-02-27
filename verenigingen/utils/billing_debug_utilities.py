# vereinigingen/utils/billing_debug_utilities.py — DEPRECATED: moved to services/billing/
import warnings

warnings.warn(
    "Import from verenigingen.services.billing.billing_debug_utilities instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.billing.billing_debug_utilities import *  # noqa: E402,F401,F403
