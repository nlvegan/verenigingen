# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Member API Package - Extracted from member.py module-level functions.

This package provides a modular organization for member-related API endpoints,
previously located as module-level functions in the Member DocType file.

Modules:
    - sepa_api: SEPA mandate management endpoints
    - member_id_api: Member ID assignment and debugging endpoints
    - chapter_api: Chapter membership endpoints
    - financial_api: Dues and financial management endpoints

Migration Notes:
    All functions maintain backward compatibility through re-exports in member.py.
    The original import paths continue to work for existing code.

Usage:
    # Direct import (preferred)
    from verenigingen.api.member.sepa_api import refresh_sepa_mandates

    # Or via package
    from verenigingen.api.member import refresh_sepa_mandates

    # Legacy import (deprecated, still works)
    from verenigingen.verenigingen.doctype.member.member import refresh_sepa_mandates
"""

# SEPA API functions
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
from verenigingen.api.member.sepa_api import (
    create_and_link_mandate_enhanced,
    deactivate_old_sepa_mandates,
    derive_bic_from_iban,
    get_active_sepa_mandate,
    refresh_sepa_mandates,
    validate_mandate_creation,
)

__all__ = [
    # SEPA
    "refresh_sepa_mandates",
    "get_active_sepa_mandate",
    "create_and_link_mandate_enhanced",
    "derive_bic_from_iban",
    "deactivate_old_sepa_mandates",
    "validate_mandate_creation",
    # Member ID
    "assign_missing_member_ids",
    "debug_member_id_assignment",
    # Chapter
    "get_member_current_chapters",
    "get_member_chapter_names",
    "get_member_chapter_display_html",
    # Financial
    "sync_member_dues_rate",
    "get_current_dues_schedule_details",
    "refresh_fee_change_history",
    # General
    "create_member_user_account",
    "check_donor_exists",
    "create_donor_from_member",
    "get_linked_donations",
    "test_member_form_functionality",
]
