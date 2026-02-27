# verenigingen/utils/expense_history_batch_processor.py — DEPRECATED: moved to services/volunteer/
import warnings

warnings.warn(
    "Import from verenigingen.services.volunteer.expense_history_batch_processor instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.volunteer.expense_history_batch_processor import *  # noqa: E402,F401,F403
