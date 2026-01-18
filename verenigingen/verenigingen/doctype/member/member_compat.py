# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Member Backward Compatibility Re-exports

This module provides backward compatibility re-exports for functions that have been
extracted from member.py to the api/member/ package.

DEPRECATION NOTICE:
These re-exports are provided for backward compatibility only.
New code should import directly from the api/member/ package:

    # Instead of:
    from verenigingen.verenigingen.doctype.member.member import get_member_chapter_names

    # Use:
    from verenigingen.api.member.chapter_api import get_member_chapter_names

Functions by module:
- SEPA functions → api/member/sepa_api.py
- Member ID functions → api/member/member_id_api.py
- Chapter functions → api/member/chapter_api.py
- Financial functions → api/member/financial_api.py
- General functions → api/member/general_api.py
"""

# Chapter API functions
from verenigingen.api.member.chapter_api import (
    get_member_chapter_display_html,
    get_member_chapter_names,
    get_member_current_chapters,
)

# Financial API functions
from verenigingen.api.member.financial_api import (
    get_current_dues_schedule_details,
    refresh_fee_change_history,
    sync_member_dues_rate,
)

# General member API functions
from verenigingen.api.member.general_api import (
    check_donor_exists,
    create_donor_from_member,
    create_member_user_account,
    get_linked_donations,
    test_member_form_functionality,
)

# Member ID API functions
from verenigingen.api.member.member_id_api import (
    assign_missing_member_ids,
    debug_member_id_assignment,
)

# SEPA API functions
from verenigingen.api.member.sepa_api import (
    create_and_link_mandate_enhanced,
    deactivate_old_sepa_mandates,
    derive_bic_from_iban,
    get_active_sepa_mandate,
    refresh_sepa_mandates,
    validate_mandate_creation,
)

# Re-export all for `from member_compat import *`
__all__ = [
    # Chapter
    "get_member_chapter_display_html",
    "get_member_chapter_names",
    "get_member_current_chapters",
    # Financial
    "get_current_dues_schedule_details",
    "refresh_fee_change_history",
    "sync_member_dues_rate",
    # General
    "check_donor_exists",
    "create_donor_from_member",
    "create_member_user_account",
    "get_linked_donations",
    "test_member_form_functionality",
    # Member ID
    "assign_missing_member_ids",
    "debug_member_id_assignment",
    # SEPA
    "create_and_link_mandate_enhanced",
    "deactivate_old_sepa_mandates",
    "derive_bic_from_iban",
    "get_active_sepa_mandate",
    "refresh_sepa_mandates",
    "validate_mandate_creation",
]
