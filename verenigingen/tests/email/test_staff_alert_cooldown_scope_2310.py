"""Staff alerts sent through EmailService carry a per-incident cooldown scope (#2310), and EmailService
always queues (#2336), and the two Ponto hand-booking keys carry no cooldown (#2248).

A registry key with no ``cooldown_minutes`` is seeded with the 60-minute default, and EmailService applies
it per key AND per recipient. A sender that passes no ``cooldown_scope`` therefore mails each recipient about
the FIRST incident of the hour only: a second, DIFFERENT incident reaches nobody. The ruling (2026-11-10) is a
per-incident ``cooldown_scope`` for every such staff alert (the shape #2177 used for contribution amendments).

Every test drives the REAL sender against the REAL EmailService with the SEEDED cooldown (it asserts the key's
row still holds a non-zero cooldown; ``allow_reminder_sends`` would zero it and hide the defect). Only
``frappe.sendmail`` (the boundary below EmailService) is captured, by the harness. Each test sends incident A,
incident B and A again for one recipient and asserts: A and B were each mailed exactly once (B is the red;
A twice is the control that the cooldown still suppresses the SAME incident, which a bypass/no-cooldown wrong
fix would fail).

Stand-ins (stated, per the probe-shortcut rule): ``MollieSecurityManager`` and ``BalanceMonitor`` are built with
``__new__`` (their constructors open an encryption key / API clients and the alert method reads no instance
state); the termination request, expulsion entry and analytics rule are unsaved documents or plain objects
carrying only what the sender reads.

Run:
    bench --site test_site_6 run-tests --app verenigingen --module verenigingen.tests.email.test_staff_alert_cooldown_scope_2310
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.notification_registry import NOTIFICATION_KEYS
from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.reminder_mail_state import (
    clear_email_cooldowns,
    ensure_outgoing_email_account,
)
from verenigingen.utils.constants import Roles

CONFIG = "Verenigingen Email Configuration"
ROLES = [Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN, Roles.FINANCIAL_MANAGER]
PONTO_KEYS = ("ponto_executed_on_cancelled_row", "ponto_executed_unbookable")


class TestStaffAlertCooldownScope2310(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        ensure_outgoing_email_account(self)
        ensure_notification_registry_rows()
        config = frappe.get_single(CONFIG)
        config.master_email_enabled = 1
        for row in config.notification_types:
            row.enabled = 1
        config.save()
        clear_email_cooldowns()
        self.addCleanup(clear_email_cooldowns)
        self.holder = f"holder-2310-{frappe.generate_hash(length=5)}@example.org"
        self.create_test_user(self.holder, roles=ROLES)

    # -- helpers -------------------------------------------------------------------------------

    def _token(self):
        return f"T2310{frappe.generate_hash(length=8)}"

    def _seeded_cooldown(self, key):
        config = frappe.get_single(CONFIG)
        return next(r.cooldown_minutes for r in config.notification_types if r.notification_key == key)

    def _count(self, token):
        return sum(
            1
            for mail in self.captured_emails
            if self.holder in mail["recipients"] and token in f"{mail['subject']} {mail['message']}"
        )

    def _assert_scoped(self, key, send):
        """``send(token)`` raises one alert for the incident named by ``token``."""
        self.assertGreater(self._seeded_cooldown(key), 0, f"{key} must carry the seeded cooldown here")
        first, second = self._token(), self._token()
        send(first)
        send(second)
        send(first)
        self.assertEqual(self._count(first), 1, "the same incident twice is suppressed (control)")
        self.assertEqual(
            self._count(second), 1, "a different incident within the hour reaches the same recipient"
        )

    # -- the named keys -----------------------------------------------------------------------

    def test_audit_alert(self):
        from verenigingen.utils.security.audit_logging import get_audit_logger

        self._assert_scoped(
            "audit_alert", lambda t: get_audit_logger()._send_security_notification("msg", t, 3)
        )

    def _payment_alert(self, key, call):
        from verenigingen.verenigingen_payments.utils.payment_alert_service import PaymentAlertService

        service = PaymentAlertService()
        service._recipients_cache = [self.holder]  # the hook-resolved list, replaced for the test
        self._assert_scoped(key, lambda t: call(service, t))

    def test_payment_alert_overpayment(self):
        self.expectErrorLog("Overpayment detected")  # the sender logs the overpayment it reports, by design
        self._payment_alert(
            "payment_alert_overpayment",
            lambda s, t: s.send_overpayment_alert("Src", t, "REF", 20.0, 10.0),
        )

    def test_payment_alert_failure(self):
        self._payment_alert(
            "payment_alert_failure",
            lambda s, t: s.send_payment_entry_failure_alert("Src", t, "REF", 10.0, "boom"),
        )

    def test_payment_alert_reconciliation(self):
        self._payment_alert(
            "payment_alert_reconciliation",
            lambda s, t: s.send_reconciliation_alert("Src", t, "issue", "details"),
        )

    def test_sepa_batch_scheduler_alert(self):
        from verenigingen.verenigingen_payments.api.dd_batch_scheduler import send_batch_creation_notification

        def send(token):
            send_batch_creation_notification(
                {
                    "batches_created": 1,
                    "total_invoices": 1,
                    "optimization_report": {
                        "summary": {},
                        "batch_details": [
                            {"name": token, "invoice_count": 1, "total_amount": 1.0, "risk_level": "Low"}
                        ],
                    },
                }
            )

        self._assert_scoped("sepa_batch_scheduler_alert", send)

    def test_termination_pending_approval(self):
        from verenigingen.services.approval.termination_approval_service import TerminationApprovalService

        member = self.create_test_member(
            first_name="Term", last_name=f"T{frappe.generate_hash(length=6)}", birth_date="1990-01-01"
        )
        approver = self.holder

        def send(token):
            request = SimpleNamespace(
                name=token,
                member=member.name,
                secondary_approver=approver,
                termination_type="Expulsion",
                termination_reason="r",
                requested_by=approver,
            )
            TerminationApprovalService(request).send_approval_notification()

        # the mail is addressed to the approver, and carries the request id in its body
        self._assert_scoped("termination_pending_approval", send)

    # -- sweep findings -------------------------------------------------------------------------

    def test_mollie_security_alert(self):
        from verenigingen.verenigingen_payments.core.security.mollie_security_manager import (
            MollieSecurityManager,
        )

        manager = MollieSecurityManager.__new__(MollieSecurityManager)
        self.expectErrorLog("Mollie Security Alert")
        self._assert_scoped(
            "mollie_security_alert", lambda t: manager._create_security_alert(t, "critical", "d")
        )

    def test_balance_monitor_alert(self):
        """The type is FIXED at the only value that reaches the sender (negative balance); the incident
        identity that varies is the currency."""
        from verenigingen.verenigingen_payments.monitoring.balance_monitor import AlertType, BalanceMonitor

        monitor = BalanceMonitor.__new__(BalanceMonitor)

        def send(currency):
            monitor._send_emergency_notification(
                {
                    "type": AlertType.NEGATIVE_BALANCE.value,
                    "currency": currency,
                    "message": f"Negative balance detected: {currency}",
                    "severity": "critical",
                },
                {"type": "emergency_escalation"},
            )

        self._assert_scoped("balance_monitor_alert", send)

    def test_contact_request_escalated(self):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            escalate_contact_request,
        )

        def send(token):
            request = frappe._dict(
                name=token,
                subject=token,
                member_name="M",
                urgency="High",
                request_date="2026-01-01",
                assigned_to=None,
            )
            try:
                escalate_contact_request(request, 3)
            except frappe.DoesNotExistError:
                # the escalation NOTE is written to the real request after the mail went out; this
                # stand-in has no row, so the lookup raises. The mail is what is asserted.
                pass

        self._assert_scoped("contact_request_escalated", send)

    def _expulsion(self, token):
        return frappe.get_doc(
            {
                "doctype": "Expulsion Report Entry",
                "name": token,
                "member_name": token,
                "member_id": "M-1",
                "expulsion_type": "Expulsion",
                "expulsion_date": "2026-01-01",
                "initiated_by": "a",
                "approved_by": "b",
                "reversal_date": "2026-01-02",
                "reversal_reason": "r",
            }
        )

    def test_expulsion_submitted(self):
        self._assert_scoped(
            "expulsion_report_submitted", lambda t: self._expulsion(t).notify_governance_team()
        )

    def test_expulsion_reversed(self):
        self._assert_scoped(
            "expulsion_report_submitted", lambda t: self._expulsion(t).send_reversal_notification()
        )

    def test_analytics_alert(self):
        def send(token):
            rule = frappe.get_doc(
                {
                    "doctype": "Analytics Alert Rule",
                    "name": token,
                    "rule_name": token,
                    "send_email": 1,
                    "alert_recipients": [{"recipient": self.holder}],
                }
            )
            rule.send_notifications(
                {"metric": "m", "value": 1, "current_value": 1, "threshold": 2, "condition": "c"}
            )

        self._assert_scoped("analytics_alert", send)

    def test_expense_approval_request(self):
        from verenigingen.services.volunteer.expense_handlers import notify_expense_approvers

        company = frappe.defaults.get_global_default("company") or frappe.db.get_value(
            "Company", {"is_group": 0}, "name", order_by="name asc"
        )
        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Exp{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
                "expense_approver": self.holder,
            }
        ).insert()
        self._track_test_document("Employee", employee.name, priority=2)

        def send(token):
            # an unsaved Expense Claim: the sender reads only these fields (stand-in, not a flow)
            claim = frappe.get_doc(
                {
                    "doctype": "Expense Claim",
                    "name": token,
                    "employee": employee.name,
                    "expense_approver": self.holder,
                    "company": company,
                    "total_claimed_amount": 5,
                    "posting_date": "2026-01-01",
                }
            )
            notify_expense_approvers(claim)

        self._assert_scoped("expense_approval_request", send)


class TestPontoHandBookingKeysNoCooldown2248(EnhancedTestCase):
    def test_registry_carries_no_cooldown(self):
        for key in PONTO_KEYS:
            self.assertEqual(NOTIFICATION_KEYS[key].get("cooldown_minutes"), 0, key)

    def test_a_row_still_holding_the_seeded_default_moves_to_zero(self):
        from verenigingen.setup.notification_registry_setup import DEFAULT_COOLDOWN_MINUTES

        ensure_notification_registry_rows()
        config = frappe.get_single(CONFIG)
        seeded, custom = PONTO_KEYS
        for row in config.notification_types:
            if row.notification_key == seeded:
                row.cooldown_minutes = DEFAULT_COOLDOWN_MINUTES
            if row.notification_key == custom:
                row.cooldown_minutes = DEFAULT_COOLDOWN_MINUTES + 15
        config.save()
        from verenigingen.patches.v2_2.zero_ponto_hand_booking_cooldown_2248 import execute

        execute()
        cooldowns = {
            r.notification_key: r.cooldown_minutes for r in frappe.get_single(CONFIG).notification_types
        }
        self.assertEqual(cooldowns[seeded], 0)
        self.assertEqual(cooldowns[custom], DEFAULT_COOLDOWN_MINUTES + 15, "an admin's own value stays")


class TestEmailServiceAlwaysQueues2336(EnhancedTestCase):
    CALLER_FILES = (
        "verenigingen_payments/api/dd_batch_scheduler.py",
        "verenigingen_payments/api/dd_batch_api.py",
        "utils/auth_monitoring.py",
        "utils/alert_manager.py",
    )

    def test_a_delayed_false_option_still_queues(self):
        """EmailService ignores ``delayed`` (maintainer ruling, option B). This is the behaviour the
        callers' ``delayed=False`` was silently getting; it must not change."""
        ensure_outgoing_email_account(self)
        self.captured_emails.clear()
        from verenigingen.services.communication.email_service import get_email_service

        result = get_email_service().send_simple_email(
            recipients=["queued-2336@example.org"], subject="s", message="m", delayed=False
        )
        self.assertTrue(result.success, result)
        self.assertIs(self.captured_emails[-1]["kwargs"]["delayed"], True)

    def test_no_caller_passes_delayed_false(self):
        """Every non-test module: a ``delayed=`` keyword on an EmailService method is dead. Raw
        ``frappe.sendmail`` is not EmailService and honours it, so it is not flagged."""
        import ast
        import os

        methods = {"send_simple_email", "send_templated_email", "send_notification_email", "send_email"}
        app = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        roots = [app, os.path.join(os.path.dirname(app), "scripts")]
        offenders = []
        for root in roots:
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    if not name.endswith(".py") or name.startswith("test_") or "/tests" in dirpath:
                        continue
                    path = os.path.join(dirpath, name)
                    try:
                        with open(path) as handle:
                            tree = ast.parse(handle.read())
                    except (SyntaxError, UnicodeDecodeError):
                        continue
                    for node in ast.walk(tree):
                        if (
                            isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr in methods
                            and any(kw.arg == "delayed" for kw in node.keywords)
                        ):
                            offenders.append(f"{os.path.relpath(path, app)}:{node.lineno}")
        self.assertEqual(offenders, [], "EmailService always queues; delayed= is ignored")
