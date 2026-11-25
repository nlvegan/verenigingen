"""
A member is mailed the payment_failure_final notice once their payment's retries are
exhausted, and not on an intermediate failure (maintainer ruling (c) on #3103).

Mock justification: the mail path is real (the harness's sendmail captures are switched off) and
assertions read the real Email Queue. Only the Mollie company lookup (not under test) is stubbed.

Run:
    bench --site test_site_2 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_member_mail_on_retry_exhaustion_3103
"""

from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.payment.test_payment_retry import RetryBase
from verenigingen.tests.utils.reminder_mail_state import clear_email_cooldowns, ensure_outgoing_email_account
from verenigingen.tests.utils.test_config import disable_test_email_mocking, restore_test_email_mocking
from verenigingen.verenigingen_payments.utils import payment_retry as retry

FINAL_NOTICE_MARKER = "Final Notice"


class TestMemberMailOnRetryExhaustion3103(RetryBase):
    def setUp(self):
        super().setUp()
        # EnhancedTestCase patches frappe.sendmail per test, so no Email Queue row could appear;
        # stop its capture (its own cleanup tolerates a second stop), then the process-wide mock too
        self._stop_email_patches()
        was_mocked = disable_test_email_mocking()
        self.addCleanup(restore_test_email_mocking, was_mocked)  # not enable_*: #2060
        ensure_outgoing_email_account(self)
        clear_email_cooldowns()
        frappe.db.set_single_value("Verenigingen Email Configuration", "master_email_enabled", 1)

    def _member_final_notices(self, member):
        """Email Queue rows holding the shipped payment_failure_final subject, sent to the member."""
        rows = frappe.get_all(
            "Email Queue",
            filters={"reference_doctype": "Member", "reference_name": member.name},
            fields=["name", "message"],
        )
        return [
            r
            for r in rows
            if FINAL_NOTICE_MARKER in (r.message or "")
            and member.email in frappe.get_all("Email Queue Recipient", {"parent": r.name}, pluck="recipient")
        ]

    def _fail_payment_3103(self, invoice):
        with patch.object(retry, "get_mollie_config", return_value=MagicMock()):
            return self.manager.schedule_retry(invoice.name, "AM04", "x")

    def _exhausted_setup(self, first_name):
        member = self._make_member_with_customer(first_name)
        invoice = self._make_unpaid_invoice(member)
        self.manager.get_or_create_retry_record(invoice.name)
        rec = frappe.get_doc("SEPA Payment Retry", {"invoice": invoice.name})
        rec.db_set("retry_count", self.manager.retry_config["max_retries"])
        return member, invoice

    def test_exhaustion_queues_the_member_the_final_notice(self):
        member, invoice = self._exhausted_setup("ExhaustMail")
        self.assertEqual(self._member_final_notices(member), [])

        result = self._fail_payment_3103(invoice)

        self.assertFalse(result["scheduled"])
        self.assertEqual(len(self._member_final_notices(member)), 1)

    def test_intermediate_failure_does_not_queue_the_final_notice(self):
        member = self._make_member_with_customer("MidFail")
        invoice = self._make_unpaid_invoice(member)

        result = self._fail_payment_3103(invoice)

        self.assertTrue(result["scheduled"])
        rec = frappe.get_doc("SEPA Payment Retry", {"invoice": invoice.name})
        self.assertLess(rec.retry_count, self.manager.retry_config["max_retries"])
        self.assertEqual(self._member_final_notices(member), [])

    def test_a_rerun_after_exhaustion_sends_no_second_notice(self):
        member, invoice = self._exhausted_setup("ExhaustTwice")

        self._fail_payment_3103(invoice)
        self._fail_payment_3103(invoice)

        self.assertEqual(len(self._member_final_notices(member)), 1)

    def test_mail_failure_does_not_undo_the_escalation(self):
        member, invoice = self._exhausted_setup("ExhaustBoom")
        self.expectErrorLog("Payment failure member notification")  # asserted below by assertErrorLog
        # Mock justified: forces the member send to fail; staff alert is not under test here.
        with patch.object(self.manager, "send_escalation_notification"), patch(
            "verenigingen.services.communication.email_service.get_email_service",
            side_effect=RuntimeError("smtp down"),
        ), self.assertErrorLog("Payment failure member notification"):
            result = self._fail_payment_3103(invoice)

        self.assertFalse(result["scheduled"])
        rec = frappe.get_doc("SEPA Payment Retry", {"invoice": invoice.name})
        self.assertEqual(rec.status, "Escalated")
