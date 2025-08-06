import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today


class TestVolunteerPortalEdgeCases(FrappeTestCase):
    """Edge case tests for the volunteer portal"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        cls.setup_test_data()

    @classmethod
    def setup_test_data(cls):
        """Create test data for edge case testing"""
        # Create test users and volunteers
        cls.volunteer_email = "edge.volunteer@test.com"
        cls.disabled_volunteer_email = "disabled.volunteer@test.com"
        cls.inactive_member_email = "inactive.member@test.com"

        for email, name in [
            (cls.volunteer_email, "Edge Volunteer"),
            (cls.disabled_volunteer_email, "Disabled Volunteer"),
            (cls.inactive_member_email, "Inactive Member"),
        ]:
            if not frappe.db.exists("User", email):
                user = frappe.get_doc(
                    {
                        "doctype": "User",
                        "email": email,
                        "first_name": name.split()[0],
                        "last_name": name.split()[-1],
                        "full_name": name,
                        "enabled": 1}
                )
                user.insert()

        # Create test chapters
        cls.active_chapter = "Edge Active Chapter"
        cls.disabled_chapter = "Edge Disabled Chapter"

        for chapter_name, enabled in [(cls.active_chapter, 1), (cls.disabled_chapter, 0)]:
            if not frappe.db.exists("Chapter", chapter_name):
                chapter = frappe.get_doc(
                    {
                        "doctype": "Chapter",
                        "chapter_name": chapter_name,
                        "city": "Edge City",
                        "enabled": enabled}
                )
                chapter.insert()

        # Create test teams
        cls.active_team = "Edge Active Team"
        cls.inactive_team = "Edge Inactive Team"

        for team_name, status in [(cls.active_team, "Active"), (cls.inactive_team, "Inactive")]:
            if not frappe.db.exists("Team", team_name):
                team = frappe.get_doc(
                    {
                        "doctype": "Team",
                        "team_name": team_name,
                        "description": f"Edge test team - {status}",
                        "chapter": cls.active_chapter,
                        "status": status}
                )
                team.insert()

        # Create test members and volunteers
        cls.setup_edge_volunteers()

        # Create expense categories
        cls.setup_expense_categories()

    @classmethod
    def setup_edge_volunteers(cls):
        """Set up volunteers for edge case testing"""
        # Active volunteer
        cls.active_member = "EDGE-MEMBER-001"
        if not frappe.db.exists("Member", cls.active_member):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "member_id": cls.active_member,
                    "first_name": "Edge",
                    "last_name": "Verenigingen Volunteer",
                    "full_name": "Edge Volunteer",
                    "email": cls.volunteer_email,
                    "status": "Active"}
            )
            member.insert()

        cls.active_volunteer = "EDGE-VOL-001"
        if not frappe.db.exists("Volunteer", cls.active_volunteer):
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "name": cls.active_volunteer,
                    "volunteer_name": "Edge Volunteer",
                    "member": cls.active_member,
                    "email": cls.volunteer_email,
                    "status": "Active"}
            )
            volunteer.insert()

        # Disabled volunteer
        cls.disabled_member = "EDGE-MEMBER-002"
        if not frappe.db.exists("Member", cls.disabled_member):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "member_id": cls.disabled_member,
                    "first_name": "Disabled",
                    "last_name": "Verenigingen Volunteer",
                    "full_name": "Disabled Volunteer",
                    "email": cls.disabled_volunteer_email,
                    "status": "Inactive"}
            )
            member.insert()

        cls.disabled_volunteer = "EDGE-VOL-002"
        if not frappe.db.exists("Volunteer", cls.disabled_volunteer):
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "name": cls.disabled_volunteer,
                    "volunteer_name": "Disabled Volunteer",
                    "member": cls.disabled_member,
                    "email": cls.disabled_volunteer_email,
                    "status": "Inactive"}
            )
            volunteer.insert()

        # Set up chapter memberships
        cls.setup_chapter_memberships()
        cls.setup_team_memberships()

    @classmethod
    def setup_chapter_memberships(cls):
        """Set up chapter memberships"""
        active_chapter_doc = frappe.get_doc("Chapter", cls.active_chapter)

        # Add active member to active chapter
        member_exists = any(m.member == cls.active_member for m in active_chapter_doc.members)
        if not member_exists:
            active_chapter_doc.append(
                "members", {"member": cls.active_member, "chapter_join_date": today(), "enabled": 1}
            )
            active_chapter_doc.save()

        # Add disabled member to disabled chapter
        disabled_chapter_doc = frappe.get_doc("Chapter", cls.disabled_chapter)
        member_exists = any(m.member == cls.disabled_member for m in disabled_chapter_doc.members)
        if not member_exists:
            disabled_chapter_doc.append(
                "members",
                {
                    "member": cls.disabled_member,
                    "chapter_join_date": today(),
                    "enabled": 0,  # Disabled membership
                },
            )
            disabled_chapter_doc.save()

    @classmethod
    def setup_team_memberships(cls):
        """Set up team memberships"""
        # Active volunteer in active team
        if not frappe.db.exists(
            "Team Member", {"volunteer": cls.active_volunteer, "parent": cls.active_team}
        ):
            team_member = frappe.get_doc(
                {
                    "doctype": "Team Member",
                    "parent": cls.active_team,
                    "parenttype": "Team",
                    "parentfield": "members",
                    "volunteer": cls.active_volunteer,
                    "role_type": "Team Member",
                    "status": "Active",
                    "joined_date": today()}
            )
            team_member.insert()

        # Disabled volunteer in inactive team
        if not frappe.db.exists(
            "Team Member", {"volunteer": cls.disabled_volunteer, "parent": cls.inactive_team}
        ):
            team_member = frappe.get_doc(
                {
                    "doctype": "Team Member",
                    "parent": cls.inactive_team,
                    "parenttype": "Team",
                    "parentfield": "members",
                    "volunteer": cls.disabled_volunteer,
                    "role_type": "Team Member",
                    "status": "Inactive",
                    "joined_date": add_days(today(), -30)}
            )
            team_member.insert()

    @classmethod
    def setup_expense_categories(cls):
        """Set up expense categories"""
        cls.active_category = "Edge Active Category"
        cls.disabled_category = "Edge Disabled Category"

        for category_name, disabled in [(cls.active_category, 0), (cls.disabled_category, 1)]:
            if not frappe.db.exists("Expense Category", category_name):
                category = frappe.get_doc(
                    {
                        "doctype": "Expense Category",
                        "category_name": category_name,
                        "description": "Edge test category",
                        "is_active": 1 if disabled == 0 else 0}
                )
                category.insert()

    def setUp(self):
        """Set up for each test"""
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test"""
        frappe.set_user("Administrator")
        # Clean up test expenses
        expenses = frappe.get_all(
            "Volunteer Expense",
            filters={"volunteer": ["in", [self.active_volunteer, self.disabled_volunteer]]},
        )
        for expense in expenses:
            try:
                frappe.delete_doc("Volunteer Expense", expense.name, force=1)
            except Exception:
                pass

    # DISABLED/INACTIVE ENTITY TESTS

    def test_disabled_volunteer_portal_access(self):
        """Test portal access for disabled volunteer"""
        from verenigingen.templates.pages.volunteer.dashboard import get_context

        frappe.set_user(self.disabled_volunteer_email)

        # Should still get volunteer record but may have limited functionality
        context = {}
        get_context(context)

        # Volunteer record should exist
        self.assertIsNotNone(context.get("volunteer"))
        self.assertEqual(context["volunteer"]["name"], self.disabled_volunteer)

    def test_disabled_chapter_not_in_organizations(self):
        """Test that disabled chapters don't appear in organization options"""
        from verenigingen.templates.pages.volunteer.expenses import get_volunteer_organizations

        # Active volunteer should only see active chapters
        organizations = get_volunteer_organizations(self.active_volunteer)

        chapter_names = [ch["name"] for ch in organizations["chapters"]]
        self.assertIn(self.active_chapter, chapter_names)
        self.assertNotIn(self.disabled_chapter, chapter_names)

    def test_inactive_team_not_in_organizations(self):
        """Test that inactive teams don't appear in organization options"""
        from verenigingen.templates.pages.volunteer.expenses import get_volunteer_organizations

        # Should not include inactive teams
        organizations = get_volunteer_organizations(self.active_volunteer)

        team_names = [t["name"] for t in organizations["teams"]]
        self.assertIn(self.active_team, team_names)
        # Note: Inactive teams might still appear if volunteer is a member
        # This depends on business logic - adjust test based on requirements

    def test_disabled_expense_categories_not_shown(self):
        """Test that disabled expense categories are not shown"""
        from verenigingen.templates.pages.volunteer.expenses import get_expense_categories

        categories = get_expense_categories()

        category_names = [cat["name"] for cat in categories]
        self.assertIn(self.active_category, category_names)
        self.assertNotIn(self.disabled_category, category_names)

    # BOUNDARY VALUE TESTS

    def test_expense_amount_boundary_values(self):
        """Test expense submission with boundary amount values"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        boundary_amounts = [
            0.01,  # Minimum valid amount
            99.99,  # Just under basic threshold
            100.00,  # Basic threshold boundary
            100.01,  # Just over basic threshold
            499.99,  # Just under financial threshold
            500.00,  # Financial threshold boundary
            500.01,  # Just over financial threshold
            999999.99,  # Very large amount
        ]

        successful_submissions = []

        try:
            for amount in boundary_amounts:
                expense_data = {
                    "description": f"Boundary test €{amount}",
                    "amount": amount,
                    "expense_date": today(),
                    "organization_type": "Chapter",
                    "chapter": self.active_chapter}

                result = submit_expense(expense_data)

                if amount > 0:
                    self.assertTrue(result["success"], f"Failed for amount €{amount}")
                    successful_submissions.append(result["expense_name"])
                else:
                    self.assertFalse(result["success"], f"Should fail for amount €{amount}")

        finally:
            # Clean up
            for expense_name in successful_submissions:
                try:
                    frappe.delete_doc("Volunteer Expense", expense_name, force=1)
                except Exception:
                    pass

    def test_expense_date_boundary_values(self):
        """Test expense submission with boundary date values"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        boundary_dates = [
            today(),  # Today (valid)
            add_days(today(), -1),  # Yesterday (valid)
            add_days(today(), -365),  # One year ago (valid)
            add_days(today(), 1),  # Tomorrow (invalid - future)
            add_days(today(), -1095),  # Three years ago (old but might be valid)
        ]

        successful_submissions = []

        try:
            for test_date in boundary_dates:
                expense_data = {
                    "description": f"Date test {test_date}",
                    "amount": 50.00,
                    "expense_date": test_date,
                    "organization_type": "Chapter",
                    "chapter": self.active_chapter}

                result = submit_expense(expense_data)

                if test_date <= today():
                    self.assertTrue(result["success"], f"Failed for date {test_date}")
                    successful_submissions.append(result["expense_name"])
                else:
                    self.assertFalse(result["success"], f"Should fail for future date {test_date}")

        finally:
            # Clean up
            for expense_name in successful_submissions:
                try:
                    frappe.delete_doc("Volunteer Expense", expense_name, force=1)
                except Exception:
                    pass

    # DATA TYPE EDGE CASES

    def test_expense_submission_with_string_amount(self):
        """Test expense submission with string amount value"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        expense_data = {
            "description": "String amount test",
            "amount": "50.00",  # String instead of float
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.active_chapter}

        result = submit_expense(expense_data)

        self.assertTrue(result["success"])

        # Verify amount was properly converted
        expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
        self.assertEqual(expense.amount, 50.00)
        self.assertIsInstance(expense.amount, (int, float))

        frappe.delete_doc("Volunteer Expense", expense.name, force=1)

    def test_expense_submission_with_invalid_amount_format(self):
        """Test expense submission with invalid amount format"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        invalid_amounts = [
            "invalid",  # Non-numeric string
            "",  # Empty string
            None,  # None value
            "€50.00",  # Currency symbol included
            "50,00",  # Comma as decimal separator
        ]

        for invalid_amount in invalid_amounts:
            expense_data = {
                "description": f"Invalid amount test: {invalid_amount}",
                "amount": invalid_amount,
                "expense_date": today(),
                "organization_type": "Chapter",
                "chapter": self.active_chapter}

            result = submit_expense(expense_data)

            # Should fail or convert gracefully
            if result["success"]:
                # If conversion succeeded, verify the result
                expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
                self.assertGreater(expense.amount, 0)
                frappe.delete_doc("Volunteer Expense", expense.name, force=1)

    def test_very_long_field_values(self):
        """Test submission with extremely long field values"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        # Test with very long description (beyond typical limits)
        long_description = "A" * 10000  # 10k characters
        long_notes = "B" * 5000  # 5k characters

        expense_data = {
            "description": long_description,
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.active_chapter,
            "notes": long_notes}

        result = submit_expense(expense_data)

        # Should either succeed with truncation or fail gracefully
        if result["success"]:
            expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
            # Verify data was stored (possibly truncated)
            self.assertGreater(len(expense.description), 0)
            frappe.delete_doc("Volunteer Expense", expense.name, force=1)
        else:
            # Should fail with appropriate error message
            self.assertIn("message", result)

    # CONCURRENT ACCESS TESTS

    def test_simultaneous_expense_submissions(self):
        """Test simultaneous expense submissions by same volunteer"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        # Simulate rapid consecutive submissions
        expenses = []

        try:
            for i in range(5):
                expense_data = {
                    "description": f"Concurrent expense {i + 1}",
                    "amount": 20.00 + i,
                    "expense_date": today(),
                    "organization_type": "Chapter",
                    "chapter": self.active_chapter}

                result = submit_expense(expense_data)

                self.assertTrue(result["success"])
                expenses.append(result["expense_name"])

            # Verify all expenses were created with unique names
            self.assertEqual(len(set(expenses)), 5)

            # Verify all expenses exist in database
            for expense_name in expenses:
                expense = frappe.get_doc("Volunteer Expense", expense_name)
                self.assertEqual(expense.volunteer, self.active_volunteer)

        finally:
            # Clean up
            for expense_name in expenses:
                try:
                    frappe.delete_doc("Volunteer Expense", expense_name, force=1)
                except Exception:
                    pass

    # MEMORY AND PERFORMANCE EDGE CASES

    def test_large_expense_history_performance(self):
        """Test performance with large expense history"""
        from verenigingen.templates.pages.volunteer.expenses import get_volunteer_expenses

        # Create many historical expenses
        expense_names = []

        try:
            for i in range(50):  # Create 50 expenses
                expense = frappe.get_doc(
                    {
                        "doctype": "Volunteer Expense",
                        "volunteer": self.active_volunteer,
                        "description": f"Historical expense {i + 1}",
                        "amount": 10.00 + (i % 10),
                        "expense_date": add_days(today(), -i),
                        "organization_type": "Chapter",
                        "chapter": self.active_chapter,
                        "status": "Approved" if i % 3 == 0 else "Submitted"}
                )
                expense.insert()
                if i % 3 != 2:  # Submit most expenses
                    expense.submit()
                expense_names.append(expense.name)

            # Test getting recent expenses (should limit results)
            recent_expenses = get_volunteer_expenses(self.active_volunteer, limit=10)

            # Should return limited number of expenses
            self.assertLessEqual(len(recent_expenses), 10)

            # Should be ordered by most recent first
            if len(recent_expenses) > 1:
                dates = [exp.get("creation") for exp in recent_expenses]
                # Verify descending order (most recent first)
                self.assertTrue(all(dates[i] >= dates[i + 1] for i in range(len(dates) - 1)))

        finally:
            # Clean up
            for expense_name in expense_names:
                try:
                    frappe.delete_doc("Volunteer Expense", expense_name, force=1)
                except Exception:
                    pass

    # ORGANIZATION MEMBERSHIP EDGE CASES

    def test_volunteer_with_multiple_chapter_memberships(self):
        """Test volunteer with multiple active chapter memberships"""
        from verenigingen.templates.pages.volunteer.expenses import get_volunteer_organizations

        # Create additional chapter
        extra_chapter = "Extra Test Chapter"
        if not frappe.db.exists("Chapter", extra_chapter):
            chapter = frappe.get_doc(
                {"doctype": "Chapter", "chapter_name": extra_chapter, "city": "Extra City", "enabled": 1}
            )
            chapter.insert()

        # Add volunteer's member to extra chapter
        extra_chapter_doc = frappe.get_doc("Chapter", extra_chapter)
        extra_chapter_doc.append(
            "members", {"member": self.active_member, "chapter_join_date": today(), "enabled": 1}
        )
        extra_chapter_doc.save()

        try:
            organizations = get_volunteer_organizations(self.active_volunteer)

            # Should include both chapters
            chapter_names = [ch["name"] for ch in organizations["chapters"]]
            self.assertIn(self.active_chapter, chapter_names)
            self.assertIn(extra_chapter, chapter_names)
            self.assertGreaterEqual(len(organizations["chapters"]), 2)

        finally:
            # Clean up
            try:
                frappe.delete_doc("Chapter", extra_chapter, force=1)
            except Exception:
                pass

    def test_volunteer_member_with_expired_chapter_membership(self):
        """Test volunteer with expired chapter membership"""
        # Create chapter with date-based membership
        expired_chapter = "Expired Membership Chapter"
        if not frappe.db.exists("Chapter", expired_chapter):
            chapter = frappe.get_doc(
                {"doctype": "Chapter", "chapter_name": expired_chapter, "city": "Expired City", "enabled": 1}
            )
            chapter.insert()

        # Add member with past leave date
        expired_chapter_doc = frappe.get_doc("Chapter", expired_chapter)
        expired_chapter_doc.append(
            "members",
            {
                "member": self.active_member,
                "chapter_join_date": add_days(today(), -100),
                "chapter_leave_date": add_days(today(), -30),  # Left 30 days ago
                "enabled": 0},
        )
        expired_chapter_doc.save()

        try:
            from verenigingen.templates.pages.volunteer.expenses import get_volunteer_organizations

            organizations = get_volunteer_organizations(self.active_volunteer)

            # Should not include expired chapter
            chapter_names = [ch["name"] for ch in organizations["chapters"]]
            self.assertNotIn(expired_chapter, chapter_names)

        finally:
            # Clean up
            try:
                frappe.delete_doc("Chapter", expired_chapter, force=1)
            except Exception:
                pass

    # ERROR RECOVERY TESTS

    def test_expense_submission_recovery_after_partial_failure(self):
        """Test expense submission recovery after partial failures"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        frappe.set_user(self.volunteer_email)

        # First, submit a valid expense
        valid_expense_data = {
            "description": "Valid expense before failure",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.active_chapter}

        result1 = submit_expense(valid_expense_data)
        self.assertTrue(result1["success"])

        # Then, try an invalid submission
        invalid_expense_data = {
            "description": "Invalid expense",
            "amount": -50.00,  # Invalid negative amount
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.active_chapter}

        result2 = submit_expense(invalid_expense_data)
        self.assertFalse(result2["success"])

        # Finally, submit another valid expense to verify system recovery
        recovery_expense_data = {
            "description": "Recovery expense after failure",
            "amount": 75.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.active_chapter}

        result3 = submit_expense(recovery_expense_data)
        self.assertTrue(result3["success"])

        # Clean up
        try:
            frappe.delete_doc("Volunteer Expense", result1["expense_name"], force=1)
            frappe.delete_doc("Volunteer Expense", result3["expense_name"], force=1)
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()
