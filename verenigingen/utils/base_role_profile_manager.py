# verenigingen/utils/base_role_profile_manager.py — DEPRECATED: moved to services/member/account/
import warnings

warnings.warn(
    "Import from verenigingen.services.member.account.base_role_profile_manager instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.member.account.base_role_profile_manager import *  # noqa: E402,F401,F403
