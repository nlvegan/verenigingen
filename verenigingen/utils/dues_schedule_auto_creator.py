# vereinigingen/utils/dues_schedule_auto_creator.py — DEPRECATED: moved to services/billing/
import warnings

warnings.warn(
    "Import from verenigingen.services.billing.dues_schedule_auto_creator instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.billing.dues_schedule_auto_creator import *  # noqa: E402,F401,F403
