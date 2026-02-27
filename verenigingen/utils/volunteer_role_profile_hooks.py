# verenigingen/utils/volunteer_role_profile_hooks.py — DEPRECATED: moved to services/volunteer/
import warnings

warnings.warn(
    "Import from verenigingen.services.volunteer.volunteer_role_profile_hooks instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.volunteer.volunteer_role_profile_hooks import *  # noqa: E402,F401,F403
