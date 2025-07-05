import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, today


class TestVolunteerExpense(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test data for the entire test class"""
        cls.company = "Test Company"
        cls.setup_test_data()

    @classmethod
    def setup_test_data(cls):
        """Create comprehensive test data"""
        # Create test company
        if not frappe.db.exists("Company", cls.company):
            company = frappe.get_doc(
                {"doctype": "Company", "company_name": cls.company, "abbr": "TC", "default_currency": "EUR"}
            )
            company.insert()

        # Create test accounts
        cls.setup_test_accounts()

        # Create test chapter
        if not frappe.db.exists("Chapter", "Test Chapter"):
            cls.test_chapter = frappe.get_doc(
                {"doctype": "Chapter", "chapter_name": "Test Chapter", "chapter_code": "TC001"}
            )
            cls.test_chapter.name = "Test Chapter"  # Set name explicitly for prompt autoname
            cls.test_chapter.insert()
        else:
            cls.test_chapter = frappe.get_doc("Chapter", "Test Chapter")

        # Create test team
        if not frappe.db.exists("Team", "Test Team"):
            cls.test_team = frappe.get_doc(
                {
                    "doctype": "Team",
                    "team_name": "Test Team",
                    "description": "Test team for expenses",
                    "status": "Active",
                }
            )
            cls.test_team.insert()
        else:
            cls.test_team = frappe.get_doc("Team", "Test Team")

        # Create test members and volunteers
        cls.setup_test_volunteers()

        # Create expense categories
        cls.setup_expense_categories()

    @classmethod
    def setup_test_accounts(cls):
        """Create test accounts"""
        # Use existing company if available
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

        # Find or create expense account
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
                cls.expense_account = None
        else:
            cls.expense_account = frappe.get_doc("Account", expense_account_name)

    @classmethod
    def setup_test_volunteers(cls):
        """Create test volunteers with different access levels"""
        # Volunteer with chapter access
        if not frappe.db.exists("Member", "chapter.volunteer@test.com"):
            cls.chapter_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "email": "chapter.volunteer@test.com",
                    "full_name": "Chapter Volunteer",
                    "membership_status": "Active",
                }
            )
            cls.chapter_member.insert()
        else:
            cls.chapter_member = frappe.get_doc("Member", "chapter.volunteer@test.com")

        if not frappe.db.exists("Volunteer", "Chapter Volunteer - CV"):
            cls.chapter_volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": "Chapter Volunteer",
                    "member": cls.chapter_member.name,
                    "status": "Active",
                }
            )
            cls.chapter_volunteer.insert()
        else:
            cls.chapter_volunteer = frappe.get_doc("Volunteer", "Chapter Volunteer - CV")

        # Create chapter membership
        if not frappe.db.exists(
            "Chapter Member", {"member": cls.chapter_member.name, "chapter": cls.test_chapter.name}
        ):
            chapter_membership = frappe.get_doc(
                {
                    "doctype": "Chapter Member",
                    "member": cls.chapter_member.name,
                    "chapter": cls.test_chapter.name,
                    "status": "Active",
                }
            )
            chapter_membership.insert()

        # Volunteer with team access
        if not frappe.db.exists("Member", "team.volunteer@test.com"):
            cls.team_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "email": "team.volunteer@test.com",
                    "full_name": "Team Volunteer",
                    "membership_status": "Active",
                }
            )
            cls.team_member.insert()
        else:
            cls.team_member = frappe.get_doc("Member", "team.volunteer@test.com")

        if not frappe.db.exists("Volunteer", "Team Volunteer - TV"):
            cls.team_volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": "Team Volunteer",
                    "member": cls.team_member.name,
                    "status": "Active",
                }
            )
            cls.team_volunteer.insert()
        else:
            cls.team_volunteer = frappe.get_doc("Volunteer", "Team Volunteer - TV")

        # Create team membership
        if not frappe.db.exists(
            "Team Member", {"volunteer": cls.team_volunteer.name, "team": cls.test_team.name}
        ):
            team_membership = frappe.get_doc(
                {
                    "doctype": "Team Member",
                    "volunteer": cls.team_volunteer.name,
                    "team": cls.test_team.name,
                    "status": "Active",
                    "is_team_lead": 0,
                }
            )
            team_membership.insert()

        # Volunteer with no access
        if not frappe.db.exists("Member", "no.access@test.com"):
            cls.no_access_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "email": "no.access@test.com",
                    "full_name": "No Access Volunteer",
                    "membership_status": "Active",
                }
            )
            cls.no_access_member.insert()
        else:
            cls.no_access_member = frappe.get_doc("Member", "no.access@test.com")

        if not frappe.db.exists("Volunteer", "No Access Volunteer - NAV"):
            cls.no_access_volunteer = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": "No Access Volunteer",
                    "member": cls.no_access_member.name,
                    "status": "Active",
                }
            )
            cls.no_access_volunteer.insert()
        else:
            cls.no_access_volunteer = frappe.get_doc("Volunteer", "No Access Volunteer - NAV")

    @classmethod
    def setup_expense_categories(cls):
        """Create test expense categories"""
        if cls.expense_account:
            if not frappe.db.exists("Expense Category", "Travel"):
                cls.travel_category = frappe.get_doc(
                    {
                        "doctype": "Expense Category",
                        "category_name": "Travel",
                        "expense_account": cls.expense_account.name,
                        "description": "Travel and transportation expenses",
                        "is_active": 1,
                    }
                )
                cls.travel_category.insert()
            else:
                cls.travel_category = frappe.get_doc("Expense Category", "Travel")

            if not frappe.db.exists("Expense Category", "Inactive Category"):
                cls.inactive_category = frappe.get_doc(
                    {
                        "doctype": "Expense Category",
                        "category_name": "Inactive Category",
                        "expense_account": cls.expense_account.name,
                        "description": "Inactive category for testing",
                        "is_active": 0,
                    }
                )
                cls.inactive_category.insert()
            else:
                cls.inactive_category = frappe.get_doc("Expense Category", "Inactive Category")
        else:
            cls.travel_category = None
            cls.inactive_category = None

    def test_chapter_expense_creation(self):
        """Test creating a valid chapter expense"""
        if not self.travel_category:
            self.skipTest("No expense category available for testing")

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
                "description": "Train ticket to conference",
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
        self.assertEqual(expense.organization_type, "Chapter")
        self.assertEqual(expense.chapter, self.test_chapter.name)
        self.assertIsNone(expense.team)

        # Clean up
        expense.delete()

    def test_team_expense_creation(self):
        """Test creating a valid team expense"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.team_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
                "description": "Team meeting expenses",
                "amount": 25.00,
                "currency": "EUR",
                "organization_type": "Team",
                "team": self.test_team.name,
                "company": self.company,
            }
        )
        expense.insert()

        self.assertTrue(expense.name)
        self.assertEqual(expense.status, "Draft")
        self.assertEqual(expense.organization_type, "Team")
        self.assertEqual(expense.team, self.test_team.name)
        self.assertIsNone(expense.chapter)

        # Clean up
        expense.delete()

    def test_future_date_validation(self):
        """Test that future expense dates are rejected"""
        future_date = add_days(today(), 5)

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": future_date,
                "category": self.travel_category.name,
                "description": "Future expense",
                "amount": 25.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )

        with self.assertRaises(frappe.ValidationError):
            expense.insert()

    def test_negative_amount_validation(self):
        """Test that negative amounts are rejected"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
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

    def test_zero_amount_validation(self):
        """Test that zero amounts are rejected"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
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
        """Test organization type and selection validation"""
        # Test chapter type without chapter
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
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
                "volunteer": self.team_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
                "description": "Missing team",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Team",
                "company": self.company,
            }
        )

        with self.assertRaises(frappe.ValidationError):
            expense.insert()

    def test_volunteer_chapter_access_validation(self):
        """Test that volunteer must have access to selected chapter"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.no_access_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
                "description": "Unauthorized chapter access",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )

        with self.assertRaises(frappe.ValidationError):
            expense.insert()

    def test_volunteer_team_access_validation(self):
        """Test that volunteer must be member of selected team"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.no_access_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
                "description": "Unauthorized team access",
                "amount": 50.00,
                "currency": "EUR",
                "organization_type": "Team",
                "team": self.test_team.name,
                "company": self.company,
            }
        )

        with self.assertRaises(frappe.ValidationError):
            expense.insert()

    def test_cross_organization_clearing(self):
        """Test that selecting chapter clears team and vice versa"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
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

    def test_auto_organization_setting(self):
        """Test automatic organization setting for volunteers with single access"""
        # This volunteer only has chapter access
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
                "description": "Auto organization test",
                "amount": 50.00,
                "currency": "EUR",
                "company": self.company,
            }
        )
        expense.insert()

        # Should auto-set to chapter
        self.assertEqual(expense.organization_type, "Chapter")
        self.assertEqual(expense.chapter, self.test_chapter.name)

        # Clean up
        expense.delete()

    def test_expense_submission_status_change(self):
        """Test that submission changes status to Submitted"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
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

        expense.submit()
        self.assertEqual(expense.status, "Submitted")

        # Clean up
        expense.cancel()
        expense.delete()

    def test_approved_expense_cancel_restriction(self):
        """Test that approved expenses cannot be cancelled"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
                "description": "Cancel restriction test",
                "amount": 100.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()
        expense.submit()

        # Manually set to approved status
        expense.db_set("status", "Approved")

        with self.assertRaises(frappe.ValidationError):
            expense.cancel()

        # Clean up
        expense.db_set("status", "Submitted")
        expense.cancel()
        expense.delete()

    def test_missing_required_fields(self):
        """Test validation of required fields"""
        # Test missing volunteer
        with self.assertRaises(frappe.MandatoryError):
            frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "expense_date": today(),
                    "category": self.travel_category.name,
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
                    "volunteer": self.chapter_volunteer.name,
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
                    "volunteer": self.chapter_volunteer.name,
                    "expense_date": today(),
                    "category": self.travel_category.name,
                    "amount": 50.00,
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter.name,
                }
            ).insert()

    def test_nonexistent_links(self):
        """Test validation with non-existent linked records"""
        # Test non-existent volunteer
        with self.assertRaises(frappe.LinkValidationError):
            frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": "Nonexistent Volunteer",
                    "expense_date": today(),
                    "category": self.travel_category.name,
                    "description": "Invalid volunteer",
                    "amount": 50.00,
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter.name,
                }
            ).insert()

        # Test non-existent category
        with self.assertRaises(frappe.LinkValidationError):
            frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.chapter_volunteer.name,
                    "expense_date": today(),
                    "category": "Nonexistent Category",
                    "description": "Invalid category",
                    "amount": 50.00,
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter.name,
                }
            ).insert()

    @patch("frappe.sendmail")
    def test_expense_approval_workflow(self, mock_sendmail):
        """Test expense approval workflow"""
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import approve_expense

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
                "description": "Approval workflow test",
                "amount": 150.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()
        expense.submit()

        # Test approval
        approve_expense(expense.name)
        expense.reload()

        self.assertEqual(expense.status, "Approved")
        self.assertIsNotNone(expense.approved_by)
        self.assertIsNotNone(expense.approved_on)

        # Clean up
        expense.cancel()
        expense.delete()

    @patch("frappe.sendmail")
    def test_expense_rejection_workflow(self, mock_sendmail):
        """Test expense rejection workflow"""
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import reject_expense

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
                "description": "Rejection workflow test",
                "amount": 200.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()
        expense.submit()

        # Test rejection
        reject_expense(expense.name, "Test rejection reason")
        expense.reload()

        self.assertEqual(expense.status, "Rejected")
        self.assertIn("Test rejection reason", expense.notes)

        # Clean up
        expense.cancel()
        expense.delete()

    def test_large_amount_handling(self):
        """Test handling of large expense amounts"""
        large_amount = 999999.99

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
                "description": "Large amount test",
                "amount": large_amount,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        self.assertEqual(flt(expense.amount), large_amount)

        # Clean up
        expense.delete()

    def test_special_characters_in_description(self):
        """Test handling of special characters in description"""
        special_description = "Travel expenses for conference: München & Berlin (50% reimbursable) @2024"

        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
                "description": special_description,
                "amount": 100.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        self.assertEqual(expense.description, special_description)

        # Clean up
        expense.delete()

    def test_empty_notes_field(self):
        """Test expense creation with empty optional fields"""
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.chapter_volunteer.name,
                "expense_date": today(),
                "category": self.travel_category.name,
                "description": "Minimal expense",
                "amount": 30.00,
                "currency": "EUR",
                "organization_type": "Chapter",
                "chapter": self.test_chapter.name,
                "company": self.company,
            }
        )
        expense.insert()

        self.assertIsNone(expense.notes)
        self.assertIsNone(expense.receipt_attachment)

        # Clean up
        expense.delete()

    def test_company_auto_setting(self):
        """Test automatic company setting when not provided"""
        # Set a default company for testing
        original_default = frappe.defaults.get_global_default("company")
        frappe.defaults.set_global_default("company", self.company)

        try:
            expense = frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.chapter_volunteer.name,
                    "expense_date": today(),
                    "category": self.travel_category.name,
                    "description": "Auto company test",
                    "amount": 40.00,
                    "currency": "EUR",
                    "organization_type": "Chapter",
                    "chapter": self.test_chapter.name
                    # No company specified
                }
            )
            expense.insert()

            self.assertEqual(expense.company, self.company)

            # Clean up
            expense.delete()
        finally:
            # Restore original default
            if original_default:
                frappe.defaults.set_global_default("company", original_default)

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        # Clean up test records
        test_docs = [
            ("Volunteer Expense", {}),
            ("Expense Category", {"category_name": ["like", "%Test%"]}),
            ("Team Member", {"team": cls.test_team.name}),
            ("Chapter Member", {"chapter": cls.test_chapter.name}),
            ("Volunteer", {"volunteer_name": ["like", "%Test%"]}),
            ("Member", {"email": ["like", "%test.com"]}),
            ("Team", {"team_name": ["like", "%Test%"]}),
            ("Chapter", {"chapter_name": ["like", "%Test%"]}),
            ("Account", {"account_name": ["like", "%Test%"]}),
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
