"""

Chapter Board Member Permissions Test Suite
===========================================

Comprehensive test suite for Chapter Board Member permission system including:
- Chapter-based data filtering for memberships and termination requests
- Treasurer-only expense approval validation
- Automatic role assignment and removal
- Security boundary validation and privilege escalation prevention
- Cross-chapter access restriction testing

This test suite validates the complete permission system implementation
to ensure proper security boundaries and functional correctness.
"""

from verenigingen.utils.validation_utilities import DocumentExistenceValidator

import frappe
import unittest
from unittest.mock import patch, MagicMock
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.skip_reasons import VOLUNTEER_EXPENSE_ARCHIVED


def _ensure_test_region():
    """Idempotently ensure a "Test Region" exists and return its docname.

    Region autoname is field:region_name, which slugifies "Test Region" to the
    docname "test-region". The Enhanced create_chapter factory only rewrites the
    region kwarg to the slug when it creates the region; if the slug already
    exists it leaves the literal "Test Region" in place, which then fails link
    validation. Creating it here and passing back the slug avoids that.
    """
    slug = "test-region"
    if not frappe.db.exists("Region", slug):
        region = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": "Test Region",
                "region_code": "TR",
                "country": "Netherlands",
                "is_active": 1,
            }
        )
        region.insert(ignore_permissions=True)
    return slug


class TestChapterBoardPermissions(EnhancedTestCase):
    """
    Test Chapter Board Member permissions system
    """

    def setUp(self):
        """Set up test data for permission testing"""
        super().setUp()

        # Create test chapters
        self.chapter_1 = self.create_chapter(chapter_name="Test Chapter 1", region=_ensure_test_region())

        self.chapter_2 = self.create_chapter(chapter_name="Test Chapter 2", region=_ensure_test_region())

        # Create test members and volunteers. The permission functions resolve
        # the acting user -> Member -> Volunteer -> board Chapter, so the board
        # members must be backed by real User accounts.
        board_user_1 = self.create_test_user(email="board1@test.com", roles=["Verenigingen Member"])
        board_user_2 = self.create_test_user(email="board2@test.com", roles=["Verenigingen Member"])

        self.board_member_1 = self.create_test_member(
            first_name="Board",
            last_name="Member1",
            email="board1@test.com",
            user=board_user_1.name,
        )

        self.board_member_2 = self.create_test_member(
            first_name="Board",
            last_name="Member2",
            email="board2@test.com",
            user=board_user_2.name,
        )

        self.regular_member = self.create_test_member(
            first_name="Regular", last_name="Member", email="regular@test.com"
        )

        # Create volunteers for board members
        self.volunteer_1 = self.create_test_volunteer(self.board_member_1.name)
        self.volunteer_2 = self.create_test_volunteer(self.board_member_2.name)

        # Create chapter roles
        self.treasurer_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": "Treasurer",
                "permissions_level": "Financial",
                "is_unique": 1,
                "is_active": 1,
            }
        )
        self.treasurer_role.save()

        self.secretary_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": "Secretary",
                "permissions_level": "Basic",
                "is_unique": 1,
                "is_active": 1,
            }
        )
        self.secretary_role.save()

        # Create board positions
        self.board_position_1 = frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": self.chapter_1.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": self.volunteer_1.name,
                "chapter_role": self.treasurer_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            }
        )
        self.board_position_1.insert()

        self.board_position_2 = frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": self.chapter_2.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": self.volunteer_2.name,
                "chapter_role": self.secretary_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            }
        )
        self.board_position_2.insert()

        # Add members to chapters
        self.add_member_to_chapter(self.board_member_1.name, self.chapter_1.name)
        self.add_member_to_chapter(self.board_member_2.name, self.chapter_2.name)
        self.add_member_to_chapter(self.regular_member.name, self.chapter_1.name)

        frappe.db.commit()

    def test_membership_chapter_filtering(self):
        """Board members see only memberships of members in their own chapter.

        Chapter scoping for Membership is enforced by the permission QUERY
        (get_membership_permission_query), mirroring the Member/Employee/Donor
        scoping. The has_membership_permission hook only short-circuits for admins
        (returns None otherwise to defer to DocPerm + the query).
        """
        from verenigingen.permissions import get_membership_permission_query

        # Membership for the regular member, who belongs to chapter 1
        membership = self.create_test_membership(
            member=self.regular_member.name,
            membership_type="Basic Membership",
            start_date=frappe.utils.today(),
        )

        def membership_visible_to(user):
            condition = get_membership_permission_query(user)
            # Non-admin board members must be scoped, never granted the open "" query
            self.assertTrue(condition, f"Expected a scoping condition for {user}")
            rows = frappe.db.sql(
                f"SELECT name FROM `tabMembership` WHERE name = %s AND {condition}",
                membership.name,
            )
            return bool(rows)

        # Board member 1 (chapter 1) sees it; board member 2 (chapter 2) does not.
        self.assertTrue(
            membership_visible_to(self.board_member_1.email),
            "Board member should see memberships from their own chapter",
        )
        self.assertFalse(
            membership_visible_to(self.board_member_2.email),
            "Board member should not see memberships from other chapters",
        )

    def test_termination_request_chapter_filtering(self):
        """Test that board members can only access termination requests for their chapter members"""
        from verenigingen.permissions import has_membership_termination_request_permission

        # Create termination request for regular member (in chapter 1)
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.regular_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test termination",
                "requested_by": frappe.session.user,
            }
        )
        termination_request.save()

        # Board member 1 (chapter 1) should have access
        with self.set_user(self.board_member_1.email):
            self.assertTrue(
                has_membership_termination_request_permission(termination_request, self.board_member_1.email),
                "Board member should have access to termination requests for their chapter members",
            )

        # Board member 2 (chapter 2) should not have access
        with self.set_user(self.board_member_2.email):
            self.assertFalse(
                has_membership_termination_request_permission(termination_request, self.board_member_2.email),
                "Board member should not have access to termination requests from other chapters",
            )

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_volunteer_expense_chapter_filtering(self):
        """Test that board members can only see expenses from their chapters"""
        from verenigingen.permissions import has_volunteer_expense_permission

        # Create volunteer expense for chapter 1
        volunteer_expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.volunteer_1.name,
                "expense_date": frappe.utils.today(),
                "category": "Travel",
                "description": "Test expense",
                "amount": 100.00,
                "organization_type": "Chapter",
                "chapter": self.chapter_1.name,
                "company": "Test Company",
            }
        )
        volunteer_expense.save()

        # Board member 1 (chapter 1) should have access
        with self.set_user(self.board_member_1.email):
            self.assertTrue(
                has_volunteer_expense_permission(volunteer_expense, self.board_member_1.email),
                "Board member should have access to expenses from their chapter",
            )

        # Board member 2 (chapter 2) should not have access
        with self.set_user(self.board_member_2.email):
            self.assertFalse(
                has_volunteer_expense_permission(volunteer_expense, self.board_member_2.email),
                "Board member should not have access to expenses from other chapters",
            )

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_treasurer_expense_approval(self):
        """Test that only treasurers can approve volunteer expenses"""
        from verenigingen.permissions import can_approve_volunteer_expense

        # Create volunteer expense for chapter 1
        volunteer_expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.volunteer_1.name,
                "expense_date": frappe.utils.today(),
                "category": "Travel",
                "description": "Test expense",
                "amount": 100.00,
                "organization_type": "Chapter",
                "chapter": self.chapter_1.name,
                "company": "Test Company",
            }
        )
        volunteer_expense.save()

        # Board member 1 (treasurer in chapter 1) should be able to approve
        with self.set_user(self.board_member_1.email):
            self.assertTrue(
                can_approve_volunteer_expense(volunteer_expense, self.board_member_1.email),
                "Treasurer should be able to approve expenses",
            )

        # Board member 2 (secretary in chapter 2) should not be able to approve
        with self.set_user(self.board_member_2.email):
            self.assertFalse(
                can_approve_volunteer_expense(volunteer_expense, self.board_member_2.email),
                "Non-treasurer board member should not be able to approve expenses",
            )

    def test_automatic_role_assignment(self):
        """Test automatic Chapter Board Member role assignment"""
        from verenigingen.permissions import assign_chapter_board_role

        # Clear any existing roles
        frappe.db.delete(
            "Has Role", {"parent": self.board_member_1.email, "role": "Verenigingen Chapter Board Member"}
        )

        # Assign role based on board position
        result = assign_chapter_board_role(self.board_member_1.email)

        self.assertTrue(result, "Role assignment should succeed")

        # Verify role was assigned
        has_role = DocumentExistenceValidator.check_document_exists(
            "Has Role", {"parent": self.board_member_1.email, "role": "Verenigingen Chapter Board Member"}
        )

        self.assertTrue(has_role, "Chapter Board Member role should be assigned")

    def test_automatic_role_removal(self):
        """Test automatic Chapter Board Member role removal when board position ends"""
        from verenigingen.permissions import assign_chapter_board_role

        # Ensure user has role initially
        assign_chapter_board_role(self.board_member_1.email)

        # Deactivate board position
        self.board_position_1.is_active = 0
        self.board_position_1.save()

        # Re-evaluate role assignment
        assign_chapter_board_role(self.board_member_1.email)

        # Verify role was removed
        has_role = DocumentExistenceValidator.check_document_exists(
            "Has Role", {"parent": self.board_member_1.email, "role": "Verenigingen Chapter Board Member"}
        )

        self.assertFalse(has_role, "Chapter Board Member role should be removed when position ends")

    def test_permission_query_security(self):
        """Test that permission queries prevent cross-chapter data access"""
        from verenigingen.permissions import get_member_permission_query

        with self.set_user(self.board_member_1.email):
            # Get permission query for board member 1
            query_condition = get_member_permission_query(self.board_member_1.email)

            # Query condition should include chapter restriction
            self.assertIsNotNone(query_condition, "Permission query should return conditions")
            self.assertIn("Chapter Member", query_condition, "Query should reference Chapter Member table")

    def test_security_validation_no_privilege_escalation(self):
        """Test that board members cannot escalate privileges beyond their chapter scope"""
        from verenigingen.utils.chapter_board_permissions import validate_permission_security

        # Run security validation
        is_valid, issues = validate_permission_security()

        # Should pass security validation
        self.assertTrue(is_valid, f"Security validation should pass. Issues found: {issues}")
        self.assertEqual(len(issues), 0, "No security issues should be found")

    def test_cross_chapter_access_prevention(self):
        """Test that board members cannot access data from other chapters"""

        # Create member in chapter 2
        other_member = self.create_test_member(first_name="Other", last_name="Member", email="other@test.com")
        self.add_member_to_chapter(other_member.name, self.chapter_2.name)

        # Create membership in chapter 2
        other_membership = self.create_test_membership(
            member=other_member.name, membership_type="Basic Membership", start_date=frappe.utils.today()
        )

        # Board member 1 (chapter 1) should not have access to chapter 2 data
        with self.set_user(self.board_member_1.email):
            from verenigingen.permissions import has_membership_permission

            access_granted = has_membership_permission(other_membership, self.board_member_1.email)

            self.assertFalse(
                access_granted, "Board member should not have access to memberships from other chapters"
            )

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_expense_approval_workflow_validation(self):
        """Test that expense approval workflow properly validates treasurer permissions"""
        from verenigingen.utils.chapter_role_events import before_volunteer_expense_submit

        # Create expense
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.volunteer_1.name,
                "expense_date": frappe.utils.today(),
                "category": "Travel",
                "description": "Test expense",
                "amount": 100.00,
                "organization_type": "Chapter",
                "chapter": self.chapter_1.name,
                "company": "Test Company",
                "status": "Approved",  # Try to set to approved
            }
        )

        # Should allow treasurer to approve (board member 1)
        with self.set_user(self.board_member_1.email):
            try:
                before_volunteer_expense_submit(expense, "on_submit")
                # Should not raise exception
            except frappe.PermissionError:
                self.fail("Treasurer should be able to approve expenses")

        # Should not allow non-treasurer to approve (board member 2)
        with self.set_user(self.board_member_2.email):
            with self.assertRaises(frappe.PermissionError):
                before_volunteer_expense_submit(expense, "on_submit")

    def add_member_to_chapter(self, member_name, chapter_name):
        """Helper method to add member to chapter"""
        chapter_member = frappe.get_doc(
            {
                "doctype": "Chapter Member",
                "parent": chapter_name,
                "parenttype": "Chapter",
                "parentfield": "members",
                "member": member_name,
                "status": "Active",
                "chapter_join_date": frappe.utils.today(),
            }
        )
        chapter_member.insert()
        return chapter_member

    def create_test_membership(self, member, membership_type, start_date):
        """Helper method to create test membership"""
        from verenigingen.tests.fixtures.test_data_factory import ensure_membership_type_exists

        # Ensure the referenced Membership Type exists (fresh sites do not seed
        # "Basic Membership"), otherwise the insert fails link validation.
        membership_type = ensure_membership_type_exists(membership_type)

        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member,
                "membership_type": membership_type,
                "start_date": start_date,
                "status": "Active",
            }
        )
        membership.save()
        membership.submit()
        # EnhancedTestCase cleans up via transaction rollback (no track_doc).
        return membership


class TestChapterBoardRoleManagement(EnhancedTestCase):
    """
    Test automatic role assignment and management
    """

    def setUp(self):
        """Set up test data for role management testing"""
        super().setUp()

        self.test_user = self.create_test_user("testboard@example.com")
        self.test_member = self.create_test_member(
            first_name="Test", last_name="Board", email="testboard@example.com", user=self.test_user.name
        )

        self.test_chapter = self.create_chapter(chapter_name="Test Chapter", region=_ensure_test_region())

        self.test_volunteer = self.create_test_volunteer(self.test_member.name)

        self.test_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": "Test Board Role",
                "permissions_level": "Basic",
                "is_active": 1,
            }
        )
        self.test_role.save()

    def test_role_assignment_on_board_member_creation(self):
        """Test that Chapter Board Member role is automatically assigned when board position is created"""

        # Ensure user doesn't have role initially
        frappe.db.delete(
            "Has Role", {"parent": self.test_user.name, "role": "Verenigingen Chapter Board Member"}
        )

        # Create board position
        board_member = frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": self.test_chapter.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": self.test_volunteer.name,
                "chapter_role": self.test_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            }
        )
        board_member.insert()

        # Verify role was assigned
        has_role = DocumentExistenceValidator.check_document_exists(
            "Has Role", {"parent": self.test_user.name, "role": "Verenigingen Chapter Board Member"}
        )

        self.assertTrue(has_role, "Chapter Board Member role should be automatically assigned")

    def test_role_removal_on_board_member_deletion(self):
        """Test that Chapter Board Member role is removed when all board positions are deleted"""

        # Create board position
        board_member = frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": self.test_chapter.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": self.test_volunteer.name,
                "chapter_role": self.test_role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            }
        )
        board_member.insert()

        # Verify role was assigned
        has_role_before = DocumentExistenceValidator.check_document_exists(
            "Has Role", {"parent": self.test_user.name, "role": "Verenigingen Chapter Board Member"}
        )
        self.assertTrue(has_role_before, "Role should be assigned after board position creation")

        # Delete board position
        board_member.delete()

        # Verify role was removed
        has_role_after = DocumentExistenceValidator.check_document_exists(
            "Has Role", {"parent": self.test_user.name, "role": "Verenigingen Chapter Board Member"}
        )

        self.assertFalse(
            has_role_after, "Chapter Board Member role should be removed when position is deleted"
        )

    def test_bulk_role_synchronization(self):
        """Test bulk synchronization of Chapter Board Member roles"""
        from verenigingen.permissions import update_all_chapter_board_roles

        # Create multiple board positions
        for i in range(3):
            user = self.create_test_user(f"board{i}@example.com")
            member = self.create_test_member(
                first_name=f"Board{i}", last_name="Member", email=f"board{i}@example.com", user=user.name
            )
            volunteer = self.create_test_volunteer(member.name)

            board_member = frappe.get_doc(
                {
                    "doctype": "Chapter Board Member",
                    "parent": self.test_chapter.name,
                    "parenttype": "Chapter",
                    "parentfield": "board_members",
                    "volunteer": volunteer.name,
                    "chapter_role": self.test_role.name,
                    "from_date": frappe.utils.today(),
                    "is_active": 1,
                }
            )
            board_member.insert()

        # Run bulk synchronization
        updated_count = update_all_chapter_board_roles()

        self.assertGreaterEqual(updated_count, 3, "Should update at least 3 board member roles")

    def create_test_user(self, email, roles=None):
        """Create a test user, delegating to the base factory.

        The previous implementation called itself recursively with a `roles`
        kwarg it did not accept (TypeError). Delegate to the base
        create_test_user (which accepts and applies roles), defaulting to the
        Employee role these board tests expect.
        """
        if DocumentExistenceValidator.check_document_exists("User", email):
            return frappe.get_doc("User", email)

        return super().create_test_user(email=email, roles=roles or ["Employee"])


class TestPermissionIntegration(EnhancedTestCase):
    """
    Integration tests for the complete permission system
    """

    def test_setup_chapter_board_permissions_api(self):
        """Test the API for setting up chapter board permissions"""
        from verenigingen.utils.chapter_board_permissions import setup_chapter_board_permissions

        result = setup_chapter_board_permissions()

        # "Volunteer Expense" has been archived/dropped, so its permission update
        # returns False and overall result["success"] can no longer be True. Assert
        # the live (non-archived) doctype permissions succeed plus security checks.
        self.assertTrue(result["results"]["membership"], f"Membership perms should succeed: {result}")
        self.assertTrue(
            result["results"]["termination_request"],
            f"Termination request perms should succeed: {result}",
        )
        self.assertTrue(result["security_valid"], "Security validation should pass")
        self.assertEqual(len(result["security_issues"]), 0, "No security issues should be found")

    def test_permission_system_integration(self):
        """Test complete integration of permission system components"""

        # Setup permissions
        from verenigingen.utils.chapter_board_permissions import setup_chapter_board_permissions

        result = setup_chapter_board_permissions()

        # Volunteer Expense is archived, so only assert the live doctypes succeed.
        self.assertTrue(result["results"]["membership"], "Membership perms should succeed")
        self.assertTrue(result["results"]["termination_request"], "Termination request perms should succeed")

        # Test role assignment
        from verenigingen.permissions import update_all_chapter_board_roles

        roles_updated = update_all_chapter_board_roles()

        self.assertGreaterEqual(roles_updated, 0, "Role synchronization should complete")

        # Test security validation
        from verenigingen.utils.chapter_board_permissions import validate_permission_security

        is_valid, issues = validate_permission_security()

        self.assertTrue(is_valid, f"Complete system should pass security validation: {issues}")


if __name__ == "__main__":
    unittest.main()
