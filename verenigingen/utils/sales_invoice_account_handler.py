# vereinigingen/utils/sales_invoice_account_handler.py — DEPRECATED: moved to services/billing/
import warnings

warnings.warn(
    "Import from verenigingen.services.billing.sales_invoice_account_handler instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.billing.sales_invoice_account_handler import *  # noqa: E402,F401,F403
