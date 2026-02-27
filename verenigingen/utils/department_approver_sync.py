# verenigingen/utils/department_approver_sync.py — DEPRECATED: moved to services/volunteer/
import warnings

warnings.warn(
    "Import from verenigingen.services.volunteer.department_approver_sync instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.volunteer.department_approver_sync import *  # noqa: E402,F401,F403
