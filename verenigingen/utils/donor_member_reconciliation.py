# verenigingen/utils/donor_member_reconciliation.py — DEPRECATED: moved to services/member/donor/
import warnings

warnings.warn(
    "Import from verenigingen.services.member.donor.donor_member_reconciliation instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.member.donor.donor_member_reconciliation import *  # noqa: E402,F401,F403
