# verenigingen/utils/volunteer_expense_setup.py — DEPRECATED: moved to services/volunteer/
import warnings

warnings.warn(
    "Import from verenigingen.services.volunteer.volunteer_expense_setup instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.volunteer.volunteer_expense_setup import *  # noqa: E402,F401,F403
