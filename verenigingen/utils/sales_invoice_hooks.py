# vereinigingen/utils/sales_invoice_hooks.py — DEPRECATED: moved to services/billing/
import warnings

warnings.warn(
    "Import from verenigingen.services.billing.sales_invoice_hooks instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.billing.sales_invoice_hooks import *  # noqa: E402,F401,F403
