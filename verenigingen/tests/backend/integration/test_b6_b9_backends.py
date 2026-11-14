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

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
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


class TestSendOverdueReminders(EnhancedTestCase):
    """B9 — expense_notifications.send_overdue_reminders."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        # HRMS notify_approver reads Employee.user_id as the notification's
        # from_user, and PWA Notification validates it as a Link to User. An
        # Employee a sibling test leaked (user deleted, Employee left) would die
        # here with "Could not find From User" (#1689), so skip those.
        emp = [
            e
            for e in frappe.get_all(
                "Employee", fields=["name", "company", "user_id"], order_by="creation asc"
            )
            if not e.user_id or frappe.db.exists("User", e.user_id)
        ][:1]
        if not emp:
            self.skipTest(
                "No Employee master with a usable user_id for Expense Claim seeding "
                "(none exist, or every Employee has a user_id whose User is gone; see #1689, #1694)"
            )
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

    def _make_overdue_claim(self, approver, days_ago=30, employee_name=None, chapter=None):
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
        if chapter:
            updates["custom_chapter"] = chapter
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

    # --- #1809: a board member's reminder covers only their own chapter(s) ---------------

    def _two_chapters_with_claims(self):
        """Chapter A (board member caller) and B, each with overdue claims and its own approver.

        Also one chapterless approver-less claim: unattributed claims are staff-only.
        """
        self.chapter_a = self.create_test_chapter()
        self.chapter_b = self.create_test_chapter()
        self.approver_a = self._make_approver()
        self.approver_b = self._make_approver()
        self.a_claims = [
            self._make_overdue_claim(self.approver_a, chapter=self.chapter_a.name) for _ in range(2)
        ]
        self.a_unassigned = self._make_overdue_claim(None, chapter=self.chapter_a.name)
        self.b_claims = [
            self._make_overdue_claim(self.approver_b, chapter=self.chapter_b.name) for _ in range(3)
        ]
        self.b_unassigned = self._make_overdue_claim(None, chapter=self.chapter_b.name)
        self.no_chapter_claim = self._make_overdue_claim(None)
        self.board_a = self.create_test_board_member(self.chapter_a.name)

    def _approvers_mailed(self, *addresses):
        """Which of ``addresses`` frappe.sendmail was asked to mail. EnhancedTestCase captures the
        call at the sendmail boundary (it replaces the Email Queue write), so this reads that capture."""
        return {a for a in addresses if self.get_sent_emails(to=a, method="frappe.sendmail")}

    def test_board_member_counts_cover_only_own_chapter(self):
        self._two_chapters_with_claims()
        self.assertIn(send_overdue_reminders, frappe.whitelisted)
        frappe.set_user(self.board_a.user)
        result = send_overdue_reminders(days_overdue=7)
        # A: 2 assigned + 1 unassigned. B's 4 claims and the chapterless claim are not theirs.
        self.assertEqual(result["claims_found"], 3)
        self.assertEqual(result["unassigned"], 1)
        self.assertEqual(result["approvers_notified"], 1)
        self.assertIn("covering 2 overdue", result["message"])

    def test_board_member_mails_only_own_chapter_approvers(self):
        self._two_chapters_with_claims()
        frappe.set_user(self.board_a.user)
        send_overdue_reminders(days_overdue=7)
        self.assertEqual(self._approvers_mailed(self.approver_a, self.approver_b), {self.approver_a})

    def test_staff_caller_keeps_org_wide_run(self):
        self._two_chapters_with_claims()
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        admin = self._make_approver()
        assign_role_profile_to_user(admin, "Verenigingen Administrator")
        frappe.set_user(admin)
        result = send_overdue_reminders(days_overdue=7)
        # lower bounds: the site may hold other overdue claims
        self.assertGreaterEqual(result["claims_found"], 3 + 4 + 1)
        self.assertGreaterEqual(result["unassigned"], 3)
        self.assertEqual(self._approvers_mailed(self.approver_a, self.approver_b), {self.approver_a, self.approver_b})

    def test_board_member_with_no_active_seat_is_refused_and_nothing_is_mailed(self):
        self._two_chapters_with_claims()
        frappe.db.set_value("Chapter Board Member", {"parent": self.chapter_a.name}, "is_active", 0)
        frappe.set_user(self.board_a.user)
        log_len = len(frappe.message_log)
        with self.assertRaises(frappe.ValidationError) as ctx:
            send_overdue_reminders(days_overdue=7)
        self.assertEqual(str(ctx.exception), "You are not permitted to send expense reminders")
        # frappe.throw appends to message_log before raising: it must carry only that message
        self.assertEqual(len(frappe.message_log) - log_len, 1)
        self.assertIn("not permitted to send expense reminders", str(frappe.message_log[-1]))
        del frappe.message_log[log_len:]
        self.assertEqual(self._approvers_mailed(self.approver_a, self.approver_b), set())

    def test_ordinary_chapter_member_without_a_seat_gets_nothing(self):
        """A plain Chapter Member of B (no board seat) holding the board role: refused, nothing mailed.
        Catches a fix that resolves chapters by membership instead of board seats."""
        self._two_chapters_with_claims()
        other = self.create_test_board_member(self.chapter_a.name)
        frappe.db.set_value("Chapter Board Member", {"volunteer": other.volunteer}, "is_active", 0)
        self.add_member_to_test_chapter(other.member, self.chapter_b.name)
        frappe.set_user(other.user)
        with self.assertRaises(frappe.ValidationError):
            send_overdue_reminders(days_overdue=7)
        self.assertEqual(self._approvers_mailed(self.approver_a, self.approver_b), set())

    def test_national_board_seat_also_covers_chapterless_claims(self):
        self._two_chapters_with_claims()
        national = self.create_test_chapter()
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", national.name)
        national_approver = self._make_approver()
        national_claim = self._make_overdue_claim(national_approver)  # no custom_chapter
        board = self.create_test_board_member(national.name)
        frappe.set_user(board.user)
        result = send_overdue_reminders(days_overdue=7)
        # the chapterless claim(s): national_claim plus the fixture's unassigned one; none of A/B
        self.assertGreaterEqual(result["claims_found"], 2)
        self.assertEqual(self._approvers_mailed(national_approver, self.approver_a, self.approver_b),
                         {national_approver})
        self.assertIn(national_claim, str(self.get_sent_emails(to=national_approver)))

    def test_non_national_board_member_never_sees_chapterless_claims(self):
        """Control for the national rule: a national board chapter exists and a chapterless claim
        with an approver exists, but chapter A's board member gets neither."""
        self._two_chapters_with_claims()
        national = self.create_test_chapter()
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", national.name)
        national_approver = self._make_approver()
        self._make_overdue_claim(national_approver)
        frappe.set_user(self.board_a.user)
        result = send_overdue_reminders(days_overdue=7)
        self.assertEqual(result["claims_found"], 3)
        self.assertEqual(self._approvers_mailed(national_approver), set())

    def test_foreign_chapter_data_leaves_no_trace_on_any_channel(self):
        """A seat on a chapter with NO overdue claims, while another chapter has some: the answer is
        zeros, no mail, and no message_log / Error Log residue, exactly as if nothing existed."""
        self._two_chapters_with_claims()
        empty = self.create_test_chapter()
        quiet_board = self.create_test_board_member(empty.name)
        frappe.set_user(quiet_board.user)
        log_len = len(frappe.message_log)
        errors = frappe.db.count("Error Log")
        result = send_overdue_reminders(days_overdue=7)
        self.assertEqual(
            (result["claims_found"], result["unassigned"], result["approvers_notified"]), (0, 0, 0)
        )
        self.assertIn("covering 0 overdue", result["message"])
        self.assertEqual(len(frappe.message_log), log_len)
        self.assertEqual(frappe.db.count("Error Log"), errors)
        self.assertEqual(self._approvers_mailed(self.approver_a, self.approver_b), set())
