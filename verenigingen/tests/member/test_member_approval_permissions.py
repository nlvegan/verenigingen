# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
Permission-tier regression tests for member approval.

The approval workflow is a HIGH-security operation that should be callable by
Verenigingen Staff and up. Frappe's Administrator user bypasses all DocPerms
(frappe/permissions.py:107), so a test that runs as Administrator silently
masks permission gaps for real Staff/Admin role users. These tests use the
EnhancedTestCase as_staff() and as_admin_role() helpers to exercise the flow
under the actual target roles.
"""

import unittest

import frappe
from frappe.utils import add_days, today

from verenigingen.api.membership_application_review import approve_membership_application
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberApprovalPermissions(EnhancedTestCase):
    """Regression: approve_membership_application must work for non-Admin actors."""

    def setUp(self):
        super().setUp()
        # Reuse / ensure a default Membership Type exists (matches existing tests).
        # is_active=1 is required for approve_membership_application — the canonical
        # impl validates is_active before creating the Membership record.
        if not frappe.db.exists("Membership Type", "Test Approval Membership"):
            mt = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type_name": "Test Approval Membership",
                "minimum_amount": 15,
                "is_active": 1,
                "role_profile": "Verenigingen Member",
            })
            mt.insert(ignore_permissions=True)
            self.factory.track_document("Membership Type", mt.name, priority=1)
        else:
            # Ensure is_active=1 even if the type was created by a previous test
            frappe.db.set_value(
                "Membership Type", "Test Approval Membership", "is_active", 1, update_modified=False
            )
        self.membership_type = "Test Approval Membership"

    def _create_pending_member(self, suffix):
        """Create a Member in 'Pending' application_status ready for approval."""
        # Include uid to avoid Customer/Member name collisions across test runs
        # (EnhancedTestCase doesn't roll back Customer rows committed via member.save())
        unique = f"{suffix}{self.uid[:6]}"
        member = self.create_test_member(
            first_name=f"Pending{unique}",
            last_name=f"Approval{self.uid[6:]}",
            email=f"pending.approval.{unique}.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )
        member.reload()
        member.application_status = "Pending"
        member.status = "Pending"
        member.selected_membership_type = self.membership_type
        member.save(ignore_permissions=True)
        member.reload()
        return member

    def test_approval_succeeds_for_verenigingen_staff(self):
        """Verenigingen Staff IS allowed to approve memberships.

        Membership approval is a HIGH-security operation that, by design, is
        callable by "Verenigingen Staff and up" (see this module's docstring).
        The permission gate is
        ``chapter_security.get_user_manageable_chapters``, which grants Staff
        (alongside Verenigingen Administrator, System Manager and National Board)
        management of *all* chapters' applications. This test is the regression
        guard for that tier: any change that revokes Staff approval rights should
        be deliberate and update ``get_user_manageable_chapters`` + this test
        together.
        """
        member = self._create_pending_member("staff")

        with self.as_staff():
            result = approve_membership_application(
                member_name=member.name,
                membership_type=self.membership_type,
                create_invoice=False,
                notes="Approved by Verenigingen Staff",
            )

        self.assertTrue(
            result.get("success"),
            f"Approval failed for Verenigingen Staff: "
            f"{result.get('message') or result}",
        )
        member.reload()
        self.assertEqual(
            member.application_status, "Approved",
            "Member should be Approved after Staff approval",
        )

    def test_approval_succeeds_for_verenigingen_administrator_role(self):
        """The Verenigingen Administrator *role* (not the Administrator *user*)
        must also work. Administrator-the-user bypasses DocPerms; this test
        ensures the role itself grants enough access.
        """
        member = self._create_pending_member("adminrole")

        with self.as_admin_role():
            result = approve_membership_application(
                member_name=member.name,
                membership_type=self.membership_type,
                create_invoice=False,
                notes="Approved by Verenigingen Administrator role",
            )

        self.assertTrue(
            result.get("success"),
            f"Approval failed for Verenigingen Administrator role: "
            f"{result.get('message') or result}",
        )
        member.reload()
        self.assertEqual(member.application_status, "Approved")


if __name__ == "__main__":
    unittest.main()
