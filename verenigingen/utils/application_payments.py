# verenigingen/utils/application_payments.py — DEPRECATED: moved to services/member/approval/
import warnings

warnings.warn(
    "Import from verenigingen.services.member.approval.application_payments instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.member.approval.application_payments import *  # noqa: E402,F401,F403
