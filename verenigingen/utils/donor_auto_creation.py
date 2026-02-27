# verenigingen/utils/donor_auto_creation.py — DEPRECATED: moved to services/member/donor/
import warnings

warnings.warn(
    "Import from verenigingen.services.member.donor.donor_auto_creation instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.member.donor.donor_auto_creation import *  # noqa: E402,F401,F403
