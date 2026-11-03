"""
Literal recipient fallbacks in SEPA staff alerts (#2002).

Three senders used to fall back to a placeholder address when no staff recipient
resolved: ``admin@example.com`` (sepa_batch_notifications), ``finance@company.com``
(balance_monitor) and ``@vereniging.nl`` defaults (sepa_alerting_system). Mail to those
is reported as queued and goes nowhere. Now nothing is sent and an Error Log row says why.

Mock justification: EmailService / get_email_service are the outgoing-mail boundary. The
"nobody resolves" state cannot be built from real rows (a test site always has other
System Managers), so the three recipient SOURCES are blanked; the resolver logic itself
runs for real.

Run:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_sepa_literal_recipients
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.api import sepa_batch_notifications as notif
from verenigingen.verenigingen_payments.monitoring.balance_monitor import AlertType, BalanceMonitor
from verenigingen.verenigingen_payments.utils import sepa_alerting_system as sas

PLACEHOLDERS = ("admin@example.com", "finance@company.com", "vereniging.nl")
BM_EMAIL_SERVICE = "verenigingen.verenigingen_payments.monitoring.balance_monitor.get_email_service"
NOTIF_ERROR_LOG_TITLE = "SEPA notification recipients"


def _error_rows_titled(title):
    return frappe.db.count("Error Log", {"method": title})


def _no_source_resolves():
    """Blank all three recipient sources of get_financial_admin_emails."""
    return (
        patch.object(notif, "_get_email_config_service", return_value=None),
        patch.object(notif, "get_payments_settings", return_value=frappe._dict(financial_admin_emails="")),
        patch.object(notif, "_financial_role_recipients", return_value=[], create=True),
    )


class _NoSources:
    def __enter__(self):
        self.patchers = _no_source_resolves()
        for p in self.patchers:
            p.start()

    def __exit__(self, *exc):
        for p in self.patchers:
            p.stop()


class TestFinancialAdminResolver(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.admin_email = "administrator-2002@example.org"
        frappe.db.set_value("User", "Administrator", "email", self.admin_email, update_modified=False)

    def test_nobody_resolves_returns_nothing_and_logs(self):
        before = _error_rows_titled(NOTIF_ERROR_LOG_TITLE)
        with _NoSources():
            recipients = notif.get_financial_admin_emails()
        self.assertEqual(recipients, [])
        self.assertEqual(_error_rows_titled(NOTIF_ERROR_LOG_TITLE), before + 1)

    def test_lookup_error_returns_nothing_and_logs(self):
        before = _error_rows_titled(NOTIF_ERROR_LOG_TITLE)
        with patch.object(notif, "_get_email_config_service", return_value=None), patch.object(
            notif, "get_payments_settings", side_effect=RuntimeError("settings unavailable")
        ):
            recipients = notif.get_financial_admin_emails()
        self.assertEqual(recipients, [])
        self.assertEqual(_error_rows_titled(NOTIF_ERROR_LOG_TITLE), before + 1)

    def test_administrator_is_never_a_recipient_of_configured_list(self):
        service = MagicMock()
        service.get_category_recipients.return_value = [self.admin_email, "treasurer-2002@example.org"]
        with patch.object(notif, "_get_email_config_service", return_value=service):
            recipients = notif.get_financial_admin_emails()
        self.assertEqual(recipients, ["treasurer-2002@example.org"])

    def test_administrator_only_configured_list_falls_through_not_to_a_placeholder(self):
        service = MagicMock()
        service.get_category_recipients.return_value = [self.admin_email]
        with patch.object(notif, "_get_email_config_service", return_value=service), patch.object(
            notif, "get_payments_settings", return_value=frappe._dict(financial_admin_emails="")
        ), patch.object(notif, "_financial_role_recipients", return_value=[], create=True):
            self.assertEqual(notif.get_financial_admin_emails(), [])

    def test_role_holders_exclude_administrator_but_include_real_staff(self):
        email = "fin-admin-2002@example.org"
        self.create_test_user(email, roles=["Accounts Manager"])
        with patch.object(notif, "_get_email_config_service", return_value=None), patch.object(
            notif, "get_payments_settings", return_value=frappe._dict(financial_admin_emails="")
        ):
            recipients = notif.get_financial_admin_emails()
        self.assertIn(email, recipients)  # control: a real holder is still found
        self.assertNotIn(self.admin_email, recipients)
        for placeholder in PLACEHOLDERS:
            self.assertFalse(any(placeholder in r for r in recipients))


class TestBatchSendersSkipWithoutRecipients(EnhancedTestCase):
    def _run_all(self):
        batch = frappe._dict(name="DD-2002", total_amount=10.0, batch_date="2026-01-01")
        issue = [{"invoice": "SINV-1", "issue": "x"}]
        notif.send_critical_batch_notification(batch, issue)
        notif.send_batch_warning_notification(batch, issue)
        notif.send_daily_batch_summary({"processed": 1}, {"total_invoices": 1})
        notif.send_system_error_notification("boom")
        return notif.test_notification_system()

    def test_no_sender_mails_nobody(self):
        sender = MagicMock()
        with patch("verenigingen.services.communication.email_service.EmailService.send_templated_email", sender):
            with patch.object(notif, "get_financial_admin_emails", return_value=[]):
                result = self._run_all()
        self.assertEqual(sender.call_count, 0)
        self.assertFalse(result["success"])

    def test_control_senders_do_mail_a_resolved_recipient(self):
        sender = MagicMock()
        with patch("verenigingen.services.communication.email_service.EmailService.send_templated_email", sender):
            with patch.object(notif, "get_financial_admin_emails", return_value=["fin-2002@example.org"]):
                result = self._run_all()
        self.assertEqual(sender.call_count, 5)
        for call in sender.call_args_list:
            self.assertEqual(call.kwargs["recipients"], ["fin-2002@example.org"])
        self.assertTrue(result["success"])


class TestBalanceMonitorEmergency(EnhancedTestCase):
    def _fire(self, recipients):
        # BalanceMonitor.__init__ builds Mollie API clients; this path needs none of them.
        monitor = BalanceMonitor.__new__(BalanceMonitor)
        email_service = MagicMock()
        alert = {"type": AlertType.NEGATIVE_BALANCE.value, "severity": "critical", "message": "negative"}
        with patch(BM_EMAIL_SERVICE, return_value=email_service), patch.object(
            notif, "get_financial_admin_emails", return_value=recipients
        ), patch.object(frappe, "publish_realtime") as realtime:
            monitor._take_automated_actions(frappe._dict(id="bal_1", currency="EUR"), [alert])
        return email_service, realtime

    def test_nobody_resolves_no_mail_but_realtime_still_published(self):
        email_service, realtime = self._fire([])
        self.assertEqual(email_service.send_simple_email.call_count, 0)
        self.assertEqual(realtime.call_count, 1)

    def test_resolved_recipients_are_used_verbatim(self):
        email_service, _realtime = self._fire(["fin-2002@example.org"])
        email_service.send_simple_email.assert_called_once()
        kwargs = email_service.send_simple_email.call_args.kwargs
        self.assertEqual(kwargs["recipients"], ["fin-2002@example.org"])
        self.assertEqual(kwargs["notification_key"], "balance_monitor_alert")


class TestAlertingSystemRecipients(EnhancedTestCase):
    def _alert(self, severity):
        return sas.SEPAAlert(
            alert_id="A-2002",
            alert_type="t",
            severity=severity,
            title="T",
            message="m",
            details={},
            timestamp=datetime.now(),
        )

    def setUp(self):
        super().setUp()
        self.system = sas.SEPAAlertingSystem()

    def test_config_carries_no_literal_addresses(self):
        config = self.system.notification_config
        self.assertNotIn("default_recipients", config)
        self.assertNotIn("escalation_recipients", config)
        self.assertNotIn("@", repr(config))

    def test_critical_alert_goes_to_resolved_staff_only(self):
        with patch.object(notif, "get_financial_admin_emails", return_value=["fin-2002@example.org"]):
            for severity in (sas.AlertSeverity.WARNING, sas.AlertSeverity.CRITICAL):
                self.assertEqual(
                    self.system._get_notification_recipients(self._alert(severity)), ["fin-2002@example.org"]
                )

    def test_nobody_resolves_means_no_recipients(self):
        with patch.object(notif, "get_financial_admin_emails", return_value=[]):
            self.assertEqual(self.system._get_notification_recipients(self._alert(sas.AlertSeverity.CRITICAL)), [])

    def test_escalation_mails_resolved_staff_and_nobody_else(self):
        service = MagicMock()
        with patch.object(sas, "get_email_service", return_value=service), patch.object(
            notif, "get_financial_admin_emails", return_value=["fin-2002@example.org"]
        ):
            self.system._escalate_alert(self._alert(sas.AlertSeverity.CRITICAL))
        recipients = [c.kwargs["recipients"] for c in service.send_simple_email.call_args_list]
        self.assertEqual(recipients, [["fin-2002@example.org"]])

    def test_escalation_with_nobody_sends_nothing(self):
        service = MagicMock()
        with patch.object(sas, "get_email_service", return_value=service), patch.object(
            notif, "get_financial_admin_emails", return_value=[]
        ):
            self.system._escalate_alert(self._alert(sas.AlertSeverity.CRITICAL))
        self.assertEqual(service.send_simple_email.call_count, 0)
