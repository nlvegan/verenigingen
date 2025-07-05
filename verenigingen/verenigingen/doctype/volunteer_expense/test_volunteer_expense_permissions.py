import unittest
from unittest.mock import patch

import frappe
from frappe.utils import today


class TestVolunteerExpensePermissions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test data for permission testing"""
        cls.company = "Test Company"
        cls.setup_test_data()
        cls.setup_test_users()

    @classmethod
    def setup_test_data(cls):
        """Create test organizational data"""
        # Create test company
        if not frappe.db.exists("Company", cls.company):
            company = frappe.get_doc(
                {"doctype": "Company", "company_name": cls.company, "abbr": "TC", "default_currency": "EUR"}
            )
            company.insert()

        # Create test chapter
        if not frappe.db.exists("Chapter", "Permission Test Chapter"):
            cls.test_chapter = frappe.get_doc(
                {"doctype": "Chapter", "chapter_name": "Permission Test Chapter", "chapter_code": "PTC001"}
            )
            cls.test_chapter.insert()
        else:
            cls.test_chapter = frappe.get_doc("Chapter", "Permission Test Chapter")

        # Create test team
        if not frappe.db.exists("Team", "Permission Test Team"):
            cls.test_team = frappe.get_doc(
                {"doctype": "Team", "team_name": "Permission Test Team", "team_code": "PTT001"}
            )
            cls.test_team.insert()
        else:
            cls.test_team = frappe.get_doc("Team", "Permission Test Team")

        # Create expense account and category
        cls.setup_expense_infrastructure()

    @classmethod
    def setup_expense_infrastructure(cls):
        """Create expense accounts and categories"""
        # Create expense account
        if not frappe.db.exists("Account", f"Permission Test Expenses - {cls.company[:2]}"):
            cls.expense_account = frappe.get_doc(
                {
                    "doctype": "Account",
                    "account_name": "Permission Test Expenses",
                    "account_type": "Expense Account",
                    "company": cls.company,
                    "parent_account": frappe.get_value(
                        "Account", {"account_name": "Expenses", "company": cls.company}, "name"
                    )
                    or "Application of Funds (Assets) - TC",
                }
            )
            cls.expense_account.insert()
        else:
            cls.expense_account = frappe.get_doc("Account", f"Permission Test Expenses - {cls.company[:2]}")

        # Create expense category
        if not frappe.db.exists("Expense Category", "Permission Travel"):
            cls.expense_category = frappe.get_doc(
                {
                    "doctype": "Expense Category",
                    "category_name": "Permission Travel",
                    "expense_account": cls.expense_account.name,
                    "description": "Travel expenses for permission testing",
                    "is_active": 1,
                }
            )
            cls.expense_category.insert()
        else:
            cls.expense_category = frappe.get_doc("Expense Category", "Permission Travel")

    @classmethod
    def setup_test_users(cls):
        """Create test users with different roles and access levels"""
        # Chapter board member
        cls.chapter_board_user = cls.create_test_user(
            "chapter.board@test.com",
            "Chapter Board Member",
            ["Chapter Board Member"],
            cls.test_chapter,
            is_board_member=True,
        )

        # Team lead
        cls.team_lead_user = cls.create_test_user(
            "team.lead@test.com", "Team Lead User", ["Volunteer"], cls.test_team, is_team_lead=True
        )

        # Regular volunteer (chapter member)
        cls.chapter_volunteer_user = cls.create_test_user(
            "chapter.volunteer@test.com",
            "Chapter Volunteer User",
            ["Volunteer"],
            cls.test_chapter,
            is_board_member=False,
        )

        # Regular volunteer (team member)
        cls.team_volunteer_user = cls.create_test_user(
            "team.volunteer@test.com", "Team Volunteer User", ["Volunteer"], cls.test_team, is_team_lead=False
        )

        # Verenigingen manager
        cls.manager_user = cls.create_test_user(
            "manager@test.com", "Verenigingen Administrator", ["Verenigingen Administrator"], None
        )

        # User with no relevant permissions
        cls.no_permission_user = cls.create_test_user(
            "noperm@test.com", "No Permission User", ["Guest"], None
        )

    @classmethod
    def create_test_user(
        cls, email, full_name, roles, organization=None, is_board_member=False, is_team_lead=False
    ):
        """Create a test user with specified roles and organization access"""
        # Create user if not exists
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": full_name.split()[0],
                    "last_name": " ".join(full_name.split()[1:]) if len(full_name.split()) > 1 else "",
                    "enabled": 1,
                    "new_password": "test123",
                }
            )
            user.insert()

            # Add roles
            for role in roles:
                user.add_roles(role)
        else:
            user = frappe.get_doc("User", email)

        # Create member if organization access is needed
        if organization:
            if not frappe.db.exists("Member", email):
                member = frappe.get_doc(
                    {
                        "doctype": "Member",
                        "email": email,
                        "full_name": full_name,
                        "membership_status": "Active",
                    }
                )
                member.insert()
            else:
                member = frappe.get_doc("Member", email)

            # Create volunteer
            volunteer_name = f"{full_name} - {full_name.split()[0][:2].upper()}"
            if not frappe.db.exists("Volunteer", volunteer_name):
                volunteer = frappe.get_doc(
                    {
                        "doctype": "Volunteer",
                        "volunteer_name": full_name,
                        "member": member.name,
                        "status": "Active",
                        "user": email,
                    }
                )
                volunteer.insert()
            else:
                volunteer = frappe.get_doc("Volunteer", volunteer_name)

            # Create organization membership
            if organization.doctype == "Chapter":
                # Create chapter membership
                if not frappe.db.exists(
                    "Chapter Member", {"member": member.name, "chapter": organization.name}
                ):
                    chapter_member = frappe.get_doc(
                        {
                            "doctype": "Chapter Member",
                            "member": member.name,
                            "chapter": organization.name,
                            "status": "Active",
                        }
                    )
                    chapter_member.insert()

                # Create board membership if needed
                if is_board_member and not frappe.db.exists(
                    "Chapter Board Member", {"volunteer": volunteer.name, "chapter": organization.name}
                ):
                    board_member = frappe.get_doc(
                        {
                            "doctype": "Chapter Board Member",
                            "volunteer": volunteer.name,
                            "chapter": organization.name,
                            "is_active": 1,
                        }
                    )
                    board_member.insert()

            elif organization.doctype == "Team":
                # Create team membership
                if not frappe.db.exists(
                    "Team Member", {"volunteer": volunteer.name, "team": organization.name}
                ):
                    team_member = frappe.get_doc(
                        {
                            "doctype": "Team Member",
                            "volunteer": volunteer.name,
                            "team": organization.name,
                            "status": "Active",
                            "is_team_lead": is_team_lead,
                        }
                    )
                    team_member.insert()

            return {"user": user, "member": member, "volunteer": volunteer}
        else:
            return {"user": user}

    def test_can_approve_expense_chapter_board_member(self):
        """Test chapter board member can approve chapter expenses"""
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import can_approve_expense

        # Create test expense
        expense = self.create_test_expense(
            self.chapter_volunteer_user["volunteer"].name, "Chapter", self.test_chapter.name
        )

        # Test with chapter board member user
        with patch("frappe.session.user", self.chapter_board_user["user"].email):
            with patch("frappe.get_roles", return_value=["Chapter Board Member"]):
                can_approve = can_approve_expense(expense)
                self.assertTrue(can_approve)

        # Clean up
        expense.delete()

    def test_can_approve_expense_team_lead(self):
        """Test team lead can approve team expenses"""
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import can_approve_expense

        # Create test expense
        expense = self.create_test_expense(
            self.team_volunteer_user["volunteer"].name, "Team", self.test_team.name
        )

        # Test with team lead user
        with patch("frappe.session.user", self.team_lead_user["user"].email):
            with patch("frappe.get_roles", return_value=["Volunteer"]):
                can_approve = can_approve_expense(expense)
                self.assertTrue(can_approve)

        # Clean up
        expense.delete()

    def test_can_approve_expense_verenigingen_manager(self):
        """Test Verenigingen Administrator can approve any expense"""
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import can_approve_expense

        # Create test expense
        expense = self.create_test_expense(
            self.chapter_volunteer_user["volunteer"].name, "Chapter", self.test_chapter.name
        )

        # Test with manager user
        with patch("frappe.session.user", self.manager_user["user"].email):
            with patch("frappe.get_roles", return_value=["Verenigingen Administrator"]):
                can_approve = can_approve_expense(expense)
                self.assertTrue(can_approve)

        # Clean up
        expense.delete()

    def test_cannot_approve_expense_wrong_organization(self):
        """Test user cannot approve expense from different organization"""
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import can_approve_expense

        # Create chapter expense
        expense = self.create_test_expense(
            self.chapter_volunteer_user["volunteer"].name, "Chapter", self.test_chapter.name
        )

        # Test with team lead (should not be able to approve chapter expense)
        with patch("frappe.session.user", self.team_lead_user["user"].email):
            with patch("frappe.get_roles", return_value=["Volunteer"]):
                can_approve = can_approve_expense(expense)
                self.assertFalse(can_approve)

        # Clean up
        expense.delete()

    def test_cannot_approve_expense_no_volunteer_record(self):
        """Test user without volunteer record cannot approve"""
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import can_approve_expense

        # Create test expense
        expense = self.create_test_expense(
            self.chapter_volunteer_user["volunteer"].name, "Chapter", self.test_chapter.name
        )

        # Test with user who has no volunteer record
        with patch("frappe.session.user", self.no_permission_user["user"].email):
            with patch("frappe.get_roles", return_value=["Guest"]):
                can_approve = can_approve_expense(expense)
                self.assertFalse(can_approve)

        # Clean up
        expense.delete()

    def test_cannot_approve_expense_regular_volunteer(self):
        """Test regular volunteer cannot approve expenses"""
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import can_approve_expense

        # Create test expense
        expense = self.create_test_expense(
            self.chapter_volunteer_user["volunteer"].name, "Chapter", self.test_chapter.name
        )

        # Test with regular volunteer (not board member)
        with patch("frappe.session.user", self.chapter_volunteer_user["user"].email):
            with patch("frappe.get_roles", return_value=["Volunteer"]):
                can_approve = can_approve_expense(expense)
                self.assertFalse(can_approve)

        # Clean up
        expense.delete()

    def test_expense_approval_unauthorized_user(self):
        """Test that unauthorized users cannot approve expenses"""
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import approve_expense

        # Create and submit test expense
        expense = self.create_test_expense(
            self.chapter_volunteer_user["volunteer"].name, "Chapter", self.test_chapter.name
        )
        expense.submit()

        # Test with unauthorized user
        with patch("frappe.session.user", self.no_permission_user["user"].email):
            with self.assertRaises(frappe.PermissionError):
                approve_expense(expense.name)

        # Clean up
        expense.cancel()
        expense.delete()

    def test_expense_rejection_unauthorized_user(self):
        """Test that unauthorized users cannot reject expenses"""
        from verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense import reject_expense

        # Create and submit test expense
        expense = self.create_test_expense(
            self.chapter_volunteer_user["volunteer"].name, "Chapter", self.test_chapter.name
        )
        expense.submit()

        # Test with unauthorized user
        with patch("frappe.session.user", self.no_permission_user["user"].email):
            with self.assertRaises(frappe.PermissionError):
                reject_expense(expense.name, "Unauthorized rejection")

        # Clean up
        expense.cancel()
        expense.delete()

    @patch("frappe.sendmail")
    def test_expense_approval_notification_chapter(self, mock_sendmail):
        """Test approval notification for chapter expenses"""
        # Create test expense
        expense = self.create_test_expense(
            self.chapter_volunteer_user["volunteer"].name, "Chapter", self.test_chapter.name
        )
        expense.submit()

        # Check that notification was sent to board members
        self.assertTrue(mock_sendmail.called)

        # Verify notification content
        call_args = mock_sendmail.call_args
        self.assertIn(self.chapter_board_user["member"].email, call_args[1]["recipients"])
        self.assertIn("Expense Approval Required", call_args[1]["subject"])

        # Clean up
        expense.cancel()
        expense.delete()

    @patch("frappe.sendmail")
    def test_expense_approval_notification_team(self, mock_sendmail):
        """Test approval notification for team expenses"""
        # Create test expense
        expense = self.create_test_expense(
            self.team_volunteer_user["volunteer"].name, "Team", self.test_team.name
        )
        expense.submit()

        # Check that notification was sent to team leads
        self.assertTrue(mock_sendmail.called)

        # Verify notification content
        call_args = mock_sendmail.call_args
        self.assertIn(self.team_lead_user["member"].email, call_args[1]["recipients"])
        self.assertIn("Expense Approval Required", call_args[1]["subject"])

        # Clean up
        expense.cancel()
        expense.delete()

    def test_get_expense_approvers_chapter(self):
        """Test getting list of approvers for chapter expenses"""
        # Create test expense
        expense = self.create_test_expense(
            self.chapter_volunteer_user["volunteer"].name, "Chapter", self.test_chapter.name
        )

        approvers = expense.get_expense_approvers()

        # Should include chapter board member
        approver_emails = [email for email, name in approvers]
        self.assertIn(self.chapter_board_user["member"].email, approver_emails)

        # Clean up
        expense.delete()

    def test_get_expense_approvers_team(self):
        """Test getting list of approvers for team expenses"""
        # Create test expense
        expense = self.create_test_expense(
            self.team_volunteer_user["volunteer"].name, "Team", self.test_team.name
        )

        approvers = expense.get_expense_approvers()

        # Should include team lead
        approver_emails = [email for email, name in approvers]
        self.assertIn(self.team_lead_user["member"].email, approver_emails)

        # Clean up
        expense.delete()

    def test_expense_creation_permission_check(self):
        """Test that volunteers can only create expenses for organizations they belong to"""
        # Test chapter volunteer creating chapter expense - should work
        expense = self.create_test_expense(
            self.chapter_volunteer_user["volunteer"].name, "Chapter", self.test_chapter.name
        )
        self.assertTrue(expense.name)
        expense.delete()

        # Test team volunteer creating team expense - should work
        expense = self.create_test_expense(
            self.team_volunteer_user["volunteer"].name, "Team", self.test_team.name
        )
        self.assertTrue(expense.name)
        expense.delete()

    def create_test_expense(self, volunteer_name, organization_type, organization_name):
        """Helper method to create test expenses"""
        expense_data = {
            "doctype": "Volunteer Expense",
            "volunteer": volunteer_name,
            "expense_date": today(),
            "category": self.expense_category.name,
            "description": f"Test {organization_type} expense",
            "amount": 50.00,
            "currency": "EUR",
            "organization_type": organization_type,
            "company": self.company,
        }

        if organization_type == "Chapter":
            expense_data["chapter"] = organization_name
        else:
            expense_data["team"] = organization_name

        expense = frappe.get_doc(expense_data)
        expense.insert()
        return expense

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        # Clean up test records
        test_docs = [
            ("Volunteer Expense", {}),
            ("Chapter Board Member", {"chapter": cls.test_chapter.name}),
            ("Team Member", {"team": cls.test_team.name}),
            ("Chapter Member", {"chapter": cls.test_chapter.name}),
            ("Volunteer", {"volunteer_name": ["like", "%Test%"]}),
            ("Member", {"email": ["like", "%test.com"]}),
            ("User", {"email": ["like", "%test.com"]}),
            ("Team", {"team_name": ["like", "%Permission Test%"]}),
            ("Chapter", {"chapter_name": ["like", "%Permission Test%"]}),
            ("Expense Category", {"category_name": ["like", "%Permission%"]}),
            ("Account", {"account_name": ["like", "%Permission Test%"]}),
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
