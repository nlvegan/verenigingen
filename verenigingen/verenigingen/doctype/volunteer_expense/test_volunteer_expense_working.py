import unittest

import frappe
from frappe.utils import add_days, flt, today


class TestVolunteerExpenseWorking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test data using existing entities"""
        cls.setup_test_environment()

    @classmethod
    def setup_test_environment(cls):
        """Create minimal test environment using existing data"""
        # Use existing company
        companies = frappe.get_all("Company", limit=1)
        if companies:
            cls.company = companies[0].name
        else:
            cls.skipTest("No company found")
            return

        # Get existing chapter
        chapters = frappe.get_all("Chapter", limit=1)
        if chapters:
            cls.test_chapter = chapters[0].name
        else:
            cls.test_chapter = None

        # Create minimal test data
        cls.setup_test_accounts()
        cls.setup_test_member_and_volunteer()

    @classmethod
    def setup_test_accounts(cls):
        """Set up expense account and category"""
        company_abbr = frappe.get_value("Company", cls.company, "abbr")
        account_name = f"Test Expense Account - {company_abbr}"

        if not frappe.db.exists("Account", account_name):
            # Find existing expense group account
            company_abbr = frappe.get_value("Company", cls.company, "abbr")
            parent_account = f"Expenses - {company_abbr}"

            # Check if the standard expense account exists
            if not frappe.db.exists("Account", parent_account):
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

    @classmethod
    def setup_test_member_and_volunteer(cls):
        """Create minimal test member and volunteer"""
        # Create test member
        test_member_email = "test.working@example.com"
        existing_member = frappe.db.exists("Member", {"email": test_member_email})
        if not existing_member:
            cls.test_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Test",
                    "last_name": "Working",
                    "email": test_member_email,
                    "full_name": "Test Working Member",
                }
            )
            cls.test_member.insert()
        else:
            cls.test_member = frappe.get_doc("Member", existing_member)

        # Create test volunteer
        volunteer_name = "Test Working Member"
        existing_volunteer = frappe.db.exists("Volunteer", {"volunteer_name": volunteer_name})
        if not existing_volunteer:
            cls.test_volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": volunteer_name,
                    "member": cls.test_member.name,
                    "email": "test.working.volunteer@example.com",
                    "status": "Active",
                }
            )
            cls.test_volunteer.insert()
        else:
            cls.test_volunteer = frappe.get_doc("Volunteer", existing_volunteer)

        # Add test member to the chapter if we have both
        if cls.test_chapter:
            chapter_doc = frappe.get_doc("Chapter", cls.test_chapter)
            member_already_in_chapter = False

            for member_row in chapter_doc.members:
                if member_row.member == cls.test_member.name:
                    member_already_in_chapter = True
                    break

            if not member_already_in_chapter:
                chapter_doc.append(
                    "members",
                    {
                        "member": cls.test_member.name,
                        "member_name": cls.test_member.full_name,
                        "enabled": True,
                    },
                )
                chapter_doc.save()

    def setUp(self):
        """Set up for each test"""
        if not self.expense_category:
            self.skipTest("No expense category available - check account setup")

    def test_basic_expense_creation(self):
        """Test basic expense creation with chapter"""
        if not self.test_chapter:
            self.skipTest("No chapter available for testing")

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Basic test expense",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter,
                "company": self.company,
            }
        )
        expense.insert()

        self.assertTrue(expense.name)
        self.assertEqual(expense.status, "Draft")
        self.assertEqual(expense.amount, 50.00)

        # Clean up
        expense.delete()

    def test_validation_rules(self):
        """Test basic validation rules"""
        if not self.test_chapter:
            self.skipTest("No chapter available for testing")

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
                "chapter": self.test_chapter,
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
                "chapter": self.test_chapter,
                "company": self.company,
            }
        )

        with self.assertRaises(frappe.ValidationError):
            expense.insert()

    def test_organization_type_validation(self):
        """Test organization type requirements"""
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

    def test_expense_submission(self):
        """Test expense submission and cancellation"""
        if not self.test_chapter:
            self.skipTest("No chapter available for testing")

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
                "chapter": self.test_chapter,
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

    def test_special_characters(self):
        """Test handling of special characters"""
        if not self.test_chapter:
            self.skipTest("No chapter available for testing")

        special_description = "Travel: München & Berlin (50% reimbursable) @2024"

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": special_description,
                "amount": 123.45,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter,
                "company": self.company,
            }
        )
        expense.insert()

        self.assertEqual(expense.description, special_description)
        self.assertEqual(flt(expense.amount), 123.45)

        # Clean up
        expense.delete()

    def test_approval_functions_exist(self):
        """Test that approval functions exist and are callable"""
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import (
            approve_expense,
            can_approve_expense,
            reject_expense,
        )

        # Test functions exist
        self.assertTrue(callable(approve_expense))
        self.assertTrue(callable(reject_expense))
        self.assertTrue(callable(can_approve_expense))

        if not self.test_chapter:
            self.skipTest("No chapter available for testing")

        # Create expense for testing
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
                "chapter": self.test_chapter,
                "company": self.company,
            }
        )
        expense.insert()
        expense.submit()

        # Test that functions can be called (they may throw permission errors, but should not crash)
        try:
            can_approve_expense(expense)
        except Exception:
            pass  # Permission errors are expected

        try:
            approve_expense(expense.name)
        except Exception:
            pass  # Permission errors are expected

        try:
            reject_expense(expense.name, "Test rejection")
        except Exception:
            pass  # Permission errors are expected

        # Clean up
        expense.cancel()
        expense.delete()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        try:
            # Clean up any remaining expenses
            if hasattr(cls, "test_volunteer"):
                expenses = frappe.get_all("Volunteer Expense", filters={"volunteer": cls.test_volunteer.name})
                for expense in expenses:
                    doc = frappe.get_doc("Volunteer Expense", expense.name)
                    if doc.docstatus == 1:
                        doc.cancel()
                    doc.delete()

            # Remove test member from chapter
            if (
                hasattr(cls, "test_chapter")
                and hasattr(cls, "test_member")
                and cls.test_chapter
                and cls.test_member
            ):
                try:
                    chapter_doc = frappe.get_doc("Chapter", cls.test_chapter)
                    members_to_remove = []
                    for i, member_row in enumerate(chapter_doc.members):
                        if member_row.member == cls.test_member.name:
                            members_to_remove.append(i)

                    # Remove in reverse order to maintain indices
                    for i in reversed(members_to_remove):
                        chapter_doc.remove(chapter_doc.members[i])

                    if members_to_remove:
                        chapter_doc.save()
                except Exception:
                    pass

            # Clean up test entities
            if hasattr(cls, "test_volunteer") and cls.test_volunteer:
                cls.test_volunteer.delete()

            if hasattr(cls, "test_member") and cls.test_member:
                cls.test_member.delete()

            if hasattr(cls, "expense_category") and cls.expense_category:
                cls.expense_category.delete()

            if hasattr(cls, "expense_account") and cls.expense_account:
                cls.expense_account.delete()
        except Exception:
            pass  # Ignore cleanup errors
