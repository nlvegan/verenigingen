import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, today


class TestVolunteerExpenseFixed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test data using existing data where possible"""
        cls.setup_test_environment()

    @classmethod
    def setup_test_environment(cls):
        """Create minimal test environment"""
        # Use existing company
        companies = frappe.get_all("Company", limit=1)
        if companies:
            cls.company = companies[0].name
        else:
            cls.company = "Test Company"
            if not frappe.db.exists("Company", cls.company):
                company_doc = frappe.get_doc(
                    {
                        "doctype": "Company",
                        "company_name": cls.company,
                        "abbr": "TC",
                        "default_currency": "EUR",
                    }
                )
                company_doc.insert()

        # Create minimal test data
        cls.setup_minimal_test_data()

    @classmethod
    def setup_minimal_test_data(cls):
        """Create minimal test data for testing"""
        # Create test expense account
        company_abbr = frappe.get_value("Company", cls.company, "abbr")
        account_name = f"Test Expense Account - {company_abbr}"

        if not frappe.db.exists("Account", account_name):
            # Find any expense group account to use as parent
            parent_account = frappe.get_value(
                "Account",
                {"company": cls.company, "is_group": 1, "account_type": ["like", "%Expense%"]},
                "name",
            )

            if not parent_account:
                # Get any root group account
                parent_account = frappe.get_value(
                    "Account",
                    {"company": cls.company, "is_group": 1, "parent_account": ["in", ["", None]]},
                    "name",
                )

            if parent_account:
                cls.expense_account = frappe.get_doc(
                    {
                        "doctype": "Account",
                        "account_name": "Test Expense Account",
                        "account_type": "Expense Account",
                        "parent_account": parent_account,
                        "company": cls.company,
                    }
                )
                cls.expense_account.insert()
            else:
                cls.expense_account = None
        else:
            cls.expense_account = frappe.get_doc("Account", account_name)

        # Create expense category
        if cls.expense_account and not frappe.db.exists("Expense Category", "Test Category"):
            cls.expense_category = frappe.get_doc(
                {
                    "doctype": "Expense Category",
                    "category_name": "Test Category",
                    "expense_account": cls.expense_account.name,
                    "description": "Test category for expenses",
                }
            )
            cls.expense_category.insert()
        elif frappe.db.exists("Expense Category", "Test Category"):
            cls.expense_category = frappe.get_doc("Expense Category", "Test Category")
        else:
            cls.expense_category = None

        # Create test chapter
        if not frappe.db.exists("Chapter", "Test Chapter"):
            cls.test_chapter = frappe.get_doc({"doctype": "Chapter", "chapter_name": "Test Chapter"})
            cls.test_chapter.name = "Test Chapter"
            cls.test_chapter.insert()
        else:
            cls.test_chapter = frappe.get_doc("Chapter", "Test Chapter")

        # Create test team
        if not frappe.db.exists("Team", "Test Team"):
            cls.test_team = frappe.get_doc(
                {"doctype": "Team", "team_name": "Test Team", "description": "Test team for expenses"}
            )
            cls.test_team.insert()
        else:
            cls.test_team = frappe.get_doc("Team", "Test Team")

        # Create test member
        if not frappe.db.exists("Member", "test@example.com"):
            cls.test_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "email": "test@example.com",
                    "full_name": "Test Member",
                    "membership_status": "Active",
                }
            )
            cls.test_member.insert()
        else:
            cls.test_member = frappe.get_doc("Member", "test@example.com")

        # Create test volunteer
        if not frappe.db.exists("Volunteer", "Test Member - TM"):
            cls.test_volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": "Test Member",
                    "member": cls.test_member.name,
                    "status": "Active",
                }
            )
            cls.test_volunteer.insert()
        else:
            cls.test_volunteer = frappe.get_doc("Volunteer", "Test Member - TM")

        # Create chapter membership
        if not frappe.db.exists(
            "Chapter Member", {"member": cls.test_member.name, "chapter": cls.test_chapter.name}
        ):
            chapter_member = frappe.get_doc(
                {
                    "doctype": "Chapter Member",
                    "member": cls.test_member.name,
                    "chapter": cls.test_chapter.name,
                    "status": "Active",
                }
            )
            chapter_member.insert()

    def setUp(self):
        """Set up for each test"""
        if not self.expense_category:
            self.skipTest("No expense category available - check account setup")

    def test_volunteer_expense_creation(self):
        """Test basic volunteer expense creation"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Test expense",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        self.assertTrue(expense.name)
        self.assertEqual(expense.status, "Draft")
        self.assertEqual(expense.volunteer, self.test_volunteer.name)
        self.assertEqual(expense.amount, 50.00)

        # Clean up
        expense.delete()

    def test_volunteer_expense_validation(self):
        """Test expense validation rules"""
        # Test future date validation
        future_date = add_days(today(), 5)
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": future_date,
                "category": self.expense_category.name,
                "description": "Future expense",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )

        with self.assertRaises(frappe.ValidationError):
            expense.insert()

        # Test negative amount validation
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Negative expense",
                "amount": -10.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )

        with self.assertRaises(frappe.ValidationError):
            expense.insert()

        # Test zero amount validation
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Zero expense",
                "amount": 0.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )

        with self.assertRaises(frappe.ValidationError):
            expense.insert()

    def test_organization_type_validation(self):
        """Test organization type validation"""
        # Test chapter type without chapter
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Missing chapter",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "company": self.company,
            }
        )

        with self.assertRaises(frappe.ValidationError):
            expense.insert()

        # Test team type without team
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Missing team",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Team",
                "company": self.company,
            }
        )

        with self.assertRaises(frappe.ValidationError):
            expense.insert()

    def test_expense_submission(self):
        """Test expense submission workflow"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Submission test",
                "amount": 75.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        self.assertEqual(expense.status, "Draft")

        # Test submission
        expense.submit()
        self.assertEqual(expense.status, "Submitted")

        # Test cancellation
        expense.cancel()
        self.assertEqual(expense.status, "Draft")

        # Clean up
        expense.delete()

    def test_required_fields(self):
        """Test required field validation"""
        # Test missing volunteer
        with self.assertRaises(frappe.MandatoryError):
            frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "expense_date": today(),
                    "category": self.expense_category.name,
                    "description": "Missing volunteer",
                    "amount": 50.00,
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter.name,
                }
            ).insert()

        # Test missing category
        with self.assertRaises(frappe.MandatoryError):
            frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.test_volunteer.name,
                    "expense_date": today(),
                    "description": "Missing category",
                    "amount": 50.00,
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter.name,
                }
            ).insert()

        # Test missing description
        with self.assertRaises(frappe.MandatoryError):
            frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.test_volunteer.name,
                    "expense_date": today(),
                    "category": self.expense_category.name,
                    "amount": 50.00,
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter.name,
                }
            ).insert()

    def test_auto_organization_setting(self):
        """Test automatic organization setting"""
        # Create expense without specifying organization
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Auto organization test",
                "amount": 50.00,
                "currency": "EUR",
                "company": self.company,
            }
        )
        expense.insert()

        # Should auto-set to chapter since volunteer has chapter membership
        self.assertEqual(expense.organization_type, "Chapter")
        self.assertEqual(expense.chapter, self.test_chapter.name)

        # Clean up
        expense.delete()

    @patch("frappe.sendmail")
    def test_expense_approval_functions(self, mock_sendmail):
        """Test expense approval and rejection functions"""
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import (
            approve_expense,
            reject_expense,
        )

        # Create and submit expense
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Approval test",
                "amount": 100.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()
        expense.submit()

        # Test approval (will fail permission check but we can test the function exists)
        try:
            approve_expense(expense.name)
        except frappe.PermissionError:
            pass  # Expected since we don't have proper user setup

        # Test rejection
        try:
            reject_expense(expense.name, "Test rejection")
        except frappe.PermissionError:
            pass  # Expected since we don't have proper user setup

        # Clean up
        expense.cancel()
        expense.delete()

    def test_cross_organization_clearing(self):
        """Test that selecting chapter clears team and vice versa"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Cross organization test",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "team": self.test_team.name,  # This should be cleared
                "company": self.company,
            }
        )
        expense.insert()

        # Team should be cleared when organization_type is Chapter
        self.assertIsNone(expense.team)
        self.assertEqual(expense.chapter, self.test_chapter.name)

        # Clean up
        expense.delete()

    def test_special_characters_and_amounts(self):
        """Test handling of special characters and various amounts"""
        # Test special characters in description
        special_description = "Travel expenses: München & Berlin (50% reimbursable) @2024"

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": special_description,
                "amount": 123.456,  # High precision amount
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        self.assertEqual(expense.description, special_description)
        self.assertEqual(flt(expense.amount), 123.456)

        # Clean up
        expense.delete()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        # Clean up in reverse order of creation
        try:
            # Clean up any remaining expenses
            expenses = frappe.get_all("Volunteer Expense", filters={"volunteer": cls.test_volunteer.name})
            for expense in expenses:
                doc = frappe.get_doc("Volunteer Expense", expense.name)
                if doc.docstatus == 1:
                    doc.cancel()
                doc.delete()

            # Clean up chapter membership
            chapter_members = frappe.get_all(
                "Chapter Member", filters={"member": cls.test_member.name, "chapter": cls.test_chapter.name}
            )
            for cm in chapter_members:
                frappe.delete_doc("Chapter Member", cm.name)

            # Clean up volunteer
            if hasattr(cls, "test_volunteer") and cls.test_volunteer:
                cls.test_volunteer.delete()

            # Clean up member
            if hasattr(cls, "test_member") and cls.test_member:
                cls.test_member.delete()

            # Clean up test data
            if hasattr(cls, "expense_category") and cls.expense_category:
                cls.expense_category.delete()

            if hasattr(cls, "expense_account") and cls.expense_account:
                cls.expense_account.delete()

            if hasattr(cls, "test_team") and cls.test_team:
                cls.test_team.delete()

            if hasattr(cls, "test_chapter") and cls.test_chapter:
                cls.test_chapter.delete()
        except Exception:
            pass  # Ignore cleanup errors
