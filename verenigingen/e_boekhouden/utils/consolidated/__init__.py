"""
E-Boekhouden Consolidated Utilities

This package contains consolidated implementations that replace scattered
functionality throughout the E-Boekhouden module.

Live utility submodules (imported on the REST migration path):
- date_utils: Shared date utilities (fiscal year management)
- ledger_utils: Canonical ledger ID resolution with auto-create capability
- bank_account_utils: Bank account resolution for payment processing

Account typing/classification lives in
verenigingen.e_boekhouden.services.account_classification_service
(AccountClassificationService); party resolution lives in
verenigingen.e_boekhouden.utils.party_resolver (EBoekhoudenPartyResolver).
The former in-package account_manager / migration_coordinator / party_manager
classes were superseded duplicates and have been removed.
"""

from .bank_account_utils import resolve_bank_account_for_ledger, resolve_bank_account_or_raise
from .date_utils import ensure_fiscal_year_exists
from .ledger_utils import get_ledger_mapping, resolve_ledger_code

__all__ = [
    "ensure_fiscal_year_exists",
    "get_ledger_mapping",
    "resolve_ledger_code",
    "resolve_bank_account_for_ledger",
    "resolve_bank_account_or_raise",
]
