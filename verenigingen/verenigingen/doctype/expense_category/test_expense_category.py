import unittest

import frappe


class TestExpenseCategory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test data for the entire test class"""
        cls.company = frappe.defaults.get_global_default("company") or "Test Company"
        cls.setup_test_accounts()

    @classmethod
    def setup_test_accounts(cls):
        """Create test accounts if they don't exist"""
        # Use existing company if available, otherwise create test company
        existing_companies = frappe.get_all("Company", limit=1)
        if existing_companies:
            cls.company = existing_companies[0].name
        else:
            # Create test company
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

        # Get company abbreviation
        company_abbr = frappe.get_value("Company", cls.company, "abbr")

        # Find existing expense account or create one
        expense_account_name = f"Test Travel Expenses - {company_abbr}"
        if not frappe.db.exists("Account", expense_account_name):
            # Get existing expense group account
            root_expense = frappe.get_value(
                "Account", {"company": cls.company, "account_type": "Expense Account", "is_group": 1}, "name"
            )

            if not root_expense:
                # Try different expense account patterns
                root_expense = frappe.get_value(
                    "Account",
                    {"company": cls.company, "account_name": ["like", "%Expense%"], "is_group": 1},
                    "name",
                )

            if not root_expense:
                # Get any root account to use as parent
                root_expense = frappe.get_value(
                    "Account",
                    {"company": cls.company, "parent_account": ["in", ["", None]], "is_group": 1},
                    "name",
                )

            if root_expense:
                cls.expense_account = frappe.get_doc(
                    {
                        "doctype": "Account",
                        "account_name": "Test Travel Expenses",
                        "account_type": "Expense Account",
                        "parent_account": root_expense,
                        "company": cls.company,
                    }
                )
                cls.expense_account.insert()
            else:
                # Skip account creation if we can't find a parent
                cls.expense_account = None
        else:
            cls.expense_account = frappe.get_doc("Account", expense_account_name)

        # Find existing asset account for testing invalid category
        asset_account_name = f"Test Asset Account - {company_abbr}"
        if not frappe.db.exists("Account", asset_account_name) and cls.expense_account:
            # Get existing asset group account
            root_asset = frappe.get_value(
                "Account",
                {
                    "company": cls.company,
                    "account_type": ["in", ["Current Asset", "Fixed Asset"]],
                    "is_group": 1,
                },
                "name",
            )

            if not root_asset:
                # Try different asset account patterns
                root_asset = frappe.get_value(
                    "Account",
                    {"company": cls.company, "account_name": ["like", "%Asset%"], "is_group": 1},
                    "name",
                )

            if root_asset:
                cls.asset_account = frappe.get_doc(
                    {
                        "doctype": "Account",
                        "account_name": "Test Asset Account",
                        "account_type": "Current Asset",
                        "parent_account": root_asset,
                        "company": cls.company,
                    }
                )
                cls.asset_account.insert()
            else:
                cls.asset_account = None
        elif frappe.db.exists("Account", asset_account_name):
            cls.asset_account = frappe.get_doc("Account", asset_account_name)
        else:
            cls.asset_account = None

    def test_expense_category_creation(self):
        """Test creating a valid expense category"""
        if not self.expense_account:
            self.skipTest("No expense account available for testing")

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
        if not self.asset_account:
            self.skipTest("No asset account available for testing")

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
        if not self.expense_account:
            self.skipTest("No expense account available for testing")

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
        if not self.expense_account:
            self.skipTest("No expense account available for testing")

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
        if not self.expense_account:
            self.skipTest("No expense account available for testing")

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
        if not self.expense_account:
            self.skipTest("No expense account available for testing")

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
        if not self.expense_account:
            self.skipTest("No expense account available for testing")

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
        if not self.expense_account:
            self.skipTest("No expense account available for testing")

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
        # Clean up test accounts
        try:
            if hasattr(cls, "expense_account") and cls.expense_account:
                cls.expense_account.delete()
            if hasattr(cls, "asset_account") and cls.asset_account:
                cls.asset_account.delete()
        except Exception:
            pass
