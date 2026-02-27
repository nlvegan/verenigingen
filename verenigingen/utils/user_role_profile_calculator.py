# verenigingen/utils/user_role_profile_calculator.py — DEPRECATED: moved to services/member/account/
import warnings

warnings.warn(
    "Import from verenigingen.services.member.account.user_role_profile_calculator instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.member.account.user_role_profile_calculator import *  # noqa: E402,F401,F403
