# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Regression test for the canonical membership-approval path activating
pre-existing pending Chapter Members.

T4.1 retires the second approval orchestrator (`MemberLifecycleService.
approve_application`). Before deletion we need behavioural equivalence:
the canonical path at ``api.membership_application_review.approve_membership_
application`` must subsume the lifecycle service's pending-chapter activation
step.

This test mirrors ``test_chapter_membership_approval_integration.
test_lifecycle_service_activates_chapter_membership`` but exercises the
canonical API. It fails RED on the unpatched canonical path and passes
GREEN after the §2.3 fix in the T4.1 design doc is applied.
"""

import frappe
from frappe.utils import now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCanonicalApprovalChapterActivation(EnhancedTestCase):
    """The canonical approve API must activate pending Chapter Members."""

    def setUp(self):
        super().setUp()
        # Chapter uses autoname='prompt'; create manually as the sibling test does.
        chapter_name = f"Test Chapter Canonical {int(now_datetime().timestamp())}"
        self.test_chapter = frappe.get_doc({
            "doctype": "Chapter",
            "name": chapter_name,
            "status": "Active",
        })
        self.test_chapter.insert(ignore_permissions=True)
        frappe.db.commit()

        # Get-or-create the shared "Standard Member" type and guarantee it is
        # ACTIVE. A bare `if not exists` insert leaves the type untouched when a
        # prior test module deactivated it on the same DB, surfacing as
        # "Membership Type Standard Member is inactive" during approval. The
        # canonical helper both creates (active, with an aligned dues template)
        # and re-activates an existing inactive row.
        from verenigingen.tests.fixtures.test_data_factory import (
            ensure_membership_type_exists,
        )

        ensure_membership_type_exists("Standard Member", amount=25.0)
        if not frappe.db.get_value("Membership Type", "Standard Member", "is_active"):
            frappe.db.set_value("Membership Type", "Standard Member", "is_active", 1)
        frappe.db.commit()

    def test_canonical_approval_activates_pending_chapter_membership(self):
        """When a member application has a pending Chapter Member row (created
        by the application form), the canonical approve API must flip its
        status to 'Active' on approval - matching MemberLifecycleService's
        legacy behaviour. Without the §2.3 patch the pending row stays
        Pending and members lose their chapter assignment on approval."""
        from verenigingen.api.membership_application_review import (
            approve_membership_application,
        )
        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        # 1. Create a pending member application.
        member = self.create_test_member(
            first_name="Canonical",
            last_name=f"ApprovalUser{int(now_datetime().timestamp())}",
            email=f"canonical_approval_{now_datetime().timestamp()}@example.com",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending",
            application_id=f"CANON-{int(now_datetime().timestamp())}",
            selected_membership_type="Standard Member",
        )

        # 2. Create the pending Chapter Member row (simulates the application
        #    form's behaviour - chapter chosen at submit time, not approval).
        chapter_member = create_pending_chapter_membership(member, self.test_chapter.name)
        self.assertIsNotNone(chapter_member)

        # 3. Verify initial state - Chapter Member is Pending.
        chapter_doc = frappe.get_doc("Chapter", self.test_chapter.name)
        pending = [m for m in chapter_doc.members if m.member == member.name]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].status, "Pending")

        # 4. Approve via the CANONICAL API (the path we are about to
        #    consolidate onto). Pass chapter=None so the function doesn't
        #    try to assign a new chapter - the test is about whether the
        #    EXISTING pending row is activated, not new assignment.
        member.reload()
        approve_membership_application(
            member_name=member.name,
            membership_type="Standard Member",
            chapter=None,
        )

        # 5. The pending row should now be Active. This is the RED-first
        #    assertion: it fails on develop until the §2.3 patch is applied
        #    in step 2 of the T4.1 plan.
        chapter_doc.reload()
        post_approval = [m for m in chapter_doc.members if m.member == member.name]
        self.assertEqual(len(post_approval), 1, "Should still have 1 Chapter Member row")
        self.assertEqual(
            post_approval[0].status,
            "Active",
            "Chapter Member status should be 'Active' after canonical approval. "
            "If this is 'Pending', the canonical path is missing the "
            "pending-chapter activation step that the lifecycle service has - "
            "see T4.1 design §2.3.",
        )
