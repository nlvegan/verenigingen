# vereinigingen/utils/invoice_management.py — DEPRECATED: moved to services/billing/
import warnings

warnings.warn(
    "Import from verenigingen.services.billing.invoice_management instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.billing.invoice_management import *  # noqa: E402,F401,F403
