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
from verenigingen.utils.notification_helpers import notify_administrators, resolve_admin_recipients
from verenigingen.verenigingen_payments.api import sepa_batch_notifications as notif
from verenigingen.verenigingen_payments.monitoring.balance_monitor import AlertType, BalanceMonitor
from verenigingen.verenigingen_payments.utils import sepa_alerting_system as sas

PLACEHOLDERS = ("admin@example.com", "finance@company.com", "vereniging.nl")
BM_EMAIL_SERVICE = "verenigingen.verenigingen_payments.monitoring.balance_monitor.get_email_service"
NOTIF_ERROR_LOG_TITLE = "SEPA notification recipients"


def _error_rows_titled(title):
    return frappe.db.count("Error Log", {"method": title})


CONFIG_DOCTYPE = "Verenigingen Email Configuration"
SEPA_KEY = "sepa_batch_error"


def _snapshot_rows():
    """Plain copy of the child rows (hand-rolled; singleton_backup has restored child tables since #2091, #2159)."""
    fields = [f.fieldname for f in frappe.get_meta("Email Notification Type").fields if f.fieldtype != "Section Break"]
    return [{f: r.get(f) for f in fields} for r in frappe.get_single(CONFIG_DOCTYPE).notification_types]


def _restore_rows(rows):
    config = frappe.get_single(CONFIG_DOCTYPE)
    config.set("notification_types", rows)
    config.save()


def _put_key_row(key, policy, **fields):
    """Replace the key's row in Verenigingen Email Configuration with one in the given state."""
    config = frappe.get_single(CONFIG_DOCTYPE)
    config.set("notification_types", [r for r in config.notification_types if r.notification_key != key])
    config.append(
        "notification_types",
        {"notification_key": key, "label": key, "category": "Payment", "recipient_policy": policy, "enabled": 1, **fields},
    )
    config.save()


class TestFinancialAdminResolver(EnhancedTestCase):
    """Real resolver, real rows: only the Payments Settings list and Email Configuration are set up."""

    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        self.addCleanup(frappe.cache().delete_value, f"{notif.NO_RECIPIENTS_CACHE_PREFIX}:{SEPA_KEY}")
        frappe.cache().delete_value(f"{notif.NO_RECIPIENTS_CACHE_PREFIX}:{SEPA_KEY}")
        self.admin_email = "administrator-2002@example.org"
        frappe.db.set_value("User", "Administrator", "email", self.admin_email, update_modified=False)
        frappe.db.set_single_value("Verenigingen Email Configuration", "admin_notification_emails", "")
        self._set_payments_emails("")

    def _set_payments_emails(self, value):
        frappe.db.set_single_value("Verenigingen Payments Settings", "financial_admin_emails", value)
        frappe.clear_cache(doctype="Verenigingen Payments Settings")

    def test_configured_treasurer_is_reached_when_no_admin_emails_are_configured(self):
        """The reviewer's probe (F1): the Admin category's System Manager fallback must not shadow it."""
        _put_key_row(SEPA_KEY, "Role-Based")  # a row with no recipients of its own
        self._set_payments_emails("treasurer-2002@example.org")
        self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), ["treasurer-2002@example.org"])

    def test_the_keys_own_recipients_come_first(self):
        _put_key_row(SEPA_KEY, "Fixed", fixed_recipients="board-2002@example.org")
        self._set_payments_emails("treasurer-2002@example.org")
        self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), ["board-2002@example.org"])

    def test_configured_admin_emails_beat_the_payments_list(self):
        _put_key_row(SEPA_KEY, "Role-Based")
        frappe.db.set_single_value(CONFIG_DOCTYPE, "admin_notification_emails", "cfg-admin-2002@example.org")
        self._set_payments_emails("treasurer-2002@example.org")
        self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), ["cfg-admin-2002@example.org"])

    def test_administrator_is_never_a_recipient(self):
        _put_key_row(SEPA_KEY, "Fixed", fixed_recipients=f"{self.admin_email}, board-2002@example.org")
        self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), ["board-2002@example.org"])

    def test_administrator_only_tier_falls_through_to_the_next_tier(self):
        _put_key_row(SEPA_KEY, "Fixed", fixed_recipients=self.admin_email)
        self._set_payments_emails("treasurer-2002@example.org")
        self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), ["treasurer-2002@example.org"])

    def test_a_key_with_no_row_has_no_recipients_of_its_own(self):
        """An emptied registry (a polluting test, a fresh site) must not turn the key tier into the
        System Manager fallback, which would also make recipients depend on which key was passed."""
        config = frappe.get_single(CONFIG_DOCTYPE)
        config.set("notification_types", [r for r in config.notification_types if r.notification_key != SEPA_KEY])
        config.save()
        self._set_payments_emails("treasurer-2002@example.org")
        self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), ["treasurer-2002@example.org"])
        self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), notif.get_financial_admin_emails())

    def test_duplicates_are_sent_once(self):
        _put_key_row(SEPA_KEY, "Role-Based")
        self._set_payments_emails("dup-2002@example.org, dup-2002@example.org")
        self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), ["dup-2002@example.org"])

    def test_role_fallback_holds_admin_roles_only_enabled_and_not_accounts_manager(self):
        _put_key_row(SEPA_KEY, "Role-Based")
        live = "va-live-2002@example.org"
        gone = "va-disabled-2002@example.org"
        accounts = "accounts-2002@example.org"
        self.create_test_user(live, roles=["Verenigingen Administrator"])
        self.create_test_user(gone, roles=["Verenigingen Administrator"], enabled=0)
        self.create_test_user(accounts, roles=["Accounts Manager"])
        recipients = notif.get_financial_admin_emails(SEPA_KEY)
        self.assertIn(live, recipients)  # control: a real holder is found
        self.assertNotIn(gone, recipients)
        self.assertNotIn(accounts, recipients)
        self.assertNotIn(self.admin_email, recipients)
        self.assertEqual(len(recipients), len(set(recipients)))

    def test_disabled_key_still_resolves_its_recipients(self):
        """EmailService skips a disabled key itself; the resolver must not make that decision (#2002 R2)."""
        _put_key_row(SEPA_KEY, "Fixed", fixed_recipients="board-2002@example.org", enabled=0)
        self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), ["board-2002@example.org"])

    def test_disabled_key_with_nobody_resolved_logs_nothing(self):
        _put_key_row(SEPA_KEY, "Fixed", fixed_recipients="board-2002@example.org", enabled=0)
        before = _error_rows_titled(NOTIF_ERROR_LOG_TITLE)
        # Mock justified: "nobody" cannot be built from real rows on a site that has admin-role holders.
        with patch.object(notif, "resolve_admin_recipients", return_value=[]):
            self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), [])
        self.assertEqual(_error_rows_titled(NOTIF_ERROR_LOG_TITLE), before)

    def test_nobody_resolves_logs_once_a_day_per_key(self):
        _put_key_row(SEPA_KEY, "Fixed", fixed_recipients="board-2002@example.org")
        self.expectErrorLog(NOTIF_ERROR_LOG_TITLE)
        before = _error_rows_titled(NOTIF_ERROR_LOG_TITLE)
        # Mock justified: a test site always has other admin-role holders, so "nobody" cannot
        # be built from real rows; the once-a-day logging around the resolver is what runs.
        with patch.object(notif, "resolve_admin_recipients", return_value=[]):
            with self.assertErrorLog(NOTIF_ERROR_LOG_TITLE):
                self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), [])
            self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), [])  # same day: no 2nd row
        self.assertEqual(_error_rows_titled(NOTIF_ERROR_LOG_TITLE), before + 1)

    def test_lookup_error_returns_nothing_and_logs(self):
        _put_key_row(SEPA_KEY, "Fixed", fixed_recipients="board-2002@example.org")
        self.expectErrorLog(NOTIF_ERROR_LOG_TITLE)
        before = _error_rows_titled(NOTIF_ERROR_LOG_TITLE)
        with patch.object(notif, "get_payments_settings", side_effect=RuntimeError("settings unavailable")):
            with self.assertErrorLog(NOTIF_ERROR_LOG_TITLE):
                self.assertEqual(notif.get_financial_admin_emails(SEPA_KEY), [])
        self.assertEqual(_error_rows_titled(NOTIF_ERROR_LOG_TITLE), before + 1)


class TestNotifyAdministratorsKeyBeatsCategory(EnhancedTestCase):
    """A call passing BOTH a category and a key reaches the KEY's own recipients (#2043).

    This replaces ``test_category_recipients_beat_the_keys_own_recipients``, which pinned the opposite
    order and was written to go red on exactly this change. Evidence the old assertion was wrong, not
    the code: the maintainer ruling on #2043 (2026-11-04): "the key wins ... the category is only a
    fallback, for a key that has no row or whose row resolves to nobody". Control assertion: the
    category's recipient is still what a category-only call returns, and what the key falls back to.
    """

    def test_the_keys_own_recipients_beat_the_category_recipients(self):
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        cat_user, key_user = "cat-user-2002@example.org", "key-user-2002@example.org"
        self.create_test_user(cat_user, roles=["Verenigingen Administrator"])
        self.create_test_user(key_user, roles=["Verenigingen Administrator"])
        frappe.db.set_single_value("Verenigingen Email Configuration", "admin_notification_emails", cat_user)
        _put_key_row("termination_overdue", "Fixed", fixed_recipients=key_user)
        self.assertEqual(
            resolve_admin_recipients(notification_key="termination_overdue", category="Admin"), [key_user]
        )
        self.assertEqual(resolve_admin_recipients(notification_key="termination_overdue"), [key_user])
        self.assertEqual(resolve_admin_recipients(category="Admin"), [cat_user])  # control
        subject = f"order-pin-2002-{frappe.generate_hash(length=6)}"
        notify_administrators(subject=subject, message="m", notification_key="termination_overdue", category="Admin")
        self.assertEqual(frappe.get_all("Notification Log", {"subject": subject}, pluck="for_user"), [key_user])


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


class TestAlertingSystemCooldown(EnhancedTestCase):
    """The key's real per-recipient cooldown (60 min, shared with the batch scheduler) must not
    swallow a second alert or an escalation. Real EmailService and cooldown rows; only the final
    frappe.sendmail and the "is an outgoing account configured" probe are stubbed."""

    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        self.recipient = "ops-2002@example.org"
        _put_key_row(sas.SEPA_ALERT_NOTIFICATION_KEY, "Fixed", fixed_recipients=self.recipient, cooldown_minutes=60)
        self.system = sas.SEPAAlertingSystem()
        self.system.notification_config["webhook_enabled"] = False
        # Mock justified: External Service - the outgoing mail hand-off; cooldown and EmailService run for real.
        sendmail = patch("frappe.sendmail")
        account = patch(
            "verenigingen.services.communication.email_service.EmailService._has_active_email_account",
            return_value=True,
        )
        self.sendmail = sendmail.start()
        account.start()
        self.addCleanup(sendmail.stop)
        self.addCleanup(account.stop)

    def _alert(self, alert_id):
        return sas.SEPAAlert(
            alert_id=alert_id,
            alert_type="t",
            severity=sas.AlertSeverity.CRITICAL,
            title="T",
            message="m",
            details={},
            timestamp=datetime.now(),
        )

    def test_escalation_is_mailed_after_the_initial_alert(self):
        alert = self._alert("A-2002-esc")
        self.system._send_notification(alert)
        self.assertEqual(self.sendmail.call_count, 1)
        self.system._escalate_alert(alert)
        self.assertEqual(self.sendmail.call_count, 2)

    def test_a_second_distinct_alert_is_mailed(self):
        self.system._send_notification(self._alert("A-2002-one"))
        self.system._send_notification(self._alert("A-2002-two"))
        self.assertEqual(self.sendmail.call_count, 2)

    def test_the_same_alert_at_the_same_level_is_still_suppressed(self):
        """Control: the cooldown still works; it is scoped, not removed."""
        alert = self._alert("A-2002-same")
        self.system._send_notification(alert)
        self.system._send_notification(alert)
        self.assertEqual(self.sendmail.call_count, 1)
