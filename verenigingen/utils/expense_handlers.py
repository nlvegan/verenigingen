# verenigingen/utils/expense_handlers.py — DEPRECATED: moved to services/volunteer/
import warnings

warnings.warn(
    "Import from verenigingen.services.volunteer.expense_handlers instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.volunteer.expense_handlers import *  # noqa: E402,F401,F403
