"""
PaymentAlertService mails reach staff without any app defining the ``accounts_managers_email`` hook (#2555).

No app defines that hook, so the service used to resolve nobody and every ING Checkout / Mollie / Ponto
alert it carries died as an Error Log row. Recipients now come from the key-first staff resolver
(Verenigingen Email Configuration row, then Verenigingen Financial Manager holders); the hook stays
as an optional override.

Mock justification: ``get_email_service`` is the outgoing-mail boundary; recipient resolution runs against
real Verenigingen Email Configuration rows and real Users. ``frappe.get_hooks`` is patched only to
stand in for an app that defines the optional override.

Run:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_payment_alert_recipients_2555
"""

from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_sepa_literal_recipients import (
    _put_key_row,
    _restore_rows,
    _snapshot_rows,
)
from verenigingen.utils.constants import Roles
from verenigingen.verenigingen_payments.utils.payment_alert_service import PaymentAlertService

CONFIG = "Verenigingen Email Configuration"
KEYS = ("payment_alert_failure", "payment_alert_overpayment", "payment_alert_reconciliation")


class TestPaymentAlertRecipients2555(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        suffix = frappe.generate_hash(length=5)
        self.finance = f"fm-2555-{suffix}@example.org"
        self.create_test_user(self.finance, roles=[Roles.FINANCIAL_MANAGER])
        self.finance_gone = f"fm-gone-2555-{suffix}@example.org"
        self.create_test_user(self.finance_gone, roles=[Roles.FINANCIAL_MANAGER], enabled=0)
        old_email = frappe.db.get_value("User", "Administrator", "email")
        self.addCleanup(frappe.db.set_value, "User", "Administrator", "email", old_email, update_modified=False)
        self.admin_email = f"administrator-2555-{suffix}@example.org"
        frappe.db.set_value("User", "Administrator", "email", self.admin_email, update_modified=False)
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", "")
        frappe.db.set_single_value("Verenigingen Payments Settings", "financial_admin_emails", "")
        frappe.clear_cache(doctype="Verenigingen Payments Settings")
        self.assertFalse(frappe.get_hooks("accounts_managers_email"), "premise: no app defines the hook")

    def _send_alert_2555(self, alert_type, hook=None):
        """Drive the real service through ``_send_email_alert``; return the recorded send calls."""
        hooks = {"accounts_managers_email": hook} if hook else {}
        real = frappe.get_hooks
        # Mock justified: stands in for an app defining the optional hook override; all other hooks are real.
        fake_hooks = lambda name=None, *a, **kw: hooks[name] if name in hooks else real(name, *a, **kw)  # noqa: E731
        # Mock justified: EmailService is the outgoing-mail boundary; recipient resolution runs for real.
        with patch(
            "verenigingen.services.communication.email_service.get_email_service"
        ) as get_service, patch("frappe.get_hooks", side_effect=fake_hooks):
            get_service.return_value = MagicMock()
            get_service.return_value.send_simple_email.return_value = MagicMock(success=True, skip_reason=None)
            sent = PaymentAlertService()._send_email_alert(
                subject="s", message="m", alert_type=alert_type, context_id="CTX-2555"
            )
        return sent, get_service.return_value.send_simple_email.call_args_list

    def _drop_key_rows(self):
        config = frappe.get_single(CONFIG)
        config.set("notification_types", [r for r in config.notification_types if r.notification_key not in KEYS])
        config.save()

    def test_each_alert_reaches_staff_without_the_hook(self):
        """Rows set explicitly (not seed-dependent): failure -> Financial Managers (#1330 ruling);
        the other two on the stock admin pair, as seeded."""
        admin_holder = f"va-2555-{frappe.generate_hash(length=5)}@example.org"
        self.create_test_user(admin_holder, roles=[Roles.VERENIGINGEN_ADMIN])
        _put_key_row(KEYS[0], "Role-Based", recipient_roles=Roles.FINANCIAL_MANAGER)
        for key in KEYS[1:]:
            _put_key_row(key, "Role-Based", recipient_roles=f"{Roles.SYSTEM_MANAGER}, {Roles.VERENIGINGEN_ADMIN}")
        for alert_type, key, expected in (
            ("payment_entry_failure", KEYS[0], self.finance),
            ("overpayment", KEYS[1], admin_holder),
            ("reconciliation", KEYS[2], admin_holder),
        ):
            with self.subTest(alert_type=alert_type):
                sent, calls = self._send_alert_2555(alert_type)
                self.assertTrue(sent)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0].kwargs["notification_key"], key)
                recipients = calls[0].kwargs["recipients"]
                self.assertIn(expected, recipients)
                self.assertNotIn(self.finance_gone, recipients)  # a disabled holder is not reached
                self.assertNotIn(self.admin_email, recipients)
                self.assertNotIn("Administrator", recipients)
        _, calls = self._send_alert_2555("payment_entry_failure")
        self.assertNotIn(admin_holder, calls[0].kwargs["recipients"])  # failure is finance only

    def test_with_no_key_row_each_alert_reaches_enabled_financial_managers(self):
        self._drop_key_rows()
        for alert_type in ("payment_entry_failure", "overpayment", "reconciliation"):
            with self.subTest(alert_type=alert_type):
                sent, calls = self._send_alert_2555(alert_type)
                self.assertTrue(sent)
                recipients = calls[0].kwargs["recipients"]
                self.assertIn(self.finance, recipients)
                self.assertNotIn(self.finance_gone, recipients)
                self.assertNotIn(self.admin_email, recipients)

    def test_configured_key_row_wins_over_the_role_fallback(self):
        _put_key_row(KEYS[0], "Fixed", fixed_recipients="board-2555@example.org")
        _, calls = self._send_alert_2555("payment_entry_failure")
        self.assertEqual(calls[0].kwargs["recipients"], ["board-2555@example.org"])

    def test_the_hook_still_overrides_when_an_app_defines_it(self):
        sent, calls = self._send_alert_2555("payment_entry_failure", hook=["hook-2555@example.org"])
        self.assertTrue(sent)
        self.assertEqual(calls[0].kwargs["recipients"], ["hook-2555@example.org"])  # not the Financial Manager

    def test_nobody_resolvable_sends_nothing_and_logs(self):
        role = frappe.get_doc({"doctype": "Role", "role_name": f"No Holder 2555 {frappe.generate_hash(length=5)}"})
        role.insert()
        for key in KEYS:
            _put_key_row(key, "Role-Based", recipient_roles=role.name)  # a row that resolves nobody
        self.expectErrorLog("No Alert Recipients Configured")
        with patch(
            "verenigingen.verenigingen_payments.api.sepa_batch_notifications.get_financial_admin_emails",
            return_value=[],
        ):  # Mock justified: forces the resolver's "nobody" answer, which depends on site users.
            sent, calls = self._send_alert_2555("reconciliation")
        self.assertFalse(sent)
        self.assertEqual(calls, [])
        self.assertTrue(
            frappe.get_all("Error Log", filters={"error": ["like", "%CTX-2555%no recipient is configured%"]}),
            "the dropped alert must leave an Error Log row",
        )
