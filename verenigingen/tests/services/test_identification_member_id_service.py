# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Integration tests for services/member/identification/member_id_service.py.

This is the MemberIDService class (OperationResult-based admin utility),
distinct from the core module-level functions. Covers single assignment,
bulk assignment, and the debug diagnostic, all against real Member docs.
"""

import unittest

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.services.member.identification.member_id_service import (
    MemberIDService,
    get_member_id_service,
)


class TestAssignMemberId(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = MemberIDService()

    def test_empty_name_fails(self):
        result = self.service.assign_member_id("")
        self.assertFalse(result.success)
        self.assertIn("required", result.error_message.lower())

    def test_nonexistent_member_fails(self):
        result = self.service.assign_member_id("NONEXISTENT-MEMBER-XYZ")
        self.assertFalse(result.success)
        self.assertIn("does not exist", result.error_message.lower())

    def test_already_has_id_fails_with_existing(self):
        member = self.create_test_member(
            first_name="Assign",
            last_name="Has",
            email="assign.has@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", "445566")
        result = self.service.assign_member_id(member.name)
        self.assertFalse(result.success)
        self.assertEqual(result.metadata.get("existing_member_id"), "445566")

    def test_assigns_numeric_id_to_eligible_member(self):
        """A non-application member without an ID is assigned a numeric ID."""
        member = self.create_test_member(
            first_name="Assign",
            last_name="New",
            email="assign.new@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", None)
        result = self.service.assign_member_id(member.name)
        self.assertTrue(result.success)
        self.assertTrue(str(result.data).isdigit())
        # Verify persisted on the member
        self.assertEqual(frappe.db.get_value("Member", member.name, "member_id"), str(result.data))


class TestAssignMissingMemberIds(EnhancedTestCase):
    def test_bulk_assigns_to_eligible_members(self):
        """Bulk assignment fills IDs for eligible members lacking them."""
        member = self.create_test_member(
            first_name="Bulk",
            last_name="Eligible",
            email="bulk.eligible@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", None)
        frappe.db.commit()

        result = get_member_id_service().assign_missing_member_ids()
        self.assertTrue(result.success)
        self.assertGreaterEqual(result.data["assigned"], 1)
        self.assertGreaterEqual(result.data["total_checked"], 1)
        # Our member should now have an id
        member.reload()
        self.assertTrue(member.member_id)

    def test_result_shape(self):
        """Seed one eligible member so the bulk op reports the standard keys."""
        member = self.create_test_member(
            first_name="Bulk",
            last_name="Shape",
            email="bulk.shape@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", None)
        frappe.db.commit()

        result = get_member_id_service().assign_missing_member_ids()
        # At least our seeded member is assigned -> success path with data dict
        self.assertTrue(result.success)
        self.assertIn("total_checked", result.data)
        self.assertIn("assigned", result.data)
        self.assertIn("errors", result.data)


class TestDebugMemberIdAssignment(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = MemberIDService()

    def test_empty_name_fails(self):
        result = self.service.debug_member_id_assignment("")
        self.assertFalse(result.success)

    def test_nonexistent_member_fails(self):
        result = self.service.debug_member_id_assignment("NONEXISTENT-MEMBER-XYZ")
        self.assertFalse(result.success)

    def test_member_with_id_explains_already_has(self):
        member = self.create_test_member(
            first_name="Debug",
            last_name="Has",
            email="debug.has@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", "112233")
        member.reload()
        result = self.service.debug_member_id_assignment(member.name)
        self.assertTrue(result.success)
        info = result.data
        self.assertTrue(info["has_member_id"])
        self.assertEqual(info["current_member_id"], "112233")
        self.assertFalse(info["can_assign_id"])
        self.assertIn("already has ID", info["explanation"])

    def test_eligible_member_can_assign(self):
        member = self.create_test_member(
            first_name="Debug",
            last_name="Eligible",
            email="debug.eligible@example.com",
        )
        frappe.db.set_value("Member", member.name, "member_id", None)
        member.reload()
        result = self.service.debug_member_id_assignment(member.name)
        self.assertTrue(result.success)
        info = result.data
        self.assertFalse(info["has_member_id"])
        # Non-application member is eligible -> can assign
        self.assertTrue(info["should_have_member_id"])
        self.assertTrue(info["can_assign_id"])
        self.assertIn("eligible", info["explanation"].lower())


if __name__ == "__main__":
    unittest.main()
