"""#2596: retry_failed_payment must be reachable by the member who owns the invoice.

The endpoint was @critical_api (CRITICAL, Role Profile only), which no plain Member or
Staff profile holds, so its own is_owner / has_write branch never ran for the people it
was written for. Ruling (a): a member retries their OWN failed payment; staff may retry
on a member's behalf (#1101). Real users, real Role Profiles, dispatched through the
real whitelist gate.
"""

from unittest.mock import MagicMock

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

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
