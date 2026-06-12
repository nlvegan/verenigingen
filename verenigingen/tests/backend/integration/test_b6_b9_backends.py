"""Integration tests for two UI-action backends added in commit 7ef5004d.

These endpoints back broken Member-form / Chapter-Expense-Report buttons and
were previously only manually verified:

- B6: ``member.create_organization_user`` — provisions a System User from a
  caller-supplied org-domain email/name, assigns member roles, transfers
  ownership and links ``member.user``.
- B9: ``expense_notifications.send_overdue_reminders`` — emails each expense
  approver a summary of their overdue, still-pending ERPNext Expense Claims.

Real integration (no business-logic mocks). Only ``frappe.sendmail`` (an
external boundary) is patched, per the test-quality rules.

Gotcha (B6): ``secure_document_operation`` commits the ``User`` insert
internally, so ``frappe.db.rollback()`` does NOT undo it — the created user is
registered via ``track_doc`` for teardown deletion instead.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.expense_notifications import send_overdue_reminders
from verenigingen.verenigingen.doctype.member.member import create_organization_user


class TestCreateOrganizationUser(VereningingenTestCase):
    """B6 — member.create_organization_user."""

    def _unique_email(self):
        return f"orguser-{frappe.generate_hash(length=8)}@example.org"

    def test_creates_new_system_user_linked_to_member(self):
        member = self.create_test_member()
        self.assertFalse(member.user, "factory member should start without a user")
        email = self._unique_email()

        # Mock justified: External Service - email service, not business logic
        with patch("frappe.sendmail"):
            result = create_organization_user(
                member=member.name,
                email=email,
                first_name="Org",
                last_name="Account",
                send_welcome_email=False,
            )
        self.track_doc("User", email)

        # Return contract
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "created_new")
        self.assertEqual(result["user"], email)

        # A real System User was created
        self.assertTrue(frappe.db.exists("User", email))
        user = frappe.get_doc("User", email)
        self.assertEqual(user.user_type, "System User")
        self.assertEqual(user.first_name, "Org")
        self.assertTrue(user.enabled)

        # Member is linked and ownership transferred to the new account
        member.reload()
        self.assertEqual(member.user, email)
        self.assertEqual(member.owner, email)

        # Member roles were assigned (add_member_roles_to_user ran)
        self.assertIn("Verenigingen Member", frappe.get_roles(email))

    def test_links_existing_user_instead_of_duplicating(self):
        member = self.create_test_member()
        email = self._unique_email()
        # Pre-existing user with the same email
        existing = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Existing",
                "user_type": "System User",
                "send_welcome_email": 0,
            }
        ).insert()
        self.track_doc("User", existing.name)

        # Mock justified: External Service - email service, not business logic
        with patch("frappe.sendmail"):
            result = create_organization_user(
                member=member.name, email=email, first_name="Org", send_welcome_email=False
            )

        self.assertEqual(result["action"], "linked_existing")
        self.assertEqual(result["user"], email)
        member.reload()
        self.assertEqual(member.user, email)

    def test_idempotent_when_member_already_has_user(self):
        member = self.create_test_member()
        email = self._unique_email()
        # Mock justified: External Service - email service, not business logic
        with patch("frappe.sendmail"):
            create_organization_user(
                member=member.name, email=email, first_name="Org", send_welcome_email=False
            )
        self.track_doc("User", email)

        # Second call must not create another user
        # Mock justified: External Service - email service, not business logic
        with patch("frappe.sendmail"):
            result = create_organization_user(
                member=member.name, email=self._unique_email(), first_name="Org2", send_welcome_email=False
            )
        self.assertEqual(result["action"], "already_exists")
        self.assertEqual(result["user"], email)

    def test_missing_first_name_is_rejected(self):
        member = self.create_test_member()
        # Mock justified: External Service - email service, not business logic
        with patch("frappe.sendmail"):
            with self.assertRaises(frappe.ValidationError):
                create_organization_user(
                    member=member.name, email=self._unique_email(), first_name="", send_welcome_email=False
                )


class TestSendOverdueReminders(VereningingenTestCase):
    """B9 — expense_notifications.send_overdue_reminders."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        emp = frappe.get_all("Employee", fields=["name", "company"], limit=1)
        if not emp:
            self.skipTest("No Employee master available for Expense Claim seeding")
        self.employee = emp[0].name
        self.company = emp[0].company
        self.currency = frappe.db.get_value("Company", self.company, "default_currency") or "EUR"
        self.cost_center = frappe.db.get_value("Company", self.company, "cost_center")
        self.payable = frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": "Liability", "account_type": "Payable", "is_group": 0},
            "name",
        )
        expense_acct = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Expense", "is_group": 0}, "name"
        )
        if not (self.payable and expense_acct and self.cost_center):
            self.skipTest("Company lacks the accounts/cost center needed for Expense Claims")

        # Dedicated Expense Claim Type so we don't mutate shared masters
        ect = frappe.get_doc(
            {
                "doctype": "Expense Claim Type",
                "expense_type": f"ZZ Overdue Test {frappe.generate_hash(length=6)}",
                "accounts": [{"company": self.company, "default_account": expense_acct}],
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Expense Claim Type", ect.name)
        self.expense_type = ect.name

        self._org_type = (
            frappe.get_meta("Expense Claim").get_field("custom_organization_type").options or "Chapter"
        ).split("\n")[0]

    def _make_approver(self):
        email = f"approver-{frappe.generate_hash(length=8)}@example.org"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Approver",
                "user_type": "System User",
                "send_welcome_email": 0,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("User", email)
        return email

    def _make_overdue_claim(self, approver, days_ago=30, employee_name=None):
        """Create a Draft Expense Claim with a controlled posting_date/approver."""
        claim = frappe.new_doc("Expense Claim")
        claim.employee = self.employee
        claim.company = self.company
        claim.currency = self.currency
        claim.exchange_rate = 1.0
        claim.custom_organization_type = self._org_type
        claim.posting_date = add_days(today(), -days_ago)
        claim.payable_account = self.payable
        claim.cost_center = self.cost_center
        if approver:
            claim.expense_approver = approver
        claim.append(
            "expenses",
            {
                "expense_type": self.expense_type,
                "amount": 50,
                "sanctioned_amount": 50,
                "expense_date": add_days(today(), -days_ago),
                "description": "test",
                "cost_center": self.cost_center,
            },
        )
        claim.insert(ignore_permissions=True)
        self.track_doc("Expense Claim", claim.name)
        # Force exact DB state regardless of HRMS auto-population on validate
        updates = {"approval_status": "Draft"}
        updates["expense_approver"] = approver or ""
        if employee_name is not None:
            updates["employee_name"] = employee_name
        for field, value in updates.items():
            frappe.db.set_value("Expense Claim", claim.name, field, value, update_modified=False)
        return claim.name

    def test_groups_by_approver_counts_unassigned_and_escapes_html(self):
        approver1 = self._make_approver()
        approver2 = self._make_approver()
        # approver1 gets two overdue claims (one with an XSS-laden claimant name)
        c1 = self._make_overdue_claim(approver1, employee_name="<script>alert(1)</script>")
        c2 = self._make_overdue_claim(approver1)
        # approver2 gets one
        c3 = self._make_overdue_claim(approver2)
        # one overdue claim with NO approver -> unassigned
        self._make_overdue_claim(None)
        # one recent (not overdue) claim for approver1 -> excluded by the cutoff
        recent = self._make_overdue_claim(approver1, days_ago=1)

        # Mock justified: External Service - email service, not business logic
        with patch("frappe.sendmail") as mock_sendmail:
            result = send_overdue_reminders(days_overdue=7)

        self.assertTrue(result["success"])
        # Aggregates count the whole DB, so assert lower bounds for our additions
        self.assertGreaterEqual(result["claims_found"], 4)
        self.assertGreaterEqual(result["approvers_notified"], 2)
        self.assertGreaterEqual(result["unassigned"], 1)

        # Index the captured emails by recipient
        by_recipient = {}
        for call in mock_sendmail.call_args_list:
            recipients = call.kwargs.get("recipients") or (call.args[0] if call.args else None)
            (key,) = recipients if isinstance(recipients, (list, tuple)) else (recipients,)
            by_recipient[key] = call.kwargs.get("message", "")

        # Each of our approvers was emailed exactly once
        self.assertIn(approver1, by_recipient)
        self.assertIn(approver2, by_recipient)

        # Grouping: approver1's single email lists BOTH of their overdue claims,
        # and NOT the recent (excluded) one.
        msg1 = by_recipient[approver1]
        self.assertIn(c1, msg1)
        self.assertIn(c2, msg1)
        self.assertNotIn(recent, msg1)
        # approver2's claim does not leak into approver1's email
        self.assertNotIn(c3, msg1)

        # HTML escaping of the claimant name (no raw <script>)
        self.assertIn("&lt;script&gt;", msg1)
        self.assertNotIn("<script>alert(1)</script>", msg1)

    def test_unauthorized_user_is_denied(self):
        denied_email = f"plain-{frappe.generate_hash(length=8)}@example.org"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": denied_email,
                "first_name": "Plain",
                "user_type": "Website User",
                "send_welcome_email": 0,
            }
        ).insert()
        self.track_doc("User", denied_email)

        # The role gate must deny a user lacking the reminder roles. Session user
        # is restored to the original by the base tearDown.
        frappe.set_user(denied_email)
        # Mock justified: External Service - email service, not business logic
        with patch("frappe.sendmail"):
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                send_overdue_reminders(days_overdue=7)
