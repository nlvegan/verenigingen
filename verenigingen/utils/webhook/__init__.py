# verenigingen/utils/webhook/ — DEPRECATED: moved to verenigingen_payments/utils/webhook/
import warnings

warnings.warn(
    "Import from verenigingen.verenigingen_payments.utils.webhook instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.verenigingen_payments.utils.webhook import *  # noqa: E402,F401,F403
