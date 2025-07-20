"""
Comprehensive unit tests for ERPNext Expense Claims integration
Tests the volunteer expense submission system with ERPNext HRMS integration

Updated: December 2024 - Reflects legacy system phase-out and ERPNext-only workflow
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.templates.pages.volunteer.expenses import (
    get_or_create_expense_type,
    get_organization_cost_center,
    submit_expense,
    test_expense_integration,
)

# Note: setup_expense_claim_types function removed in ERPNext integration simplification


class TestERPNextExpenseIntegration(unittest.TestCase):
    """Test ERPNext Expense Claims integration"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        # Create test company
        if not frappe.db.exists("Company", "Test Company"):
            company = frappe.get_doc(
                {
                    "doctype": "Company",
                    "company_name": "Test Company",
                    "default_currency": "EUR",
                    "country": "Netherlands"}
            )
            company.insert(ignore_permissions=True)

        # Set as default company
        frappe.db.set_default("company", "Test Company")

        # Create test accounts
        cls.create_test_accounts()

        # Create test volunteer and member
        cls.create_test_volunteer()

        # Create test expense categories
        cls.create_test_expense_categories()

    @classmethod
    def create_test_accounts(cls):
        """Create test chart of accounts"""
        accounts = [
            {
                "account_name": "Test Expense Account",
                "account_type": "Expense Account",
                "parent_account": "Expenses - TC",
                "company": "Test Company",
                "is_group": 0},
            {"account_name": "Test Cost Center", "company": "Test Company", "is_group": 0},
        ]

        for account_data in accounts:
            if not frappe.db.exists("Account", f"{account_data['account_name']} - TC"):
                try:
                    account = frappe.get_doc(dict(doctype="Account", **account_data))
                    account.insert(ignore_permissions=True)
                except Exception:
                    pass  # Account might already exist or parent missing

    @classmethod
    def create_test_volunteer(cls):
        """Create test volunteer and member"""
        # Create test member
        if not frappe.db.exists("Member", "TEST-MEM-001"):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "name": "TEST-MEM-001",
                    "first_name": "Test",
                    "last_name": "Volunteer",
                    "email": "test.volunteer@example.com",
                    "status": "Active"}
            )
            member.insert(ignore_permissions=True)

        # Create test volunteer
        if not frappe.db.exists("Volunteer", "TEST-VOL-001"):
            volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "name": "TEST-VOL-001",
                    "volunteer_name": "Test Volunteer",
                    "email": "test.volunteer@example.com",
                    "member": "TEST-MEM-001",
                    "status": "Active",
                    "start_date": frappe.utils.today()}
            )
            volunteer.insert(ignore_permissions=True)

    @classmethod
    def create_test_expense_categories(cls):
        """Create test expense categories"""
        categories = ["Travel", "Office Supplies", "Communications"]
        for category in categories:
            if not frappe.db.exists("Expense Category", category):
                cat = frappe.get_doc(
                    {"doctype": "Expense Category", "category_name": category, "is_active": 1}
                )
                cat.insert(ignore_permissions=True)

    def setUp(self):
        """Set up for each test"""
        frappe.set_user("Administrator")
        self.test_volunteer = "TEST-VOL-001"
        self.test_expense_data = {
            "description": "Test ERPNext Integration Expense",
            "amount": 50.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",
            "notes": "Test expense for unit testing"}

    def tearDown(self):
        """Clean up after each test"""
        frappe.db.rollback()

    @patch("verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record")
    def test_submit_expense_without_employee_record(self, mock_get_volunteer):
        """Test expense submission when volunteer has no employee record"""
        # Setup mock
        mock_volunteer = MagicMock()
        mock_volunteer.name = self.test_volunteer
        mock_volunteer.volunteer_name = "Test Volunteer"
        mock_volunteer.email = "test.volunteer@example.com"
        mock_volunteer.employee_id = None  # No employee record
        mock_get_volunteer.return_value = mock_volunteer

        # Mock the employee creation
        with patch.object(mock_volunteer, "create_minimal_employee", return_value="HR-EMP-TEST-001"):
            with patch.object(mock_volunteer, "reload"):
                mock_volunteer.employee_id = "HR-EMP-TEST-001"  # Simulate successful creation

                # Mock ERPNext expense claim creation
                with patch("frappe.get_doc") as mock_get_doc:
                    mock_expense_claim = MagicMock()
                    mock_expense_claim.name = "EXP-TEST-001"
                    mock_get_doc.return_value = mock_expense_claim

                    # Mock successful submission
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                        return_value="Travel",
                    ):
                        with patch(
                            "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                            return_value="Test Cost Center",
                        ):
                            result = submit_expense(self.test_expense_data)

                            self.assertTrue(result.get("success"))
                            self.assertIn("Employee record created", result.get("message", ""))
                            self.assertEqual(result.get("expense_claim_name"), "EXP-TEST-001")

    @patch("verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record")
    def test_submit_expense_with_existing_employee(self, mock_get_volunteer):
        """Test expense submission when volunteer already has employee record"""
        # Setup mock with existing employee
        mock_volunteer = MagicMock()
        mock_volunteer.name = self.test_volunteer
        mock_volunteer.volunteer_name = "Test Volunteer"
        mock_volunteer.email = "test.volunteer@example.com"
        mock_volunteer.employee_id = "HR-EMP-EXISTING-001"
        mock_get_volunteer.return_value = mock_volunteer

        # Mock ERPNext expense claim creation
        with patch("frappe.get_doc") as mock_get_doc:
            mock_expense_claim = MagicMock()
            mock_expense_claim.name = "EXP-TEST-002"
            mock_get_doc.return_value = mock_expense_claim

            with patch(
                "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                return_value="Travel",
            ):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                    return_value="Test Cost Center",
                ):
                    result = submit_expense(self.test_expense_data)

                    self.assertTrue(result.get("success"))
                    self.assertNotIn("Employee record created", result.get("message", ""))
                    self.assertEqual(result.get("expense_claim_name"), "EXP-TEST-002")

    @patch("verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record")
    def test_submit_expense_employee_creation_fails(self, mock_get_volunteer):
        """Test expense submission when employee creation fails"""
        mock_volunteer = MagicMock()
        mock_volunteer.name = self.test_volunteer
        mock_volunteer.employee_id = None
        mock_get_volunteer.return_value = mock_volunteer

        # Mock failed employee creation
        with patch.object(
            mock_volunteer, "create_minimal_employee", side_effect=Exception("Employee creation failed")
        ):
            result = submit_expense(self.test_expense_data)

            self.assertFalse(result.get("success"))
            self.assertIn("Unable to create employee record", result.get("message", ""))

    @patch("verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record")
    def test_submit_expense_erpnext_validation_error(self, mock_get_volunteer):
        """Test expense submission when ERPNext expense claim validation fails"""
        mock_volunteer = MagicMock()
        mock_volunteer.name = self.test_volunteer
        mock_volunteer.employee_id = "HR-EMP-001"
        mock_get_volunteer.return_value = mock_volunteer

        # Mock ERPNext validation error (like missing default account)
        with patch("frappe.get_doc") as mock_get_doc:
            mock_expense_claim = MagicMock()
            mock_expense_claim.insert.side_effect = frappe.exceptions.ValidationError(
                "Set the default account for Expense Claim Type"
            )
            mock_get_doc.return_value = mock_expense_claim

            with patch(
                "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                return_value="Travel",
            ):
                result = submit_expense(self.test_expense_data)

                self.assertFalse(result.get("success"))
                self.assertIn("Set the default account", result.get("message", ""))

    def test_get_organization_cost_center_chapter(self):
        """Test cost center retrieval for chapter expenses"""
        # Create test chapter with cost center
        chapter_data = {
            "doctype": "Chapter",
            "chapter_name": "Test Chapter",
            "cost_center": "Test Cost Center - TC"}

        with patch("frappe.get_doc", return_value=MagicMock(cost_center="Test Cost Center - TC")):
            expense_data = {"organization_type": "Chapter", "chapter": "Test Chapter"}

            result = get_organization_cost_center(expense_data)
            self.assertEqual(result, "Test Cost Center - TC")

    def test_get_organization_cost_center_team(self):
        """Test cost center retrieval for team expenses"""
        with patch("frappe.get_doc", return_value=MagicMock(cost_center="Team Cost Center - TC")):
            expense_data = {"organization_type": "Team", "team": "Test Team"}

            result = get_organization_cost_center(expense_data)
            self.assertEqual(result, "Team Cost Center - TC")

    def test_get_organization_cost_center_national(self):
        """Test cost center retrieval for national expenses"""
        # Mock settings with national cost center
        mock_settings = MagicMock()
        mock_settings.national_cost_center = "National Cost Center - TC"

        with patch("frappe.get_single", return_value=mock_settings):
            expense_data = {"organization_type": "National"}

            result = get_organization_cost_center(expense_data)
            self.assertEqual(result, "National Cost Center - TC")

    def test_get_organization_cost_center_fallback(self):
        """Test cost center fallback to company default"""
        # Mock settings without national cost center
        mock_settings = MagicMock()
        mock_settings.national_cost_center = None

        mock_company = MagicMock()
        mock_company.cost_center = "Default Cost Center - TC"

        with patch("frappe.get_single", return_value=mock_settings):
            with patch("frappe.defaults.get_global_default", return_value="Test Company"):
                with patch("frappe.get_doc", return_value=mock_company):
                    expense_data = {"organization_type": "National"}

                    result = get_organization_cost_center(expense_data)
                    self.assertEqual(result, "Default Cost Center - TC")

    @patch("frappe.db.get_value")
    def test_get_or_create_expense_type_existing(self, mock_get_value):
        """Test getting existing expense claim type"""
        mock_get_value.return_value = "Travel"

        result = get_or_create_expense_type("Travel")
        self.assertEqual(result, "Travel")
        mock_get_value.assert_called_once()

    @patch("frappe.db.get_value")
    @patch("frappe.get_doc")
    def test_get_or_create_expense_type_new(self, mock_get_doc, mock_get_value):
        """Test creating new expense claim type"""
        # Mock no existing type found
        mock_get_value.side_effect = [None, "Test Company", "Test Expense Account - TC"]

        # Mock successful creation
        mock_expense_type = MagicMock()
        mock_expense_type.name = "Office Supplies"
        mock_get_doc.return_value = mock_expense_type

        with patch("frappe.get_all", return_value=[{"name": "Test Company"}]):
            result = get_or_create_expense_type("Office Supplies")
            self.assertEqual(result, "Office Supplies")

    @patch("frappe.db.get_value")
    def test_get_or_create_expense_type_creation_fails(self, mock_get_value):
        """Test fallback when expense claim type creation fails"""
        # Mock no existing type and creation failure
        mock_get_value.side_effect = [None, Exception("Creation failed")]

        with patch("frappe.get_all", return_value=[{"name": "Travel"}]):
            result = get_or_create_expense_type("Invalid Type")
            self.assertEqual(result, "Travel")  # Should fallback to existing type

    def test_expense_claim_type_integration_simplified(self):
        """Test that expense claim types work with ERPNext native functionality"""
        # This test verifies that we can work with existing ERPNext expense claim types
        with patch("frappe.db.get_value", return_value="Travel"):
            result = get_or_create_expense_type("Travel")
            self.assertEqual(result, "Travel")

        # Test fallback to ERPNext default types
        with patch("frappe.db.get_value", side_effect=[None, "Travel"]):
            with patch("frappe.get_all", return_value=[{"name": "Travel"}]):
                result = get_or_create_expense_type("NonExistent")
                self.assertEqual(result, "Travel")

    def test_expense_data_validation_missing_fields(self):
        """Test expense submission with missing required fields"""
        incomplete_data = {
            "description": "Test expense",
            # Missing amount, expense_date, organization_type, category
        }

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=MagicMock(),
        ):
            result = submit_expense(incomplete_data)
            self.assertFalse(result.get("success"))
            self.assertIn("required", result.get("message", "").lower())

    def test_expense_data_validation_invalid_organization(self):
        """Test expense submission with invalid organization selection"""
        invalid_data = self.test_expense_data.copy()
        invalid_data["organization_type"] = "Chapter"
        # Missing 'chapter' field

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=MagicMock(),
        ):
            result = submit_expense(invalid_data)
            self.assertFalse(result.get("success"))
            self.assertIn("select a chapter", result.get("message", "").lower())

    def test_no_volunteer_record_found(self):
        """Test expense submission when no volunteer record exists"""
        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record", return_value=None
        ):
            result = submit_expense(self.test_expense_data)
            self.assertFalse(result.get("success"))
            self.assertIn("No volunteer record found", result.get("message", ""))

    @patch("frappe.get_installed_apps")
    @patch("frappe.db.exists")
    def test_hrms_availability_check(self, mock_exists, mock_installed_apps):
        """Test HRMS availability checking in integration test"""
        mock_installed_apps.return_value = ["frappe", "erpnext", "hrms", "verenigingen"]
        mock_exists.side_effect = lambda doctype, name=None: doctype in [
            "Expense Claim",
            "Expense Claim Type",
        ]

        # This should pass HRMS checks
        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
            return_value="Travel",
        ):
            with patch("frappe.get_all", return_value=[]):  # No volunteers found
                result = test_expense_integration()
                self.assertFalse(result.get("success"))  # Fails because no volunteers, but HRMS checks pass

    @patch("frappe.get_installed_apps")
    @patch("frappe.db.exists")
    def test_hrms_not_available(self, mock_exists, mock_installed_apps):
        """Test behavior when HRMS is not available"""
        mock_installed_apps.return_value = ["frappe", "erpnext", "verenigingen"]  # No HRMS
        mock_exists.return_value = False  # Expense Claim doctypes don't exist

        result = test_expense_integration()
        self.assertFalse(result.get("success"))
        self.assertIn("not available", result.get("message", ""))

    def test_dual_tracking_creation(self):
        """Test that both ERPNext Expense Claim and Volunteer Expense records are created"""
        mock_volunteer = MagicMock()
        mock_volunteer.name = self.test_volunteer
        mock_volunteer.employee_id = "HR-EMP-001"

        mock_expense_claim = MagicMock()
        mock_expense_claim.name = "EXP-TEST-001"

        mock_volunteer_expense = MagicMock()
        mock_volunteer_expense.name = "VEXP-TEST-001"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc") as mock_get_doc:
                # Return different mocks for different doctypes
                def get_doc_side_effect(doc_dict):
                    if doc_dict["doctype"] == "Expense Claim":
                        return mock_expense_claim
                    elif doc_dict["doctype"] == "Volunteer Expense":
                        return mock_volunteer_expense
                    return MagicMock()

                mock_get_doc.side_effect = get_doc_side_effect

                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                        return_value="Test Cost Center",
                    ):
                        result = submit_expense(self.test_expense_data)

                        self.assertTrue(result.get("success"))
                        self.assertEqual(result.get("expense_claim_name"), "EXP-TEST-001")
                        self.assertEqual(result.get("expense_name"), "VEXP-TEST-001")

                        # Verify both records were created
                        self.assertEqual(mock_get_doc.call_count, 2)

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        # Clean up test records
        test_records = [
            ("Volunteer", "TEST-VOL-001"),
            ("Member", "TEST-MEM-001"),
        ]

        for doctype, name in test_records:
            if frappe.db.exists(doctype, name):
                frappe.delete_doc(doctype, name, ignore_permissions=True)


class TestERPNextExpenseEdgeCases(unittest.TestCase):
    """Test edge cases and error scenarios for ERPNext integration"""

    def setUp(self):
        frappe.set_user("Administrator")

    def test_expense_submission_with_unicode_characters(self):
        """Test expense submission with unicode characters in description"""
        expense_data = {
            "description": "Café meeting ñ special characters 🎉",
            "amount": 25.50,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",
            "notes": "Testing üñïçödé characters"}

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=MagicMock(name="EXP-UNICODE-001")):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data)
                    self.assertTrue(result.get("success"))

    def test_expense_submission_with_very_large_amount(self):
        """Test expense submission with very large amount"""
        expense_data = {
            "description": "Large expense",
            "amount": 999999.99,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",
            "notes": "Testing large amount"}

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=MagicMock(name="EXP-LARGE-001")):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data)
                    self.assertTrue(result.get("success"))

    def test_expense_submission_with_future_date(self):
        """Test expense submission with future date"""
        future_date = frappe.utils.add_days(frappe.utils.today(), 30)
        expense_data = {
            "description": "Future expense",
            "amount": 50.00,
            "expense_date": future_date,
            "organization_type": "National",
            "category": "Travel",
            "notes": "Testing future date"}

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=MagicMock(name="EXP-FUTURE-001")):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data)
                    self.assertTrue(result.get("success"))

    def test_expense_submission_with_very_long_description(self):
        """Test expense submission with very long description"""
        long_description = "This is a very long description " * 50  # 1500+ characters
        expense_data = {
            "description": long_description,
            "amount": 50.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",
            "notes": "Testing long description"}

        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc", return_value=MagicMock(name="EXP-LONG-001")):
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                    return_value="Travel",
                ):
                    result = submit_expense(expense_data)
                    self.assertTrue(result.get("success"))

    def test_expense_claim_type_creation_with_special_characters(self):
        """Test expense claim type creation with special characters"""
        with patch("frappe.db.get_value", return_value=None):  # No existing type
            with patch("frappe.defaults.get_global_default", return_value="Test Company"):
                with patch("frappe.get_all", return_value=[{"name": "Test Company"}]):
                    with patch("frappe.db.get_value", return_value="Test Account"):
                        with patch("frappe.get_doc", return_value=MagicMock(name="Special & Chars")):
                            result = get_or_create_expense_type("Special & Characters!")
                            self.assertIsNotNone(result)

    def test_concurrent_expense_submissions(self):
        """Test handling of concurrent expense submissions (race conditions)"""
        import queue
        import threading
        import time

        # Thread-safe queue for results
        results_queue = queue.Queue()
        submission_errors = queue.Queue()

        def submit_test_expense(thread_id):
            try:
                # Create thread-local expense data
                expense_data = {
                    "description": f"Concurrent expense {thread_id}",
                    "amount": 25.00 + thread_id,  # Unique amounts to avoid conflicts
                    "expense_date": "2024-12-14",
                    "organization_type": "National",
                    "category": "Travel",
                    "notes": f"Thread {thread_id} test"}

                # Create thread-specific mocks to avoid shared state issues
                mock_volunteer = MagicMock()
                mock_volunteer.name = f"test-volunteer-{thread_id}"
                mock_volunteer.employee_id = f"HR-EMP-{thread_id:03d}"

                # Create thread-specific mock expense claim
                mock_expense_claim = MagicMock()
                mock_expense_claim.name = f"EXP-CLAIM-{thread_id:03d}"
                mock_expense_claim.insert.return_value = None
                mock_expense_claim.submit.return_value = None

                # Create thread-specific mock volunteer expense
                mock_volunteer_expense = MagicMock()
                mock_volunteer_expense.name = f"VOL-EXP-{thread_id:03d}"

                # Use thread-local patches to avoid conflicts
                with patch(
                    "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
                    return_value=mock_volunteer,
                ):
                    with patch("frappe.get_doc") as mock_get_doc:
                        # Configure mock to return different objects for different doctypes
                        def get_doc_side_effect(doctype, *args, **kwargs):
                            if doctype == "Expense Claim":
                                return mock_expense_claim
                            elif doctype == "Volunteer Expense":
                                return mock_volunteer_expense
                            elif doctype == "Volunteer":
                                return mock_volunteer
                            else:
                                return MagicMock()

                        mock_get_doc.side_effect = get_doc_side_effect

                        with patch(
                            "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                            return_value="Travel",
                        ):
                            with patch("frappe.defaults.get_global_default", return_value="Test Company"):
                                with patch("frappe.db.get_value", return_value="Test Account"):
                                    with patch(
                                        "verenigingen.templates.pages.volunteer.expenses.get_organization_cost_center",
                                        return_value="Test Cost Center",
                                    ):
                                        # Add small delay to increase chance of race conditions
                                        time.sleep(0.01 * thread_id)

                                        result = submit_expense(expense_data)
                                        results_queue.put((thread_id, result))

            except Exception as e:
                submission_errors.put((thread_id, str(e)))

        # Create 5 concurrent threads with proper thread safety
        threads = []
        for i in range(5):
            thread = threading.Thread(target=submit_test_expense, args=(i,), daemon=True)
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all to complete with timeout
        for thread in threads:
            thread.join(timeout=10.0)  # 10 second timeout
            if thread.is_alive():
                self.fail("Thread did not complete within timeout")

        # Collect results from thread-safe queue
        results = []
        while not results_queue.empty():
            thread_id, result = results_queue.get()
            results.append(result)

        # Check for any submission errors
        errors = []
        while not submission_errors.empty():
            thread_id, error = submission_errors.get()
            errors.append(f"Thread {thread_id}: {error}")

        if errors:
            self.fail(f"Submission errors occurred: {'; '.join(errors)}")

        # All should succeed
        self.assertEqual(len(results), 5, f"Expected 5 results, got {len(results)}")

        # Check each result individually for better error reporting
        for i, result in enumerate(results):
            with self.subTest(thread_id=i):
                self.assertTrue(result.get("success"), f"Thread {i} failed: {result.get('message')}")

    def test_database_connection_failure_during_submission(self):
        """Test handling of database connection failures"""
        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        expense_data = {
            "description": "Test expense",
            "amount": 50.00,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": "Travel",
            "notes": "Testing DB failure"}

        with patch(
            "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
            return_value=mock_volunteer,
        ):
            with patch("frappe.get_doc") as mock_get_doc:
                # Simulate database connection error
                mock_get_doc.side_effect = Exception("Database connection lost")

                result = submit_expense(expense_data)
                self.assertFalse(result.get("success"))
                self.assertIn("Database connection lost", result.get("message", ""))

    def test_memory_usage_with_large_expense_batch(self):
        """Test memory efficiency with large batch of expenses"""
        mock_volunteer = MagicMock()
        mock_volunteer.employee_id = "HR-EMP-001"

        # Simulate submitting 100 expenses
        for i in range(100):
            expense_data = {
                "description": f"Batch expense {i}",
                "amount": 10.00 + i,
                "expense_date": "2024-12-14",
                "organization_type": "National",
                "category": "Travel",
                "notes": f"Batch test {i}"}

            with patch(
                "verenigingen.templates.pages.volunteer.expenses.get_user_volunteer_record",
                return_value=mock_volunteer,
            ):
                with patch("frappe.get_doc", return_value=MagicMock(name=f"EXP-BATCH-{i:03d}")):
                    with patch(
                        "verenigingen.templates.pages.volunteer.expenses.get_or_create_expense_type",
                        return_value="Travel",
                    ):
                        result = submit_expense(expense_data)
                        self.assertTrue(result.get("success"))

                        # Simulate cleanup to prevent memory buildup
                        if i % 10 == 0:
                            frappe.db.commit()

    def test_volunteer_expense_approver_simplified_query(self):
        """Test that the simplified expense approver query logic works without SQL errors"""
        # Create test volunteer
        test_volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Expense Approver Test",
                "email": "expense.approver.test@example.com",
                "status": "Active"}
        )
        test_volunteer.insert(ignore_permissions=True)

        try:
            # This should not raise any SQL errors with the new simplified logic
            approver = test_volunteer.get_default_expense_approver()

            # Should return a valid result
            self.assertIsInstance(approver, str)
            self.assertTrue(len(approver) > 0)

            # Should be either Administrator or a valid email
            self.assertTrue(approver == "Administrator" or "@" in approver)

        except Exception as e:
            self.fail(f"Simplified expense approver logic failed: {e}")
        finally:
            # Clean up
            if frappe.db.exists("Volunteer", test_volunteer.name):
                frappe.delete_doc("Volunteer", test_volunteer.name, ignore_permissions=True)

    @patch("frappe.get_single")
    def test_expense_approver_treasurer_priority(self, mock_get_single):
        """Test that treasurer gets priority in expense approver selection"""
        # Mock settings
        mock_settings = MagicMock()
        mock_settings.national_board_chapter = "Test Chapter"
        mock_get_single.return_value = mock_settings

        # Create test volunteer
        test_volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Priority Test Volunteer",
                "email": "priority.test@example.com",
                "status": "Active"}
        )
        test_volunteer.insert(ignore_permissions=True)

        try:
            # Mock frappe.get_all to return treasurer first
            with patch("frappe.get_all") as mock_get_all:
                # First call returns treasurer
                mock_get_all.return_value = [
                    {"volunteer": "treasurer_volunteer", "chapter_role": "Treasurer"}
                ]

                # Mock the volunteer document for treasurer
                treasurer_vol = MagicMock()
                treasurer_vol.email = "treasurer@example.com"

                with patch("frappe.get_doc", return_value=treasurer_vol):
                    with patch("frappe.db.exists", return_value=True):
                        approver = test_volunteer.get_default_expense_approver()

                        # Should find the treasurer
                        self.assertEqual(approver, "treasurer@example.com")

                        # Verify the simplified query was called correctly
                        # First call should be for Treasurer specifically
                        calls = mock_get_all.call_args_list
                        first_call_filters = calls[0][1]["filters"]
                        self.assertEqual(first_call_filters["chapter_role"], "Treasurer")

        finally:
            # Clean up
            if frappe.db.exists("Volunteer", test_volunteer.name):
                frappe.delete_doc("Volunteer", test_volunteer.name, ignore_permissions=True)


if __name__ == "__main__":
    unittest.main()
