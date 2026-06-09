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
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestExpenseClaimQueryAPIs(EnhancedTestCase):
    """Test expense claim query API functions"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Single-module runs do not fire before_tests, so seed the shared
        # masters (creation_user, Team Roles, Membership Types, etc.) here.
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create test chapters
        self.chapter1 = self.create_test_chapter()
        self.chapter2 = self.create_test_chapter()

        # Create staff user. Uniquify the email per run: create_test_user() reuses
        # any existing User with the same address (and v16 role-profile sync can
        # leave a foreign role profile on a reused user), so a fixed
        # "expense_staff@test.com" left behind by another file in the shard would
        # make these role-sensitive assertions order-dependent.
        self.staff_user = self.create_test_user(
            email=f"expense_staff_{self.uid}@test.com",
            roles=["Verenigingen Staff"]
        )

        # Create chapter board member
        self.board_member = self.create_test_member(
            first_name="Board",
            last_name="Member",
            birth_date="1990-01-01"
        )

        # Uniquify per run (see staff_user note). Keep the "expense_board" prefix:
        # test_approver_query_with_search_text searches by that substring.
        self.board_user = self.create_test_user(
            email=f"expense_board_{self.uid}@test.com",
            roles=["Verenigingen Chapter Board Member"]
        )

        self.board_member.user = self.board_user.name
        self.board_member.save()

        # Create volunteer and board position. The volunteer factory sets
        # frappe.flags.skip_volunteer_account_creation, so the controller never
        # links volunteer.user from the member. The expense-approver query joins
        # tabVolunteer.user = tabUser.email, so link it explicitly here.
        self.volunteer = self.create_test_volunteer(member=self.board_member.name)
        frappe.db.set_value("Volunteer", self.volunteer.name, "user", self.board_user.name)
        self.volunteer.reload()

        # Create chapter role with Financial permissions. role_name is the
        # Chapter Role primary key, so uniquify it per run to avoid PRIMARY
        # collisions; the test references self.chapter_role.name, not the literal.
        self.chapter_role = frappe.get_doc({
            "doctype": "Chapter Role",
            "role_name": f"Test Financial Role {frappe.generate_hash(length=6)}",
            "permissions_level": "Financial"
        })
        self.chapter_role.insert()

        # Make volunteer a board member of chapter1
        chapter1_doc = frappe.get_doc("Chapter", self.chapter1.name)
        self.board_position = chapter1_doc.append("board_members", {
            "volunteer": self.volunteer.name,
            "chapter_role": self.chapter_role.name,
            "from_date": today(),
            "is_active": 1
        })
        chapter1_doc.save()

        # Give board user the Expense Approver role.
        # Frappe v16 makes role_profiles exclusive: User.populate_role_profile_roles()
        # strips any role not contained in an assigned role profile. Linking the
        # member/volunteer applied the "Verenigingen Volunteer" role profile, so a
        # plain append("roles", {...}) would be silently removed on save. Clear the
        # profile first so the directly-assigned role persists (the approver query
        # reads tabHas Role, not role profiles).
        self._grant_expense_approver_role(self.board_user.name)

    def _grant_expense_approver_role(self, user_name):
        """Assign the Expense Approver role so it survives v16 role-profile sync."""
        user_doc = frappe.get_doc("User", user_name)
        user_doc.set("role_profiles", [])
        user_doc.role_profile_name = None
        if "Expense Approver" not in [r.role for r in user_doc.roles]:
            user_doc.append("roles", {"role": "Expense Approver"})
        user_doc.save(ignore_permissions=True)

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

            # frappe.whitelisted is a set of the registered function objects
            # (not names), so check membership by identity.
            self.assertIn(
                func,
                frappe.whitelisted,
                f"{func_name} should be whitelisted"
            )

    def test_staff_sees_all_chapters_for_expenses(self):
        """Staff users should see all active chapters"""
        frappe.set_user(self.staff_user.name)

        from verenigingen.api.expense_claim_queries import get_user_accessible_chapters_for_expenses

        # The staff/admin branch returns ALL active chapters with LIMIT page_len.
        # In a full parallel shard, leftover chapters from co-located tests can fill
        # the first page and push this run's chapters off it (ORDER BY name). Filter
        # by this run's id (shared by chapter1 & chapter2 — same factory) so the
        # assertion is independent of leftover rows. This mirrors how the Link query
        # is actually used (user types text to narrow the list).
        run_id = self.chapter1.name.rsplit(" - ", 1)[-1]
        result = get_user_accessible_chapters_for_expenses(
            doctype="Chapter",
            txt=run_id,
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
        # Build the additional fixtures as Administrator; a Staff user cannot
        # insert Chapter Role / Member / Volunteer master records.
        non_financial_member = self.create_test_member(
            first_name="NonFinancial",
            last_name="Member",
            birth_date="1990-01-01"
        )

        # Uniquify per run (see staff_user note in setUp).
        non_financial_user = self.create_test_user(
            email=f"non_financial_{self.uid}@test.com",
            roles=["Verenigingen Chapter Board Member", "Expense Approver"]
        )

        non_financial_member.user = non_financial_user.name
        non_financial_member.save()

        volunteer2 = self.create_test_volunteer(member=non_financial_member.name)
        frappe.db.set_value("Volunteer", volunteer2.name, "user", non_financial_user.name)

        # Create a role with a non-Financial permission level. The valid
        # Chapter Role levels are Basic/Financial/Admin; "Basic" is the
        # non-financial case here. role_name is the primary key; uniquify
        # per run to avoid PRIMARY collisions.
        ops_role = frappe.get_doc({
            "doctype": "Chapter Role",
            "role_name": f"Test Basic Role {frappe.generate_hash(length=6)}",
            "permissions_level": "Basic"
        })
        ops_role.insert()

        chapter1_doc = frappe.get_doc("Chapter", self.chapter1.name)
        board_pos2 = chapter1_doc.append("board_members", {
            "volunteer": volunteer2.name,
            "chapter_role": ops_role.name,
            "from_date": today(),
            "is_active": 1
        })
        chapter1_doc.save()

        # Run the query under test as the staff user.
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

        # Should NOT include the non-financial board member
        user_emails = [r[0] for r in result]
        self.assertNotIn(non_financial_user.name, user_emails)

    def test_team_expense_approvers_uses_team_chapter(self):
        """Team expense approvers should come from the team's parent chapter"""
        # Create the team as Administrator (Staff cannot insert Team masters).
        team = self.create_test_team(
            chapter=self.chapter1.name
        )

        # Run the query under test as the staff user.
        frappe.set_user(self.staff_user.name)

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

        # The function has two independent branches (admin sees all chapters,
        # board members see only theirs) and each builds its own query, so the
        # LIKE clause legitimately appears once per branch. The bug this guards
        # against is the SAME query carrying a duplicated LIKE condition, which
        # would surface as two "name LIKE %(txt)s" with no intervening SQL.
        import re

        normalized = re.sub(r"\s+", " ", source)
        self.assertNotIn(
            "name LIKE %(txt)s AND name LIKE %(txt)s",
            normalized,
            "Query must not contain a duplicated LIKE condition",
        )
        self.assertNotIn(
            "name LIKE %(txt)s name LIKE %(txt)s",
            normalized,
            "Query must not contain a duplicated LIKE condition",
        )

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

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()

    def test_expense_claim_form_integration(self):
        """Test that expense query APIs work with actual Expense Claim form"""
        # Create test setup
        chapter = self.create_test_chapter()

        # Uniquify per run: create_test_user() reuses an existing same-email User,
        # so a fixed address shared with another shard file would bleed roles.
        staff_user = self.create_test_user(
            email=f"integration_staff_{self.uid}@test.com",
            roles=["Verenigingen Staff", "Expense Approver"]
        )

        frappe.set_user(staff_user.name)

        # Simulate getting chapters for expense claim
        from verenigingen.api.expense_claim_queries import get_user_accessible_chapters_for_expenses

        # Filter by this run's id so leftover chapters from co-located tests can't
        # fill the LIMIT page and hide this chapter (see staff-sees-all test).
        run_id = chapter.name.rsplit(" - ", 1)[-1]
        chapters = get_user_accessible_chapters_for_expenses(
            doctype="Chapter",
            txt=run_id,
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
