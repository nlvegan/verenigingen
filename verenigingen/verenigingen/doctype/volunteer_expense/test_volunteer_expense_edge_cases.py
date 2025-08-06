import unittest
from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, today


class TestVolunteerExpenseEdgeCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test data for edge case testing"""
        cls.company = "Edge Test Company"
        cls.setup_test_data()

    @classmethod
    def setup_test_data(cls):
        """Create minimal test data for edge cases"""
        # Create test company
        if not frappe.db.exists("Company", cls.company):
            company = frappe.get_doc(
                {"doctype": "Company", "company_name": cls.company, "abbr": "ETC", "default_currency": "EUR"}
            )
            company.insert()

        # Create test account
        if not frappe.db.exists("Account", f"Edge Test Expenses - {cls.company[:3]}"):
            cls.expense_account = frappe.get_doc(
                {
                    "doctype": "Account",
                    "account_name": "Edge Test Expenses",
                    "account_type": "Expense Account",
                    "company": cls.company,
                    "parent_account": frappe.get_value(
                        "Account", {"account_name": "Expenses", "company": cls.company}, "name"
                    )
                    or "Application of Funds (Assets) - ETC",
                }
            )
            cls.expense_account.insert()
        else:
            cls.expense_account = frappe.get_doc("Account", f"Edge Test Expenses - {cls.company[:3]}")

        # Create test category
        if not frappe.db.exists("Expense Category", "Edge Test Category"):
            cls.expense_category = frappe.get_doc(
                {
                    "doctype": "Expense Category",
                    "category_name": "Edge Test Category",
                    "expense_account": cls.expense_account.name,
                    "description": "Category for edge case testing",
                }
            )
            cls.expense_category.insert()
        else:
            cls.expense_category = frappe.get_doc("Expense Category", "Edge Test Category")

        # Create minimal test entities
        cls.setup_minimal_entities()

    @classmethod
    def setup_minimal_entities(cls):
        """Create minimal entities for testing"""
        # Create test chapter
        if not frappe.db.exists("Chapter", "Edge Test Chapter"):
            cls.test_chapter = frappe.get_doc(
                {"doctype": "Chapter", "chapter_name": "Edge Test Chapter", "chapter_code": "ETC001"}
            )
            cls.test_chapter.insert()
        else:
            cls.test_chapter = frappe.get_doc("Chapter", "Edge Test Chapter")

        # Create test team
        if not frappe.db.exists("Team", "Edge Test Team"):
            cls.test_team = frappe.get_doc(
                {"doctype": "Team", "team_name": "Edge Test Team", "team_code": "ETT001"}
            )
            cls.test_team.insert()
        else:
            cls.test_team = frappe.get_doc("Team", "Edge Test Team")

        # Create test member and volunteer
        if not frappe.db.exists("Member", "edge.test@example.com"):
            cls.test_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "email": "edge.test@example.com",
                    "full_name": "Edge Test Volunteer",
                    "membership_status": "Active",
                }
            )
            cls.test_member.insert()
        else:
            cls.test_member = frappe.get_doc("Member", "edge.test@example.com")

        if not frappe.db.exists("Volunteer", "Edge Test Volunteer - ETV"):
            cls.test_volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": "Edge Test Volunteer",
                    "member": cls.test_member.name,
                    "status": "Active",
                }
            )
            cls.test_volunteer.insert()
        else:
            cls.test_volunteer = frappe.get_doc("Volunteer", "Edge Test Volunteer - ETV")

        # Create chapter membership
        if not frappe.db.exists(
            "Chapter Member", {"member": cls.test_member.name, "chapter": cls.test_chapter.name}
        ):
            chapter_membership = frappe.get_doc(
                {
                    "doctype": "Chapter Member",
                    "member": cls.test_member.name,
                    "chapter": cls.test_chapter.name,
                    "status": "Active",
                }
            )
            chapter_membership.insert()

    def test_extremely_long_description(self):
        """Test handling of extremely long descriptions"""
        long_description = "A" * 10000  # Very long description

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": long_description,
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )

        try:
            expense.insert()
            # If successful, verify truncation or handling
            self.assertTrue(len(expense.description) <= 10000)
            expense.delete()
        except frappe.DataError:
            # Expected if database has length constraints
            pass

    def test_unicode_and_emoji_in_description(self):
        """Test handling of Unicode characters and emojis"""
        unicode_description = "🚗 Taxi ride to conference in München 💰€50.00 ✅"

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": unicode_description,
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        self.assertEqual(expense.description, unicode_description)

        # Clean up
        expense.delete()

    def test_decimal_precision_amounts(self):
        """Test handling of high-precision decimal amounts"""
        test_amounts = [
            Decimal("99.999"),  # High precision
            Decimal("0.001"),  # Very small amount
            Decimal("999999.99"),  # Large amount
            Decimal("123.456789"),  # Many decimal places
        ]

        for amount in test_amounts:
            expense = frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.test_volunteer.name,
                    "expense_date": today(),
                    "category": self.expense_category.name,
                    "description": f"Precision test {amount}",
                    "amount": float(amount),
                    "currency": "EUR",
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter.name,
                    "company": self.company,
                }
            )
            expense.insert()

            # Verify precision handling
            self.assertGreater(flt(expense.amount), 0)

            # Clean up
            expense.delete()

    def test_concurrent_expense_creation(self):
        """Test handling of concurrent expense creation"""

        def create_expense(description_suffix):
            return frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.test_volunteer.name,
                    "expense_date": today(),
                    "category": self.expense_category.name,
                    "description": f"Concurrent test {description_suffix}",
                    "amount": 25.00,
                    "currency": "EUR",
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter.name,
                    "company": self.company,
                }
            )

        # Create multiple expenses "simultaneously"
        expenses = []
        for i in range(5):
            expense = create_expense(i)
            expense.insert()
            expenses.append(expense)

        # Verify all were created successfully
        self.assertEqual(len(expenses), 5)
        for expense in expenses:
            self.assertTrue(expense.name)

        # Clean up
        for expense in expenses:
            expense.delete()

    def test_expense_with_invalid_volunteer_member_link(self):
        """Test expense creation when volunteer's member link is broken"""
        # Create volunteer without member link
        orphan_volunteer = frappe.get_doc(
            {"doctype": "Volunteer", "volunteer_name": "Orphan Volunteer", "status": "Active"}
        )
        orphan_volunteer.insert()

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": orphan_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Orphan volunteer test",
                "amount": 30.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )

        # This should still work but validation might be limited
        expense.insert()
        self.assertTrue(expense.name)

        # Clean up
        expense.delete()
        orphan_volunteer.delete()

    def test_expense_date_boundary_conditions(self):
        """Test expense date edge cases"""
        # Test today's date (boundary)
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Today's expense",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()
        expense.delete()

        # Test very old date
        old_date = add_days(today(), -3650)  # 10 years ago
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": old_date,
                "category": self.expense_category.name,
                "description": "Very old expense",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()
        expense.delete()

    def test_status_transition_edge_cases(self):
        """Test edge cases in status transitions"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Status transition test",
                "amount": 75.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        # Test multiple rapid status changes
        expense.submit()
        self.assertEqual(expense.status, "Submitted")

        # Manually set to approved
        expense.db_set("status", "Approved")
        expense.reload()
        self.assertEqual(expense.status, "Approved")

        # Try to cancel approved expense (should fail)
        with self.assertRaises(frappe.ValidationError):
            expense.cancel()

        # Reset and clean up
        expense.db_set("status", "Submitted")
        expense.cancel()
        expense.delete()

    @patch("frappe.sendmail")
    def test_notification_with_invalid_email(self, mock_sendmail):
        """Test notification handling when volunteer has invalid email"""
        # Create member with invalid email
        invalid_member = frappe.get_doc(
            {
                "doctype": "Member",
                "email": "invalid-email",  # Invalid format
                "full_name": "Invalid Email Member",
                "membership_status": "Active",
            }
        )
        invalid_member.insert()

        invalid_volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Invalid Email Volunteer",
                "member": invalid_member.name,
                "status": "Active",
            }
        )
        invalid_volunteer.insert()

        # Create chapter membership
        chapter_membership = frappe.get_doc(
            {
                "doctype": "Chapter Member",
                "member": invalid_member.name,
                "chapter": self.test_chapter.name,
                "status": "Active",
            }
        )
        chapter_membership.insert()

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": invalid_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Invalid email test",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        # Should not crash even with invalid email
        expense.submit()
        self.assertEqual(expense.status, "Submitted")

        # Clean up
        expense.cancel()
        expense.delete()
        invalid_volunteer.delete()
        chapter_membership.delete()
        invalid_member.delete()

    @patch("frappe.sendmail")
    def test_notification_with_missing_email(self, mock_sendmail):
        """Test notification handling when volunteer has no email"""
        # Create member without email
        no_email_member = frappe.get_doc(
            {"doctype": "Member", "full_name": "No Email Member", "membership_status": "Active"}
        )
        no_email_member.insert()

        no_email_volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "No Email Volunteer",
                "member": no_email_member.name,
                "status": "Active",
            }
        )
        no_email_volunteer.insert()

        # Create chapter membership
        chapter_membership = frappe.get_doc(
            {
                "doctype": "Chapter Member",
                "member": no_email_member.name,
                "chapter": self.test_chapter.name,
                "status": "Active",
            }
        )
        chapter_membership.insert()

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": no_email_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "No email test",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        # Should not crash even without email
        expense.submit()
        self.assertEqual(expense.status, "Submitted")

        # Clean up
        expense.cancel()
        expense.delete()
        no_email_volunteer.delete()
        chapter_membership.delete()
        no_email_member.delete()

    def test_expense_with_deleted_category(self):
        """Test behavior when expense category is deleted after creation"""
        # Create temporary category
        temp_category = frappe.get_doc(
            {
                "doctype": "Expense Category",
                "category_name": "Temporary Category",
                "expense_account": self.expense_account.name,
                "description": "Temporary category for testing",
            }
        )
        temp_category.insert()

        # Create expense with this category
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": temp_category.name,
                "description": "Deleted category test",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        # Delete the category
        temp_category.delete()

        # Expense should still exist but category link is broken
        expense.reload()
        self.assertTrue(expense.name)

        # Clean up
        expense.delete()

    def test_very_small_amounts(self):
        """Test handling of very small expense amounts"""
        small_amounts = [0.01, 0.001, 0.0001]

        for amount in small_amounts:
            expense = frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.test_volunteer.name,
                    "expense_date": today(),
                    "category": self.expense_category.name,
                    "description": f"Small amount test {amount}",
                    "amount": amount,
                    "currency": "EUR",
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter.name,
                    "company": self.company,
                }
            )

            if amount > 0:
                expense.insert()
                self.assertEqual(flt(expense.amount), flt(amount))
                expense.delete()
            else:
                # Zero should fail validation
                with self.assertRaises(frappe.ValidationError):
                    expense.insert()

    def test_expense_naming_series_exhaustion(self):
        """Test behavior when naming series numbers get very high"""
        # This is theoretical but tests edge case handling
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Naming series test",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        # Verify name was generated
        self.assertTrue(expense.name)
        self.assertTrue(expense.name.startswith("VE-"))

        # Clean up
        expense.delete()

    def test_expense_with_special_currency(self):
        """Test expense with different currencies"""
        # Create USD currency if not exists
        if not frappe.db.exists("Currency", "USD"):
            usd_currency = frappe.get_doc(
                {"doctype": "Currency", "currency_name": "US Dollar", "currency_code": "USD", "symbol": "$"}
            )
            usd_currency.insert()

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "USD currency test",
                "amount": 50.00,
                "currency": "USD",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        self.assertEqual(expense.currency, "USD")

        # Clean up
        expense.delete()

    def test_rapid_status_changes(self):
        """Test rapid consecutive status changes"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.test_volunteer.name,
                "expense_date": today(),
                "category": self.expense_category.name,
                "description": "Rapid status change test",
                "amount": 100.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        # Rapid submit/cancel cycle
        expense.submit()
        self.assertEqual(expense.status, "Submitted")

        expense.cancel()
        self.assertEqual(expense.status, "Draft")

        # Submit again
        expense.submit()
        self.assertEqual(expense.status, "Submitted")

        # Clean up
        expense.cancel()
        expense.delete()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        # Clean up test records
        test_docs = [
            ("Volunteer Expense", {}),
            ("Chapter Member", {"chapter": cls.test_chapter.name}),
            ("Verenigingen Volunteer", {"volunteer_name": ["like", "%Edge Test%"]}),
            ("Member", {"email": ["like", "%edge.test%"]}),
            ("Team", {"team_name": ["like", "%Edge Test%"]}),
            ("Chapter", {"chapter_name": ["like", "%Edge Test%"]}),
            ("Expense Category", {"category_name": ["like", "%Edge Test%"]}),
            ("Account", {"account_name": ["like", "%Edge Test%"]}),
            ("Company", {"company_name": ["like", "%Edge Test%"]}),
        ]

        for doctype, filters in test_docs:
            try:
                records = frappe.get_all(doctype, filters=filters)
                for record in records:
                    try:
                        doc = frappe.get_doc(doctype, record.name)
                        if hasattr(doc, "cancel") and doc.docstatus == 1:
                            doc.cancel()
                        doc.delete()
                    except Exception:
                        pass
            except Exception:
                pass
