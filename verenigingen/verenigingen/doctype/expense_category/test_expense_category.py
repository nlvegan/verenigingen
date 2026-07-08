import unittest

import frappe


class TestExpenseCategory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Seed a Company plus an expense and a non-expense (asset) Account.

        Previously every test was guarded by ``skipTest`` on account
        availability, so on a bare site the assertions silently no-oped. The
        seeding below deterministically finds an Expense-root and Asset-root
        group (always present in the ERPNext chart of accounts on the test
        sites) and creates the child accounts, then asserts they exist so a
        seeding failure surfaces loudly instead of skipping.
        """
        cls.company = cls._ensure_company()
        cls.expense_account = cls._ensure_account(
            account_name="Test Travel Expenses",
            account_type="Expense Account",
            root_type="Expense",
        )
        cls.asset_account = cls._ensure_account(
            account_name="Test Asset Account",
            account_type="Current Asset",
            root_type="Asset",
        )
        # Fail loudly rather than skip: these are prerequisites, not optionals.
        assert cls.expense_account, "Failed to seed expense account for tests"
        assert cls.asset_account, "Failed to seed asset account for tests"

    @classmethod
    def _ensure_company(cls):
        company = frappe.defaults.get_global_default("company")
        if company and frappe.db.exists("Company", company):
            return company
        existing = frappe.get_all("Company", limit=1, pluck="name")
        return existing[0] if existing else None

    @classmethod
    def _ensure_account(cls, account_name, account_type, root_type):
        """Get or create a leaf Account of the given type under a root group."""
        abbr = frappe.get_value("Company", cls.company, "abbr")
        full_name = f"{account_name} - {abbr}"
        if frappe.db.exists("Account", full_name):
            return frappe.get_doc("Account", full_name)

        parent = frappe.get_value(
            "Account",
            {"company": cls.company, "root_type": root_type, "is_group": 1},
            "name",
        )
        if not parent:
            return None

        account = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": account_name,
                "account_type": account_type,
                "parent_account": parent,
                "company": cls.company,
            }
        )
        account.insert()
        return account

    def test_expense_category_creation(self):
        """Test creating a valid expense category"""
        expense_category = frappe.get_doc(
            {
                "doctype": "Expense Category",
                "category_name": "Test Travel",
                "expense_account": self.expense_account.name,
                "description": "Travel and transportation expenses",
                "is_active": 1,
            }
        )
        expense_category.insert()

        self.assertTrue(expense_category.name)
        self.assertEqual(expense_category.category_name, "Test Travel")
        self.assertEqual(expense_category.expense_account, self.expense_account.name)
        self.assertTrue(expense_category.is_active)

        # Clean up
        expense_category.delete()

    def test_invalid_expense_account(self):
        """Test that non-expense account throws validation error"""
        expense_category = frappe.get_doc(
            {
                "doctype": "Expense Category",
                "category_name": "Test Invalid",
                "expense_account": self.asset_account.name,
                "description": "This should fail",
            }
        )

        with self.assertRaises(frappe.ValidationError):
            expense_category.insert()

    def test_duplicate_category_name(self):
        """Test that duplicate category names are prevented"""
        # Create first category
        category1 = frappe.get_doc(
            {
                "doctype": "Expense Category",
                "category_name": "Duplicate Test",
                "expense_account": self.expense_account.name,
                "description": "First category",
            }
        )
        category1.insert()

        # Try to create duplicate
        category2 = frappe.get_doc(
            {
                "doctype": "Expense Category",
                "category_name": "Duplicate Test",
                "expense_account": self.expense_account.name,
                "description": "Second category",
            }
        )

        with self.assertRaises(frappe.DuplicateEntryError):
            category2.insert()

        # Clean up
        category1.delete()

    def test_missing_required_fields(self):
        """Test validation of required fields"""
        # Test missing category name (this will fail during naming since category_name is used for autoname)
        with self.assertRaises((frappe.MandatoryError, frappe.ValidationError)):
            frappe.get_doc(
                {
                    "doctype": "Expense Category",
                    "expense_account": self.expense_account.name,
                    "description": "Missing name",
                }
            ).insert()

        # Test missing expense account
        with self.assertRaises(frappe.MandatoryError):
            frappe.get_doc(
                {
                    "doctype": "Expense Category",
                    "category_name": "Missing Account",
                    "description": "Missing expense account",
                }
            ).insert()

    def test_nonexistent_account(self):
        """Test linking to non-existent account"""
        expense_category = frappe.get_doc(
            {
                "doctype": "Expense Category",
                "category_name": "Nonexistent Account Test",
                "expense_account": "Nonexistent Account",
                "description": "Should fail",
            }
        )

        with self.assertRaises(frappe.LinkValidationError):
            expense_category.insert()

    def test_inactive_category(self):
        """Test creating inactive category"""
        expense_category = frappe.get_doc(
            {
                "doctype": "Expense Category",
                "category_name": "Inactive Test",
                "expense_account": self.expense_account.name,
                "description": "Inactive category",
                "is_active": 0,
            }
        )
        expense_category.insert()

        self.assertFalse(expense_category.is_active)

        # Clean up
        expense_category.delete()

    def test_category_update(self):
        """Test updating expense category"""
        expense_category = frappe.get_doc(
            {
                "doctype": "Expense Category",
                "category_name": "Update Test",
                "expense_account": self.expense_account.name,
                "description": "Original description",
                "is_active": 1,
            }
        )
        expense_category.insert()

        # Update description
        expense_category.description = "Updated description"
        expense_category.save()

        # Reload and verify
        expense_category.reload()
        self.assertEqual(expense_category.description, "Updated description")

        # Clean up
        expense_category.delete()

    def test_long_category_name(self):
        """Test category name length limits"""
        long_name = "A" * 200  # Very long name

        expense_category = frappe.get_doc(
            {
                "doctype": "Expense Category",
                "category_name": long_name,
                "expense_account": self.expense_account.name,
                "description": "Long name test",
            }
        )

        # This should fail due to length constraints
        with self.assertRaises((frappe.DataError, frappe.CharacterLengthExceededError)):
            expense_category.insert()

    def test_special_characters_in_name(self):
        """Test category names with special characters"""
        special_name = "Travel & Entertainment (T&E)"

        expense_category = frappe.get_doc(
            {
                "doctype": "Expense Category",
                "category_name": special_name,
                "expense_account": self.expense_account.name,
                "description": "Special characters test",
            }
        )
        expense_category.insert()

        self.assertEqual(expense_category.category_name, special_name)

        # Clean up
        expense_category.delete()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        try:
            if getattr(cls, "expense_account", None):
                cls.expense_account.delete()
            if getattr(cls, "asset_account", None):
                cls.asset_account.delete()
        except Exception:
            pass
