# verenigingen/utils/account_creation_manager.py — DEPRECATED: moved to services/member/account/
import warnings

warnings.warn(
    "Import from verenigingen.services.member.account.account_creation_manager "
    "(AccountCreationManager class) or account_creation_api (whitelisted endpoints) instead",
    DeprecationWarning,
    stacklevel=2,
)
from verenigingen.services.member.account.account_creation_api import *  # noqa: E402,F401,F403
from verenigingen.services.member.account.account_creation_manager import *  # noqa: E402,F401,F403
