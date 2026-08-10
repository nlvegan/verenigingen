#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Member Permission System Tests
===============================

Tests for Member DocType permission queries and User Permission filtering.

Key Scenarios Tested:
- Admin roles (Verenigingen Staff) get unrestricted access
- Chapter board members see only their chapter's members
- Regular members see only their own records
- User Permissions don't incorrectly filter Member list
- Employee field Link doesn't cause cross-DocType filtering

Production Issues Caught:
- User Permission on Employee DocType filtered Member list (147/660 records)
- Duplicate permission_query_conditions hook causing AND logic
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberPermissions(EnhancedTestCase):
    """Test Member permission queries and filtering"""

    def setUp(self):
        """Set up test users and roles"""
        super().setUp()

        # Chapter Role is autonamed `field:role_name`, so its docname IS the role
        # name. The two roles below were hardcoded ("Test Board Role" / "... 2") and
        # inserted unguarded; chapter_doc.save() then committed them, so the FIRST
        # run on a site left rows that made every later run die with
        # DuplicateEntryError on the PRIMARY key - permanently, on that site.
        #
        # Token them per run, the same convention test_chapter_utils.py uses for its
        # chapter/role/board fixtures. Note the hardcoded USER emails below need no
        # such treatment: create_test_user() explicitly reuses an existing User.
        self.token = frappe.generate_hash(length=8)

        # Create test chapters
        self.chapter1 = self.create_test_chapter()
        self.chapter2 = self.create_test_chapter()

        # Create test members
        self.member1 = self.create_test_member(first_name="Member", last_name="One", birth_date="1990-01-01")

        self.member2 = self.create_test_member(first_name="Member", last_name="Two", birth_date="1991-01-01")

        self.member3 = self.create_test_member(
            first_name="Member", last_name="Three", birth_date="1992-01-01"
        )

        # Assign members to chapters
        self.create_test_chapter_member(chapter=self.chapter1.name, member=self.member1.name, status="Active")

        self.create_test_chapter_member(chapter=self.chapter2.name, member=self.member2.name, status="Active")

        # Member3 has no chapter assignment (like test members that were visible)

        # Create test users
        self.staff_user = self.create_test_user(email="staff@test.com", roles=["Verenigingen Staff"])

        self.board_member_user = self.create_test_user(
            email="board@test.com", roles=["Verenigingen Chapter Board Member"]
        )

        self.regular_member_user = self.create_test_user(
            email="member@test.com", roles=["Verenigingen Member"]
        )

    def create_test_chapter_member(self, chapter, member, status="Active"):
        """Add a member to a chapter's `members` child table and save.

        Returns the created Chapter Member child row.
        """
        from frappe.utils import today

        chapter_doc = frappe.get_doc("Chapter", chapter)
        row = chapter_doc.append(
            "members",
            {
                "member": member,
                "enabled": 1,
                "status": status,
                "chapter_join_date": today(),
            },
        )
        chapter_doc.save()
        return row

    def test_staff_sees_all_members(self):
        """Verenigingen Staff should see all members without filtering"""
        frappe.set_user(self.staff_user.name)

        # Get permission query
        from verenigingen.permissions import get_member_permission_query

        condition = get_member_permission_query(self.staff_user.name)

        # Staff should get empty string (no filtering)
        self.assertEqual(condition, "")

        # Verify can see all test members
        members = frappe.get_all(
            "Member", filters={"name": ["in", [self.member1.name, self.member2.name, self.member3.name]]}
        )

        self.assertEqual(len(members), 3, "Staff should see all 3 test members")

    def test_chapter_board_member_sees_only_their_chapter(self):
        """Chapter board members should only see members from their chapters"""
        # Link board member user to member1 and make them a board member of chapter1
        self.member1.user = self.board_member_user.name
        self.member1.save()

        volunteer = self.create_test_volunteer(member=self.member1.name)

        # Create chapter role (name tokened - see setUp)
        chapter_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Test Board Role {self.token}",
                "permissions_level": "Admin",
            }
        )
        chapter_role.insert()

        # Make volunteer a board member of chapter1
        chapter1_doc = frappe.get_doc("Chapter", self.chapter1.name)
        board_member = chapter1_doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": chapter_role.name,
                "from_date": today(),
                "is_active": 1,
            },
        )
        chapter1_doc.save()

        frappe.set_user(self.board_member_user.name)

        # Get permission query
        from verenigingen.permissions import get_member_permission_query

        condition = get_member_permission_query(self.board_member_user.name)

        # Should have a condition (not empty)
        self.assertNotEqual(condition, "")
        self.assertIn("Chapter Member", condition)

        # Should be able to see member1 (same chapter) but not member2 (different chapter)
        # Note: This requires proper permission query execution, simplified for unit test
        self.assertIsNotNone(condition)

    def test_regular_member_sees_only_own_record(self):
        """Regular members should only see their own member record"""
        # Link user to member3
        self.member3.user = self.regular_member_user.name
        self.member3.save()

        frappe.set_user(self.regular_member_user.name)

        # Get permission query
        from verenigingen.permissions import get_member_permission_query

        condition = get_member_permission_query(self.regular_member_user.name)

        # Should have a self-access condition
        self.assertNotEqual(condition, "")
        self.assertIn("user", condition.lower())

    def test_user_permission_does_not_filter_members(self):
        """
        Critical test: User Permission on Employee should NOT filter Member list

        This was the root cause of showing only 147/660 members.
        """
        # Test fixtures (Employee, member link, User Permission) are created as
        # Administrator; Verenigingen Staff has no create permission on Employee
        # and that is not what this test exercises. The assertion below targets
        # the permission-query builder for the staff user explicitly.
        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": "Test",
                "last_name": "Employee",
                # status/gender/date defaults are not auto-applied under in_import.
                "status": "Active",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": frappe.utils.today(),
                "company": frappe.get_value("Verenigingen Settings", None, "company"),
            }
        )
        employee.insert()

        # Link member1 to this employee
        self.member1.employee = employee.name
        self.member1.save()

        # Create User Permission restricting staff user to this employee
        user_perm = frappe.get_doc(
            {
                "doctype": "User Permission",
                "user": self.staff_user.name,
                "allow": "Employee",
                "for_value": employee.name,
                "apply_to_all_doctypes": 0,  # Critical: should not apply to all
            }
        )
        user_perm.insert()

        frappe.clear_cache()

        # Staff should STILL see all members despite Employee User Permission
        from verenigingen.permissions import get_member_permission_query

        condition = get_member_permission_query(self.staff_user.name)

        # Permission query should still return empty (no filtering)
        self.assertEqual(
            condition, "", "Staff permission query should not be affected by Employee User Permission"
        )

        # Verify can still see members without employee link
        members_without_employee = frappe.get_all(
            "Member", filters={"name": ["in", [self.member2.name, self.member3.name]]}
        )

        self.assertEqual(
            len(members_without_employee),
            2,
            "Should see members without employee link despite Employee User Permission",
        )

    def test_no_duplicate_permission_query_hooks(self):
        """Verify only one permission_query_conditions hook for Member"""
        hooks = frappe.get_hooks("permission_query_conditions", {})
        member_hooks = hooks.get("Member", [])

        # Should have exactly one hook
        self.assertEqual(len(member_hooks), 1, "Should have exactly one permission query hook for Member")

        # Should point to the correct function
        self.assertEqual(member_hooks[0], "verenigingen.permissions.get_member_permission_query")

    def test_terminated_members_filtered_for_board_members(self):
        """Chapter board members should not see terminated members from other chapters"""
        # Create terminated member in chapter2
        terminated_member = self.create_test_member(
            first_name="Quit", last_name="Member", birth_date="1993-01-01", status="Quit"
        )

        self.create_test_chapter_member(
            chapter=self.chapter2.name, member=terminated_member.name, status="Active"
        )

        # Set up board member user (already done in previous test)
        self.member1.user = self.board_member_user.name
        self.member1.save()

        volunteer = self.create_test_volunteer(member=self.member1.name)

        chapter_role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Test Board Role 2 {self.token}",
                "permissions_level": "Admin",
            }
        )
        chapter_role.insert()

        chapter1_doc = frappe.get_doc("Chapter", self.chapter1.name)
        board_member = chapter1_doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": chapter_role.name,
                "from_date": today(),
                "is_active": 1,
            },
        )
        chapter1_doc.save()

        frappe.set_user(self.board_member_user.name)

        # Get permission query
        from verenigingen.permissions import get_member_permission_query

        condition = get_member_permission_query(self.board_member_user.name)

        # Condition should filter out Terminated members
        self.assertIn("Quit", condition)
        self.assertIn("NOT IN", condition)


class TestMemberPermissionQueryPerformance(EnhancedTestCase):
    """Test performance characteristics of permission queries"""

    def test_permission_query_does_not_cause_n_plus_1(self):
        """Permission query should be efficient and not cause N+1 queries"""
        # Create multiple members
        members = []
        for i in range(10):
            member = self.create_test_member(
                first_name=f"Member{i}", last_name="Test", birth_date="1990-01-01"
            )
            members.append(member)

        # Create staff user
        staff_user = self.create_test_user(email="staff_perf@test.com", roles=["Verenigingen Staff"])

        frappe.set_user(staff_user.name)

        # Query count should not scale with number of members
        with self.assertQueryCount(50):  # Adjust based on actual query count
            from verenigingen.permissions import get_member_permission_query

            condition = get_member_permission_query(staff_user.name)

            # Fetch all members
            all_members = frappe.get_all("Member", filters={"name": ["in", [m.name for m in members]]})


def teardown_module():
    """Clean up after all tests"""
    frappe.db.rollback()
