# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Integration tests for services/member/core/member_id_service.py.

This is the module-level ID-generation service (distinct from the
identification/member_id_service.py MemberIDService class). Covers sequential
member-ID generation/increment, application-ID format + uniqueness, uniqueness
validation, and the ensure/force-assign helpers on real Member docs.
"""

import unittest

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.services.member.core.member_id_service import (
    ensure_member_has_id,
    force_assign_member_id,
    generate_application_id,
    generate_member_id,
    validate_id_uniqueness,
)


class TestGenerateMemberId(EnhancedTestCase):
    def test_member_id_is_numeric_string(self):
        member_id = generate_member_id()
        self.assertIsInstance(member_id, str)
        self.assertTrue(member_id.isdigit(), f"member_id {member_id!r} should be numeric")

    def test_member_id_increments(self):
        """Successive calls return strictly increasing IDs."""
        first = int(generate_member_id())
        second = int(generate_member_id())
        self.assertGreater(second, first)

    def test_member_id_unique_in_db(self):
        """A freshly generated ID does not collide with an existing member."""
        member_id = generate_member_id()
        self.assertFalse(frappe.db.exists("Member", {"member_id": member_id}))


class TestGenerateApplicationId(EnhancedTestCase):
    def test_application_id_format(self):
        app_id = generate_application_id()
        # APP-YYYYMMDD-XXXX
        self.assertRegex(app_id, r"^APP-\d{8}-[0-9A-F]{3,4}$")

    def test_application_id_unique(self):
        a = generate_application_id()
        b = generate_application_id()
        # Not guaranteed distinct by format alone, but neither should already
        # exist on a Member at generation time.
        self.assertFalse(frappe.db.exists("Member", {"application_id": a}))
        self.assertFalse(frappe.db.exists("Member", {"application_id": b}))

    def test_application_id_avoids_existing(self):
        """Generation never returns an application_id already on a Member."""
        member = self.create_test_member(
            first_name="App",
            last_name="Existing",
            email="app.existing@example.com",
        )
        existing_app_id = generate_application_id()
        frappe.db.set_value("Member", member.name, "application_id", existing_app_id)
        # Next generation must not collide with the one we just stored
        for _ in range(5):
            new_id = generate_application_id()
            self.assertNotEqual(new_id, existing_app_id)


class TestValidateIdUniqueness(EnhancedTestCase):
    def test_empty_id_not_unique(self):
        self.assertFalse(validate_id_uniqueness(None))
        self.assertFalse(validate_id_uniqueness(""))

    def test_existing_member_id_not_unique(self):
        member = self.create_test_member(
            first_name="Uniq",
            last_name="Member",
            email="uniq.member@example.com",
        )
        # Assign a known member_id
        frappe.db.set_value("Member", member.name, "member_id", "990011")
        self.assertFalse(validate_id_uniqueness("990011", id_type="member_id"))

    def test_unused_id_is_unique(self):
        self.assertTrue(validate_id_uniqueness("ZZZ-NONEXISTENT-99887766"))

    def test_application_id_uniqueness_field(self):
        member = self.create_test_member(
            first_name="Uniq",
            last_name="App",
            email="uniq.app@example.com",
        )
        frappe.db.set_value("Member", member.name, "application_id", "APP-19990101-ABCD")
        self.assertFalse(validate_id_uniqueness("APP-19990101-ABCD", id_type="application_id"))
        self.assertTrue(validate_id_uniqueness("APP-19990101-WXYZ", id_type="application_id"))


class TestEnsureMemberHasId(EnhancedTestCase):
    def test_assigns_when_eligible_and_missing(self):
        """A non-application member without a member_id gets one assigned."""
        member = self.create_test_member(
            first_name="Ensure",
            last_name="Eligible",
            email="ensure.eligible@example.com",
        )
        # Clear any auto-assigned id to exercise the assignment branch
        member.member_id = None
        result = ensure_member_has_id(member)
        self.assertTrue(result.success)
        self.assertTrue(result.data)
        member.reload()
        self.assertEqual(str(member.member_id), str(result.data))

    def test_fails_when_already_has_id(self):
        member = self.create_test_member(
            first_name="Ensure",
            last_name="Has",
            email="ensure.has@example.com",
        )
        member.member_id = "123456"
        result = ensure_member_has_id(member)
        self.assertFalse(result.success)


class TestForceAssignMemberId(EnhancedTestCase):
    def test_force_assign_as_system_manager(self):
        """System Manager (the test runner user) can force-assign an ID."""
        member = self.create_test_member(
            first_name="Force",
            last_name="Assign",
            email="force.assign@example.com",
        )
        member.member_id = None
        result = force_assign_member_id(member)
        self.assertTrue(result.success)
        self.assertTrue(result.data)
        self.assertTrue(str(result.data).isdigit())

    def test_force_assign_fails_if_already_has_id(self):
        member = self.create_test_member(
            first_name="Force",
            last_name="Dup",
            email="force.dup@example.com",
        )
        member.member_id = "777888"
        result = force_assign_member_id(member)
        self.assertFalse(result.success)
        self.assertEqual(result.metadata.get("existing_id"), "777888")


if __name__ == "__main__":
    unittest.main()
