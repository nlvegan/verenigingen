"""A skipped mail is not a sent one: the remaining EmailService callers (#2096, sweep of #2044).

EmailService reports a cooldown, a disabled key or an opt-out as a *successful*
OperationResult carrying ``data["skipped"]``. Each test here drives the caller through the
real EmailService (no stub of the result): a CONTROL run with the key enabled must really
queue a mail and be reported as sent, then the key is disabled and the same call must queue
nothing and must not be reported as sent.

Two kinds of "reported as sent":
  * a log line saying "sent": captured by swapping the caller's logger for ``_Recorder``
    (Mock justified: the logging boundary; bare ``frappe.logger()`` writes nothing readable in CI);
  * a bool returned to the caller.

Probe shortcuts, stated: the termination request is a ``frappe._dict`` carrying the fields
the notification methods read (not a persisted Membership Termination Request), and the
Mollie payment is a ``frappe._dict`` with the fields the notifier reads.
"""

from unittest.mock import patch

import frappe

from verenigingen.api.email_template_manager import send_template_email
from verenigingen.services.approval.termination_approval_service import TerminationApprovalService
from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.notification_state import own_notification_keys, queued_mail_count
from verenigingen.tests.utils.reminder_mail_state import (
    clear_email_cooldowns,
    configure_notification_key,
    ensure_outgoing_email_account,
)
from verenigingen.tests.utils.stock_email_templates import _load_fixture_rows
from verenigingen.verenigingen.doctype.donation.donation import (
    send_donation_confirmation_email,
    send_payment_confirmation_email,
)
from verenigingen.verenigingen_payments.mollie.api.payment_webhook import _notify_member_of_payment_failure
from verenigingen.verenigingen_payments.mollie.api.sync import _notify_subscription_status_change
from verenigingen.verenigingen_payments.utils.payment_alert_service import PaymentAlertService


class _Recorder:
    """Stands in for a logger and keeps what was logged."""

    def __init__(self):
        self.lines = []

    def _add(self, level, msg, *a, **k):
        self.lines.append((level, str(msg)))

    def info(self, msg, *a, **k):
        self._add("info", msg)

    def warning(self, msg, *a, **k):
        self._add("warning", msg)

    def error(self, msg, *a, **k):
        self._add("error", msg)

    def debug(self, msg, *a, **k):
        self._add("debug", msg)

    def sent_lines(self):
        return [m for _lvl, m in self.lines if "sent" in m.lower()]


class TestSkippedMailNotReportedSent(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._accounts_before = set(frappe.db.sql_list("select name from `tabEmail Account`"))

    @classmethod
    def tearDownClass(cls):
        leaked = set(frappe.db.sql_list("select name from `tabEmail Account`")) - cls._accounts_before
        super().tearDownClass()
        if leaked:
            raise AssertionError(f"Email Account(s) leaked by this module: {sorted(leaked)}")

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        ensure_outgoing_email_account(self)
        ensure_notification_registry_rows()
        clear_email_cooldowns()
        self.addCleanup(clear_email_cooldowns)

    # ---- helpers -------------------------------------------------------

    def _ensure_stock_template(self, name):
        if frappe.db.exists("Email Template", name):
            return
        row = {k: v for k, v in _load_fixture_rows()[name].items() if k != "modified"}
        doc = frappe.get_doc(row)
        doc.flags.ignore_links = True
        doc.insert()

    def _sweep_member(self, tag):
        return self.create_test_member(
            first_name=tag,
            last_name="Sweep",
            email=f"{tag.lower()}.{frappe.generate_hash(length=6)}@example.com",
            status="Active",
        )

    def _control_then_skip(self, key, email, run, recorder_target):
        """Run once with the key enabled (must queue + log 'sent'), then disabled (must not)."""
        own_notification_keys(self, key)
        before = queued_mail_count(email)
        with recorder_target() as rec:
            run()
        self.assertEqual(queued_mail_count(email), before + 1, "control: the enabled run must queue a mail")
        self.assertTrue(rec.sent_lines(), "control: a real send is logged as sent")

        configure_notification_key(key, 0, 0)
        with recorder_target() as rec:
            run()
        self.assertEqual(queued_mail_count(email), before + 1, "a skipped run must queue nothing")
        self.assertEqual(rec.sent_lines(), [], "a skipped mail must not be logged as sent")

    class _swap_frappe_logger:
        # Mock justified: the logging boundary (see module docstring).
        def __enter__(self):
            self.rec = _Recorder()
            self._p = patch("frappe.logger", return_value=self.rec)
            self._p.start()
            return self.rec

        def __exit__(self, *exc):
            self._p.stop()

    # ---- termination approval service (log-only) ---------------------------

    def _termination_case(self, notification, key, field, template):
        self._ensure_stock_template(template)
        member = self._sweep_member("Term")
        user_email = member.email
        request = frappe._dict(
            name=f"MTR-SWEEP-{frappe.generate_hash(length=6)}",
            member=member.name,
            secondary_approver=user_email,
            requested_by=user_email,
            approved_by="Administrator",
            termination_type="Policy Violation",
            termination_reason="sweep",
            termination_date=None,
            approver_notes="n",
            company=None,
        )
        service = TerminationApprovalService(request)

        class _Ctx:
            def __enter__(ctx):
                ctx.rec = _Recorder()
                ctx.old = service.logger
                service.logger = ctx.rec
                return ctx.rec

            def __exit__(ctx, *exc):
                service.logger = ctx.old

        self._control_then_skip(key, user_email, getattr(service, notification), _Ctx)

    def test_termination_pending_approval_skip_is_not_logged_sent(self):
        self._termination_case(
            "send_approval_notification",
            "termination_pending_approval",
            "secondary_approver",
            "Termination Approval Required",
        )

    def test_termination_approved_skip_is_not_logged_sent(self):
        self._termination_case(
            "send_approved_notification", "termination_approved", "requested_by", "Termination Execution Notice"
        )

    def test_termination_rejected_skip_is_not_logged_sent(self):
        self._termination_case(
            "send_rejection_notification", "termination_rejected", "requested_by", "termination_rejected"
        )

    # ---- mollie (log-only) --------------------------------------------------

    def test_mollie_subscription_status_skip_is_not_logged_sent(self):
        self._ensure_stock_template("subscription_cancelled")
        member = self._sweep_member("Sub")
        self._control_then_skip(
            "subscription_cancelled",
            member.email,
            lambda: _notify_subscription_status_change(member, "active", "canceled", {"id": "sub_sweep"}),
            self._swap_frappe_logger,
        )

    def test_mollie_payment_failure_skip_is_not_logged_sent(self):
        self._ensure_stock_template("payment_failure_first")
        member = self._sweep_member("Fail")
        payment = frappe._dict(status="failed", amount={"value": "10.00", "currency": "EUR"}, id="tr_sweep")
        self._control_then_skip(
            "payment_failure_first",
            member.email,
            lambda: _notify_member_of_payment_failure(member, payment, 1),
            self._swap_frappe_logger,
        )

    # ---- bool returns -----------------------------------------------------

    def _sweep_donation(self):
        donor = self.create_test_donor(donor_type="Individual", anbi_consent=0)
        donation = self.create_test_donation(donor=donor.name, amount=25.0, paid=1)
        donation.reload()
        if donation.docstatus == 0:
            donation.submit()
        return donor, donation

    def _bool_control_then_skip(self, key, email, call):
        own_notification_keys(self, key)
        before = queued_mail_count(email)
        self.assertIs(call(), True, "control: a real send returns True")
        self.assertEqual(queued_mail_count(email), before + 1)
        configure_notification_key(key, 0, 0)
        self.assertIs(call(), False, "a skip must not be reported as sent")
        self.assertEqual(queued_mail_count(email), before + 1)

    def test_donation_confirmation_returns_false_on_skip(self):
        self._ensure_stock_template("donation_confirmation")
        donor, donation = self._sweep_donation()
        self._bool_control_then_skip(
            "donation_confirmation",
            donor.donor_email,
            lambda: send_donation_confirmation_email(donation.name),
        )

    def test_donation_payment_confirmation_returns_false_on_skip(self):
        self._ensure_stock_template("donation_payment_confirmation")
        donor, donation = self._sweep_donation()
        self._bool_control_then_skip(
            "donation_payment_confirmation",
            donor.donor_email,
            lambda: send_payment_confirmation_email(donation.name),
        )

    def test_send_template_email_returns_false_on_skip(self):
        recipient = f"tmpl.{frappe.generate_hash(length=6)}@example.com"
        self._bool_control_then_skip(
            "member_activated",
            recipient,
            lambda: send_template_email(
                "no_such_template_sweep", [recipient], {}, notification_key="member_activated"
            ),
        )

    def test_payment_alert_email_returns_false_on_skip(self):
        recipient = f"alert.{frappe.generate_hash(length=6)}@example.com"
        service = PaymentAlertService()
        service._recipients_cache = [recipient]
        self._bool_control_then_skip(
            "payment_alert_overpayment",
            recipient,
            lambda: service._send_email_alert("s", "m", "overpayment", "CTX-SWEEP"),
        )
