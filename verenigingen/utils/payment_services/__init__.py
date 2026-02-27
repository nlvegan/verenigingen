# verenigingen/utils/payment_services/ — DEPRECATED: moved to verenigingen_payments/utils/payment_services/
import warnings

warnings.warn(
    "Import from verenigingen.verenigingen_payments.utils.payment_services instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.verenigingen_payments.utils.payment_services import *  # noqa: E402,F401,F403
