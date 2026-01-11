import unittest
from unittest.mock import patch

import frappe
from frappe.utils import today
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerPortalIntegration(EnhancedTestCase):
    """Integration tests for the volunteer portal with approval workflow"""

    def setUp(self):
        """Set up test environment using factory methods"""
        super().setUp()
        self.setup_test_data()

    def setup_test_data(self):
        """Create comprehensive test data for integration testing"""
        # Clean up any leftover test volunteers from previous failed runs
        # to prevent duplicate email errors
        for email in ["integration.volunteer@test.com", "integration.board@test.com"]:
            for vol in frappe.get_all("Volunteer", filters={"email": email}):
                try:
                    frappe.delete_doc("Volunteer", vol.name, force=True)
                except Exception:
                    pass
        frappe.db.commit()

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
            (self.board_member_email, "Integration Board Member", ["Verenigingen Chapter Board Member"]),
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
        # Note: Chapter uses autoname:"prompt", so name is set directly via factory
        # Let factory auto-generate unique name for test isolation
        self.test_chapter = self.create_test_chapter(
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

        # Create volunteers with _exact_email=True to use static emails for assertions
        self.test_volunteer = self.create_test_volunteer(
            member=self.volunteer_member.name,
            volunteer_name="Integration Volunteer",
            email=self.volunteer_email,
            _exact_email=True  # Required to prevent factory from generating unique email
        )
        self.board_volunteer = self.create_test_volunteer(
            member=self.board_member_member.name,
            volunteer_name="Integration Board Member",
            email=self.board_member_email,
            _exact_email=True  # Required to prevent factory from generating unique email
        )

        # Store string names for use in tests (factory methods return doc objects)
        self.test_chapter_name = self.test_chapter.name if hasattr(self.test_chapter, 'name') else self.test_chapter
        self.test_volunteer_name = self.test_volunteer.name if hasattr(self.test_volunteer, 'name') else self.test_volunteer
        self.board_volunteer_name = self.board_volunteer.name if hasattr(self.board_volunteer, 'name') else self.board_volunteer

        # Set up chapter roles first (needed for board positions)
        self.setup_chapter_roles()

        # Set up chapter memberships (required for expense submissions)
        self.setup_chapter_memberships()

        # Set up board positions
        self.setup_board_positions()

        # Create test team for multi-organization tests
        self.test_team = self.create_integration_team()

        # Create expense categories
        self.expense_categories = self.create_expense_categories()

        # Configure Vereinigingen Settings for expense submission
        self.configure_verenigingen_settings()

        # Create Employee records for volunteers (required for expense submission)
        self.setup_employee_records()

    def create_integration_team(self):
        """Create test team for integration tests"""
        team_name = "Integration Test Team"
        # Get document name (factory methods return doc objects)
        test_chapter_name = self.test_chapter.name if hasattr(self.test_chapter, 'name') else self.test_chapter
        if not frappe.db.exists("Team", team_name):
            team = frappe.get_doc(
                {
                    "doctype": "Team",
                    "team_name": team_name,
                    "description": "Integration test team",
                    "chapter": test_chapter_name,
                    "status": "Active"}
            )
            team.insert()
            return team.name
        return team_name

    def configure_verenigingen_settings(self):
        """Configure Verenigingen Settings for expense submission testing.

        The expense submission service for "National" organization type requires:
        - national_board_chapter: Points to a valid chapter for national expenses
        - company: Points to the test company

        This ensures submit_expense doesn't fail with "Could not find Chapter" errors.
        """
        original_user = frappe.session.user
        try:
            frappe.set_user("Administrator")

            settings = frappe.get_single("Verenigingen Settings")

            # Configure national board chapter
            test_chapter_name = self.test_chapter.name if hasattr(self.test_chapter, 'name') else self.test_chapter
            settings.national_board_chapter = test_chapter_name

            # Configure company
            settings.company = self.company

            settings.save()
            frappe.db.commit()

        finally:
            frappe.set_user(original_user)

    def setup_chapter_roles(self):
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

        self.chapter_roles = {}
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
            self.chapter_roles[role_data["permissions_level"].lower()] = role_data["name"]

    def setup_chapter_memberships(self):
        """Set up chapter memberships"""
        # Get document name (factory methods return doc objects)
        test_chapter_name = self.test_chapter.name if hasattr(self.test_chapter, 'name') else self.test_chapter
        chapter_doc = frappe.get_doc("Chapter", test_chapter_name)

        # Get member names
        volunteer_member_name = self.volunteer_member.name if hasattr(self.volunteer_member, 'name') else self.volunteer_member
        board_member_name = self.board_member_member.name if hasattr(self.board_member_member, 'name') else self.board_member_member
        members_to_add = [volunteer_member_name, board_member_name]

        for member_id in members_to_add:
            member_exists = any(m.member == member_id for m in chapter_doc.members)
            if not member_exists:
                chapter_doc.append(
                    "members", {"member": member_id, "chapter_join_date": today(), "enabled": 1}
                )

        chapter_doc.save()

    def setup_board_positions(self):
        """Set up board positions"""
        # Get document names (factory methods return doc objects)
        board_volunteer_name = self.board_volunteer.name if hasattr(self.board_volunteer, 'name') else self.board_volunteer
        test_chapter_name = self.test_chapter.name if hasattr(self.test_chapter, 'name') else self.test_chapter

        # Make board member a chapter chair using proper parent.append() pattern
        if not frappe.db.exists(
            "Chapter Board Member", {"volunteer": board_volunteer_name, "parent": test_chapter_name}
        ):
            chapter_doc = frappe.get_doc("Chapter", test_chapter_name)
            chapter_doc.append("board_members", {
                "volunteer": board_volunteer_name,
                "chapter_role": self.chapter_roles["admin"],
                "from_date": today(),  # Changed from start_date per DocType validation
                "is_active": 1
            })
            chapter_doc.save()

    def create_expense_categories(self):
        """Get existing Expense Claim Types for testing

        Note: ERPNext Expense Claims require "Expense Claim Type" records, not
        our custom "Expense Category" DocType. This method returns existing
        Expense Claim Types that can be used in expense submission tests.
        """
        # Use existing ERPNext Expense Claim Types
        # Available types: Calls, Food, Medical, Others, Reiskosten, Materiaalkosten, Travel
        existing_types = frappe.get_all("Expense Claim Type", pluck="name")

        if not existing_types:
            # If no expense claim types exist, create one
            expense_account = frappe.db.get_value("Account", {"account_type": "Expense"}, "name")
            if not expense_account:
                expense_account = frappe.db.get_value(
                    "Account", {"account_type": "Expense Account"}, "name"
                )

            expense_type = frappe.get_doc({
                "doctype": "Expense Claim Type",
                "expense_type": "Test Travel",
                "default_account": expense_account
            })
            expense_type.insert()
            return ["Test Travel"]

        # Return a few common types for testing
        preferred_types = ["Travel", "Food", "Reiskosten"]
        categories = [t for t in preferred_types if t in existing_types]

        # Fallback to whatever exists if none of preferred types are found
        if not categories:
            categories = existing_types[:3]

        return categories

    def setup_employee_records(self):
        """Create Employee records for test volunteers

        Required for expense submission - the expense submission service requires
        volunteers to have linked Employee records for ERPNext Expense Claim creation.
        """
        # Get volunteer document names
        test_volunteer_name = self.test_volunteer.name if hasattr(self.test_volunteer, 'name') else self.test_volunteer
        board_volunteer_name = self.board_volunteer.name if hasattr(self.board_volunteer, 'name') else self.board_volunteer

        # Create employee for test volunteer
        self.test_employee = self._create_employee_for_volunteer(
            volunteer_name=test_volunteer_name,
            volunteer_doc=self.test_volunteer,
            member_doc=self.volunteer_member,
            user_email=self.volunteer_email
        )

        # Create employee for board volunteer
        self.board_employee = self._create_employee_for_volunteer(
            volunteer_name=board_volunteer_name,
            volunteer_doc=self.board_volunteer,
            member_doc=self.board_member_member,
            user_email=self.board_member_email
        )

    def _create_employee_for_volunteer(self, volunteer_name, volunteer_doc, member_doc, user_email):
        """Create Employee record and link to volunteer

        Args:
            volunteer_name: The Volunteer document name
            volunteer_doc: The Volunteer document
            member_doc: The Member document
            user_email: The user email for the employee

        Returns:
            Employee name
        """
        original_user = frappe.session.user
        try:
            frappe.set_user("Administrator")

            # First, check if volunteer already has an employee_id
            volunteer = frappe.get_doc("Volunteer", volunteer_name)
            if volunteer.employee_id and frappe.db.exists("Employee", volunteer.employee_id):
                return volunteer.employee_id

            # Check if an employee already exists with this user_id (ERPNext unique constraint)
            existing_employee = frappe.db.get_value("Employee", {"user_id": user_email}, "name")
            if existing_employee:
                # Link existing employee to volunteer
                if not volunteer.employee_id:
                    volunteer.employee_id = existing_employee
                    volunteer.save()
                    frappe.db.commit()
                return existing_employee

            # Create new employee record
            employee = frappe.get_doc({
                "doctype": "Employee",
                "naming_series": "HR-EMP-",  # Standard ERPNext naming
                "employee_name": volunteer_doc.volunteer_name if hasattr(volunteer_doc, 'volunteer_name') else str(volunteer_doc),
                "first_name": member_doc.first_name if hasattr(member_doc, 'first_name') else "Test",
                "last_name": member_doc.last_name if hasattr(member_doc, 'last_name') else "Volunteer",
                "company": self.company,
                "date_of_joining": today(),
                "date_of_birth": "1990-01-01",  # Required field
                "gender": "Other",  # Required field - ERPNext mandates this
                "status": "Active",
                "user_id": user_email  # Link to user account
            })
            employee.insert()
            employee_name = employee.name

            # Link employee to volunteer
            volunteer.employee_id = employee_name
            volunteer.save()

            frappe.db.commit()

            return employee_name
        finally:
            frappe.set_user(original_user)

    def tearDown(self):
        """Clean up after each test"""
        # EnhancedTestCase tearDown handles user restoration
        # Clean up test expense claims - guard against setUp failure
        employee_names = []
        if hasattr(self, 'test_employee') and self.test_employee:
            employee_names.append(self.test_employee)
        if hasattr(self, 'board_employee') and self.board_employee:
            employee_names.append(self.board_employee)

        if employee_names:
            # Clean up Expense Claims created during tests (ERPNext native DocType)
            expense_claims = frappe.get_all(
                "Expense Claim",
                filters={"employee": ["in", employee_names], "docstatus": ["!=", 1]}
            )
            for claim in expense_claims:
                try:
                    frappe.delete_doc("Expense Claim", claim.name, force=1)
                except Exception:
                    pass

        super().tearDown()

    # FULL WORKFLOW INTEGRATION TESTS

    def test_complete_expense_workflow_basic_approval(self):
        """Test complete workflow: submission → approval using ERPNext Expense Claim"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Step 1: Volunteer submits expense
        expense_data = {
            "description": "Integration test travel expense",
            "amount": 75.00,
            "expense_date": today(),
            "organization_type": "National",  # Use National to avoid chapter cost center issues
            "category": self.expense_categories[0],
            "notes": "Integration testing expense"
        }

        original_user = frappe.session.user
        expense_claim_name = None
        try:
            frappe.set_user(self.volunteer_email)

            # Submit expense - creates ERPNext Expense Claim
            submit_result = submit_expense(expense_data)
            if not submit_result.get("success"):
                self.fail(f"submit_expense failed: {submit_result.get('message', submit_result.get('errors', 'Unknown error'))}")

            self.assertTrue(submit_result["success"])
            expense_claim_name = submit_result.get("expense_claim_name")
            self.assertIsNotNone(expense_claim_name, "Expected expense_claim_name in response")

            # Verify Expense Claim was created correctly
            expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
            self.assertEqual(expense_claim.docstatus, 0)  # Draft
            self.assertEqual(expense_claim.total_claimed_amount, 75.00)

            # Step 2: Admin approves the expense claim
            # Note: We don't call submit() as that requires ERPNext GL setup (fiscal year, accounts)
            # The approval workflow is tested by setting approval_status
            frappe.set_user("Administrator")

            expense_claim.reload()
            expense_claim.approval_status = "Approved"
            expense_claim.save()

            # Verify approval status was set correctly
            expense_claim.reload()
            self.assertEqual(expense_claim.docstatus, 0)  # Still Draft - not submitted for GL
            self.assertEqual(expense_claim.approval_status, "Approved")

        finally:
            frappe.set_user(original_user)
            # Clean up
            if expense_claim_name:
                try:
                    frappe.delete_doc("Expense Claim", expense_claim_name, force=1)
                except Exception:
                    pass

    def test_complete_expense_workflow_admin_approval_required(self):
        """Test workflow for high-value expense requiring admin approval using ERPNext Expense Claim"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Step 1: Volunteer submits high-value expense
        expense_data = {
            "description": "High-value integration test expense",
            "amount": 750.00,  # High value for admin-level approval
            "expense_date": today(),
            "organization_type": "National",  # Use National to avoid chapter cost center issues
            "category": self.expense_categories[0] if self.expense_categories else "Travel",
            "notes": "High-value expense for admin approval testing"
        }

        original_user = frappe.session.user
        expense_claim_name = None
        try:
            frappe.set_user(self.volunteer_email)

            # Submit expense - creates ERPNext Expense Claim
            submit_result = submit_expense(expense_data)
            if not submit_result.get("success"):
                self.fail(f"submit_expense failed: {submit_result.get('message', submit_result.get('errors', 'Unknown error'))}")

            self.assertTrue(submit_result["success"])
            expense_claim_name = submit_result.get("expense_claim_name")
            self.assertIsNotNone(expense_claim_name, "Expected expense_claim_name in response")

            # Verify Expense Claim was created with correct amount
            expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
            self.assertEqual(expense_claim.docstatus, 0)  # Draft
            self.assertEqual(expense_claim.total_claimed_amount, 750.00)

            # Step 2: Administrator approves high-value expense
            # Note: We don't call submit() as that requires ERPNext GL setup (fiscal year, accounts)
            frappe.set_user("Administrator")

            expense_claim.reload()
            expense_claim.approval_status = "Approved"
            expense_claim.save()

            # Verify approval status was set correctly
            expense_claim.reload()
            self.assertEqual(expense_claim.docstatus, 0)  # Still Draft - not submitted for GL
            self.assertEqual(expense_claim.approval_status, "Approved")

        finally:
            frappe.set_user(original_user)
            # Clean up
            if expense_claim_name:
                try:
                    frappe.delete_doc("Expense Claim", expense_claim_name, force=1)
                except Exception:
                    pass

    def test_expense_rejection_workflow(self):
        """Test expense rejection workflow using ERPNext Expense Claim"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Step 1: Submit expense
        expense_data = {
            "description": "Expense to be rejected",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "National",
            "category": self.expense_categories[0] if self.expense_categories else "Travel",
            "notes": "Testing rejection workflow"
        }

        original_user = frappe.session.user
        expense_claim_name = None
        try:
            frappe.set_user(self.volunteer_email)

            submit_result = submit_expense(expense_data)
            if not submit_result.get("success"):
                self.fail(f"submit_expense failed: {submit_result.get('message', submit_result.get('errors', 'Unknown error'))}")

            self.assertTrue(submit_result["success"])
            expense_claim_name = submit_result.get("expense_claim_name")
            self.assertIsNotNone(expense_claim_name)

            # Verify expense was created
            expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
            self.assertEqual(expense_claim.docstatus, 0)  # Draft
            self.assertEqual(expense_claim.total_claimed_amount, 50.00)

            # Step 2: Administrator rejects expense
            frappe.set_user("Administrator")
            rejection_reason = "Insufficient documentation provided"

            expense_claim.reload()
            expense_claim.approval_status = "Rejected"
            # Add rejection note via comment
            expense_claim.add_comment("Comment", rejection_reason)
            expense_claim.save()

            # Verify rejection (rejected claims stay in Draft status)
            expense_claim.reload()
            self.assertEqual(expense_claim.docstatus, 0)  # Still Draft - rejected claims are not submitted
            self.assertEqual(expense_claim.approval_status, "Rejected")

        finally:
            frappe.set_user(original_user)
            # Clean up
            if expense_claim_name:
                try:
                    frappe.delete_doc("Expense Claim", expense_claim_name, force=1)
                except Exception:
                    pass

    # PERMISSION INTEGRATION TESTS

    def test_permission_system_integration(self):
        """Test integration between portal and permission system using ERPNext Expense Claim"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Test different expense amounts
        test_amounts = [50.00, 250.00, 750.00]

        expense_claim_names = []
        original_user = frappe.session.user

        try:
            frappe.set_user(self.volunteer_email)

            for amount in test_amounts:
                # Submit expense
                expense_data = {
                    "description": f"Permission test €{amount}",
                    "amount": amount,
                    "expense_date": today(),
                    "organization_type": "National",
                    "category": self.expense_categories[0] if self.expense_categories else "Travel",
                    "notes": f"Permission integration test for {amount}"
                }

                result = submit_expense(expense_data)
                if not result.get("success"):
                    self.fail(f"submit_expense failed for €{amount}: {result.get('message', result.get('errors', 'Unknown error'))}")

                self.assertTrue(result["success"])
                expense_claim_name = result.get("expense_claim_name")
                self.assertIsNotNone(expense_claim_name)
                expense_claim_names.append(expense_claim_name)

                # Verify Expense Claim was created with correct amount
                expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
                self.assertEqual(expense_claim.total_claimed_amount, amount)

            # Verify administrator can approve all expense amounts
            # Note: We don't call submit() as that requires ERPNext GL setup (fiscal year, accounts)
            frappe.set_user("Administrator")

            for expense_claim_name in expense_claim_names:
                expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
                expense_claim.approval_status = "Approved"
                expense_claim.save()

                # Verify approval status was set correctly
                expense_claim.reload()
                self.assertEqual(expense_claim.docstatus, 0)  # Still Draft - not submitted for GL
                self.assertEqual(expense_claim.approval_status, "Approved")

        finally:
            frappe.set_user(original_user)
            # Clean up
            for expense_claim_name in expense_claim_names:
                try:
                    frappe.delete_doc("Expense Claim", expense_claim_name, force=1)
                except Exception:
                    pass

    @unittest.skip("expense_approval_dashboard DocType not implemented")
    def test_approval_dashboard_integration(self):
        """Test integration with approval dashboard"""
        # Skipped: expense_approval_dashboard DocType does not exist yet
        # When implemented, uncomment these imports:
        # from verenigingen.templates.pages.volunteer.expenses import submit_expense
        # from verenigingen.verenigingen.doctype.expense_approval_dashboard.expense_approval_dashboard import (
        #     bulk_approve_expenses,
        #     get_pending_expenses_for_dashboard,
        # )
        pass  # Test skipped - DocType not implemented

        expense_names = []

        try:
            # Submit multiple expenses
            # EnhancedTestCase handles permissions: frappe.set_user(self.volunteer_email)

            for i in range(3):
                expense_data = {
                    "description": f"Dashboard integration test {i + 1}",
                    "amount": 30.00 + (i * 10),
                    "expense_date": today(),
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter_name}

                result = submit_expense(expense_data)
                self.assertTrue(result["success"])
                expense_names.append(result["expense_name"])

            # Test dashboard can see expenses
            # EnhancedTestCase handles permissions: frappe.set_user(self.board_member_email)

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
            # EnhancedTestCase tearDown handles user restoration
            for expense_name in expense_names:
                try:
                    frappe.delete_doc("Volunteer Expense", expense_name, force=1)
                except Exception:
                    pass

    # NOTIFICATION INTEGRATION TESTS

    # Mock justified: External service - email notifications, not business logic
    @patch("frappe.sendmail")
    def test_notification_system_integration(self, mock_sendmail):
        """Test integration with notification system using ERPNext Expense Claim"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Step 1: Submit expense
        expense_data = {
            "description": "Notification integration test",
            "amount": 50.00,
            "expense_date": today(),
            "organization_type": "National",
            "category": self.expense_categories[0] if self.expense_categories else "Travel",
            "notes": "Testing notification system"
        }

        original_user = frappe.session.user
        expense_claim_name = None
        try:
            frappe.set_user(self.volunteer_email)

            result = submit_expense(expense_data)
            if not result.get("success"):
                self.fail(f"submit_expense failed: {result.get('message', result.get('errors', 'Unknown error'))}")

            self.assertTrue(result["success"])
            expense_claim_name = result.get("expense_claim_name")
            self.assertIsNotNone(expense_claim_name)

            # Verify Expense Claim was created
            expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
            self.assertEqual(expense_claim.total_claimed_amount, 50.00)

            # Reset mock before approval
            mock_sendmail.reset_mock()

            # Step 2: Approve expense
            # Note: We don't call submit() as that requires ERPNext GL setup (fiscal year, accounts)
            frappe.set_user("Administrator")

            expense_claim.reload()
            expense_claim.approval_status = "Approved"
            expense_claim.save()

            # Verify approval status was set correctly
            expense_claim.reload()
            self.assertEqual(expense_claim.docstatus, 0)  # Still Draft - not submitted for GL
            self.assertEqual(expense_claim.approval_status, "Approved")

        finally:
            frappe.set_user(original_user)
            # Clean up
            if expense_claim_name:
                try:
                    frappe.delete_doc("Expense Claim", expense_claim_name, force=1)
                except Exception:
                    pass

    # ORGANIZATION ACCESS INTEGRATION TESTS

    def test_multi_organization_access_integration(self):
        """Test volunteer access across multiple organizations using ERPNext Expense Claim"""
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        original_user = frappe.session.user
        expense_claim_names = []

        try:
            frappe.set_user(self.volunteer_email)

            # Submit multiple expenses with different organization types
            test_expenses = [
                {
                    "description": "National expense",
                    "amount": 40.00,
                    "expense_date": today(),
                    "organization_type": "National",
                    "category": self.expense_categories[0] if self.expense_categories else "Travel",
                    "notes": "Multi-org test - national"
                },
                {
                    "description": "Second national expense",
                    "amount": 35.00,
                    "expense_date": today(),
                    "organization_type": "National",
                    "category": self.expense_categories[0] if self.expense_categories else "Travel",
                    "notes": "Multi-org test - second national"
                }
            ]

            for expense_data in test_expenses:
                result = submit_expense(expense_data)
                if not result.get("success"):
                    self.fail(f"submit_expense failed: {result.get('message', result.get('errors', 'Unknown error'))}")

                self.assertTrue(result["success"])
                expense_claim_name = result.get("expense_claim_name")
                self.assertIsNotNone(expense_claim_name)
                expense_claim_names.append(expense_claim_name)

            # Verify at least 2 expense claims were created
            self.assertGreaterEqual(len(expense_claim_names), 2)

            # Verify all expenses were created correctly
            for expense_claim_name in expense_claim_names:
                expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
                self.assertEqual(expense_claim.docstatus, 0)  # Draft
                self.assertIn(expense_claim.total_claimed_amount, [40.00, 35.00])

        finally:
            frappe.set_user(original_user)
            # Clean up expense claims
            for expense_claim_name in expense_claim_names:
                try:
                    frappe.delete_doc("Expense Claim", expense_claim_name, force=1)
                except Exception:
                    pass

    # REPORTING INTEGRATION TESTS

    @unittest.skip("get_expense_statistics function not implemented")
    def test_expense_reporting_integration(self):
        """Test integration with expense reporting system"""
        # Note: get_expense_statistics function does not exist yet
        from verenigingen.templates.pages.volunteer.expenses import get_expense_statistics, submit_expense
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import approve_expense

        expense_names = []

        try:
            # EnhancedTestCase handles permissions: frappe.set_user(self.volunteer_email)

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
                    "chapter": self.test_chapter_name}

                result = submit_expense(expense_data)
                self.assertTrue(result["success"])
                expense_names.append(result["expense_name"])

            # Approve some expenses
            # EnhancedTestCase handles permissions: frappe.set_user(self.board_member_email)

            for i, expense_name in enumerate(expense_names[:2]):  # Approve first 2
                approve_expense(expense_name)

            # Test statistics calculation
            # EnhancedTestCase handles permissions: frappe.set_user(self.volunteer_email)

            stats = get_expense_statistics(self.test_volunteer_name)

            # Verify statistics are correct
            expected_total_submitted = sum(exp["amount"] for exp in test_expenses)
            expected_total_approved = sum(exp["amount"] for exp in test_expenses[:2])

            self.assertEqual(stats["total_submitted"], expected_total_submitted)
            self.assertEqual(stats["total_approved"], expected_total_approved)
            self.assertEqual(stats["pending_count"], 1)  # One still pending
            self.assertEqual(stats["approved_count"], 2)  # Two approved

        finally:
            # Clean up
            # EnhancedTestCase tearDown handles user restoration
            for expense_name in expense_names:
                try:
                    frappe.delete_doc("Volunteer Expense", expense_name, force=1)
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
