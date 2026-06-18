"""
Integration tests for verenigingen.utils.background_jobs.

Target: BackgroundJobManager infra + module-level execution handlers used by the
payment-history / expense-event / donor-auto-creation pipelines.

These are REAL integration tests (Tier 2/3): they exercise the actual Frappe
cache (job-status records), the real document layer (Member + Sales Invoice +
payment history child rows), and the real module-level executors. We assert
concrete side effects -- cache contents, returned job_name strings, payment
history rows, Error Log entries, status transitions -- not mock call counts.

The public ``queue_*`` methods call ``frappe.enqueue`` which, in test mode,
still targets the real RQ queue (Frappe only short-circuits enqueue to an
inline call when is_async=False, which this production code does not pass).
We therefore exercise the synchronously-observable side effects of the queue
path (the job-status cache record + the returned job_name) and call the
``execute_*`` executors directly to cover the heavy work the worker would do.
"""

import time

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.background_jobs import (
    BackgroundJobManager,
    execute_donor_auto_creation,
    execute_expense_event_processing,
    execute_member_payment_history_update,
    execute_member_payment_history_update_sync,
    load_payment_history_batch_optimized,
    queue_donor_auto_creation_handler,
    queue_expense_event_processing_handler,
    refresh_member_financial_history_optimized,
    retry_job_execution,
)


class TestJobStatusTracking(EnhancedTestCase):
    """create_job_status_record / get_job_status / update_job_status / notify."""

    def test_create_and_get_job_status_round_trips_through_cache(self):
        job_name = f"jst_create_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name,
            job_type="member_payment_history_update",
            status="Queued",
            member_name="SOME-MEMBER",
        )

        status = BackgroundJobManager.get_job_status(job_name)
        self.assertEqual(status["status"], "Queued")
        self.assertEqual(status["job_type"], "member_payment_history_update")
        self.assertEqual(status["member_name"], "SOME-MEMBER")
        # create_job_status_record stamps the initiating user.
        self.assertEqual(status["user"], frappe.session.user)
        self.assertIn("created_at", status)

    def test_get_job_status_for_unknown_job_returns_unknown_sentinel(self):
        status = BackgroundJobManager.get_job_status("does-not-exist-xyz")
        self.assertEqual(status["status"], "Unknown")
        self.assertEqual(status["job_name"], "does-not-exist-xyz")

    def test_update_job_status_merges_into_existing_record(self):
        job_name = f"jst_update_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name, job_type="donor_auto_creation", status="Queued"
        )

        BackgroundJobManager.update_job_status(job_name, "Running", result={"phase": "load"}, error=None)
        status = BackgroundJobManager.get_job_status(job_name)
        self.assertEqual(status["status"], "Running")
        self.assertEqual(status["result"], {"phase": "load"})
        # Original fields (job_type) must survive the merge.
        self.assertEqual(status["job_type"], "donor_auto_creation")
        self.assertIn("updated_at", status)

    def test_update_job_status_to_completed_notifies_user(self):
        """Completed/Failed with a user attached triggers a realtime notification.

        We capture the publish_realtime call by patching the bound symbol the
        module already resolved (frappe.publish_realtime). This asserts the
        notification branch (status in [Completed, Failed] and user present)
        actually fires -- replacing the body with `pass` would fail this.
        """
        job_name = f"jst_notify_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name, job_type="expense_event_processing", status="Queued"
        )

        captured = []
        original = frappe.publish_realtime
        frappe.publish_realtime = lambda event, *a, **k: captured.append((event, a, k))
        try:
            BackgroundJobManager.update_job_status(job_name, "Completed", result={"ok": 1})
        finally:
            frappe.publish_realtime = original

        self.assertTrue(captured, "Completed status should publish a realtime event")
        event, _args, kwargs = captured[0]
        self.assertEqual(event, "background_job_update")
        self.assertEqual(kwargs["user"], frappe.session.user)
        payload = _args[0] if _args else kwargs.get("message")
        # publish_realtime(event, message, user=...) -> message is first positional
        self.assertEqual(payload["status"], "Completed")
        self.assertEqual(payload["indicator"], "green")

    def test_update_job_status_to_failed_uses_red_indicator_and_error_text(self):
        job_name = f"jst_fail_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name, job_type="donor_auto_creation", status="Queued"
        )

        captured = []
        original = frappe.publish_realtime
        frappe.publish_realtime = lambda event, *a, **k: captured.append((event, a, k))
        try:
            BackgroundJobManager.update_job_status(job_name, "Failed", error="boom")
        finally:
            frappe.publish_realtime = original

        self.assertTrue(captured)
        _event, args, _kwargs = captured[0]
        payload = args[0]
        self.assertEqual(payload["indicator"], "red")
        self.assertIn("boom", payload["message"])


class TestEnqueueTrackedJob(EnhancedTestCase):
    """The queue_* public API: returns a job_name AND writes a status record."""

    def test_queue_member_payment_history_update_returns_name_and_records_status(self):
        job_name = BackgroundJobManager.queue_member_payment_history_update(
            member_name="MEMBER-X", payment_entry="PE-X"
        )
        self.assertTrue(job_name.startswith("payment_history_update_MEMBER-X_"))

        status = BackgroundJobManager.get_job_status(job_name)
        self.assertEqual(status["status"], "Queued")
        self.assertEqual(status["job_type"], "member_payment_history_update")
        # status_kwargs are threaded into the record (retry-dispatch reads these).
        self.assertEqual(status["member_name"], "MEMBER-X")
        self.assertEqual(status["payment_entry"], "PE-X")

    def test_queue_expense_event_processing_records_reference_fields(self):
        job_name = BackgroundJobManager.queue_expense_event_processing(
            expense_doc_name="EXP-1", event_type="payment_made"
        )
        self.assertTrue(job_name.startswith("expense_event_payment_made_EXP-1_"))

        status = BackgroundJobManager.get_job_status(job_name)
        self.assertEqual(status["job_type"], "expense_event_processing")
        self.assertEqual(status["reference_doctype"], "Expense Claim")
        self.assertEqual(status["reference_name"], "EXP-1")

    def test_queue_donor_auto_creation_records_reference_fields(self):
        job_name = BackgroundJobManager.queue_donor_auto_creation(payment_doc_name="PE-DONOR")
        self.assertTrue(job_name.startswith("donor_auto_creation_PE-DONOR_"))

        status = BackgroundJobManager.get_job_status(job_name)
        self.assertEqual(status["job_type"], "donor_auto_creation")
        self.assertEqual(status["reference_doctype"], "Payment Entry")
        self.assertEqual(status["reference_name"], "PE-DONOR")

    def test_enqueue_with_tracking_creates_record_and_notifies(self):
        captured = []
        original = frappe.publish_realtime
        frappe.publish_realtime = lambda event, *a, **k: captured.append((event, a, k))
        try:
            job_id = BackgroundJobManager.enqueue_with_tracking(
                method="verenigingen.utils.background_jobs.execute_donor_auto_creation",
                job_name="manual_donor",
                user=frappe.session.user,
                payment_doc_name="PE-ANY",
            )
        finally:
            frappe.publish_realtime = original

        self.assertTrue(job_id.startswith("manual_donor_"))
        status = BackgroundJobManager.get_job_status(job_id)
        self.assertEqual(status["status"], "Queued")
        # job_type is the function name extracted from the method path.
        self.assertEqual(status["job_type"], "execute_donor_auto_creation")
        self.assertEqual(status["method"], "verenigingen.utils.background_jobs.execute_donor_auto_creation")
        # An immediate "queued" alert is published to the initiating user.
        self.assertTrue(any(ev == "show_alert" for ev, _a, _k in captured))


class TestRetryLogic(EnhancedTestCase):
    """retry_failed_job backoff + state machine, and retry_job_execution dispatch."""

    def test_retry_failed_job_only_retries_failed_jobs(self):
        job_name = f"retry_notfailed_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name, job_type="donor_auto_creation", status="Completed"
        )
        # Non-Failed jobs are not retried.
        self.assertFalse(BackgroundJobManager.retry_failed_job(job_name))

    def test_retry_failed_job_schedules_and_increments_retry_count(self):
        job_name = f"retry_ok_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name, job_type="donor_auto_creation", status="Failed"
        )

        result = BackgroundJobManager.retry_failed_job(job_name, max_retries=3)
        self.assertTrue(result)

        status = BackgroundJobManager.get_job_status(job_name)
        self.assertEqual(status["status"], "Retrying")
        self.assertEqual(status["retry_count"], 1)
        self.assertIn("retry_scheduled_at", status)

    def test_retry_failed_job_stops_after_max_retries(self):
        job_name = f"retry_exhausted_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name,
            job_type="donor_auto_creation",
            status="Failed",
            retry_count=3,
        )
        # retry_count (3) >= max_retries (3) -> refuse to retry.
        self.assertFalse(BackgroundJobManager.retry_failed_job(job_name, max_retries=3))

    def test_retry_job_execution_dispatches_donor_creation_and_skips_missing_payment(self):
        """retry_job_execution routes by job_type to the right executor.

        For a donor_auto_creation job whose Payment Entry does not exist, the
        executor takes its 'skipped' branch and marks the job Completed. We use
        delay=0 to avoid real sleeping.
        """
        job_name = f"retry_dispatch_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name,
            job_type="donor_auto_creation",
            status="Failed",
            reference_name="PE-NONEXISTENT-XYZ",
        )

        retry_job_execution(job_name=job_name, delay=0)

        status = BackgroundJobManager.get_job_status(job_name)
        self.assertEqual(status["status"], "Completed")
        self.assertEqual(status["result"]["status"], "skipped")

    def test_retry_job_execution_marks_failed_on_unknown_job_type(self):
        job_name = f"retry_unknown_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name, job_type="totally_unknown_type", status="Failed"
        )

        retry_job_execution(job_name=job_name, delay=0)

        status = BackgroundJobManager.get_job_status(job_name)
        self.assertEqual(status["status"], "Failed")
        self.assertIn("Unknown job type", status["error"])


class TestExecuteDonorAutoCreation(EnhancedTestCase):
    def test_skips_when_payment_entry_missing_and_marks_completed(self):
        job_name = f"donor_skip_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name, job_type="donor_auto_creation", status="Queued"
        )

        result = execute_donor_auto_creation(payment_doc_name="PE-MISSING-ABC", job_name=job_name)
        self.assertEqual(result["status"], "skipped")
        self.assertIn("no longer exists", result["reason"])

        # The executor flips the tracked job to Completed on the skip path.
        status = BackgroundJobManager.get_job_status(job_name)
        self.assertEqual(status["status"], "Completed")

    def test_skips_without_job_name_does_not_crash(self):
        result = execute_donor_auto_creation(payment_doc_name="PE-MISSING-NOJOB")
        self.assertEqual(result["status"], "skipped")


class TestExecuteExpenseEventProcessing(EnhancedTestCase):
    def test_unknown_event_type_raises_and_marks_failed(self):
        job_name = f"exp_bad_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name, job_type="expense_event_processing", status="Queued"
        )

        with self.assertRaises(ValueError):
            execute_expense_event_processing(
                expense_doc_name="EXP-X", event_type="not_a_real_event", job_name=job_name
            )

        status = BackgroundJobManager.get_job_status(job_name)
        self.assertEqual(status["status"], "Failed")
        self.assertIn("not_a_real_event", status["error"])


class TestExecuteMemberPaymentHistoryUpdate(EnhancedTestCase):
    def test_missing_member_raises_and_marks_failed(self):
        job_name = f"pmh_missing_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name, job_type="member_payment_history_update", status="Queued"
        )

        with self.assertRaises(frappe.DoesNotExistError):
            execute_member_payment_history_update(member_name="MEMBER-DOES-NOT-EXIST", job_name=job_name)

        status = BackgroundJobManager.get_job_status(job_name)
        self.assertEqual(status["status"], "Failed")

    def test_full_rebuild_path_updates_status_to_completed(self):
        """No payment_entry arg -> full optimized rebuild branch, job Completed."""
        member = self.create_test_member(first_name="Bg", last_name="Rebuild")

        job_name = f"pmh_full_{int(time.time()*1000)}"
        BackgroundJobManager.create_job_status_record(
            job_name=job_name, job_type="member_payment_history_update", status="Queued"
        )

        result = execute_member_payment_history_update(member_name=member.name, job_name=job_name)
        self.assertIn(result.get("status"), {"completed", "cached", "skipped"})

        status = BackgroundJobManager.get_job_status(job_name)
        self.assertEqual(status["status"], "Completed")

    def test_sync_fallback_returns_token_for_real_member(self):
        member = self.create_test_member(first_name="Bg", last_name="Sync")
        token = execute_member_payment_history_update_sync(member.name)
        self.assertTrue(token.startswith(f"sync_fallback_{member.name}_"))

    def test_sync_fallback_returns_none_on_missing_member(self):
        token = execute_member_payment_history_update_sync("MEMBER-NONE-XYZ")
        self.assertIsNone(token)


class TestRefreshFinancialHistoryOptimized(EnhancedTestCase):
    def test_skips_member_without_customer(self):
        """A bare Member doc with no customer short-circuits to 'skipped'."""
        member = frappe.new_doc("Member")
        member.customer = None
        result = refresh_member_financial_history_optimized(member)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "No customer record")

    def test_rebuild_populates_payment_history_from_real_invoice(self):
        """End-to-end: a submitted Sales Invoice for the member's customer is
        loaded into the member's payment_history child table by the optimized
        rebuild. Asserts a concrete row keyed on the invoice name."""
        member = self.create_test_member(first_name="Bg", last_name="Invoiced")
        self.assertTrue(member.customer, "factory member should auto-create a customer")

        invoice = self.create_test_sales_invoice(member.name)
        invoice.submit()

        member.reload()
        result = refresh_member_financial_history_optimized(member)
        self.assertEqual(result["status"], "completed")
        self.assertGreaterEqual(result["entries_processed"], 1)

        member.reload()
        invoice_rows = [r for r in member.payment_history if r.invoice == invoice.name]
        self.assertEqual(len(invoice_rows), 1, "the submitted invoice must appear once")
        row = invoice_rows[0]
        self.assertEqual(float(row.amount), float(invoice.grand_total))
        self.assertEqual(row.transaction_type, "Regular Invoice")

    def test_load_batch_returns_zero_for_customer_without_invoices(self):
        """load_payment_history_batch_optimized over a customer with no invoices
        returns the empty-result sentinel without appending rows."""
        member = self.create_test_member(first_name="Bg", last_name="Empty")
        member.reload()
        before = len(member.payment_history)
        result = load_payment_history_batch_optimized(member)
        self.assertEqual(result["entries_processed"], 0)
        self.assertEqual(len(member.payment_history), before)

    def test_load_batch_marks_membership_invoice_transaction_type(self):
        """An invoice flagged is_membership_invoice is classified as a
        'Membership Invoice' row -- a branch in the per-invoice processing loop."""
        member = self.create_test_member(first_name="Bg", last_name="Memb")
        invoice = self.create_test_sales_invoice(member.name, is_membership_invoice=1)
        invoice.submit()

        member.reload()
        member.payment_history = []
        load_payment_history_batch_optimized(member)

        rows = [r for r in member.payment_history if r.invoice == invoice.name]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].transaction_type, "Membership Invoice")


class TestEventHandlers(EnhancedTestCase):
    """Doc-event style handlers: (doc, method=None). They must never raise."""

    def test_payment_history_handler_ignores_non_customer_party(self):
        """Supplier-party payments are a no-op (early return); no exception."""
        doc = frappe.new_doc("Payment Entry")
        doc.party_type = "Supplier"
        doc.party = "SOME-SUPPLIER"
        doc.name = "PE-SUP"
        # Should return cleanly without touching the batch processor.
        self.assertIsNone(queue_member_payment_history_update_handler_safe(doc))

    def test_expense_handler_maps_on_cancel_to_claim_cancelled(self):
        """The handler maps the doc-event method to an event_type and forwards it
        to the enqueue boundary: on_cancel -> 'claim_cancelled', else
        'payment_made'. We patch only the enqueue method (the RQ/IO boundary) and
        assert the mapped event_type + doc name actually reach it."""
        from unittest.mock import patch

        doc = frappe.new_doc("Expense Claim")
        doc.name = "EXP-HANDLER-1"

        captured = {}

        def _capture(expense_doc_name, event_type):
            captured["doc"] = expense_doc_name
            captured["event_type"] = event_type
            return "job-fake"

        with patch.object(BackgroundJobManager, "queue_expense_event_processing", side_effect=_capture):
            queue_expense_event_processing_handler(doc, method="on_cancel")
        self.assertEqual(captured["doc"], "EXP-HANDLER-1")
        self.assertEqual(captured["event_type"], "claim_cancelled")

        # Any other method maps to the default 'payment_made'.
        captured.clear()
        with patch.object(BackgroundJobManager, "queue_expense_event_processing", side_effect=_capture):
            queue_expense_event_processing_handler(doc, method="on_submit")
        self.assertEqual(captured["event_type"], "payment_made")

    def test_donor_handler_does_not_raise(self):
        doc = frappe.new_doc("Payment Entry")
        doc.name = "PE-DONOR-HANDLER"
        queue_donor_auto_creation_handler(doc)


def queue_member_payment_history_update_handler_safe(doc):
    """Call the real handler; it returns None on the non-Customer early-out."""
    from verenigingen.utils.background_jobs import (
        queue_member_payment_history_update_handler,
    )

    return queue_member_payment_history_update_handler(doc)
