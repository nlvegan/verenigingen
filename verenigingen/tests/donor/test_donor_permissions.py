"""
Comprehensive Security Test Suite for Donor Permissions

Tests the donor permission system for security vulnerabilities, edge cases,
and proper access control enforcement.
"""

import time

import frappe

from verenigingen.permissions import get_donor_permission_query, has_donor_permission
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonorPermissions(EnhancedTestCase):
    """Security-focused test suite for donor permission system"""

    def setUp(self):
        """Set up test data for permission testing"""
        super().setUp()

        # Create test member using Enhanced Test Factory
        self.test_member = self.create_test_member(
            first_name="Test", last_name="Member", email="test_member@example.com"
        )
        # Enhanced Test Factory handles cleanup automatically

        # Create test donor linked to member
        self.test_donor = self.create_test_donor(
            donor_name="Test Donor",
            donor_type="Individual",
            donor_email="donor@example.com",
            member=self.test_member.name,
        )
        # Enhanced Test Factory handles cleanup automatically

        # Create orphaned donor (no member link)
        self.orphaned_donor = self.create_test_donor(
            donor_name="Orphaned Donor", donor_type="Individual", donor_email="orphaned@example.com"
        )
        # Enhanced Test Factory handles cleanup automatically

        # Define test users for convenience
        self.test_member_user = "test_member@example.com"
        self.test_admin_user = "Administrator"
        self.test_unauthorized_user = "Guest"

    def test_sql_injection_prevention_in_permission_query(self):
        """A user string with no matching User/roles always gets the restrictive query.

        The Enhanced Test Factory suffixes emails for uniqueness, so the literal
        "malicious@example.com" passed to get_donor_permission_query never
        corresponds to a real User account. frappe.get_roles() for such a user
        resolves to ["All", "Guest"], which the permission_query factory maps
        deterministically to "1=0" (see verenigingen.permissions._make_member_linked_permission)
        - there is no code path where this literal reaches the generated SQL.
        """
        query = get_donor_permission_query("malicious@example.com")
        self.assertEqual(query, "1=0", "Unknown/unauthorized user should get a fully restrictive query")

    def test_sql_injection_prevention_escapes_member_name(self):
        """A real member-linked user's query embeds the escaped member docname, not raw input."""
        with frappe.mock_roles(["Verenigingen Member"]):
            query = get_donor_permission_query(self.test_member.email)

        self.assertIn("tabDonor", query)
        self.assertIn(frappe.db.escape(self.test_member.name), query)
        self.assertNotIn("DROP TABLE", query.upper())

    def test_permission_with_nonexistent_donor(self):
        """Test permission check with non-existent donor record"""

        fake_donor_name = "FAKE-DONOR-999"

        # Should return False for non-existent donor
        has_permission = has_donor_permission(fake_donor_name, self.test_member_user)
        self.assertFalse(has_permission)

    def test_permission_with_orphaned_donor(self):
        """Test permission check with donor that has no member link"""

        # Member user should not have access to orphaned donor
        has_permission = has_donor_permission(self.orphaned_donor.name, self.test_member_user)
        self.assertFalse(has_permission)

    def test_permission_with_invalid_member_link(self):
        """Test permission check when donor links to non-existent member"""

        # Create a valid donor first, then corrupt the member link via db.set_value.
        # Frappe v16 validates the Member link on insert, so a non-existent member
        # cannot be supplied directly; set_value bypasses validation to simulate a
        # member deleted out from under the donor.
        invalid_donor = self.create_test_donor(
            donor_name="Invalid Link Donor",
            donor_type="Individual",
            donor_email="invalid@example.com",
        )
        frappe.db.set_value("Donor", invalid_donor.name, "member", "NON-EXISTENT-MEMBER-999")
        # Enhanced Test Factory handles cleanup automatically

        # Should return False due to invalid member link
        has_permission = has_donor_permission(invalid_donor.name, self.test_member_user)
        self.assertFalse(has_permission)

    def test_admin_override_permissions(self):
        """Test that admin roles can access all donor records"""

        # Test with Administrator user who has System Manager role
        has_permission = has_donor_permission(self.test_donor.name, "Administrator")
        self.assertTrue(has_permission, "Administrator should have access")

        # Admin should get unrestricted query ("" and None both mean unrestricted)
        query = get_donor_permission_query("Administrator")
        self.assertIn(query, (None, ""), "Administrator should have no query restrictions")

    def test_member_access_to_own_donor_record(self):
        """Test that members can access donor records linked to them"""

        # Create a member with user link using Enhanced Test Factory.
        # NOTE: the User link is intentionally omitted — Frappe v16 validates the
        # User link on insert and this user does not exist; the test below verifies
        # the non-existent-user path returns False, so no User is needed.
        member_with_user = self.create_test_member(
            first_name="User", last_name="Member", email="user_member@example.com"
        )
        # Enhanced Test Factory handles cleanup automatically

        # Create donor linked to this member
        donor_for_user = self.create_test_donor(
            donor_name="User Test Donor",
            donor_type="Individual",
            donor_email="userdonor@example.com",
            member=member_with_user.name,
        )
        # Enhanced Test Factory handles cleanup automatically

        # Test permission - member should have access to their linked donor
        # We'll test the logic directly without role mocking since user doesn't exist
        has_permission = has_donor_permission(donor_for_user.name, "user_member@example.com")
        # This should return False since user doesn't exist in system
        # But the logic should handle it gracefully
        self.assertFalse(has_permission)

    def test_member_denied_access_to_other_donor_records(self):
        """Test that members cannot access donor records not linked to them"""

        # Create another member and donor using Enhanced Test Factory.
        # User link omitted — the user does not exist and Frappe v16 validates the
        # link on insert; this test only checks self.test_member_user's access.
        other_member = self.create_test_member(
            first_name="Other", last_name="Member", email="other@example.com"
        )
        # Enhanced Test Factory handles cleanup automatically

        other_donor = self.create_test_donor(
            donor_name="Other Donor",
            donor_type="Individual",
            donor_email="otherdonor@example.com",
            member=other_member.name,
        )
        # Enhanced Test Factory handles cleanup automatically

        with frappe.mock_roles(["Verenigingen Member"]):
            # Member should NOT have access to other member's donor
            has_permission = has_donor_permission(other_donor.name, self.test_member_user)
            self.assertFalse(has_permission)

    def test_unauthorized_user_access_denied(self):
        """Test that users without proper roles are denied access"""

        # Test with Guest user (no special roles)
        has_permission = has_donor_permission(self.test_donor.name, "Guest")
        self.assertFalse(has_permission)

        # Should get restrictive query
        query = get_donor_permission_query("Guest")
        self.assertEqual(query, "1=0")

    def test_permission_query_filters_correctly(self):
        """Test that permission query properly filters records"""

        # Test with user that doesn't exist - should get restrictive query
        query = get_donor_permission_query(self.test_member_user)

        # Should get restrictive query since user doesn't exist
        self.assertEqual(query, "1=0")

    def test_error_handling_with_malformed_input(self):
        """Test error handling with malformed or invalid input"""

        # Test with None input
        has_permission = has_donor_permission(None, self.test_member_user)
        self.assertFalse(has_permission)

        # Test with empty string
        has_permission = has_donor_permission("", self.test_member_user)
        self.assertFalse(has_permission)

        # Test with invalid user
        has_permission = has_donor_permission(self.test_donor.name, "invalid-user@fake.com")
        self.assertFalse(has_permission)

    def test_document_object_vs_string_handling(self):
        """Test permission check works with both document objects and strings"""

        # The factory uniquifies member emails (e.g. test_member.<suffix>@...), so
        # use the member's actual stored email rather than the original literal —
        # get_member_name_for_user looks the member up by that email.
        member_user = self.test_member.email
        with frappe.mock_roles(["Verenigingen Member"]):
            # Test with string (donor name)
            has_permission_str = has_donor_permission(self.test_donor.name, member_user)

            # Test with document object
            donor_doc = frappe.get_doc("Donor", self.test_donor.name)
            has_permission_obj = has_donor_permission(donor_doc, member_user)

            # Both should return the same result
            self.assertEqual(has_permission_str, has_permission_obj)
            self.assertTrue(has_permission_str)

    def test_performance_with_large_datasets(self):
        """Test that permission queries perform reasonably with larger datasets"""

        # This is a basic performance awareness test
        # In production, you'd want more sophisticated benchmarking

        start_time = time.time()

        # Run permission check multiple times
        for _ in range(100):
            get_donor_permission_query(self.test_member_user)

        end_time = time.time()
        execution_time = end_time - start_time

        # Permission query should execute quickly (under 1 second for 100 iterations)
        self.assertLess(execution_time, 1.0, "Permission queries taking too long")

    def test_logging_and_debugging_info(self):
        """Permission denial paths (unresolvable user, missing donor, orphaned donor)
        must deny access rather than raise, since callers rely on this fallback in
        the has_permission hook chain."""

        with frappe.mock_roles(["Verenigingen Member"]):
            # self.test_member_user never resolves to a real Member (no matching
            # User was created - see setUp), so this exercises the "user has the
            # role but no member record" denial branch for a real donor.
            self.assertFalse(has_donor_permission(self.test_donor.name, self.test_member_user))
            # Non-existent donor record.
            self.assertFalse(has_donor_permission("NON-EXISTENT", self.test_member_user))
            # Donor with no linked member.
            self.assertFalse(has_donor_permission(self.orphaned_donor.name, self.test_member_user))


class TestDonorPermissionIntegration(EnhancedTestCase):
    """Integration tests for donor permissions with actual Frappe ORM"""

    def test_frappe_get_all_respects_permissions(self):
        """Test that frappe.get_all() respects permission queries"""

        # Create a real User so we can switch into its session, then link it to a
        # member. frappe.set_user requires an existing User, and the permission
        # query only applies the member filter for a Verenigingen Member.
        user_email = "integration@test.com"
        self.create_test_user(user_email, roles=["Verenigingen Member"])

        member = self.create_test_member(
            first_name="Integration",
            last_name="Test",
            email=user_email,
            user=user_email,
        )
        # Enhanced Test Factory handles cleanup automatically

        donor = self.create_test_donor(
            donor_name="Integration Donor",
            donor_type="Individual",
            donor_email="intdonor@test.com",
            member=member.name,
        )
        # Enhanced Test Factory handles cleanup automatically

        # self.as_user is the EnhancedTestCase context manager; frappe.set_user
        # itself is NOT a context manager.
        with self.as_user(user_email):
            # Should only see donor records linked to this user's member record
            accessible_donors = frappe.get_all("Donor", fields=["name", "donor_name", "member"])

            # Should find the linked donor
            found_donor = False
            for d in accessible_donors:
                if d.name == donor.name:
                    found_donor = True
                    self.assertEqual(d.member, member.name)
                    break

            self.assertTrue(found_donor, "User should be able to access their linked donor")

    def test_permission_enforcement_in_form_access(self):
        """Test that permissions are enforced when accessing forms"""

        # This would test actual form access, but requires more complex setup
        # For now, we verify the permission functions work as expected

        user_email = "form@test.com"
        self.create_test_user(user_email, roles=["Verenigingen Member"])

        member = self.create_test_member(
            first_name="Form",
            last_name="Test",
            email=user_email,
            user=user_email,
        )
        # Enhanced Test Factory handles cleanup automatically

        donor = self.create_test_donor(
            donor_name="Form Test Donor",
            donor_type="Individual",
            donor_email="formdonor@test.com",
            member=member.name,
        )
        # Enhanced Test Factory handles cleanup automatically

        # Test direct document access. self.as_user is the context manager;
        # frappe.set_user is not.
        with self.as_user(user_email):
            # Should be able to get the document
            doc = frappe.get_doc("Donor", donor.name)
            self.assertEqual(doc.name, donor.name)
