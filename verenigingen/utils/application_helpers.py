# verenigingen/utils/application_helpers.py — DEPRECATED: moved to services/member/approval/
import warnings

warnings.warn(
    "Import from verenigingen.services.member.approval.application_helpers instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.member.approval.application_helpers import *  # noqa: E402,F401,F403
