# verenigingen/utils/donor_customer_sync.py — DEPRECATED: moved to services/member/donor/
import warnings

warnings.warn(
    "Import from verenigingen.services.member.donor.donor_customer_sync instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.member.donor.donor_customer_sync import *  # noqa: E402,F401,F403
