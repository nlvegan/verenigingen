# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""Shared test helper for reading back a Chapter Member row's enabled/status pair.

Used by board-permission tests that drive a Chapter Member row through a REAL
production writer (remove_member(permanent=False), disable_chapter_memberships_safe,
ChapterMembershipManager.transfer_member_between_chapters) and then assert on the
resulting (enabled, status) combination, to confirm the fixture setup actually
produced the state the test claims it did.

Originally written independently, byte-identically, in two places --
verenigingen/tests/member/test_donor_sepa_address_employee_list_permission_matches_doc_permission.py
(#1543) and verenigingen/services/billing/test_dues_schedule_permission_service.py
(#1562). The two copies were byte-identical except for their name (_cm_row vs.
_cm_row_1562), and duplicate_helper_validator.py keys its clone-family detection on
function NAME -- so the renamed copy was invisible to it, not caught by it; an
independent skeptical review of #1562 found the pair by reading the code. Hoisted
here so both files import the same function instead of each keeping their own copy.
"""

import frappe


def get_chapter_member_row(member_name, chapter_name):
    """Return the Chapter Member row's enabled/status pair for member_name on chapter_name.

    Returns a frappe._dict with `enabled` and `status`, or None if no such row exists.
    """
    return frappe.db.get_value(
        "Chapter Member",
        {"member": member_name, "parent": chapter_name},
        ["enabled", "status"],
        as_dict=True,
    )
