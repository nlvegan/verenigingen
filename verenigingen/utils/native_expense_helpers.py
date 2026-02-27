# verenigingen/utils/native_expense_helpers.py — DEPRECATED: moved to services/volunteer/
import warnings

warnings.warn(
    "Import from verenigingen.services.volunteer.native_expense_helpers instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.volunteer.native_expense_helpers import *  # noqa: E402,F401,F403
