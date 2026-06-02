"""
Unit tests for the chapter membership workflow with pending status.

This test suite validates:
1. Status field functionality in Chapter Member doctype
2. Application submission with chapter selection
3. Pending Chapter Member record creation
4. Application approval and status activation
5. Report visibility and permissions
"""

from unittest.mock import patch

import frappe
from frappe.utils import now_datetime
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestChapterMembershipWorkflow(EnhancedTestCase):
    """Test the chapter membership workflow functionality"""

    def setUp(self):
        """Set up test data using Enhanced Test Factory and proper permissions"""
        super().setUp()

        # create_member_from_application runs member.insert() under
        # secure_user_context as a background system user. On a clean site that
        # user has System Manager but Customer "create" is only granted to
        # "Verenigingen Staff", so grant that role first.
        self._ensure_system_user_can_create_customers()

        # Use Enhanced Test Factory for test data creation
        # Store chapter NAME (string), not the document object
        # Functions like create_pending_chapter_membership expect chapter_name string
        # Don't pass 'title' - Chapter doctype doesn't have that field, factory auto-generates name
        chapter_doc = self.create_test_chapter(published=1)
        self.test_chapter = chapter_doc.name  # Store the name, not the document
            
        self.test_member_email = f"test-unit-{int(now_datetime().timestamp())}@example.com"
        # Unique last name so the auto-created Customer (named after full_name)
        # does not collide across tests now that customer creation succeeds.
        self.unique_last_name = f"TestUser{frappe.generate_hash(length=6)}"
        self.test_member_name = None

        # Get test membership type
        membership_types = frappe.get_all("Membership Type", limit=1)
        self.test_membership_type = membership_types[0]["name"] if membership_types else "Kwartaallid"

    def _ensure_system_user_can_create_customers(self):
        """Grant the background member-creation system user the Staff role."""
        from verenigingen.utils.secure_operations import get_system_user_for_operation

        system_user = get_system_user_for_operation("member_creation_during_application")
        if not frappe.db.exists("Has Role", {"parent": system_user, "role": "Verenigingen Staff"}):
            # Raw insert (not user.add_roles) to avoid the User on_update hooks that
            # enqueue work during tests. Idempotency is guarded above; include the
            # standard audit columns so the row isn't malformed (NULL creation/owner).
            now = frappe.utils.now()
            frappe.db.sql(
                """INSERT INTO `tabHas Role`
                    (name, parent, parenttype, parentfield, role, creation, modified, modified_by, owner)
                VALUES (%s, %s, 'User', 'roles', 'Verenigingen Staff', %s, %s, 'Administrator', 'Administrator')""",
                (frappe.generate_hash(length=10), system_user, now, now),
            )
            frappe.db.commit()
            frappe.clear_cache(user=system_user)

    def tearDown(self):
        """Clean up test data after each test"""
        try:
            # Clean up test member if created
            if self.test_member_name:
                if frappe.db.exists("Member", self.test_member_name):
                    # Remove from any chapters first
                    frappe.db.sql("DELETE FROM `tabChapter Member` WHERE member = %s", self.test_member_name)
                    frappe.delete_doc("Member", self.test_member_name, force=True)

            # Clean up by email as fallback
            member_by_email = frappe.db.get_value("Member", {"email": self.test_member_email}, "name")
            if member_by_email:
                frappe.db.sql("DELETE FROM `tabChapter Member` WHERE member = %s", member_by_email)
                frappe.delete_doc("Member", member_by_email, force=True)

        except Exception as e:
            print(f"Cleanup error (non-critical): {str(e)}")
        super().tearDown()

    def test_chapter_member_status_field_exists(self):
        """Test that the status field exists in Chapter Member doctype with correct options"""
        doctype_fields = frappe.get_meta("Chapter Member").fields
        status_field = next((f for f in doctype_fields if f.fieldname == "status"), None)

        self.assertIsNotNone(status_field, "Status field should exist in Chapter Member doctype")
        self.assertEqual(status_field.fieldtype, "Select", "Status field should be Select type")
        self.assertIn("Pending", status_field.options, "Status field should have Pending option")
        self.assertIn("Active", status_field.options, "Status field should have Active option")
        self.assertIn("Inactive", status_field.options, "Status field should have Inactive option")
        self.assertEqual(status_field.default, "Active", "Status field default should be Active")

    def test_create_member_with_chapter_selection(self):
        """Test creating a member through application with chapter selection"""
        from verenigingen.utils.application_helpers import (
            create_member_from_application,
            determine_chapter_from_application,
        )

        application_data = {
            "first_name": "Unit",
            "last_name": self.unique_last_name,
            "email": self.test_member_email,
            "birth_date": "1990-01-01",
            "address_line1": "Test Street 123",
            "city": "Test City",
            "postal_code": "1234AB",
            "country": "Netherlands",
            "selected_membership_type": self.test_membership_type,
            "selected_chapter": self.test_chapter}

        # Test chapter determination
        suggested_chapter = determine_chapter_from_application(application_data)
        self.assertEqual(
            suggested_chapter, self.test_chapter, "Chapter should be determined from application data"
        )

        # Test member creation
        application_id = f"TEST-{int(now_datetime().timestamp())}"
        # create_member_from_application already inserts the member (under
        # secure_user_context); do not insert again.
        member = create_member_from_application(application_data, application_id, None)
        self.test_member_name = member.name

        self.assertEqual(member.email, self.test_member_email, "Member email should match")
        self.assertEqual(
            member.application_status, "Pending", "Member should have pending application status"
        )

    def test_create_pending_chapter_membership(self):
        """Test creating a pending Chapter Member record"""
        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        # Create test member first
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Unit",
                "last_name": self.unique_last_name,
                "email": self.test_member_email,
                "birth_date": "1990-01-01",
                "status": "Pending",
                "application_status": "Pending"}
        )
        member.insert()  # EnhancedTestCase handles permissions
        self.test_member_name = member.name

        # Test pending chapter membership creation
        chapter_member = create_pending_chapter_membership(member, self.test_chapter)
        self.assertIsNotNone(chapter_member, "Pending chapter member should be created")

        # Verify the record was created in database
        pending_records = frappe.get_all(
            "Chapter Member",
            filters={"member": member.name, "parent": self.test_chapter, "status": "Pending"},
            fields=["status", "enabled", "chapter_join_date"],
        )

        self.assertEqual(len(pending_records), 1, "Should have exactly one pending record")
        self.assertEqual(pending_records[0]["status"], "Pending", "Status should be Pending")
        self.assertTrue(pending_records[0]["enabled"], "Record should be enabled")

    def test_activate_pending_chapter_membership(self):
        """Test activating a pending Chapter Member record"""
        from verenigingen.utils.application_helpers import (
            activate_pending_chapter_membership,
            create_pending_chapter_membership,
        )

        # Create test member and pending chapter membership
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Unit",
                "last_name": self.unique_last_name,
                "email": self.test_member_email,
                "birth_date": "1990-01-01",
                "status": "Pending",
                "application_status": "Pending"}
        )
        member.insert()  # EnhancedTestCase handles permissions
        self.test_member_name = member.name

        # Create pending record
        chapter_member = create_pending_chapter_membership(member, self.test_chapter)
        self.assertIsNotNone(chapter_member, "Pending chapter member should be created")

        # Test activation
        activated_member = activate_pending_chapter_membership(member, self.test_chapter)
        self.assertIsNotNone(activated_member, "Chapter member should be activated")

        # Verify the record was activated in database
        active_records = frappe.get_all(
            "Chapter Member",
            filters={"member": member.name, "parent": self.test_chapter, "status": "Active"},
            fields=["status", "enabled", "chapter_join_date"],
        )

        self.assertEqual(len(active_records), 1, "Should have exactly one active record")
        self.assertEqual(active_records[0]["status"], "Active", "Status should be Active")

    def test_member_approval_activates_chapter_membership(self):
        """Test that member approval activates pending chapter memberships"""
        # Create test member with pending status
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Unit",
                "last_name": self.unique_last_name,
                "email": self.test_member_email,
                "birth_date": "1990-01-01",
                "status": "Pending",
                "application_status": "Pending",
                "application_id": f"TEST-{int(now_datetime().timestamp())}",
                "selected_membership_type": self.test_membership_type,
                "current_chapter_display": self.test_chapter}
        )
        member.insert()  # EnhancedTestCase handles permissions
        self.test_member_name = member.name

        # Create pending chapter membership
        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        chapter_member = create_pending_chapter_membership(member, self.test_chapter)
        self.assertIsNotNone(chapter_member, "Pending chapter member should be created")

        # Approve via the canonical API path (T4.1 retired
        # Member.approve_application). The canonical path runs the full
        # membership creation pipeline; no need to patch.
        from verenigingen.api.membership_application_review import (
            approve_membership_application,
        )
        approve_membership_application(
            member_name=member.name,
            membership_type=member.selected_membership_type,
            chapter=None,
        )

        # Verify member was approved
        member.reload()
        self.assertEqual(member.application_status, "Approved", "Member should be approved")
        self.assertEqual(member.status, "Active", "Member should be active")

        # Verify chapter membership was activated
        active_records = frappe.get_all(
            "Chapter Member",
            filters={"member": member.name, "parent": self.test_chapter, "status": "Active"},
            fields=["status"],
        )

        self.assertEqual(len(active_records), 1, "Should have one active chapter membership")

    def test_chapter_members_report_shows_pending_to_admins(self):
        """Test that Chapter Members report shows pending members to administrators"""
        from verenigingen.verenigingen.report.chapter_members.chapter_members import (
            execute as chapter_members_report,
        )

        # Create test member with pending chapter membership
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Unit",
                "last_name": self.unique_last_name,
                "email": self.test_member_email,
                "birth_date": "1990-01-01",
                "status": "Pending",
                "application_status": "Pending"}
        )
        member.insert()  # EnhancedTestCase handles permissions
        self.test_member_name = member.name

        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        chapter_member = create_pending_chapter_membership(member, self.test_chapter)
        self.assertIsNotNone(chapter_member, "Pending chapter member should be created")

        # Run the report as a real admin user (patching frappe.session.user
        # directly breaks the report's own session access).
        original_user = frappe.session.user
        frappe.set_user("Administrator")
        try:
            columns, data = chapter_members_report({"chapter": self.test_chapter})
        finally:
            frappe.set_user(original_user)

        # Find our test member in results
        test_member_row = next((row for row in data if row.get("member") == member.name), None)
        self.assertIsNotNone(test_member_row, "Test member should appear in report for admins")
        self.assertEqual(test_member_row.get("status"), "Pending", "Status should be Pending in report")

    def test_chapter_members_report_hides_pending_from_regular_users(self):
        """Test that Chapter Members report hides pending members from regular users"""
        from verenigingen.verenigingen.report.chapter_members.chapter_members import (
            execute as chapter_members_report,
        )

        # Create test member with pending chapter membership
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Unit",
                "last_name": self.unique_last_name,
                "email": self.test_member_email,
                "birth_date": "1990-01-01",
                "status": "Pending",
                "application_status": "Pending"}
        )
        member.insert()  # EnhancedTestCase handles permissions
        self.test_member_name = member.name

        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        chapter_member = create_pending_chapter_membership(member, self.test_chapter)
        self.assertIsNotNone(chapter_member, "Pending chapter member should be created")

        # Run the report as a real regular (non-admin) member user. Heavy mocking
        # of frappe.session/get_value breaks the report internals, so act as the
        # actual target role instead.
        original_user = frappe.session.user
        regular_email = f"regular-{frappe.generate_hash(length=6)}@user.com"
        if not frappe.db.exists("User", regular_email):
            regular_user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": regular_email,
                    "first_name": "Regular",
                    "last_name": "User",
                    "enabled": 1,
                }
            )
            regular_user.insert(ignore_permissions=True)
            if frappe.db.exists("Role", "Verenigingen Member"):
                regular_user.add_roles("Verenigingen Member")

        frappe.set_user(regular_email)
        try:
            columns, data = chapter_members_report({"chapter": self.test_chapter})
            # Pending members should not be visible to a regular user
            test_member_row = next(
                (row for row in data if row.get("member") == member.name), None
            )
            self.assertIsNone(
                test_member_row, "Pending member should not be visible to regular users"
            )
        except frappe.exceptions.ValidationError:
            # Acceptable - regular users may be denied access to the report
            pass
        finally:
            frappe.set_user(original_user)

    def test_duplicate_pending_membership_prevention(self):
        """Test that duplicate pending memberships are prevented"""
        from verenigingen.utils.application_helpers import create_pending_chapter_membership

        # Create test member
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Unit",
                "last_name": self.unique_last_name,
                "email": self.test_member_email,
                "birth_date": "1990-01-01"}
        )
        member.insert()  # EnhancedTestCase handles permissions
        self.test_member_name = member.name

        # Create first pending membership
        first_result = create_pending_chapter_membership(member, self.test_chapter)
        self.assertIsNotNone(first_result, "First pending membership should be created")

        # Attempt to create duplicate - should return existing record reference or handle gracefully
        create_pending_chapter_membership(member, self.test_chapter)
        # Should either return existing record or None (not create duplicate)

        # Verify only one record exists
        pending_count = frappe.db.count(
            "Chapter Member", filters={"member": member.name, "parent": self.test_chapter}
        )
        self.assertEqual(pending_count, 1, "Should have only one chapter member record")

    def test_chapter_member_status_filtering(self):
        """Test filtering Chapter Members by status"""
        # Create test member
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Unit",
                "last_name": self.unique_last_name,
                "email": self.test_member_email,
                "birth_date": "1990-01-01"}
        )
        member.insert()  # EnhancedTestCase handles permissions
        self.test_member_name = member.name

        # Create pending membership
        from verenigingen.utils.application_helpers import (
            activate_pending_chapter_membership,
            create_pending_chapter_membership,
        )

        pending_member = create_pending_chapter_membership(member, self.test_chapter)
        self.assertIsNotNone(pending_member, "Pending membership should be created")

        # Test filtering by status
        pending_members = frappe.get_all(
            "Chapter Member",
            filters={"parent": self.test_chapter, "status": "Pending"},
            fields=["member", "status"],
        )

        test_pending = next((m for m in pending_members if m["member"] == member.name), None)
        self.assertIsNotNone(test_pending, "Should find pending member in filter")
        self.assertEqual(test_pending["status"], "Pending", "Status should be Pending")

        # Activate membership
        activated_member = activate_pending_chapter_membership(member, self.test_chapter)
        self.assertIsNotNone(activated_member, "Membership should be activated")

        # Test filtering active members
        active_members = frappe.get_all(
            "Chapter Member",
            filters={"parent": self.test_chapter, "status": "Active"},
            fields=["member", "status"],
        )

        test_active = next((m for m in active_members if m["member"] == member.name), None)
        self.assertIsNotNone(test_active, "Should find active member in filter")
        self.assertEqual(test_active["status"], "Active", "Status should be Active")


def run_tests():
    """Run the chapter membership workflow tests"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        # Run the test suite
        suite = unittest.TestLoader().loadTestsFromTestCase(TestChapterMembershipWorkflow)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        print("\n=== TEST RESULTS ===")
        print(f"Tests run: {result.testsRun}")
        print(f"Failures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")

        if result.failures:
            print("\nFAILURES:")
            for test, traceback in result.failures:
                print(f"- {test}: {traceback}")

        if result.errors:
            print("\nERRORS:")
            for test, traceback in result.errors:
                print(f"- {test}: {traceback}")

        return result.wasSuccessful()

    finally:
        frappe.destroy()


if __name__ == "__main__":
    run_tests()
