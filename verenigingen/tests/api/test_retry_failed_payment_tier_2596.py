"""#2596: retry_failed_payment must be reachable by the member who owns the invoice.

The endpoint was @critical_api (CRITICAL, Role Profile only), which no plain Member or
Staff profile holds, so its own is_owner / has_write branch never ran for the people it
was written for. Ruling (a): a member retries their OWN failed payment; staff may retry
on a member's behalf (#1101). Real users, real Role Profiles, dispatched through the
real whitelist gate.
"""

import json
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles
from verenigingen.utils.constants import Roles

CMD = "verenigingen.api.payment_dashboard.retry_failed_payment"
UNKNOWN_INVOICE = "ACC-SINV-DOES-NOT-EXIST-2596"


class TestRetryFailedPaymentTier2596(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._clear_member_cache_2596()
        self.owner_email = self._user_2596("Verenigingen Member")
        self.owner = self._member_2596(self.owner_email, "Owner")
        self.other_email = self._user_2596("Verenigingen Member")
        self.other = self._member_2596(self.other_email, "Other")
        self.invoice = self.create_test_sales_invoice(self.owner.name)
        frappe.db.set_value("Sales Invoice", self.invoice.name, "member", self.owner.name)

    def _user_2596(self, profile):
        email = f"p2596-{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(email)
        grant_matching_role_profiles(email, profile)
        return email

    def _member_2596(self, email, last_name):
        member = self.create_test_member(
            first_name="Retry", last_name=last_name, email=email, user=email, status="Active"
        )
        frappe.db.set_value("Member", member.name, "user", email)  # Probe shortcut: link the login
        self._clear_member_cache_2596()
        return member

    @staticmethod
    def _clear_member_cache_2596():
        for cell in frappe.get_attr("verenigingen.api.payment_dashboard.get_member_from_user").__closure__ or ():
            if isinstance(cell.cell_contents, dict):
                cell.cell_contents.clear()

    def _dispatch_2596(self, user, invoice_id):
        """Run the endpoint through the real whitelist gate; return (result, exc, channels)."""
        saved = (getattr(frappe.local, "request", None), frappe.local.form_dict)
        caller_before = frappe.session.user
        frappe.local.request = MagicMock(method="POST", environ={"REMOTE_ADDR": "203.0.113.9"})
        frappe.set_user(user)
        frappe.local.form_dict = frappe._dict(invoice_id=invoice_id)
        log_len = len(frappe.local.message_log)
        errors_before = frappe.db.count("Error Log")
        result = error = None
        try:
            result = frappe.handler.execute_cmd(CMD)
        except Exception as e:  # noqa: BLE001 - the refusal IS the observation
            error = e
        finally:
            frappe.set_user(caller_before)
            frappe.local.request, frappe.local.form_dict = saved  # Mock justified: request stub
        channels = {
            "message_log": [m.get("message") if isinstance(m, dict) else m for m in frappe.local.message_log[log_len:]],
            "error_logs": frappe.db.count("Error Log") - errors_before,
        }
        del frappe.local.message_log[log_len:]
        return result, error, channels

    @staticmethod
    def _shape_2596(result, error):
        if error is not None:
            return ("raised", type(error), str(error))
        return (result.get("success"), (result.get("error") or {}).get("message"), result.get("data"))

    def test_owner_member_can_retry_own_invoice(self):
        result, error, _ = self._dispatch_2596(self.owner_email, self.invoice.name)
        self.assertIsNone(error)
        self.assertTrue(result["success"], result)
        self.assertTrue(frappe.db.exists("SEPA Payment Retry", {"invoice": self.invoice.name}))

    def test_other_member_is_refused_and_no_retry_is_scheduled(self):
        result, error, _ = self._dispatch_2596(self.other_email, self.invoice.name)
        self.assertIsNone(error)
        self.assertFalse(result["success"], result)
        self.assertIn("permission", result["error"]["message"].lower())
        self.assertFalse(frappe.db.exists("SEPA Payment Retry", {"invoice": self.invoice.name}))

    def test_other_member_refusal_is_identical_for_unknown_and_forbidden_id(self):
        unknown = self._dispatch_2596(self.other_email, UNKNOWN_INVOICE)
        forbidden = self._dispatch_2596(self.other_email, self.invoice.name)
        self.assertFalse(unknown[0]["success"], unknown)  # control: a real refusal, not a crash
        self.assertEqual(self._shape_2596(unknown[0], unknown[1]), self._shape_2596(forbidden[0], forbidden[1]))
        self.assertEqual(unknown[2], forbidden[2])

    def test_staff_can_retry_on_a_members_behalf(self):
        staff = self._user_2596("Verenigingen Staff")
        result, error, _ = self._dispatch_2596(staff, self.invoice.name)
        self.assertIsNone(error)
        self.assertTrue(result["success"], result)
        self.assertTrue(frappe.db.exists("SEPA Payment Retry", {"invoice": self.invoice.name}))

    def test_guest_is_refused(self):
        result, error, _ = self._dispatch_2596("Guest", self.invoice.name)
        self.assertIsNotNone(error, result)
        self.assertFalse(frappe.db.exists("SEPA Payment Retry", {"invoice": self.invoice.name}))

    # ------------------------------------------------------------------ #
    # review round 2
    # ------------------------------------------------------------------ #
    def _retry_rows_2596(self):
        return frappe.get_all(
            "SEPA Payment Retry", filters={"invoice": self.invoice.name}, fields=["name", "status"]
        )

    def _audit_names_2596(self):
        rows = frappe.get_all("API Audit Log", fields=["name", "event_type", "details"], limit_page_length=0)
        return {
            r.name: (r.event_type, json.loads(r.details or "{}"))
            for r in rows
            if json.loads(r.details or "{}").get("function") == "retry_failed_payment"
        }

    def _new_audit_2596(self, before):
        return [v for k, v in self._audit_names_2596().items() if k not in before]

    def test_chapter_board_member_cannot_retry_another_members_invoice(self):
        """Chapter Board Member carries Sales Invoice write (Accounts User); that must not be enough
        to retry ANY member's invoice. Precondition asserts the write permission is really there,
        so the role check is what refuses."""
        board = self._user_2596("Verenigingen Chapter Board Member")
        with self.as_user(board):
            self.assertTrue(frappe.has_permission("Sales Invoice", "write"), "setup: needs has_write")
        result, error, _ = self._dispatch_2596(board, self.invoice.name)
        self.assertIsNone(error)
        self.assertFalse(result["success"], result)
        self.assertIn("permission", result["error"]["message"].lower())
        self.assertEqual(self._retry_rows_2596(), [])

    def test_treasurer_only_user_cannot_retry_another_members_invoice(self):
        """#1101 excludes treasurer and board: the staff set is Roles.ADMIN_ROLES."""
        # The Treasurer Role Profile bundles Verenigingen Staff, so use the bare roles
        treasurer = f"p2596-treas-{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(treasurer, roles=["Verenigingen Treasurer", "Accounts User"])
        with self.as_user(treasurer):
            self.assertFalse(set(frappe.get_roles()) & Roles.ADMIN_ROLES, "setup: treasurer-only")
            self.assertTrue(frappe.has_permission("Sales Invoice", "write"), "setup: needs has_write")
        result, error, _ = self._dispatch_2596(treasurer, self.invoice.name)
        self.assertIsNone(error)
        self.assertFalse(result["success"], result)
        self.assertIn("permission", result["error"]["message"].lower())
        self.assertEqual(self._retry_rows_2596(), [])

    def _assert_not_retryable_2596(self, invoice_name, caller):
        before = self._audit_names_2596()
        result, error, _ = self._dispatch_2596(caller, invoice_name)
        self.assertIsNone(error)
        self.assertFalse(result["success"], result)
        self.assertIn("outstanding", result["error"]["message"].lower())
        self.assertFalse(frappe.db.exists("SEPA Payment Retry", {"invoice": invoice_name}))
        # the manager refuses on its own too, not only the endpoint
        from verenigingen.verenigingen_payments.utils.payment_retry import PaymentRetryManager

        direct = PaymentRetryManager()._schedule_retry(invoice_name, "MANUAL", "x")
        self.assertFalse(direct["scheduled"], direct)
        self.assertFalse(frappe.db.exists("SEPA Payment Retry", {"invoice": invoice_name}))
        return before

    def test_paid_invoice_is_refused(self):
        # Probe shortcut: outstanding_amount zeroed directly instead of booking a payment
        frappe.db.set_value("Sales Invoice", self.invoice.name, "outstanding_amount", 0)
        self._assert_not_retryable_2596(self.invoice.name, self.owner_email)

    def test_cancelled_invoice_is_refused(self):
        frappe.get_doc("Sales Invoice", self.invoice.name).cancel()
        self._assert_not_retryable_2596(self.invoice.name, self.owner_email)

    def test_draft_invoice_is_refused(self):
        # Probe shortcut: docstatus set directly; the factory only builds submitted invoices
        frappe.db.set_value("Sales Invoice", self.invoice.name, "docstatus", 0)
        self._assert_not_retryable_2596(self.invoice.name, self.owner_email)

    def test_an_exhausted_record_escalates_once_not_on_every_call(self):
        from verenigingen.verenigingen_payments.utils.payment_retry import PaymentRetryManager

        manager = PaymentRetryManager()
        exhausted = frappe.get_doc(
            {
                "doctype": "SEPA Payment Retry",
                "invoice": self.invoice.name,
                "member": self.owner.name,
                "original_amount": 50,
                "retry_count": manager.retry_config["max_retries"],
                "status": "Retried",
            }
        ).insert()
        with patch.object(
            PaymentRetryManager,
            "send_escalation_notification",
            autospec=True,
            side_effect=PaymentRetryManager.send_escalation_notification,
        ) as notified:
            outcomes = [self._dispatch_2596(self.owner_email, self.invoice.name)[0] for _ in range(4)]
        self.assertEqual(notified.call_count, 1, "staff must be mailed exactly once")
        self.assertTrue(all(not o["success"] for o in outcomes), outcomes)
        self.assertEqual(frappe.db.get_value("SEPA Payment Retry", exhausted.name, "status"), "Escalated")
        self.assertIn("escalated", outcomes[-1]["error"]["message"].lower())

    def test_every_failing_exit_is_audited(self):
        staff = self._user_2596("Verenigingen Staff")
        cases = {}

        before = self._audit_names_2596()
        self._dispatch_2596(self.other_email, self.invoice.name)
        cases["refused"] = self._new_audit_2596(before)

        before = self._audit_names_2596()
        self._dispatch_2596(staff, UNKNOWN_INVOICE)
        cases["not found"] = self._new_audit_2596(before)

        frappe.get_doc(
            {
                "doctype": "SEPA Payment Retry",
                "invoice": self.invoice.name,
                "member": self.owner.name,
                "original_amount": 50,
                "retry_count": 1,
                "status": "Scheduled",
            }
        ).insert()
        before = self._audit_names_2596()
        self._dispatch_2596(self.owner_email, self.invoice.name)
        cases["already scheduled"] = self._new_audit_2596(before)

        for name, rows in cases.items():
            self.assertEqual(len(rows), 1, f"{name}: expected one audit row, got {rows}")
            self.assertEqual(rows[0][0], "api_call_failed", name)
        self.assertIn("permission", cases["refused"][0][1]["error"].lower())
        self.assertIn("not found", cases["not found"][0][1]["error"].lower())
        self.assertIn("already", cases["already scheduled"][0][1]["error"].lower())

    def test_the_cor_rate_limit_for_manual_retry_is_sane(self):
        """The shipped rule was 5000/hour; a retry mails staff and writes records.

        The fixture file is not loaded into existing sites (rules are seeded once, never
        overwritten), and the engine reads the DB row, so this runs the patch against a row
        still holding the old value and reads the row back.
        """
        from verenigingen.patches.v2_2.lower_retry_failed_payment_rate_limit import execute

        rule = "retry_failed_payment"
        fields = ["rate_limit_calls", "rate_limit_period_seconds", "rate_limit_scope"]
        original = frappe.db.get_value("Critical Operation Rule", rule, fields, as_dict=True)
        self.assertIsNotNone(original, "rule row missing on this site")
        self.addCleanup(
            lambda: frappe.db.set_value(
                "Critical Operation Rule", rule, dict(original), update_modified=False
            )
        )
        frappe.db.set_value("Critical Operation Rule", rule, "rate_limit_calls", 5000)
        execute()
        row = frappe.db.get_value("Critical Operation Rule", rule, fields, as_dict=True)
        self.assertEqual(row.rate_limit_calls, 5)
        self.assertEqual(row.rate_limit_period_seconds, 3600)
        self.assertEqual(row.rate_limit_scope, "per_user")

        # a row an operator tuned is left alone
        frappe.db.set_value("Critical Operation Rule", rule, "rate_limit_calls", 77)
        execute()
        self.assertEqual(frappe.db.get_value("Critical Operation Rule", rule, "rate_limit_calls"), 77)

    def test_a_paid_invoice_rejected_by_the_bank_logs_the_refused_retry(self):
        """pain.002 path: handle_payment_rejection drops schedule_retry's return value, so the
        refusal must leave an Error Log row naming the invoice and the reason."""
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
            handle_payment_rejection,
        )

        # Probe shortcut: outstanding_amount zeroed directly instead of booking a payment
        frappe.db.set_value("Sales Invoice", self.invoice.name, "outstanding_amount", 0)
        handle_payment_rejection(f"E2E-{self.invoice.name}", "AC04", "Closed account")
        self.assertFalse(frappe.db.exists("SEPA Payment Retry", {"invoice": self.invoice.name}))
        rows = frappe.get_all(
            "Error Log",
            filters={"error": ["like", f"%{self.invoice.name}%"]},
            fields=["method", "error"],
            order_by="creation desc",
        )
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("outstanding", rows[0].error.lower())
        self.assertIn("AC04", rows[0].error)
