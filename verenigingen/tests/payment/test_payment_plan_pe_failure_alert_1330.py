# Copyright (c) 2026, Verenigingen
"""A PERMANENT Payment Entry failure on a payment-plan installment alerts finance staff -- #1330.

After #1288/#1326 a Payment Entry failure rolls the installment back and the
webhook answers 500, so the gateway retries. For a failure that never goes away
(here: the resolved company has no Chart of Accounts, so no default receivable
account) every retry fails the same way and, once the gateway gives up, the
member has paid but the installment stays Pending and nobody is told.

Maintainer ruling (2026-11-12): after N failed attempts for the same gateway
payment id, alert finance staff with an Error Log row plus a mail naming the
payment id and the cause. No daily reconciliation job.

The failure is REAL (an unmocked create_payment_entry() on a chart-less
company); nothing is stubbed. This path has no gateway HTTP client at all: the
Mollie and Pay.nl webhook adapters only translate the payload and call
finalize_payment_plan_installment, which is what is driven here.
"""

import importlib
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.utils import cint

from verenigingen.notification_registry import NOTIFICATION_KEYS
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_sepa_literal_recipients import (
    _put_key_row,
    _restore_rows,
    _snapshot_rows,
)
from verenigingen.tests.support.invoice_payments import member_with_customer
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.tests.support.verenigingen_settings import own_settings_company
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.reminder_mail_state import (
    allow_reminder_sends,
    clear_email_cooldowns,
    ensure_outgoing_email_account,
)
from verenigingen.tests.payment.test_payment_plan_paid_after_pe import (
    _create_pp1288_intent,
    _create_pp1288_plan,
)
from verenigingen.verenigingen_payments.services import payment_plan_finalization as finalization
from verenigingen.verenigingen_payments.services.payment_plan_finalization import (
    PE_FAILURE_ALERT_THRESHOLD,
    _payment_id_line,
    finalize_payment_plan_installment,
)

ALERT_TITLE = "Payment Plan Payment Repeated Failure"
ALERT_KEY = "payment_alert_failure"
ALERT_LOG_TITLE = ALERT_TITLE


def _create_chartless_company_1330():
    """A company with no Chart of Accounts: no default_receivable_account. Committed, because
    the finalizer's failure path does a FULL rollback (an uncommitted fixture would vanish)."""
    frappe.local.flags.ignore_chart_of_accounts = True
    try:
        company = frappe.get_doc(
            {
                "doctype": "Company",
                "company_name": f"1330 Broken Co {frappe.generate_hash(length=6)}",
                "abbr": frappe.generate_hash(length=5).upper(),
                "default_currency": "EUR",
                "country": "Netherlands",
            }
        ).insert()
    finally:
        frappe.local.flags.ignore_chart_of_accounts = False
    frappe.db.commit()
    return company.name


def _create_user_with_role(email, role):
    user = frappe.get_doc(
        {"doctype": "User", "email": email, "first_name": "Pp1330", "send_welcome_email": 0}
    ).insert(ignore_permissions=True)
    user.add_roles(role)
    frappe.db.commit()
    return user.name


def _create_alert_mail_state():
    """The key's row freshly SEEDED from the registry (a seeded site), enabled, cooldown 0 and
    cleared, committed (the finalizer rolls back fully)."""
    frappe.db.delete("Email Notification Type", {"parent": "Verenigingen Email Configuration", "notification_key": ALERT_KEY})
    frappe.clear_document_cache("Verenigingen Email Configuration", "Verenigingen Email Configuration")
    allow_reminder_sends(keys=(ALERT_KEY,))
    frappe.db.commit()


def _cleanup_committed(doctype, name):
    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
    frappe.db.commit()


class TestRepeatedPaymentEntryFailureAlert(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.broken_company = _create_chartless_company_1330()
        cls.addClassCleanup(_cleanup_committed, "Company", cls.broken_company)
        suffix = frappe.generate_hash(length=6)
        cls.finance_email = f"fm-1330-{suffix}@example.org"
        cls.admin_only_email = f"sm-only-1330-{suffix}@example.org"
        for email, role in ((cls.finance_email, "Verenigingen Financial Manager"), (cls.admin_only_email, "System Manager")):
            cls.addClassCleanup(_cleanup_committed, "User", _create_user_with_role(email, role))
        own_settings_company(cls, cls.broken_company)

    def setUp(self):
        super().setUp()
        ensure_outgoing_email_account(self)
        _create_alert_mail_state()
        self.payment_id = f"tr_1330_{frappe.generate_hash(length=8)}"
        self.member = member_with_customer(self, "Pp1330")
        self.plan = _create_pp1288_plan(self, self.member.name)
        self.intent = _create_pp1288_intent(
            self, self.plan.name, self.member.name, payment_id=self.payment_id
        )
        self.addCleanup(self._cleanup_alert_traces)
        self.expectErrorLog("Payment Plan Payment Webhook")
        self.expectErrorLog(ALERT_TITLE)

    def _cleanup_alert_traces(self):
        for row in self._alert_queue_rows():
            frappe.db.delete("Email Queue Recipient", {"parent": row})
            frappe.db.delete("Email Queue", {"name": row})
        clear_email_cooldowns()
        frappe.db.commit()

    def _attempt(self):
        return finalize_payment_plan_installment(
            self.intent.name, payment_reference=self.payment_id, status="paid"
        )

    def _alert_log_rows(self):
        rows = frappe.get_all("Error Log", filters={"method": ALERT_TITLE}, fields=["error"])
        return [r for r in rows if self.payment_id in r.error]

    def _alert_queue_rows(self):
        return frappe.get_all(
            "Email Queue", filters={"message": ["like", f"%{self.payment_id}%"]}, pluck="name"
        )

    def _alert_mail_recipients(self):
        rows = self._alert_queue_rows()
        return frappe.get_all(
            "Email Queue Recipient", filters={"parent": ["in", rows or [""]]}, pluck="recipient"
        )

    def test_threshold_is_a_sensible_count(self):
        self.assertGreaterEqual(cint(PE_FAILURE_ALERT_THRESHOLD), 2)

    def test_no_alert_before_the_threshold_but_every_attempt_still_errors(self):
        for _ in range(PE_FAILURE_ALERT_THRESHOLD - 1):
            self.assertEqual(self._attempt()["status"], "error")
        self.assertEqual(self._alert_queue_rows(), [])
        self.assertEqual(self._alert_log_rows(), [])

    def test_threshold_attempt_alerts_once_with_payment_id_and_cause(self):
        for _ in range(PE_FAILURE_ALERT_THRESHOLD - 1):
            self._attempt()
        result = self._attempt()
        # The gateway must still retry: the finalizer's error result is what both webhooks
        # turn into HTTP 500.
        self.assertEqual(result["status"], "error")
        cause = result["message"]
        self.assertTrue(cause)

        rows = self._alert_queue_rows()
        self.assertEqual(len(rows), 1, "exactly one alert mail")
        body = frappe.db.get_value("Email Queue", rows[0], "message")
        self.assertIn(self.payment_id, body)
        self.assertIn(frappe.utils.escape_html(cause)[:60], body)
        # Maintainer ruling: finance staff. The key's seeded row is Financial Manager, so a holder
        # gets it and an admin-only user (System Manager, no finance role) does not.
        recipients = self._alert_mail_recipients()
        self.assertIn(self.finance_email, recipients)
        self.assertNotIn(self.admin_only_email, recipients)
        self.assertNotIn("Administrator", recipients)

        logged = self._alert_log_rows()
        self.assertEqual(len(logged), 1)
        self.assertIn("Mail delivered: yes", logged[0].error)

        # The member has paid and the installment is still Pending: the very state alerted on.
        self.assertEqual(frappe.get_doc("Payment Plan", self.plan.name).installments[0].status, "Pending")

    def test_attempts_after_the_threshold_send_no_second_alert(self):
        for _ in range(PE_FAILURE_ALERT_THRESHOLD + 2):
            self.assertEqual(self._attempt()["status"], "error")
        self.assertEqual(len(self._alert_queue_rows()), 1)

    def test_counter_is_per_payment_id(self):
        other = _create_pp1288_intent(
            self,
            self.plan.name,
            self.member.name,
            installment_number=2,
            payment_id=f"tr_1330_other_{frappe.generate_hash(length=6)}",
        )
        for _ in range(PE_FAILURE_ALERT_THRESHOLD - 1):
            self._attempt()
        # One failure of ANOTHER payment must not push this one over (or the other one under).
        finalize_payment_plan_installment(other.name, payment_reference=other.payment_id, status="paid")
        self.assertEqual(self._alert_queue_rows(), [])
        self.assertEqual(frappe.get_all("Email Queue", filters={"message": ["like", f"%{other.payment_id}%"]}), [])
        # ... and this payment's own next failure (its Nth) does alert, naming ITS id only.
        self._attempt()
        self.assertEqual(len(self._alert_queue_rows()), 1)
        self.addCleanup(self._cleanup_queue_for, other.payment_id)

    def _cleanup_queue_for(self, payment_id):
        for row in frappe.get_all("Email Queue", filters={"message": ["like", f"%{payment_id}%"]}, pluck="name"):
            frappe.db.delete("Email Queue Recipient", {"parent": row})
            frappe.db.delete("Email Queue", {"name": row})
        frappe.db.commit()

    def _create_no_finance_holder_state(self):
        """No enabled Verenigingen Financial Manager holder and no Payments Settings addresses:
        the alert has nobody to reach. Committed (the finalizer rolls back fully); restored on cleanup."""
        holders = frappe.get_all(
            "Has Role",
            filters={"role": FINANCE_ROLE, "parenttype": "User"},
            pluck="parent",
        )
        enabled = frappe.get_all("User", filters={"name": ["in", holders or [""]], "enabled": 1}, pluck="name")
        for user in enabled:
            frappe.db.set_value("User", user, "enabled", 0)
        frappe.db.commit()
        self.addCleanup(self._cleanup_enable_users, enabled)

    def _create_foreign_error_log_row(self, title, message):
        """A seeded Error Log row, committed (the finalizer rolls back fully)."""
        frappe.log_error(title=title, message=message)
        frappe.db.commit()

    def _cleanup_enable_users(self, users):
        for user in users:
            frappe.db.set_value("User", user, "enabled", 1)
        frappe.db.commit()

    def test_an_undelivered_alert_is_marked_no_then_retried_until_delivered(self):
        self._create_no_finance_holder_state()
        settings_addresses = frappe.db.get_single_value("Verenigingen Payments Settings", "financial_admin_emails")
        self.assertFalse(settings_addresses, "fixture: no Payments Settings address may exist")
        self.expectErrorLog("SEPA notification recipients")
        for _ in range(PE_FAILURE_ALERT_THRESHOLD - 1):
            self._attempt()
        self._attempt()  # attempt N: nobody to tell
        self.assertEqual(self._alert_queue_rows(), [])
        logged = self._alert_log_rows()
        self.assertEqual(len(logged), 1)
        self.assertIn("Mail delivered: no", logged[0].error)
        self.assertNotIn("Mail delivered: yes", logged[0].error)

        # A holder appears: attempt N+1 must retry the delivery (a "no" row is not "delivered").
        self._cleanup_enable_users([self.finance_email])
        self._attempt()
        self.assertEqual(len(self._alert_queue_rows()), 1)
        self.assertEqual(
            sorted("yes" if "Mail delivered: yes" in r.error else "no" for r in self._alert_log_rows()),
            ["no", "yes"],
        )

        # N+2: delivered, so silent.
        self._attempt()
        self.assertEqual(len(self._alert_queue_rows()), 1)
        self.assertEqual(len(self._alert_log_rows()), 2)

    def test_rollback_happens_before_the_alert_commits(self):
        """A failure AFTER a write: the write must be rolled back and the alert must survive.

        The chart-less failure happens before any write, so it cannot tell "rollback, then alert +
        commit" from "alert + commit, then rollback" (which would COMMIT the half-done write).
        """
        installment = self.plan.installments[0]

        def write_then_fail(*args, **kwargs):
            frappe.db.set_value("Payment Plan Installment", installment.name, "status", "Overdue")
            raise frappe.ValidationError("injected failure after a write")

        # Mock justified: fault injection. The finalizer's date helper is called just before
        # process_payment, outside its savepoint; the real PE failure writes nothing the finalizer's
        # own rollback has to undo, so only an injected write-then-fail can pin the ordering.
        with patch.object(finalization, "today", write_then_fail):
            for _ in range(PE_FAILURE_ALERT_THRESHOLD):
                self.assertEqual(self._attempt()["status"], "error")
        self.assertEqual(
            frappe.db.get_value("Payment Plan Installment", installment.name, "status"),
            "Pending",
            "the half-done write must be rolled back",
        )
        self.assertEqual(len(self._alert_queue_rows()), 1)
        self.assertEqual(len(self._alert_log_rows()), 1)

    def test_a_failed_status_delivery_that_throws_never_alerts(self):
        # Mock justified: fault injection. A failed/expired webhook normally cannot throw, so make
        # its status write raise to reach the except branch with status != "paid".
        with patch.object(frappe.db, "set_value", side_effect=frappe.ValidationError("injected")):
            for status in ("failed", "expired"):
                for _ in range(PE_FAILURE_ALERT_THRESHOLD):
                    result = finalize_payment_plan_installment(
                        self.intent.name, payment_reference=self.payment_id, status=status
                    )
                    self.assertEqual(result["status"], "error")
        self.assertEqual(self._alert_queue_rows(), [])
        self.assertEqual(self._alert_log_rows(), [])

    def _other_intent(self, payment_id):
        intent = _create_pp1288_intent(
            self, self.plan.name, self.member.name, installment_number=2, payment_id=payment_id
        )
        self.addCleanup(self._cleanup_queue_for, payment_id)
        return intent

    def test_a_forged_multiline_id_cannot_raise_anothers_count(self):
        forged = f"x\n{_payment_id_line(self.payment_id)}\n"
        other = self._other_intent(forged)
        for _ in range(PE_FAILURE_ALERT_THRESHOLD):
            finalize_payment_plan_installment(other.name, payment_reference=forged, status="paid")
        # The victim has failed ZERO times itself: its first failure must not alert.
        self.assertEqual(self._attempt()["status"], "error")
        self.assertEqual(self._alert_queue_rows(), [])
        self.assertEqual(self._alert_log_rows(), [])

    def test_forged_delivered_lines_in_another_alert_row_cannot_suppress_this_alert(self):
        """A foreign alert row whose TEXT (e.g. a cause echoing attacker input) holds this payment's
        id line followed by "Mail delivered: yes" is not this payment's delivered marker.
        Seeded directly: a forged id never reaches the threshold itself, so the row is the proxy for
        any alert whose cause text carries attacker lines."""
        self._create_foreign_error_log_row(
            ALERT_LOG_TITLE,
            f"foreign alert, cause echoes input\n{_payment_id_line(self.payment_id)}\nMail delivered: yes\nmore",
        )
        for _ in range(PE_FAILURE_ALERT_THRESHOLD):
            self._attempt()
        self.assertEqual(len(self._alert_queue_rows()), 1, "the victim's own alert must still go out")

    def test_attempt_rows_echoing_this_payments_key_line_mid_text_are_not_counted(self):
        """Foreign attempt rows whose cause text holds this payment's key line (not as their tail)
        must not count: the cause is where input can be echoed. Seeded directly as the proxy."""
        for _ in range(PE_FAILURE_ALERT_THRESHOLD):
            self._create_foreign_error_log_row(
                "Payment Plan Payment Webhook",
                f"cause echoing input\n{_payment_id_line(self.payment_id)}\nmore cause text\n"
                f"Gateway payment id: \"other\"\nGateway payment id key: other",
            )
        self.assertEqual(self._attempt()["status"], "error")
        self.assertEqual(self._alert_queue_rows(), [])
        self.assertEqual(self._alert_log_rows(), [])

    def test_transient_failure_then_success_sends_no_alert(self):
        for _ in range(PE_FAILURE_ALERT_THRESHOLD - 1):
            self.assertEqual(self._attempt()["status"], "error")
        # The cause goes away (a usable company), the gateway's next delivery succeeds.
        own_settings_company(self.__class__, get_eur_test_company())
        self.assertEqual(self._attempt()["status"], "success")
        self.assertEqual(self._alert_queue_rows(), [])
        self.assertEqual(self._alert_log_rows(), [])
        pe = frappe.get_all("Payment Entry", filters={"reference_no": self.payment_id}, pluck="name")
        self.assertEqual(len(pe), 1)
        self.track_doc("Payment Entry", pe[0])


PATCH = "verenigingen.patches.v2_2.move_payment_alert_failure_to_financial_manager_1330"
CONFIG = "Verenigingen Email Configuration"
OLD_STOCK_ROLES = "System Manager, Verenigingen Administrator"
FINANCE_ROLE = "Verenigingen Financial Manager"


class TestAlertKeyAudiencePatch(EnhancedTestCase):
    """The registry default reaches fresh installs; the patch moves an untouched stock row (#1330,
    the #2093 rule: only a row still holding EXACTLY the old stock value moves)."""

    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)

    def _roles(self, key=ALERT_KEY):
        frappe.clear_document_cache(CONFIG, CONFIG)
        return next(r for r in frappe.get_single(CONFIG).notification_types if r.notification_key == key).recipient_roles

    def test_registry_names_financial_manager_for_the_key(self):
        self.assertEqual(NOTIFICATION_KEYS[ALERT_KEY].get("recipient_roles"), FINANCE_ROLE)

    def test_patch_moves_an_untouched_stock_row(self):
        _put_key_row(ALERT_KEY, "Role-Based", recipient_roles=OLD_STOCK_ROLES)
        importlib.import_module(PATCH).execute()
        self.assertEqual(self._roles(), FINANCE_ROLE)

    def test_patch_leaves_a_customised_row_alone(self):
        _put_key_row(ALERT_KEY, "Role-Based", recipient_roles="Chapter Board Member")
        importlib.import_module(PATCH).execute()
        self.assertEqual(self._roles(), "Chapter Board Member")

    def test_patch_leaves_other_keys_with_the_old_stock_roles_alone(self):
        _put_key_row(ALERT_KEY, "Role-Based", recipient_roles=OLD_STOCK_ROLES)
        _put_key_row("payment_alert_overpayment", "Role-Based", recipient_roles=OLD_STOCK_ROLES)
        importlib.import_module(PATCH).execute()
        self.assertEqual(self._roles("payment_alert_overpayment"), OLD_STOCK_ROLES)
        self.assertEqual(self._roles(), FINANCE_ROLE)  # control: the target did move

    def test_patch_is_idempotent_and_registered_as_a_fragment(self):
        _put_key_row(ALERT_KEY, "Role-Based", recipient_roles=OLD_STOCK_ROLES)
        patch_module = importlib.import_module(PATCH)
        patch_module.execute()
        patch_module.execute()
        self.assertEqual(self._roles(), FINANCE_ROLE)
        fragments = Path(frappe.get_app_path("verenigingen", "patches.d", "post_model_sync")).glob("*.txt")
        self.assertTrue(any(PATCH in f.read_text() for f in fragments))
