from unittest.mock import patch

import frappe
from frappe.utils import today
from verenigingen.tests.utils.base import VereningingenTestCase


class TestVolunteerPortalIntegration(VereningingenTestCase):
    """Integration tests for the volunteer portal with approval workflow"""

    def setUp(self):
        """Set up test environment using factory methods"""
        super().setUp()
        self.setup_test_data()

    def setup_test_data(self):
        """Create comprehensive test data for integration testing"""
        # Create test company
        if not frappe.db.exists("Company", "Integration Test Company"):
            company = frappe.get_doc(
                {
                    "doctype": "Company",
                    "company_name": "Integration Test Company",
                    "abbr": "ITC",
                    "default_currency": "EUR",
                    "country": "Netherlands"}
            )
            company.insert()
            self.company = company.name
            self.track_doc("Company", company.name)
        else:
            self.company = "Integration Test Company"

        # Create test users
        self.volunteer_email = "integration.volunteer@test.com"
        self.board_member_email = "integration.board@test.com"
        self.admin_email = "integration.admin@test.com"

        for email, name, roles in [
            (self.volunteer_email, "Integration Volunteer", []),
            (self.board_member_email, "Integration Board Member", ["Chapter Board Member"]),
            (self.admin_email, "Integration Admin", ["System Manager"]),
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
                self.track_doc("User", user.name)

                # Add roles
                for role in roles:
                    if frappe.db.exists("Role", role):
                        user.add_roles(role)

        # Create test chapter with board structure
        self.test_chapter = self.create_test_chapter(
            chapter_name="Integration Test Chapter",
            postal_codes="1000-9999"
        )

        # Create test members and volunteers using factory methods
        self.volunteer_member = self.create_test_member(
            first_name="Integration",
            last_name="Volunteer",
            email=self.volunteer_email
        )
        self.board_member_member = self.create_test_member(
            first_name="Integration",
            last_name="BoardMember",
            email=self.board_member_email
        )

        self.test_volunteer = self.create_test_volunteer(
            member=self.volunteer_member.name,
            volunteer_name="Integration Volunteer",
            email=self.volunteer_email
        )
        self.board_volunteer = self.create_test_volunteer(
            member=self.board_member_member.name,
            volunteer_name="Integration Board Member",
            email=self.board_member_email
        )

        # Set up board positions
        cls.setup_board_positions()

        # Create expense categories
        cls.expense_categories = cls.create_expense_categories()

    def create_test_chapter_legacy(self):  # Renamed to avoid conflict with base class method
        """Create test chapter"""
        chapter_name = "Integration Test Chapter"
        if not frappe.db.exists("Chapter", chapter_name):
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "chapter_name": chapter_name,
                    "city": "Integration City",
                    "country": "Netherlands",
                    "enabled": 1}
            )
            chapter.insert()
            return chapter.name
        return chapter_name

    @classmethod
    def create_test_team(cls):
        """Create test team"""
        team_name = "Integration Test Team"
        if not frappe.db.exists("Team", team_name):
            team = frappe.get_doc(
                {
                    "doctype": "Team",
                    "team_name": team_name,
                    "description": "Integration test team",
                    "chapter": cls.test_chapter,
                    "status": "Active"}
            )
            team.insert()
            return team.name
        return team_name

    @classmethod
    def setup_chapter_roles(cls):
        """Set up chapter roles with proper permissions"""
        roles_data = [
            {
                "name": "Integration Chair",
                "permissions_level": "Admin",
                "can_approve_expenses": 1,
                "description": "Chapter chair with admin permissions"},
            {
                "name": "Integration Treasurer",
                "permissions_level": "Financial",
                "can_approve_expenses": 1,
                "description": "Treasurer with financial permissions"},
            {
                "name": "Integration Secretary",
                "permissions_level": "Basic",
                "can_approve_expenses": 1,
                "description": "Secretary with basic permissions"},
        ]

        cls.chapter_roles = {}
        for role_data in roles_data:
            if not frappe.db.exists("Chapter Role", role_data["name"]):
                role = frappe.get_doc(
                    {
                        "doctype": "Chapter Role",
                        "role_name": role_data["name"],
                        "permissions_level": role_data["permissions_level"],
                        "can_approve_expenses": role_data["can_approve_expenses"],
                        "description": role_data["description"]}
                )
                role.insert()
            cls.chapter_roles[role_data["permissions_level"].lower()] = role_data["name"]

    @classmethod
    def create_test_member(cls, email, name):
        """Create test member"""
        member_id = f"INT-{name.replace(' ', '-').upper()}"
        if not frappe.db.exists("Member", member_id):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "member_id": member_id,
                    "first_name": name.split()[0],
                    "last_name": name.split()[-1],
                    "full_name": name,
                    "email": email,
                    "user": email,
                    "status": "Active"}
            )
            member.insert()
            return member.name
        return member_id

    @classmethod
    def create_test_volunteer(cls, member_id, email):
        """Create test volunteer"""
        volunteer_name = f"INT-VOL-{member_id.split('-')[-1]}"
        if not frappe.db.exists("Volunteer", volunteer_name):
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "name": volunteer_name,
                    "volunteer_name": frappe.db.get_value("Member", member_id, "full_name"),
                    "member": member_id,
                    "email": email,
                    "status": "Active"}
            )
            volunteer.insert()
            return volunteer.name
        return volunteer_name

    @classmethod
    def setup_chapter_memberships(cls):
        """Set up chapter memberships"""
        chapter_doc = frappe.get_doc("Chapter", cls.test_chapter)

        members_to_add = [cls.volunteer_member, cls.board_member_member]

        for member_id in members_to_add:
            member_exists = any(m.member == member_id for m in chapter_doc.members)
            if not member_exists:
                chapter_doc.append(
                    "members", {"member": member_id, "chapter_join_date": today(), "enabled": 1}
                )

        chapter_doc.save()

    @classmethod
    def setup_board_positions(cls):
        """Set up board positions"""
        # Make board member a chapter chair
        if not frappe.db.exists(
            "Chapter Board Member", {"volunteer": cls.board_volunteer, "parent": cls.test_chapter}
        ):
            board_position = frappe.get_doc(
                {
                    "doctype": "Chapter Board Member",
                    "parent": cls.test_chapter,
                    "parenttype": "Chapter",
                    "parentfield": "board_members",
                    "volunteer": cls.board_volunteer,
                    "chapter_role": cls.chapter_roles["admin"],
                    "start_date": today(),
                    "is_active": 1}
            )
            board_position.insert()

    @classmethod
    def create_expense_categories(cls):
        """Create expense categories"""
        categories = []
        category_data = [
            {"name": "Integration Travel", "description": "Travel expenses for integration testing"},
            {"name": "Integration Materials", "description": "Material costs for integration testing"},
            {"name": "Integration Food", "description": "Food expenses for integration testing"},
        ]

        for cat_data in category_data:
            if not frappe.db.exists("Expense Category", cat_data["name"]):
                category = frappe.get_doc(
                    {
                        "doctype": "Expense Category",
                        "category_name": cat_data["name"],
                        "description": cat_data["description"],
                        "disabled": 0}
                )
                category.insert()
                categories.append(category.name)
            else:
                categories.append(cat_data["name"])

        return categories

    def setUp(self):
        """Set up for each test"""
        frappe.set_user("Administrator")

    def tearDown(self):
        """Clean up after each test"""
        frappe.set_user("Administrator")
        # Clean up test expenses
        expenses = frappe.get_all(
            "Volunteer Expense", filters={"volunteer": ["in", [self.test_volunteer, self.board_volunteer]]}
        )
        for expense in expenses:
            try:
                frappe.delete_doc("Volunteer Expense", expense.name, force=1)
            except Exception:
                pass

    # FULL WORKFLOW INTEGRATION TESTS

    def test_complete_expense_workflow_basic_approval(self):
        """Test complete workflow: submission → notification → approval → confirmation"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import approve_expense

        # Step 1: Volunteer submits expense
        frappe.set_user(self.volunteer_email)

        expense_data = {
            "description": "Integration test travel expense",
            "amount": 75.00,  # Basic approval level
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter,
            "category": self.expense_categories[0],
            "notes": "Integration testing expense"}

        # Submit expense
        submit_result = submit_expense(expense_data)
        self.assertTrue(submit_result["success"])
        expense_name = submit_result["expense_name"]

        # Verify expense was created correctly
        expense = frappe.get_doc("Volunteer Expense", expense_name)
        self.assertEqual(expense.status, "Submitted")
        self.assertEqual(expense.volunteer, self.test_volunteer)
        self.assertEqual(expense.amount, 75.00)

        # Step 2: Board member receives notification and approves
        frappe.set_user(self.board_member_email)

        # Verify board member can see and approve the expense
        approve_expense(expense_name)

        # Refresh expense document
        expense.reload()
        self.assertEqual(expense.status, "Approved")
        self.assertEqual(expense.approved_by, self.board_member_email)
        self.assertIsNotNone(expense.approved_on)

        # Step 3: Verify volunteer can see updated status
        frappe.set_user(self.volunteer_email)

        from verenigingen.templates.pages.volunteer.expenses import get_expense_details

        updated_details = get_expense_details(expense_name)

        self.assertEqual(updated_details["status"], "Approved")

        # Clean up
        frappe.set_user("Administrator")
        frappe.delete_doc("Volunteer Expense", expense_name, force=1)

    def test_complete_expense_workflow_admin_approval_required(self):
        """Test workflow for expense requiring admin approval"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import approve_expense

        # Step 1: Volunteer submits high-value expense
        frappe.set_user(self.volunteer_email)

        expense_data = {
            "description": "High-value integration test expense",
            "amount": 750.00,  # Admin approval level required
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter,
            "category": self.expense_categories[1]}

        submit_result = submit_expense(expense_data)
        self.assertTrue(submit_result["success"])
        expense_name = submit_result["expense_name"]

        # Verify expense was created
        expense = frappe.get_doc("Volunteer Expense", expense_name)
        self.assertEqual(expense.status, "Submitted")
        self.assertEqual(expense.amount, 750.00)

        # Step 2: Verify approval level is correctly determined
        from verenigingen.utils.expense_permissions import ExpensePermissionManager

        manager = ExpensePermissionManager()
        required_level = manager.get_required_permission_level(expense.amount)
        self.assertEqual(required_level, "admin")

        # Step 3: Board member (admin level) approves
        frappe.set_user(self.board_member_email)

        # Verify admin can approve high-value expense
        approve_expense(expense_name)

        expense.reload()
        self.assertEqual(expense.status, "Approved")
        self.assertEqual(expense.approved_by, self.board_member_email)

        # Clean up
        frappe.set_user("Administrator")
        frappe.delete_doc("Volunteer Expense", expense_name, force=1)

    def test_expense_rejection_workflow(self):
        """Test expense rejection workflow"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import reject_expense

        # Step 1: Submit expense
        frappe.set_user(self.volunteer_email)

        expense_data = {
            "description": "Expense to be rejected",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        submit_result = submit_expense(expense_data)
        self.assertTrue(submit_result["success"])
        expense_name = submit_result["expense_name"]

        # Step 2: Board member rejects expense
        frappe.set_user(self.board_member_email)

        rejection_reason = "Insufficient documentation provided"
        reject_expense(expense_name, rejection_reason)

        # Verify rejection
        expense = frappe.get_doc("Volunteer Expense", expense_name)
        self.assertEqual(expense.status, "Rejected")
        self.assertIn(rejection_reason, expense.notes or "")

        # Step 3: Verify volunteer can see rejection
        frappe.set_user(self.volunteer_email)

        from verenigingen.templates.pages.volunteer.expenses import get_expense_details

        details = get_expense_details(expense_name)
        self.assertEqual(details["status"], "Rejected")

        # Clean up
        frappe.set_user("Administrator")
        frappe.delete_doc("Volunteer Expense", expense_name, force=1)

    # PERMISSION INTEGRATION TESTS

    def test_permission_system_integration(self):
        """Test integration between portal and permission system"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense
        from verenigingen.utils.expense_permissions import ExpensePermissionManager

        # Test different approval levels
        test_amounts = [(50.00, "basic"), (250.00, "financial"), (750.00, "admin")]

        expense_names = []

        try:
            frappe.set_user(self.volunteer_email)
            manager = ExpensePermissionManager()

            for amount, expected_level in test_amounts:
                # Submit expense
                expense_data = {
                    "description": f"Permission test €{amount}",
                    "amount": amount,
                    "expense_date": today(),
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter}

                result = submit_expense(expense_data)
                self.assertTrue(result["success"])
                expense_names.append(result["expense_name"])

                # Verify permission level calculation
                expense = frappe.get_doc("Volunteer Expense", result["expense_name"])
                actual_level = manager.get_required_permission_level(expense.amount)
                self.assertEqual(actual_level, expected_level)

                # Verify board member can approve (has admin level)
                frappe.set_user(self.board_member_email)
                can_approve = manager.can_approve_expense(expense)
                self.assertTrue(can_approve)

                frappe.set_user(self.volunteer_email)

        finally:
            # Clean up
            frappe.set_user("Administrator")
            for expense_name in expense_names:
                try:
                    frappe.delete_doc("Volunteer Expense", expense_name, force=1)
                except Exception:
                    pass

    def test_approval_dashboard_integration(self):
        """Test integration with approval dashboard"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense
        from verenigingen.verenigingen.doctype.expense_approval_dashboard.expense_approval_dashboard import (
            bulk_approve_expenses,
            get_pending_expenses_for_dashboard,
        )

        expense_names = []

        try:
            # Submit multiple expenses
            frappe.set_user(self.volunteer_email)

            for i in range(3):
                expense_data = {
                    "description": f"Dashboard integration test {i + 1}",
                    "amount": 30.00 + (i * 10),
                    "expense_date": today(),
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter}

                result = submit_expense(expense_data)
                self.assertTrue(result["success"])
                expense_names.append(result["expense_name"])

            # Test dashboard can see expenses
            frappe.set_user(self.board_member_email)

            pending_expenses = get_pending_expenses_for_dashboard()

            # Should include our test expenses
            dashboard_expense_names = [exp.name for exp in pending_expenses]
            for expense_name in expense_names:
                self.assertIn(expense_name, dashboard_expense_names)

            # Test bulk approval
            bulk_result = bulk_approve_expenses(expense_names)

            self.assertGreaterEqual(len(bulk_result["approved"]), 2)  # At least 2 should be approved

            # Verify expenses are approved
            for expense_name in expense_names:
                expense = frappe.get_doc("Volunteer Expense", expense_name)
                if expense_name in bulk_result["approved"]:
                    self.assertEqual(expense.status, "Approved")

        finally:
            # Clean up
            frappe.set_user("Administrator")
            for expense_name in expense_names:
                try:
                    frappe.delete_doc("Volunteer Expense", expense_name, force=1)
                except Exception:
                    pass

    # NOTIFICATION INTEGRATION TESTS

    @patch("frappe.sendmail")
    def test_notification_system_integration(self, mock_sendmail):
        """Test integration with notification system"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import approve_expense

        # Step 1: Submit expense (should trigger approval notification)
        frappe.set_user(self.volunteer_email)

        expense_data = {
            "description": "Notification integration test",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "Chapter",
            "chapter": self.test_chapter}

        result = submit_expense(expense_data)
        self.assertTrue(result["success"])
        expense_name = result["expense_name"]

        # Verify approval notification was sent
        self.assertTrue(mock_sendmail.called)

        # Reset mock for approval notification
        mock_sendmail.reset_mock()

        # Step 2: Approve expense (should trigger approval confirmation)
        frappe.set_user(self.board_member_email)

        approve_expense(expense_name)

        # Verify approval confirmation was sent
        self.assertTrue(mock_sendmail.called)

        # Clean up
        frappe.set_user("Administrator")
        frappe.delete_doc("Volunteer Expense", expense_name, force=1)

    # ORGANIZATION ACCESS INTEGRATION TESTS

    def test_multi_organization_access_integration(self):
        """Test volunteer access across multiple organizations"""
        from verenigingen.templates.pages.volunteer.expenses import (
            get_volunteer_organizations,
            submit_expense,
        )

        # Create additional team
        extra_team = "Extra Integration Team"
        if not frappe.db.exists("Team", extra_team):
            team = frappe.get_doc(
                {
                    "doctype": "Team",
                    "team_name": extra_team,
                    "description": "Extra team for integration testing",
                    "chapter": self.test_chapter,
                    "status": "Active"}
            )
            team.insert()

        # Add volunteer to extra team
        if not frappe.db.exists("Team Member", {"volunteer": self.test_volunteer, "parent": extra_team}):
            team_member = frappe.get_doc(
                {
                    "doctype": "Team Member",
                    "parent": extra_team,
                    "parenttype": "Team",
                    "parentfield": "members",
                    "volunteer": self.test_volunteer,
                    "role_type": "Team Member",
                    "status": "Active",
                    "joined_date": today()}
            )
            team_member.insert()

        try:
            frappe.set_user(self.volunteer_email)

            # Test volunteer can see multiple organizations
            organizations = get_volunteer_organizations(self.test_volunteer)

            self.assertGreater(len(organizations["chapters"]), 0)
            self.assertGreater(len(organizations["teams"]), 1)  # Should have at least 2 teams now

            team_names = [t["name"] for t in organizations["teams"]]
            self.assertIn(self.test_team, team_names)
            self.assertIn(extra_team, team_names)

            # Test can submit expenses for both organizations
            expense_names = []

            # Submit for chapter
            chapter_expense_data = {
                "description": "Multi-org chapter expense",
                "amount": 40.00,
                "expense_date": today(),
                "organization_type": "Chapter",
                "chapter": self.test_chapter}

            result1 = submit_expense(chapter_expense_data)
            self.assertTrue(result1["success"])
            expense_names.append(result1["expense_name"])

            # Submit for team
            team_expense_data = {
                "description": "Multi-org team expense",
                "amount": 35.00,
                "expense_date": today(),
                "organization_type": "Team",
                "team": extra_team}

            result2 = submit_expense(team_expense_data)
            self.assertTrue(result2["success"])
            expense_names.append(result2["expense_name"])

            # Verify both expenses were created correctly
            for expense_name in expense_names:
                expense = frappe.get_doc("Volunteer Expense", expense_name)
                self.assertEqual(expense.volunteer, self.test_volunteer)
                self.assertEqual(expense.status, "Submitted")

            # Clean up expenses
            for expense_name in expense_names:
                frappe.delete_doc("Volunteer Expense", expense_name, force=1)

        finally:
            # Clean up team
            frappe.set_user("Administrator")
            try:
                frappe.delete_doc("Team", extra_team, force=1)
            except Exception:
                pass

    # REPORTING INTEGRATION TESTS

    def test_expense_reporting_integration(self):
        """Test integration with expense reporting system"""
        from verenigingen.templates.pages.volunteer.expenses import get_expense_statistics, submit_expense
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import approve_expense

        expense_names = []

        try:
            frappe.set_user(self.volunteer_email)

            # Submit multiple expenses with different statuses
            test_expenses = [
                {"amount": 25.00, "description": "Reporting test 1"},
                {"amount": 45.00, "description": "Reporting test 2"},
                {"amount": 35.00, "description": "Reporting test 3"},
            ]

            for exp_data in test_expenses:
                expense_data = {
                    "description": exp_data["description"],
                    "amount": exp_data["amount"],
                    "expense_date": today(),
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter}

                result = submit_expense(expense_data)
                self.assertTrue(result["success"])
                expense_names.append(result["expense_name"])

            # Approve some expenses
            frappe.set_user(self.board_member_email)

            for i, expense_name in enumerate(expense_names[:2]):  # Approve first 2
                approve_expense(expense_name)

            # Test statistics calculation
            frappe.set_user(self.volunteer_email)

            stats = get_expense_statistics(self.test_volunteer)

            # Verify statistics are correct
            expected_total_submitted = sum(exp["amount"] for exp in test_expenses)
            expected_total_approved = sum(exp["amount"] for exp in test_expenses[:2])

            self.assertEqual(stats["total_submitted"], expected_total_submitted)
            self.assertEqual(stats["total_approved"], expected_total_approved)
            self.assertEqual(stats["pending_count"], 1)  # One still pending
            self.assertEqual(stats["approved_count"], 2)  # Two approved

        finally:
            # Clean up
            frappe.set_user("Administrator")
            for expense_name in expense_names:
                try:
                    frappe.delete_doc("Volunteer Expense", expense_name, force=1)
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
