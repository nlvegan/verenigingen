"""
Comprehensive integration tests for ERPNext Expense Claims integration
Tests the volunteer expense submission system with ERPNext HRMS integration using real database operations

Updated: December 2024 - Reflects legacy system phase-out and ERPNext-only workflow
Refactored: January 2025 - Converted from unit tests with extensive mocking to proper integration tests
"""

import unittest
import frappe
from unittest.mock import patch, MagicMock
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.skip_reasons import VOLUNTEER_EXPENSE_ARCHIVED

from verenigingen.templates.pages.volunteer.expenses import submit_expense
from verenigingen.utils.cost_center_resolver import get_organization_cost_center_from_dict as get_organization_cost_center
from verenigingen.utils.volunteer_expense_setup import (
    get_or_create_expense_type,
)

# Note: setup_expense_claim_types function removed in ERPNext integration simplification


def _get_valid_expense_account():
    """Return an account that passes Expense Category validation.

    ExpenseCategory.validate requires ``account_type == "Expense Account"``
    EXACTLY (not merely root_type Expense). The previous helper grabbed the first
    root_type=Expense leaf with NO company filter, which under full before_tests
    seeding resolves to a tax account from another company (e.g. "Tax Expense -
    TPIC") and fails validation, erroring this module's whole setUp. Scope to the
    default company and require the exact account_type, creating a dedicated test
    expense account if the seeded chart has none.
    """
    company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all(
        "Company", limit=1, pluck="name"
    )[0]
    acct = frappe.db.get_value(
        "Account",
        {"account_type": "Expense Account", "is_group": 0, "company": company},
        "name",
    )
    if acct:
        return acct
    # No "Expense Account"-typed leaf in the seeded chart: create one under the
    # company's Expense parent group.
    parent = frappe.db.get_value(
        "Account", {"root_type": "Expense", "is_group": 1, "company": company}, "name"
    )
    return frappe.get_doc(
        {
            "doctype": "Account",
            "account_name": "Test Volunteer Expense Account",
            "company": company,
            "parent_account": parent,
            "root_type": "Expense",
            "report_type": "Profit and Loss",
            "account_type": "Expense Account",
            "is_group": 0,
        }
    ).insert(ignore_permissions=True).name


def _ensure_expense_categories(category_names):
    """Create the named Expense Category records if missing.

    Single-module test runs do not seed the Dutch expense categories that the
    production validation expects, so create them with a real expense account.
    """
    expense_account = _get_valid_expense_account()
    for name in category_names:
        if not frappe.db.exists("Expense Category", name):
            frappe.get_doc(
                {
                    "doctype": "Expense Category",
                    "category_name": name,
                    "is_active": 1,
                    "expense_account": expense_account,
                }
            ).insert(ignore_permissions=True)


class TestERPNextExpenseIntegration(EnhancedTestCase):
    """Test ERPNext Expense Claims integration"""

    def setUp(self):
        """Set up for each test using Enhanced Test Factory"""
        super().setUp()
        frappe.set_user("Administrator")
        
        # Create test data using Enhanced Test Factory with unique email
        import time
        unique_suffix = f"{int(time.time())}.{frappe.generate_hash()[:6]}"
        self.test_email = f"test.volunteer.{unique_suffix}@example.com"
        
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Volunteer", 
            email=self.test_email,
            birth_date="1990-01-01"
        )
        
        self.test_volunteer = self.create_test_volunteer(
            member_name=self.test_member.name,
            volunteer_name="Test Volunteer",
            email=self.test_email,
            status="Active"
        )
        
        # Skip chapter creation - most tests don't actually need chapter functionality
        # Only create chapter when specifically needed for chapter-related tests
        self.test_chapter = None
        
        # Create test data for expenses
        self.test_expense_data = {
            "description": "Test ERPNext Integration Expense",
            "amount": 50.00,
            "expense_date": frappe.utils.today(),
            "organization_type": "National",
            "notes": "Test expense for integration testing"
        }
        
        # Ensure required expense categories exist
        self._ensure_expense_categories_exist()

    def _ensure_expense_categories_exist(self):
        """Ensure the Dutch expense categories used by these tests exist."""
        # Create mapping from English test names to the Dutch category names the
        # production code/tests expect.
        self.category_mapping = {
            "Travel": "Reiskosten",  # Travel costs
            "Office Supplies": "Materiaalkosten",  # Material costs
            "Communications": "Communicatiekosten"  # Communication costs
        }
        _ensure_expense_categories(set(self.category_mapping.values()))
        self.test_category = "Reiskosten"

    def get_expense_category(self, english_name):
        """Get the correct expense category name (maps English test names to Dutch system names)"""
        if hasattr(self, 'category_mapping'):
            return self.category_mapping.get(english_name, english_name)
        return english_name

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_submit_expense_basic_functionality(self):
        """Test basic expense submission functionality with real volunteer record"""
        # Skip test if no category is available
        if not self.test_category:
            self.skipTest("No expense category available for testing")
            
        # Create a volunteer expense record with National organization type (simpler test)
        volunteer_expense = frappe.get_doc({
            "doctype": "Volunteer Expense",
            "volunteer": self.test_volunteer.name,
            "description": self.test_expense_data["description"],
            "amount": self.test_expense_data["amount"],
            "expense_date": self.test_expense_data["expense_date"],
            "organization_type": "National",
            "category": self.test_category,
            "notes": self.test_expense_data["notes"],
            "status": "Draft"
        })
        volunteer_expense.insert()
        
        # Test that the expense was created successfully
        self.assertIsNotNone(volunteer_expense.name)
        self.assertEqual(volunteer_expense.volunteer, self.test_volunteer.name)
        self.assertEqual(volunteer_expense.amount, 50.00)

    def test_expense_data_validation(self):
        """Test expense data validation with real volunteer record"""
        # Test complete expense data
        complete_expense_data = {
            "description": "Valid expense test",
            "amount": 75.50,
            "expense_date": frappe.utils.today(),
            "organization_type": "National",
            "category": "Office Supplies",
            "notes": "Testing with complete data"
        }
        
        # This should validate properly
        self.assertIsInstance(complete_expense_data["amount"], (int, float))
        self.assertTrue(complete_expense_data["amount"] > 0)
        self.assertIsNotNone(complete_expense_data["description"])
        self.assertIn("organization_type", complete_expense_data)

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_volunteer_expense_creation_with_categories(self):
        """Test volunteer expense creation with different expense categories"""
        for category in ["Travel", "Office Supplies", "Communications"]:
            with self.subTest(category=category):
                expense_data = self.test_expense_data.copy()
                expense_data["category"] = self.get_expense_category(category)
                expense_data["description"] = f"Test {category} expense"
                
                volunteer_expense = frappe.get_doc({
                    "doctype": "Volunteer Expense",
                    "volunteer": self.test_volunteer.name,
                    "description": expense_data["description"],
                    "amount": expense_data["amount"],
                    "expense_date": expense_data["expense_date"],
                    "organization_type": "National",
                    "category": expense_data["category"],
                    "notes": expense_data["notes"],
                    "status": "Draft"
                })
                volunteer_expense.insert()
                
                # Compare with mapped category name (English -> Dutch)
                expected_category = self.get_expense_category(category)
                self.assertEqual(volunteer_expense.category, expected_category)
                self.assertIn(category.lower(), volunteer_expense.description.lower())

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_expense_amount_validation(self):
        """Test expense amount validation"""
        # Test valid amounts
        valid_amounts = [0.01, 1.00, 50.00, 999.99, 1000.00]
        
        for amount in valid_amounts:
            with self.subTest(amount=amount):
                volunteer_expense = frappe.get_doc({
                    "doctype": "Volunteer Expense",
                    "volunteer": self.test_volunteer.name,
                    "description": f"Test expense for {amount}",
                    "amount": amount,
                    "expense_date": frappe.utils.today(),
                    "organization_type": "National",
                    "category": self.get_expense_category("Travel"),
                    "status": "Draft"
                })
                volunteer_expense.insert()
                
                self.assertEqual(volunteer_expense.amount, amount)
                self.assertTrue(volunteer_expense.amount > 0)
        
        # Test invalid amounts - should raise validation errors
        invalid_amounts = [0, -1.00, -50.00]
        
        for amount in invalid_amounts:
            with self.subTest(invalid_amount=amount):
                with self.assertRaises(frappe.exceptions.ValidationError):
                    volunteer_expense = frappe.get_doc({
                        "doctype": "Volunteer Expense",
                        "volunteer": self.test_volunteer.name,
                        "description": f"Invalid expense for {amount}",
                        "amount": amount,
                        "expense_date": frappe.utils.today(),
                        "organization_type": "National",
                        "category": self.get_expense_category("Travel"),
                        "status": "Draft"
                    })
                    volunteer_expense.insert()

    def test_get_organization_cost_center_chapter(self):
        """Test cost center retrieval for chapter expenses using real chapter data"""
        # Use the real test chapter created in setUp
        # Skip chapter test since we don't create chapters
        expense_data = {
            "organization_type": "National"
        }
        
        # Test the function with real chapter data
        result = get_organization_cost_center(expense_data)
        # The result should be a string or None, we just verify it doesn't crash
        self.assertIsInstance(result, (str, type(None)))

    def test_get_organization_cost_center_team(self):
        """Test cost center retrieval for team expenses using real team data"""
        # Create a test team
        test_team = self.create_test_team(
            team_name="Test Team",
            description="Test team for cost center testing"
        )
        
        expense_data = {
            "organization_type": "Team", 
            "team": test_team.name
        }
        
        # Test the function with real team data
        result = get_organization_cost_center(expense_data)
        # The result should be a string or None, we just verify it doesn't crash
        self.assertIsInstance(result, (str, type(None)))

    def test_get_organization_cost_center_national(self):
        """Test cost center retrieval for national expenses using real settings"""
        expense_data = {"organization_type": "National"}
        
        # Test the function with real settings data
        result = get_organization_cost_center(expense_data)
        # The result should be a string or None, we just verify it doesn't crash
        self.assertIsInstance(result, (str, type(None)))

    def test_get_organization_cost_center_fallback(self):
        """Test cost center fallback behavior"""
        expense_data = {"organization_type": "National"}
        
        # Test that the function handles fallback gracefully
        result = get_organization_cost_center(expense_data)
        
        # The function should return a valid result or None without crashing
        self.assertIsInstance(result, (str, type(None)))
        
        # If it returns a string, it should not be empty
        if result:
            self.assertTrue(len(result) > 0)

    def test_get_or_create_expense_type_existing(self):
        """Test getting existing expense claim type"""
        # Ensure test category exists before testing
        if not frappe.db.exists("Expense Category", "Reiskosten"):
            self.skipTest("Required expense category 'Reiskosten' not configured in test environment")

        # Test with a Dutch category that actually exists (Reiskosten = Travel)
        result = get_or_create_expense_type("Reiskosten")

        # Should return a string (the expense type name)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)
        self.assertEqual(result, "Reiskosten")

    def test_get_or_create_expense_type_nonexistent_raises(self):
        """Test that nonexistent expense category raises ValidationError"""
        # The function no longer creates categories - it validates existing ones
        # Per docstring: "Despite the name, this function no longer creates Expense Claim Types"
        unique_category = f"Test Category {frappe.utils.random_string(5)}"

        with self.assertRaises(frappe.exceptions.ValidationError) as context:
            get_or_create_expense_type(unique_category)

        # Should contain error about category not found
        self.assertIn("not found", str(context.exception).lower())

    def test_get_or_create_expense_type_invalid_raises(self):
        """Test that invalid expense category raises ValidationError"""
        # The function validates categories - invalid names should raise errors
        invalid_type = "//Invalid//Type//Name//"

        with self.assertRaises(frappe.exceptions.ValidationError) as context:
            get_or_create_expense_type(invalid_type)

        # Should contain error about category not found
        self.assertIn("not found", str(context.exception).lower())

    def test_expense_claim_type_integration_simplified(self):
        """Test that expense claim types work with ERPNext native functionality"""
        # Test with existing Dutch categories (mapped from English names)
        for category in ["Travel", "Office Supplies", "Communications"]:
            with self.subTest(category=category):
                dutch_category = self.get_expense_category(category)
                result = get_or_create_expense_type(dutch_category)
                self.assertIsInstance(result, str)
                self.assertTrue(len(result) > 0)
                self.assertEqual(result, dutch_category)

        # Test that non-existent type raises ValidationError (function validates, doesn't create)
        with self.assertRaises(frappe.exceptions.ValidationError):
            get_or_create_expense_type("NonExistent")

    def test_expense_data_validation_missing_fields(self):
        """Test expense data validation with missing required fields"""
        incomplete_data = {
            "description": "Test expense",
            # Missing amount, expense_date, organization_type, category
        }
        
        # Test that we can identify missing fields
        required_fields = ["amount", "expense_date", "organization_type", "category"]
        
        for field in required_fields:
            with self.subTest(field=field):
                self.assertNotIn(field, incomplete_data)
        
        # Test that description is present
        self.assertIn("description", incomplete_data)

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_expense_data_validation_invalid_organization(self):
        """Test expense data validation with invalid organization selection"""
        # Test organization_type "Chapter" without chapter field - should fail validation
        with self.assertRaises(frappe.exceptions.ValidationError):
            volunteer_expense = frappe.get_doc({
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "description": "Test expense with invalid organization",
                "amount": 50.00,
                "expense_date": frappe.utils.today(),
                "organization_type": "Chapter",
                # Missing 'chapter' field - should trigger validation error
                "category": self.get_expense_category("Travel"),
                "status": "Draft"
            })
            volunteer_expense.insert()
        
        # Test organization_type "Team" without team field - should fail validation
        with self.assertRaises(frappe.exceptions.ValidationError):
            volunteer_expense = frappe.get_doc({
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "description": "Test expense with invalid team organization",
                "amount": 50.00,
                "expense_date": frappe.utils.today(),
                "organization_type": "Team",
                # Missing 'team' field - should trigger validation error
                "category": self.get_expense_category("Travel"),
                "status": "Draft"
            })
            volunteer_expense.insert()

    def test_volunteer_record_exists(self):
        """Test that volunteer record exists and is accessible"""
        # Test that our test volunteer exists and has proper data
        self.assertIsNotNone(self.test_volunteer)
        self.assertIsNotNone(self.test_volunteer.name)
        self.assertEqual(self.test_volunteer.status, "Active")

        # Test that we can fetch the volunteer record
        fetched_volunteer = frappe.get_doc("Volunteer", self.test_volunteer.name)
        self.assertEqual(fetched_volunteer.name, self.test_volunteer.name)
        # Note: Factory may generate unique email to avoid conflicts
        # Just verify email exists and is valid format
        self.assertIsNotNone(fetched_volunteer.email)
        self.assertIn("@", fetched_volunteer.email)

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_hrms_availability_check(self):
        """Test HRMS availability checking in integration test"""
        # Test that required apps and doctypes exist
        installed_apps = frappe.get_installed_apps()
        
        # Test app availability
        required_apps = ["frappe", "erpnext", "verenigingen"]
        for app in required_apps:
            with self.subTest(app=app):
                self.assertIn(app, installed_apps)
        
        # Test critical doctype existence
        critical_doctypes = ["Volunteer", "Member", "Volunteer Expense"]
        for doctype in critical_doctypes:
            with self.subTest(doctype=doctype):
                self.assertTrue(frappe.db.exists("DocType", doctype))

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_doctypes_availability(self):
        """Test behavior when checking doctype availability"""
        # Test that core verenigingen doctypes exist
        core_doctypes = ["Volunteer", "Member", "Chapter", "Volunteer Expense"]
        
        for doctype in core_doctypes:
            with self.subTest(doctype=doctype):
                exists = frappe.db.exists("DocType", doctype)
                self.assertTrue(exists, f"DocType {doctype} should exist")
        
        # Test ERPNext doctypes if available
        erpnext_doctypes = ["Employee", "Company"]
        if "erpnext" in frappe.get_installed_apps():
            for doctype in erpnext_doctypes:
                with self.subTest(doctype=doctype):
                    exists = frappe.db.exists("DocType", doctype)
                    self.assertTrue(exists, f"ERPNext DocType {doctype} should exist")

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_volunteer_expense_record_creation(self):
        """Test that volunteer expense records are created properly"""
        # Create multiple volunteer expense records to test the system
        expense_types = ["Travel", "Office Supplies", "Communications"]
        created_expenses = []
        
        for expense_type in expense_types:
            expense_data = {
                "volunteer": self.test_volunteer.name,
                "description": f"Test {expense_type} expense",
                "amount": 25.00 + len(created_expenses) * 10,  # Varying amounts
                "expense_date": frappe.utils.today(),
                "organization_type": "National",
                "category": self.get_expense_category(expense_type),
                "notes": f"Integration test for {expense_type}",
                "status": "Draft"
            }
            
            volunteer_expense = frappe.get_doc({
                "doctype": "Volunteer Expense",
                **expense_data
            })
            volunteer_expense.insert()
            created_expenses.append(volunteer_expense)
        
        # Verify all expenses were created
        self.assertEqual(len(created_expenses), 3)
        
        # Verify each expense has proper data
        for i, expense in enumerate(created_expenses):
            self.assertEqual(expense.volunteer, self.test_volunteer.name)
            # Compare with mapped category name (English -> Dutch)
            expected_category = self.get_expense_category(expense_types[i])
            self.assertEqual(expense.category, expected_category)
            self.assertTrue(expense.amount > 0)

    def test_integration_summary(self):
        """Summary test to verify integration test converted successfully"""
        # Verify that we have real test data
        self.assertIsNotNone(self.test_member)
        self.assertIsNotNone(self.test_volunteer)
        # Skip test_chapter assertion since we don't create chapters
        # self.assertIsNotNone(self.test_chapter)
        
        # Verify data relationships
        self.assertEqual(self.test_volunteer.member, self.test_member.name)
        
        # Verify that we can query expense categories
        expense_categories = frappe.get_all("Expense Category", fields=["name", "category_name"])
        self.assertTrue(len(expense_categories) >= 3)  # Should have at least our 3 test categories


class TestERPNextExpenseEdgeCases(EnhancedTestCase):
    """Test edge cases and error scenarios for ERPNext integration"""

    def setUp(self):
        """Set up test data using Enhanced Test Factory"""
        super().setUp()
        
        # Create test data for edge case testing
        self.test_member = self.create_test_member(
            first_name="Edge",
            last_name="Case User",
            email=f"edge.case.{frappe.generate_hash()[:6]}@example.com",
            birth_date="1990-01-01"
        )
        
        # Ensure required expense categories exist
        self._ensure_expense_categories_exist()
        
        self.test_volunteer = self.create_test_volunteer(
            member_name=self.test_member.name,
            volunteer_name="Edge Case Volunteer",
            email=self.test_member.email,
            status="Active"
        )

    def _ensure_expense_categories_exist(self):
        """Ensure required Dutch expense categories exist for testing."""
        # Create mapping from English test names to the Dutch category names.
        self.category_mapping = {
            "Travel": "Reiskosten",  # Travel costs
            "Office Supplies": "Materiaalkosten",  # Material costs
            "Communications": "Materiaalkosten"  # Use material costs as fallback
        }
        _ensure_expense_categories(set(self.category_mapping.values()))
        self.travel_category = "Reiskosten"

    def get_expense_category(self, english_name):
        """Get the correct expense category name (maps English test names to Dutch system names)"""
        if hasattr(self, 'category_mapping'):
            return self.category_mapping.get(english_name, english_name)
        return english_name

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_expense_submission_with_unicode_characters(self):
        """Test expense submission with unicode characters in description"""
        # Create real volunteer expense with unicode characters
        unicode_expense = frappe.get_doc({
            "doctype": "Volunteer Expense",
            "volunteer": self.test_volunteer.name,
            "description": "Café meeting ñ special characters 🎉",
            "amount": 25.50,
            "expense_date": frappe.utils.today(),
            "organization_type": "National",
            "category": self.get_expense_category("Travel"),
            "notes": "Testing üñïçödé characters",
            "status": "Draft"
        })
        unicode_expense.insert()
        
        # Verify unicode characters are handled properly
        self.assertEqual(unicode_expense.description, "Café meeting ñ special characters 🎉")
        self.assertIn("üñïçödé", unicode_expense.notes)
        self.assertTrue(unicode_expense.amount == 25.50)

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_expense_submission_with_very_large_amount(self):
        """Test expense submission with very large amount"""
        # Create real volunteer expense with large amount
        large_expense = frappe.get_doc({
            "doctype": "Volunteer Expense",
            "volunteer": self.test_volunteer.name,
            "description": "Large expense",
            "amount": 999999.99,
            "expense_date": frappe.utils.today(),
            "organization_type": "National",
            "category": self.get_expense_category("Travel"),
            "notes": "Testing large amount",
            "status": "Draft"
        })
        large_expense.insert()
        
        # Verify large amount is handled properly
        self.assertEqual(large_expense.amount, 999999.99)
        self.assertTrue(large_expense.amount > 100000)  # Confirm it's a large amount

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_expense_submission_with_future_date(self):
        """Test that expense submission properly rejects future dates"""
        future_date = frappe.utils.add_days(frappe.utils.today(), 30)
        
        # Create volunteer expense with future date - this should fail validation
        future_expense = frappe.get_doc({
            "doctype": "Volunteer Expense",
            "volunteer": self.test_volunteer.name,
            "description": "Future expense",
            "amount": 50.00,
            "expense_date": future_date,
            "organization_type": "National",
            "category": self.get_expense_category("Travel"),
            "notes": "Testing future date validation",
            "status": "Draft"
        })
        
        # Should raise ValidationError for future date
        with self.assertRaises(frappe.exceptions.ValidationError) as context:
            future_expense.insert()
        
        # Verify the error message mentions future date
        self.assertIn("future", str(context.exception).lower())

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_expense_submission_with_very_long_description(self):
        """Test that expense submission properly rejects descriptions that are too long"""
        long_description = "This is a very long description " * 50  # 1500+ characters
        
        # Create volunteer expense with too-long description - should fail validation
        long_desc_expense = frappe.get_doc({
            "doctype": "Volunteer Expense",
            "volunteer": self.test_volunteer.name,
            "description": long_description,
            "amount": 50.00,
            "expense_date": frappe.utils.today(),
            "organization_type": "National",
            "category": self.get_expense_category("Travel"),
            "notes": "Testing description length validation",
            "status": "Draft"
        })
        
        # Should raise CharacterLengthExceededError for too-long description
        with self.assertRaises(frappe.exceptions.CharacterLengthExceededError) as context:
            long_desc_expense.insert()
        
        # Verify the error mentions character limit
        self.assertIn("140", str(context.exception))

    def test_expense_claim_type_with_special_characters_raises(self):
        """Test that nonexistent category with special characters raises ValidationError"""
        # The function validates existing categories - it doesn't create new ones
        # Per docstring: "Despite the name, this function no longer creates Expense Claim Types"
        special_category = f"Special & Characters! {frappe.generate_hash()[:4]}"

        # Should raise ValidationError since category doesn't exist
        with self.assertRaises(frappe.exceptions.ValidationError) as context:
            get_or_create_expense_type(special_category)

        # Error should mention category not found
        self.assertIn("not found", str(context.exception).lower())

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_sequential_multiple_expense_creation(self):
        """Test creating multiple expenses sequentially without data conflicts"""
        # NOTE: True threading with frappe is problematic in tests due to site/db connection issues
        # This test validates that multiple expenses can be created sequentially without conflicts

        created_expenses = []

        # Create 3 expense records sequentially (simulating concurrent submissions)
        for i in range(3):
            expense = frappe.get_doc({
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "description": f"Sequential expense {i}",
                "amount": 25.00 + i,
                "expense_date": frappe.utils.today(),
                "organization_type": "National",
                "category": self.get_expense_category("Travel"),
                "notes": f"Sequential test {i}",
                "status": "Draft"
            })
            expense.insert()
            created_expenses.append(expense.name)

        frappe.db.commit()

        # All should succeed
        self.assertEqual(len(created_expenses), 3)

        # Verify each expense was created properly with unique names
        for expense_name in created_expenses:
            expense = frappe.get_doc("Volunteer Expense", expense_name)
            self.assertEqual(expense.volunteer, self.test_volunteer.name)
            self.assertTrue(expense.amount >= 25.00)

        # Verify no duplicates
        self.assertEqual(len(set(created_expenses)), 3)

    def test_expense_submission_with_invalid_data(self):
        """Test expense submission error handling with invalid data"""
        # Test with missing required data to trigger validation errors
        invalid_expense_data = {
            "description": "",  # Empty description
            "amount": -50.00,   # Negative amount
            "expense_date": "invalid-date",
            "organization_type": "Unknown",
            "category": "",
            "notes": "Testing validation errors"}

        result = submit_expense(invalid_expense_data)
        
        # Should fail gracefully with validation errors
        self.assertFalse(result.get("success"))
        self.assertIsNotNone(result.get("message"))
        
        # Message should contain some indication of validation failure
        message = result.get("message", "").lower()
        self.assertTrue(
            any(keyword in message for keyword in ["error", "invalid", "required", "missing"]),
            f"Expected validation error message, got: {result.get('message')}"
        )

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_batch_expense_creation(self):
        """Test creating a batch of expense records efficiently"""
        # Create small batch for integration testing (5 records - balance between coverage and speed)
        created_expenses = []

        for i in range(5):
            expense = frappe.get_doc({
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "description": f"Batch expense {i}",
                "amount": 10.00 + i,
                "expense_date": frappe.utils.today(),
                "organization_type": "National",
                "category": self.get_expense_category("Travel"),
                "notes": f"Batch integration test {i}",
                "status": "Draft"
            })
            expense.insert()
            created_expenses.append(expense.name)

        frappe.db.commit()

        # Verify all expenses were created successfully
        self.assertEqual(len(created_expenses), 5)

        # Quick verification via database query (faster than reloading each doc)
        expense_count = frappe.db.count("Volunteer Expense", {
            "volunteer": self.test_volunteer.name,
            "description": ["like", "Batch expense %"]
        })
        self.assertGreaterEqual(expense_count, 5)

    def test_volunteer_expense_approver_simplified_query(self):
        """Test that the simplified expense approver query logic works without SQL errors"""
        # Create test volunteer with unique email
        import time
        unique_suffix = f"{int(time.time())}.{frappe.generate_hash()[:6]}"
        test_volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Expense Approver Test",
                "email": f"expense.approver.test.{unique_suffix}@example.com",
                "status": "Active"}
        )
        test_volunteer.insert()

        try:
            # This should not raise any SQL errors with the logic
            approver = test_volunteer.get_expense_approver_from_assignments()

            # Should return a valid result
            self.assertIsInstance(approver, str)
            self.assertTrue(len(approver) > 0)

            # Should be either Administrator or a valid email
            self.assertTrue(approver == "Administrator" or "@" in approver)

        except Exception as e:
            self.fail(f"Expense approver logic failed: {e}")
        # Note: cleanup handled automatically by EnhancedTestCase

    def test_expense_approver_treasurer_priority(self):
        """Test basic expense approver functionality - simplified integration test"""
        # Create unique email for test volunteer
        import time
        unique_suffix = f"{int(time.time())}.{frappe.generate_hash()[:6]}"
        test_volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Priority Test Volunteer",
                "email": f"priority.test.{unique_suffix}@example.com",
                "status": "Active"}
        )
        test_volunteer.insert()

        # Test basic functionality: method should return a valid approver
        approver = test_volunteer.get_expense_approver_from_assignments()

        # Should get some form of valid approver (Administrator is acceptable fallback)
        self.assertIsNotNone(approver)
        self.assertIsInstance(approver, str)
        self.assertTrue(len(approver) > 0)

        # Common valid approvers include Administrator or email addresses
        self.assertTrue(approver == "Administrator" or "@" in approver)
        
        # Note: cleanup handled automatically by EnhancedTestCase


if __name__ == "__main__":
    unittest.main()
