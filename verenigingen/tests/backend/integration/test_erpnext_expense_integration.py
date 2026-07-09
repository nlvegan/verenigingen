"""
Integration tests for the volunteer-expense → ERPNext cost-center / Expense
Category flow.

History: the "Volunteer Expense" DocType was archived (dropped by
patches/v2_2/drop_volunteer_expense_archived_doctype.py). All tests that created
"Volunteer Expense" documents were removed in the residual-tautology sweep
because they exercised a dropped table (dead code). The tests that remain call
LIVE production functions:
  - cost_center_resolver.get_organization_cost_center_from_dict
  - services.volunteer.volunteer_expense_setup.get_or_create_expense_type
  - templates.pages.volunteer.expenses.submit_expense
  - Volunteer.get_expense_approver_from_assignments
"""

import unittest

import frappe

from verenigingen.templates.pages.volunteer.expenses import submit_expense
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.cost_center_resolver import (
    get_organization_cost_center_from_dict as get_organization_cost_center,
)
from verenigingen.utils.volunteer_expense_setup import (
    get_or_create_expense_type,
)


def _ensure_valid_expense_account():
    """Return an account that passes Expense Category validation.

    ExpenseCategory.validate requires ``account_type == "Expense Account"``
    EXACTLY (not merely root_type Expense). The previous helper grabbed the first
    root_type=Expense leaf with NO company filter, which under full before_tests
    seeding resolves to a tax account from another company (e.g. "Tax Expense -
    TPIC") and fails validation, erroring this module's whole setUp. Scope to the
    default company and require the exact account_type, creating a dedicated test
    expense account if the seeded chart has none.
    """
    company = (
        frappe.db.get_single_value("Global Defaults", "default_company")
        or frappe.get_all("Company", limit=1, pluck="name")[0]
    )
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
    return (
        frappe.get_doc(
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
        )
        .insert(ignore_permissions=True)
        .name
    )


def _ensure_expense_categories(category_names):
    """Create the named Expense Category records if missing.

    Single-module test runs do not seed the Dutch expense categories that the
    production validation expects, so create them with a real expense account.
    """
    expense_account = _ensure_valid_expense_account()
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
            first_name="Test", last_name="Volunteer", email=self.test_email, birth_date="1990-01-01"
        )

        self.test_volunteer = self.create_test_volunteer(
            member_name=self.test_member.name,
            volunteer_name="Test Volunteer",
            email=self.test_email,
            status="Active",
        )

        # Ensure required expense categories exist
        self._ensure_expense_categories_exist()

    def _ensure_expense_categories_exist(self):
        """Ensure the Dutch expense categories used by these tests exist."""
        # Create mapping from English test names to the Dutch category names the
        # production code/tests expect.
        self.category_mapping = {
            "Travel": "Reiskosten",  # Travel costs
            "Office Supplies": "Materiaalkosten",  # Material costs
            "Communications": "Communicatiekosten",  # Communication costs
        }
        _ensure_expense_categories(set(self.category_mapping.values()))
        self.test_category = "Reiskosten"

    def get_expense_category(self, english_name):
        """Get the correct expense category name (maps English test names to Dutch system names)"""
        if hasattr(self, "category_mapping"):
            return self.category_mapping.get(english_name, english_name)
        return english_name

    def test_get_organization_cost_center_chapter(self):
        """Chapter expenses resolve through the Chapter branch to a real Cost Center."""
        chapter = self.create_test_chapter()

        result = get_organization_cost_center({"organization_type": "Chapter", "chapter": chapter.name})

        # The resolver must return a concrete, existing Cost Center (either the
        # chapter's own cost_center or the company fallback) — never empty/None.
        self.assertTrue(result, "resolver returned an empty cost center for a Chapter expense")
        self.assertTrue(
            frappe.db.exists("Cost Center", result),
            f"resolver returned {result!r} which is not a real Cost Center",
        )

    def test_get_organization_cost_center_team(self):
        """Team expenses resolve through the Team branch to a real Cost Center."""
        test_team = self.create_test_team(
            team_name="Test Team", description="Test team for cost center testing"
        )

        result = get_organization_cost_center({"organization_type": "Team", "team": test_team.name})

        self.assertTrue(result, "resolver returned an empty cost center for a Team expense")
        self.assertTrue(
            frappe.db.exists("Cost Center", result),
            f"resolver returned {result!r} which is not a real Cost Center",
        )

    def test_get_organization_cost_center_national(self):
        """National expenses resolve to a real, existing Cost Center."""
        result = get_organization_cost_center({"organization_type": "National"})

        self.assertTrue(result, "resolver returned an empty cost center for a National expense")
        self.assertTrue(
            frappe.db.exists("Cost Center", result),
            f"resolver returned {result!r} which is not a real Cost Center",
        )

    def test_get_organization_cost_center_fallback(self):
        """Unknown organization type falls back to a real company Cost Center."""
        # No Chapter/Team/National match => the resolver's enhanced-fallback
        # branch must still return a concrete company Cost Center.
        result = get_organization_cost_center({"organization_type": "Nonexistent"})

        self.assertTrue(result, "fallback returned an empty cost center")
        self.assertTrue(
            frappe.db.exists("Cost Center", result),
            f"fallback returned {result!r} which is not a real Cost Center",
        )

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
            birth_date="1990-01-01",
        )

        # Ensure required expense categories exist
        self._ensure_expense_categories_exist()

        self.test_volunteer = self.create_test_volunteer(
            member_name=self.test_member.name,
            volunteer_name="Edge Case Volunteer",
            email=self.test_member.email,
            status="Active",
        )

    def _ensure_expense_categories_exist(self):
        """Ensure required Dutch expense categories exist for testing."""
        # Create mapping from English test names to the Dutch category names.
        self.category_mapping = {
            "Travel": "Reiskosten",  # Travel costs
            "Office Supplies": "Materiaalkosten",  # Material costs
            "Communications": "Materiaalkosten",  # Use material costs as fallback
        }
        _ensure_expense_categories(set(self.category_mapping.values()))
        self.travel_category = "Reiskosten"

    def get_expense_category(self, english_name):
        """Get the correct expense category name (maps English test names to Dutch system names)"""
        if hasattr(self, "category_mapping"):
            return self.category_mapping.get(english_name, english_name)
        return english_name

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

    def test_expense_submission_with_invalid_data(self):
        """Test expense submission error handling with invalid data"""
        # Test with missing required data to trigger validation errors
        invalid_expense_data = {
            "description": "",  # Empty description
            "amount": -50.00,  # Negative amount
            "expense_date": "invalid-date",
            "organization_type": "Unknown",
            "category": "",
            "notes": "Testing validation errors",
        }

        result = submit_expense(invalid_expense_data)

        # Should fail gracefully with validation errors
        self.assertFalse(result.get("success"))
        self.assertIsNotNone(result.get("message"))

        # Message should contain some indication of validation failure
        message = result.get("message", "").lower()
        self.assertTrue(
            any(keyword in message for keyword in ["error", "invalid", "required", "missing"]),
            f"Expected validation error message, got: {result.get('message')}",
        )

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
                "status": "Active",
            }
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
                "status": "Active",
            }
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
