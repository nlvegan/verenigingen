# vereinigingen/utils/dues_schedule_health_manager.py — DEPRECATED: moved to services/billing/
import warnings

warnings.warn(
    "Import from verenigingen.services.billing.dues_schedule_health_manager instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.billing.dues_schedule_health_manager import *  # noqa: E402,F401,F403
