"""
SEPA staff alerts resolve through the shared key-first resolver and never reach Administrator (#2036).

Mock justification: EmailService / frappe.sendmail are the outgoing-mail boundary; recipient
resolution runs against real Verenigingen Email Configuration rows and real Users. The "nobody
resolves" state cannot be built from real rows (a test site always has admin-role holders), so the
resolver itself is blanked for the empty-result tests only.

Run:
    bench --site test_site_6 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_sepa_admin_recipients_2036
"""

from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_sepa_literal_recipients import (
    _put_key_row,
    _restore_rows,
    _snapshot_rows,
)
from verenigingen.verenigingen_payments.services.sepa_xml_adapter import (
    BatchValidationSummary,
    SEPAXMLAdapter,
)
from verenigingen.verenigingen_payments.utils import payment_retry as pr
from verenigingen.verenigingen_payments.utils.sepa_rollback_manager import RollbackReason, SEPARollbackManager

CONFIG_DOCTYPE = "Verenigingen Email Configuration"
ADMIN_EMAIL = "administrator-2036@example.org"


class _Base(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        old_email = frappe.db.get_value("User", "Administrator", "email")
        self.addCleanup(frappe.db.set_value, "User", "Administrator", "email", old_email, update_modified=False)
        frappe.db.set_value("User", "Administrator", "email", ADMIN_EMAIL, update_modified=False)
        for field in ("admin_notification_emails",):
            frappe.db.set_single_value(CONFIG_DOCTYPE, field, "")
        frappe.db.set_single_value("Verenigingen Payments Settings", "financial_admin_emails", "")
        frappe.clear_cache(doctype="Verenigingen Payments Settings")
        self.holder = f"holder-2036-{frappe.generate_hash(length=5)}@example.org"
        self.create_test_user(self.holder, roles=["Verenigingen Administrator", "Verenigingen Staff"])
        self.addCleanup(frappe.cache().delete_value, "sepa_no_recipients_logged:sepa_batch_error")
        frappe.cache().delete_value("sepa_no_recipients_logged:sepa_batch_error")


class TestRollbackRecipients(_Base):
    def test_configured_key_recipients_beat_the_role_fallback(self):
        _put_key_row("sepa_batch_error", "Fixed", fixed_recipients="board-2036@example.org")
        recipients = SEPARollbackManager()._get_notification_recipients(RollbackReason.BANK_REJECTION)
        self.assertEqual(recipients, ["board-2036@example.org"])

    def test_role_fallback_reaches_holder_never_administrator(self):
        _put_key_row("sepa_batch_error", "Role-Based")
        recipients = SEPARollbackManager()._get_notification_recipients(RollbackReason.BANK_REJECTION)
        self.assertIn(self.holder, recipients)
        self.assertNotIn(ADMIN_EMAIL, recipients)

    def test_nobody_resolving_leaves_an_error_log_row(self):
        self.expectErrorLog("SEPA notification recipients")  # asserted below by assertErrorLog
        # Mock justified: "nobody" cannot be built from real rows on a site with admin-role holders.
        with patch(
            "verenigingen.verenigingen_payments.api.sepa_batch_notifications.resolve_admin_recipients",
            return_value=[],
        ), self.assertErrorLog("SEPA notification recipients"):
            self.assertEqual(SEPARollbackManager()._get_notification_recipients(RollbackReason.BANK_REJECTION), [])


class TestPaymentRetryEscalationRecipients(_Base):
    def _send(self):
        member = self.create_test_member()
        retry = frappe._dict(
            member=member.name, invoice="SINV-2036", original_amount=10, retry_count=3, last_failure_reason="x"
        )
        email_service = MagicMock()
        # Mock justified: EmailService is the outgoing-mail boundary; the Mollie company lookup is not under test.
        with patch(
            "verenigingen.services.communication.email_service.get_email_service", return_value=email_service
        ), patch.object(pr, "get_mollie_config", return_value=MagicMock()):
            pr.PaymentRetryManager().send_escalation_notification(retry)
        return email_service

    def test_configured_key_recipients_beat_the_role_fallback(self):
        _put_key_row("payment_failure_final", "Fixed", fixed_recipients="treasurer-2036@example.org")
        service = self._send()
        self.assertEqual(service.send_templated_email.call_args.kwargs["recipients"], ["treasurer-2036@example.org"])

    def test_role_fallback_reaches_staff_never_administrator(self):
        _put_key_row("payment_failure_final", "Role-Based")
        service = self._send()
        recipients = service.send_templated_email.call_args.kwargs["recipients"]
        self.assertIn(self.holder, recipients)
        self.assertNotIn(ADMIN_EMAIL, recipients)

    def test_administrator_configured_on_the_key_is_dropped(self):
        """Administrator holds no Staff role row, so only a configured address can reach it here."""
        _put_key_row("payment_failure_final", "Fixed", fixed_recipients=f"{ADMIN_EMAIL}, treasurer-2036@example.org")
        recipients = self._send().send_templated_email.call_args.kwargs["recipients"]
        self.assertEqual(recipients, ["treasurer-2036@example.org"])

    def test_configured_admin_emails_replace_the_staff_fallback(self):
        """Key-first: with no recipients on the key's row, the configured admin emails come BEFORE the
        Staff role fallback (key_first=False would reach the Staff holder and Administrator too)."""
        _put_key_row("payment_failure_final", "Role-Based")  # a row with no recipients of its own
        frappe.db.set_single_value(CONFIG_DOCTYPE, "admin_notification_emails", "cfg-admin-2036@example.org")
        recipients = self._send().send_templated_email.call_args.kwargs["recipients"]
        self.assertEqual(recipients, ["cfg-admin-2036@example.org"])

    def test_nobody_resolving_sends_nothing_and_logs(self):
        self.expectErrorLog("Payment retry escalation recipients")  # asserted below by assertErrorLog
        # Mock justified: "nobody" cannot be built from real rows on a site with staff holders.
        with patch.object(pr, "resolve_admin_recipients", return_value=[]), self.assertErrorLog(
            "Payment retry escalation recipients"
        ):
            service = self._send()
        service.send_templated_email.assert_not_called()


class TestValidationAlertKey(_Base):
    def test_adapter_uses_the_sepa_batch_warning_keys_recipients(self):
        old = frappe.db.get_single_value("Verenigingen Settings", "stuck_schedule_notification_emails") or ""
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", "stuck_schedule_notification_emails", old)
        frappe.db.set_single_value("Verenigingen Settings", "stuck_schedule_notification_emails", "")
        _put_key_row("sepa_batch_warning", "Fixed", fixed_recipients="warn-2036@example.org")
        # Mock justified: frappe.sendmail is the outgoing-mail boundary.
        with patch.object(frappe, "sendmail") as sendmail:
            SEPAXMLAdapter()._send_validation_alert("DDB-2036", BatchValidationSummary(total_invoices=1))
        self.assertEqual(sendmail.call_args.kwargs["recipients"], ["warn-2036@example.org"])

    def test_a_failing_send_leaves_an_error_log_row(self):
        self.expectErrorLog("SEPA validation alert failed")  # asserted below by assertErrorLog
        # Mock justified: forces the send to fail; the logging path is what is under test.
        with patch.object(frappe, "sendmail", side_effect=RuntimeError("smtp down")), self.assertErrorLog(
            "SEPA validation alert failed"
        ):
            SEPAXMLAdapter()._send_validation_alert("DDB-2036", BatchValidationSummary(total_invoices=1))
