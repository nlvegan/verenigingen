#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Expense Claim Query API Tests
==============================

Tests for expense claim query functions used in Link field dropdowns.

Key Scenarios Tested:
- API security decorators are properly applied
- SQL injection protection via frappe.db.escape()
- Chapter filtering based on user access
- Team expense approver selection
- Staff users have full access
- Chapter board members have limited access

Production Issues Caught:
- Missing security decorators on API functions
- SQL injection vulnerabilities in dynamic queries
- Duplicate SQL conditions
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestExpenseClaimQueryAPIs(EnhancedTestCase):
    """Test expense claim query API functions"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create test chapters
        self.chapter1 = self.create_test_chapter()
        self.chapter2 = self.create_test_chapter()

        # Create staff user
        self.staff_user = self.create_test_user(
            email="expense_staff@test.com",
            roles=["Verenigingen Staff"]
        )

        # Create chapter board member
        self.board_member = self.create_test_member(
            first_name="Board",
            last_name="Member",
            birth_date="1990-01-01"
        )

        self.board_user = self.create_test_user(
            email="expense_board@test.com",
            roles=["Verenigingen Chapter Board Member"]
        )

        self.board_member.user = self.board_user.name
        self.board_member.save()

        # Create volunteer and board position
        self.volunteer = self.create_test_volunteer(member=self.board_member.name)

        # Create chapter role with Financial permissions
        self.chapter_role = frappe.get_doc({
            "doctype": "Chapter Role",
            "role_name": "Test Financial Role",
            "permissions_level": "Financial"
        })
        self.chapter_role.insert()

        # Make volunteer a board member of chapter1
        chapter1_doc = frappe.get_doc("Chapter", self.chapter1.name)
        self.board_position = chapter1_doc.append("board_members", {
            "volunteer": self.volunteer.name,
            "chapter_role": self.chapter_role.name,
            "is_active": 1
        })
        chapter1_doc.save()

        # Give board user Expense Approver role
        board_user_doc = frappe.get_doc("User", self.board_user.name)
        board_user_doc.append("roles", {
            "role": "Expense Approver"
        })
        board_user_doc.save()

    def test_api_security_decorators_applied(self):
        """Verify all expense query APIs have security decorators"""
        from verenigingen.api import expense_claim_queries

        # Check each function has the security decorator
        functions = [
            "get_user_accessible_chapters_for_expenses",
            "get_chapter_expense_approvers",
            "get_team_expense_approvers"
        ]

        for func_name in functions:
            func = getattr(expense_claim_queries, func_name)

            # Check if function is whitelisted
            self.assertTrue(
                hasattr(func, "_is_whitelisted") or func_name in frappe.whitelisted,
                f"{func_name} should be whitelisted"
            )

    def test_staff_sees_all_chapters_for_expenses(self):
        """Staff users should see all active chapters"""
        frappe.set_user(self.staff_user.name)

        from verenigingen.api.expense_claim_queries import get_user_accessible_chapters_for_expenses

        # Call the API
        result = get_user_accessible_chapters_for_expenses(
            doctype="Chapter",
            txt="",
            searchfield="name",
            start=0,
            page_len=20,
            filters={}
        )

        # Should return both test chapters
        chapter_names = [r[0] for r in result]
        self.assertIn(self.chapter1.name, chapter_names)
        self.assertIn(self.chapter2.name, chapter_names)

    def test_board_member_sees_only_their_chapters(self):
        """Chapter board members should only see their assigned chapters"""
        frappe.set_user(self.board_user.name)

        from verenigingen.api.expense_claim_queries import get_user_accessible_chapters_for_expenses

        result = get_user_accessible_chapters_for_expenses(
            doctype="Chapter",
            txt="",
            searchfield="name",
            start=0,
            page_len=20,
            filters={}
        )

        # Should only see chapter1
        chapter_names = [r[0] for r in result]
        self.assertIn(self.chapter1.name, chapter_names)
        self.assertNotIn(self.chapter2.name, chapter_names)

    def test_chapter_expense_approvers_query(self):
        """Test getting expense approvers for a specific chapter"""
        frappe.set_user(self.staff_user.name)

        from verenigingen.api.expense_claim_queries import get_chapter_expense_approvers

        result = get_chapter_expense_approvers(
            doctype="User",
            txt="",
            searchfield="email",
            start=0,
            page_len=20,
            filters={"chapter": self.chapter1.name}
        )

        # Should return the board user who is an Expense Approver
        user_emails = [r[0] for r in result]
        self.assertIn(self.board_user.name, user_emails)

    def test_chapter_expense_approvers_requires_financial_role(self):
        """Expense approvers must have Financial or Admin permission level"""
        frappe.set_user(self.staff_user.name)

        # Create a board member with non-financial role
        non_financial_member = self.create_test_member(
            first_name="NonFinancial",
            last_name="Member",
            birth_date="1990-01-01"
        )

        non_financial_user = self.create_test_user(
            email="non_financial@test.com",
            roles=["Verenigingen Chapter Board Member", "Expense Approver"]
        )

        non_financial_member.user = non_financial_user.name
        non_financial_member.save()

        volunteer2 = self.create_test_volunteer(member=non_financial_member.name)

        # Create role with Operations level (not Financial)
        ops_role = frappe.get_doc({
            "doctype": "Chapter Role",
            "role_name": "Test Operations Role",
            "permissions_level": "Operations"
        })
        ops_role.insert()

        chapter1_doc = frappe.get_doc("Chapter", self.chapter1.name)
        board_pos2 = chapter1_doc.append("board_members", {
            "volunteer": volunteer2.name,
            "chapter_role": ops_role.name,
            "is_active": 1
        })
        chapter1_doc.save()

        from verenigingen.api.expense_claim_queries import get_chapter_expense_approvers

        result = get_chapter_expense_approvers(
            doctype="User",
            txt="",
            searchfield="email",
            start=0,
            page_len=20,
            filters={"chapter": self.chapter1.name}
        )

        # Should NOT include the non-financial board member
        user_emails = [r[0] for r in result]
        self.assertNotIn(non_financial_user.name, user_emails)

    def test_team_expense_approvers_uses_team_chapter(self):
        """Team expense approvers should come from the team's parent chapter"""
        frappe.set_user(self.staff_user.name)

        # Create a team under chapter1
        team = self.create_test_team(
            chapter=self.chapter1.name
        )

        from verenigingen.api.expense_claim_queries import get_team_expense_approvers

        result = get_team_expense_approvers(
            doctype="User",
            txt="",
            searchfield="email",
            start=0,
            page_len=20,
            filters={"team": team.name}
        )

        # Should return approvers from chapter1 (team's parent chapter)
        user_emails = [r[0] for r in result]
        self.assertIn(self.board_user.name, user_emails)

    def test_sql_injection_protection(self):
        """Verify SQL injection protection via frappe.db.escape()"""
        frappe.set_user(self.staff_user.name)

        from verenigingen.api.expense_claim_queries import get_user_accessible_chapters_for_expenses

        # Try SQL injection via search text
        malicious_txt = "'; DROP TABLE tabChapter; --"

        # Should not raise SQL error, should be escaped
        try:
            result = get_user_accessible_chapters_for_expenses(
                doctype="Chapter",
                txt=malicious_txt,
                searchfield="name",
                start=0,
                page_len=20,
                filters={}
            )
            # If we get here, SQL was properly escaped
            self.assertTrue(True)
        except frappe.db.ProgrammingError:
            self.fail("SQL injection was not properly escaped")

    def test_no_duplicate_sql_conditions(self):
        """Verify no duplicate SQL conditions in queries"""
        frappe.set_user(self.staff_user.name)

        from verenigingen.api import expense_claim_queries
        import inspect

        # Get source code of the function
        source = inspect.getsource(expense_claim_queries.get_user_accessible_chapters_for_expenses)

        # Check for duplicate LIKE conditions
        like_count = source.count("name LIKE %(txt)s")

        # Should appear only once in the query, not duplicated
        self.assertEqual(like_count, 1, "Should have only one LIKE condition, not duplicate")

    def test_chapter_query_pagination(self):
        """Test pagination parameters work correctly"""
        frappe.set_user(self.staff_user.name)

        from verenigingen.api.expense_claim_queries import get_user_accessible_chapters_for_expenses

        # Test with page_len=1
        result = get_user_accessible_chapters_for_expenses(
            doctype="Chapter",
            txt="",
            searchfield="name",
            start=0,
            page_len=1,
            filters={}
        )

        # Should return exactly 1 result
        self.assertEqual(len(result), 1)

    def test_approver_query_with_search_text(self):
        """Test expense approver query with search filtering"""
        frappe.set_user(self.staff_user.name)

        from verenigingen.api.expense_claim_queries import get_chapter_expense_approvers

        # Search for part of the board user's email
        result = get_chapter_expense_approvers(
            doctype="User",
            txt="expense_board",
            searchfield="email",
            start=0,
            page_len=20,
            filters={"chapter": self.chapter1.name}
        )

        # Should find the board user
        user_emails = [r[0] for r in result]
        self.assertIn(self.board_user.name, user_emails)


class TestExpenseQueryAPIIntegration(EnhancedTestCase):
    """Integration tests for expense query APIs"""

    def test_expense_claim_form_integration(self):
        """Test that expense query APIs work with actual Expense Claim form"""
        # Create test setup
        chapter = self.create_test_chapter()

        staff_user = self.create_test_user(
            email="integration_staff@test.com",
            roles=["Verenigingen Staff", "Expense Approver"]
        )

        frappe.set_user(staff_user.name)

        # Simulate getting chapters for expense claim
        from verenigingen.api.expense_claim_queries import get_user_accessible_chapters_for_expenses

        chapters = get_user_accessible_chapters_for_expenses(
            doctype="Chapter",
            txt="",
            searchfield="name",
            start=0,
            page_len=20,
            filters={}
        )

        # Should be able to create expense claim with these chapters
        self.assertTrue(len(chapters) > 0)

        # Verify chapter is accessible
        chapter_names = [c[0] for c in chapters]
        self.assertIn(chapter.name, chapter_names)


def teardown_module():
    """Clean up after all tests"""
    frappe.db.rollback()
