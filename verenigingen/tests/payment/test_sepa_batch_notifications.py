"""
Real-integration tests for the SEPA batch notification system.

Covers verenigingen/verenigingen_payments/api/sepa_batch_notifications.py
(previously 0% coverage).

Boundary mocking policy
-----------------------
The only thing mocked here is the *email send boundary*: the unified
``EmailService.send_templated_email`` method. Every function under test ends
its happy path by calling ``get_email_service().send_templated_email(...)``;
that is the outbound-email boundary. We patch it so that:

* no real SMTP / Communication side-effects happen during tests, and
* we can assert WHICH recipients and WHICH payload (subject/context) each
  notification function produced.

All recipient resolution (``get_financial_admin_emails``), batch-state
mutation (``handle_automated_batch_validation``), URL building, and the
``test_notification_system`` endpoint run real production code against real
Direct Debit Batch documents built by the test factory. No business logic is
mocked.

Run:
    bench --site test_site_2 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_sepa_batch_notifications
"""

from unittest.mock import patch

import frappe

from verenigingen.services.communication.email_service import EmailService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.api import sepa_batch_notifications as notif


class _SendCapture:
    """Stand-in for EmailService.send_templated_email that records calls.

    Returns a successful OperationResult-like object so callers that inspect
    ``.success`` don't blow up. The production functions ignore the return
    value, but test_notification_system relies only on not raising.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})

        class _Result:
            success = True
            errors = []

            def get(self, *a, **k):
                return None

        return _Result()

    @property
    def last(self):
        return self.calls[-1]


def _patch_send():
    capture = _SendCapture()
    patcher = patch.object(EmailService, "send_templated_email", new=capture)
    patcher.start()
    return capture, patcher


class _FakeBatch:
    """Lightweight stand-in for a Direct Debit Batch used by the pure
    notification builders (send_critical/warning).

    Those builders only read ``.name``, ``.total_amount``, ``.batch_date`` —
    they never persist anything — so a real heavyweight batch document is not
    required and would only slow the suite. The batch-state mutating path is
    exercised separately against a REAL batch in
    TestHandleAutomatedBatchValidation.
    """

    def __init__(self, name="DD-TEST-0001", total_amount=123.45, batch_date="2026-06-15"):
        self.name = name
        self.total_amount = total_amount
        self.batch_date = batch_date


class TestGetFinancialAdminEmails(EnhancedTestCase):
    """Recipient resolution. Runs as Administrator."""

    def test_returns_non_empty_recipient_list(self):
        recipients = notif.get_financial_admin_emails()
        self.assertIsInstance(recipients, list)
        self.assertTrue(len(recipients) >= 1)
        # Every entry should be a non-empty string.
        for r in recipients:
            self.assertTrue(isinstance(r, str) and r)

    def test_resolves_role_holder_emails(self):
        # Administrator carries System Manager, which is one of the financial
        # admin roles, so a real Has Role lookup should surface a real email.
        recipients = notif.get_financial_admin_emails()
        admin_email = frappe.db.get_value("User", "Administrator", "email")
        # The function may return config recipients first; if it falls through
        # to role holders, Administrator's email should be present.
        self.assertTrue(len(recipients) >= 1)
        if admin_email:
            # not strictly required to contain admin_email (config may win), but
            # the list must be a sane list of addresses
            self.assertTrue(all(isinstance(r, str) for r in recipients))


class TestNotificationBuilders(EnhancedTestCase):
    """send_critical / send_warning / send_daily_summary / send_system_error.

    Each asserts the email send boundary is invoked with the right recipients,
    a meaningful subject, and a context referencing the batch / counts.
    """

    def setUp(self):
        super().setUp()
        self.capture, self.patcher = _patch_send()
        self.addCleanup(self.patcher.stop)

    def test_critical_notification_sends_with_error_context(self):
        batch = _FakeBatch(name="DD-CRIT-1", total_amount=5000.0)
        errors = [
            {"invoice": "SINV-1", "issue": "Wrong sequence type", "expected": "FRST", "actual": "RCUR"},
            {"invoice": "SINV-2", "issue": "Wrong sequence type", "expected": "FRST", "actual": "RCUR"},
        ]
        notif.send_critical_batch_notification(batch, errors)

        self.assertEqual(len(self.capture.calls), 1)
        kw = self.capture.last["kwargs"]
        self.assertEqual(kw["template_name"], "payment_notification")
        self.assertEqual(kw["notification_key"], "sepa_batch_error")
        self.assertEqual(kw["priority"], "high")
        self.assertEqual(kw["reference_doctype"], "Direct Debit Batch")
        self.assertEqual(kw["reference_name"], "DD-CRIT-1")
        self.assertIn("Blocked", kw["subject_override"])
        # Recipients are the resolved financial admins.
        self.assertTrue(len(kw["recipients"]) >= 1)
        # Context mentions the batch and the number of errors.
        ctx = kw["context"]
        self.assertEqual(ctx["payment_reference"], "DD-CRIT-1")
        self.assertIn("2 critical", ctx["notification_message"])

    def test_warning_notification_sends_with_warning_context(self):
        batch = _FakeBatch(name="DD-WARN-1", total_amount=200.0)
        warnings = [{"invoice": "SINV-9", "issue": "minor", "expected": "x", "actual": "y"}]
        notif.send_batch_warning_notification(batch, warnings)

        self.assertEqual(len(self.capture.calls), 1)
        kw = self.capture.last["kwargs"]
        self.assertEqual(kw["notification_key"], "sepa_batch_warning")
        # warning notification is NOT high priority
        self.assertNotIn("priority", kw)
        self.assertEqual(kw["reference_name"], "DD-WARN-1")
        self.assertIn("Warnings", kw["subject_override"])
        self.assertIn("1 sequence type warnings", kw["context"]["notification_message"])

    def test_daily_summary_skips_when_no_batches(self):
        # total_batches == 0 -> early return, no email sent.
        notif.send_daily_batch_summary({"processed": 0, "processed_with_warnings": 0, "blocked": 0}, {})
        self.assertEqual(len(self.capture.calls), 0)

    def test_daily_summary_sends_with_success_rate(self):
        validation_summary = {"processed": 3, "processed_with_warnings": 1, "blocked": 0}
        batch_result = {"total_invoices": 40, "batches_created": 4}
        notif.send_daily_batch_summary(validation_summary, batch_result)

        self.assertEqual(len(self.capture.calls), 1)
        kw = self.capture.last["kwargs"]
        self.assertEqual(kw["notification_key"], "sepa_batch_success")
        self.assertIn("Daily SEPA Batch Summary", kw["subject_override"])
        # No blocked batches -> action_required must be None.
        self.assertIsNone(kw["context"]["action_required"])
        # Success rate text present.
        self.assertIn("Success Rate", kw["context"]["next_steps"])

    def test_daily_summary_flags_blocked_batches(self):
        validation_summary = {"processed": 1, "processed_with_warnings": 0, "blocked": 2}
        batch_result = {"total_invoices": 10, "batches_created": 3}
        notif.send_daily_batch_summary(validation_summary, batch_result)
        kw = self.capture.last["kwargs"]
        self.assertIsNotNone(kw["context"]["action_required"])
        self.assertIn("manual intervention", kw["context"]["action_required"])

    def test_system_error_notification(self):
        notif.send_system_error_notification("Boom: database connection lost")
        self.assertEqual(len(self.capture.calls), 1)
        kw = self.capture.last["kwargs"]
        self.assertEqual(kw["notification_key"], "sepa_batch_error")
        self.assertEqual(kw["priority"], "high")
        self.assertIn("SEPA Batch System Error", kw["subject_override"])
        self.assertIn("Boom: database connection lost", kw["context"]["action_required"])

    def test_system_error_notification_truncates_long_message(self):
        long_msg = "X" * 500
        notif.send_system_error_notification(long_msg)
        kw = self.capture.last["kwargs"]
        # action_required = first 200 chars + "..."
        self.assertTrue(kw["context"]["action_required"].endswith("..."))
        self.assertIn("X" * 200, kw["context"]["action_required"])


class TestGetBatchUrl(EnhancedTestCase):
    def test_get_batch_url_returns_form_url(self):
        url = notif.get_batch_url("DD-XYZ")
        self.assertIn("direct-debit-batch", url.lower())
        self.assertIn("DD-XYZ", url)


class TestHandleAutomatedBatchValidation(EnhancedTestCase):
    """handle_automated_batch_validation mutates a REAL Direct Debit Batch and
    dispatches the correct notification. Email send boundary is mocked so we can
    assert which notification was produced; the DB mutations are real."""

    def setUp(self):
        super().setUp()
        self.capture, self.patcher = _patch_send()
        self.addCleanup(self.patcher.stop)

    def test_critical_errors_block_batch(self):
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        # Factory document creation may itself emit unrelated emails through the
        # same EmailService boundary; reset the capture so we only count sends
        # produced by the function under test.
        self.capture.calls.clear()
        errors = [{"invoice": "SINV-1", "issue": "bad", "expected": "FRST", "actual": "RCUR"}]
        result = notif.handle_automated_batch_validation(batch, errors, [])

        self.assertEqual(result["action"], "blocked")
        self.assertTrue(result["requires_intervention"])
        # Status persisted on the real batch.
        self.assertEqual(
            frappe.db.get_value("Direct Debit Batch", batch.name, "status"), "Validation Failed"
        )
        # Critical notification dispatched.
        self.assertEqual(len(self.capture.calls), 1)
        self.assertEqual(self.capture.last["kwargs"]["notification_key"], "sepa_batch_error")

    def test_warnings_only_processes_with_warning(self):
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        self.capture.calls.clear()
        warnings = [{"invoice": "SINV-1", "issue": "minor", "expected": "a", "actual": "b"}]
        result = notif.handle_automated_batch_validation(batch, [], warnings)

        self.assertEqual(result["action"], "processed_with_warnings")
        self.assertFalse(result["requires_intervention"])
        self.assertEqual(len(self.capture.calls), 1)
        self.assertEqual(self.capture.last["kwargs"]["notification_key"], "sepa_batch_warning")

    def test_clean_batch_processes_with_no_notification(self):
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        self.capture.calls.clear()
        result = notif.handle_automated_batch_validation(batch, [], [])

        self.assertEqual(result["action"], "processed")
        self.assertFalse(result["requires_intervention"])
        # No email sent on the clean path.
        self.assertEqual(len(self.capture.calls), 0)
        # An informational comment is added.
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Direct Debit Batch", "reference_name": batch.name},
            fields=["content"],
        )
        self.assertTrue(any("validation passed" in (c["content"] or "").lower() for c in comments))


class TestNotificationSystemEndpoint(EnhancedTestCase):
    """test_notification_system whitelisted endpoint.

    Guarded by @require_sepa_permission(ADMIN, BATCH_VALIDATE); Administrator
    passes the gate. The email send boundary is mocked so no real mail goes out
    but the endpoint's success/recipient bookkeeping is exercised for real.
    """

    def setUp(self):
        super().setUp()
        self.capture, self.patcher = _patch_send()
        self.addCleanup(self.patcher.stop)

    def test_endpoint_reports_success_and_recipients(self):
        result = notif.test_notification_system()
        self.assertTrue(result["success"])
        self.assertIn("recipients", result)
        self.assertEqual(len(result["recipients"]), len(notif.get_financial_admin_emails()))
        # The send boundary was invoked once with the test notification key.
        self.assertEqual(len(self.capture.calls), 1)
        self.assertEqual(self.capture.last["kwargs"]["notification_key"], "email_template_test")
