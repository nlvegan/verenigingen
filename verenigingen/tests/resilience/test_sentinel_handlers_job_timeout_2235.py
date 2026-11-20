# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
#2235: sentinel-returning and loop-continuing handlers must not swallow an RQ job timeout.

Remainder of the #2112 sweep (same helper, ``reraise_if_job_timeout``; same shape as
``test_hand_written_retry_loops_job_timeout.py``). The real ``rq.timeouts.JobTimeoutException``
is raised from the LOWEST layer each site wraps, so every swallowing layer between it and
the assertion is on the path. Each control proves the same site still turns an ordinary
error into its sentinel, so "propagates" is not satisfied by "never handles anything".

Probe shortcuts, stated: the history-manager tests append a row to the in-memory
``payment_history`` of a real Member instead of driving a real invoice flow, and patch
``_save_with_retry`` / ``update_child_table`` as the injection boundary.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today
from rq.timeouts import JobTimeoutException

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSecureDocumentOperation(EnhancedTestCase):
    """The shared insert/submit wrapper turned ANY exception into success=False."""

    def _run(self, error):
        from verenigingen.utils.secure_operations import secure_document_operation

        todo = frappe.get_doc({"doctype": "ToDo", "description": "job timeout probe 2235"})
        with patch.object(todo, "insert", side_effect=error):
            return secure_document_operation(
                operation="create",
                doc=todo,
                justification="2235 probe",
                required_permissions=["ToDo:create"],
                allow_system_user=True,
            )

    def test_job_timeout_propagates(self):
        timeout = JobTimeoutException("t")
        with self.assertRaises(JobTimeoutException) as ctx:
            self._run(timeout)
        self.assertIs(ctx.exception, timeout)

    def test_control_ordinary_error_is_still_a_failed_result(self):
        self.expectErrorLog()
        result = self._run(RuntimeError("ordinary"))
        self.assertFalse(result.success)


class TestBankTransactionCreatorSentinel(EnhancedTestCase):
    """``_create_bank_transaction`` returned None for any Exception (the batch carries on)."""

    def _create(self, error):
        from frappe.model.document import Document

        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            BankTransactionCreator,
        )

        original = Document.insert

        def insert(doc, *a, **k):
            if doc.doctype == "Bank Transaction":
                raise error
            return original(doc, *a, **k)

        with patch.object(Document, "insert", insert), patch("time.sleep"):
            return BankTransactionCreator()._create_bank_transaction(
                date=today(),
                bank_account="NO-SUCH-BANK-ACCOUNT-2235",
                company="NO-SUCH-COMPANY-2235",
                deposit=10.0,
                withdrawal=0.0,
                currency="EUR",
                reference_number="REF-2235-PROBE",
                description="2235 probe",
            )

    def test_job_timeout_propagates(self):
        timeout = JobTimeoutException("t")
        with self.assertRaises(JobTimeoutException) as ctx:
            self._create(timeout)
        self.assertIs(ctx.exception, timeout)

    def test_control_ordinary_error_still_returns_none(self):
        self.expectErrorLog()
        self.assertIsNone(self._create(RuntimeError("ordinary")))


class _MutationFailingOnType(dict):
    """A real mutation payload whose ``invoiceNumber`` read fails: read inside the
    handler's atomic block (after the developer_mode debug read outside it), so the error is raised by the data, not by a patched method."""

    def __init__(self, error):
        super().__init__({"id": "2235-no-such-mutation", "type": 3})
        self._error = error

    def get(self, key, default=None):
        if key == "invoiceNumber" and self._error is not None:
            error, self._error = self._error, None  # fail once: the failure path reads it again
            raise error
        return super().get(key, default)


class TestEBoekhoudenPaymentEntrySentinel(EnhancedTestCase):
    def _process(self, error):
        from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
            PaymentEntryHandler,
        )

        handler = PaymentEntryHandler("NO-SUCH-COMPANY-2235", "NO-SUCH-CC")
        with patch("time.sleep"):
            return handler.process_payment_mutation(_MutationFailingOnType(error))

    def test_job_timeout_propagates(self):
        timeout = JobTimeoutException("t")
        with self.assertRaises(JobTimeoutException) as ctx:
            self._process(timeout)
        self.assertIs(ctx.exception, timeout)

    def test_control_ordinary_error_still_returns_none(self):
        self.expectErrorLog()
        self.assertIsNone(self._process(RuntimeError("ordinary")))


class TestFinancialHistoryManagerSentinels(EnhancedTestCase):
    """Five ``except Exception`` handlers that returned False."""

    def setUp(self):
        super().setUp()
        from verenigingen.utils.member_financial_history_manager import MemberFinancialHistoryManager

        self.member = self.create_test_member(first_name="Hist2235", last_name="Probe")
        self.manager = MemberFinancialHistoryManager(self.member, "payment_history")

    def _call(self, name, error):
        """Run one handler with ``error`` injected at the boundary below it."""
        m = self.manager
        # add_or_update_entry reloads the doc, which drops unsaved child rows: append per call.
        self.member.set("payment_history", [])
        self.member.append("payment_history", {"invoice": "INV-2235-PROBE"})
        if name == "builder":
            return m.add_or_update_entry("INV-2235-NEW", lambda: (_ for _ in ()).throw(error))
        if name == "update_outer":
            with patch.object(m, "_save_with_retry", side_effect=error):
                return m.add_or_update_entry("INV-2235-NEW", lambda: {"invoice": "INV-2235-NEW"})
        if name == "save":
            with patch.object(self.member, "update_child_table", side_effect=error), patch("time.sleep"):
                return m._save_with_retry()
        if name == "remove":
            with patch.object(m, "_save_with_retry", side_effect=error):
                return m.remove_entry("INV-2235-PROBE")
        if name == "update_field":
            with patch.object(m, "_save_with_retry", side_effect=error):
                return m.update_entry_field("INV-2235-PROBE", {"invoice": "INV-2235-PROBE"})
        raise AssertionError(name)

    SITES = ("builder", "update_outer", "save", "remove", "update_field")

    def test_job_timeout_propagates_from_every_handler(self):
        for name in self.SITES:
            with self.subTest(site=name):
                timeout = JobTimeoutException("t")
                with self.assertRaises(JobTimeoutException) as ctx:
                    self._call(name, timeout)
                self.assertIs(ctx.exception, timeout)

    def test_control_ordinary_error_is_still_false_at_every_handler(self):
        for name in self.SITES:
            with self.subTest(site=name):
                self.expectErrorLog()
                self.assertIs(self._call(name, RuntimeError("ordinary")), False)


class TestDuesInvoiceChain(EnhancedTestCase):
    """The scheduled dues job: timeout injected at ``Sales Invoice.submit``, the lowest layer.

    On develop it is swallowed by, in order: InvoiceGenerator._submit_invoice (OperationResult.fail),
    StatelessService.execute_operation (ServiceError), InvoiceGenerator.generate_invoice
    (OperationResult.fail), InvoiceGenerationOrchestrator.generate (ValidationError), and the
    per-schedule handlers of the sequential run and of the parallel chunk worker (error counted,
    next schedule processed).
    """

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Dues2235", last_name="Probe", birth_date="1975-09-09")
        self.create_test_membership(member_name=self.member.name, membership_type_name="Regular Member")
        self.schedule_name = frappe.get_all(
            "Membership Dues Schedule", filters={"member": self.member.name, "status": "Active"}, limit=1
        )[0].name
        frappe.db.set_value("Membership Dues Schedule", self.schedule_name, "next_invoice_date", add_days(today(), -1))
        self.schedule = frappe.get_doc("Membership Dues Schedule", self.schedule_name)

    def _submit_raises(self, error):
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

        return patch.object(SalesInvoice, "submit", side_effect=error)

    def _generate(self):
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        start = getdate(today())
        return InvoiceGenerator(self.schedule).generate_invoice(
            coverage_start=start, coverage_end=add_days(start, 29), member_doc=self.member
        )

    def test_invoice_generator_propagates_the_timeout(self):
        timeout = JobTimeoutException("t")
        with self._submit_raises(timeout), self.assertRaises(JobTimeoutException) as ctx:
            self._generate()
        self.assertIs(ctx.exception, timeout)

    def test_control_ordinary_submit_error_is_still_a_failed_result(self):
        """Also proves the injection point is on the real path: generation reaches submit."""
        self.expectErrorLog()
        with self._submit_raises(RuntimeError("ordinary submit failure")) as submit:
            result = self._generate()
        self.assertFalse(result.success)
        self.assertEqual(submit.call_count, 1)

    def test_orchestrator_propagates_the_timeout(self):
        timeout = JobTimeoutException("t")
        with self._submit_raises(timeout), self.assertRaises(JobTimeoutException):
            self.schedule.generate_invoice(force=True)

    def test_sequential_run_stops_at_the_timeout(self):
        from verenigingen.services.billing.bulk_invoice_generation_service import (
            BulkGenerationResult,
            get_bulk_invoice_generation_service,
        )

        with self._submit_raises(JobTimeoutException("t")), self.assertRaises(JobTimeoutException):
            get_bulk_invoice_generation_service()._process_sequential(
                [self.schedule_name], getdate(today()), test_mode=False, result=BulkGenerationResult()
            )

    def test_control_sequential_run_counts_an_ordinary_error_and_continues(self):
        from verenigingen.services.billing.bulk_invoice_generation_service import (
            BulkGenerationResult,
            get_bulk_invoice_generation_service,
        )

        self.expectErrorLog()
        with self._submit_raises(RuntimeError("ordinary submit failure")):
            result = get_bulk_invoice_generation_service()._process_sequential(
                [self.schedule_name], getdate(today()), test_mode=False, result=BulkGenerationResult()
            )
        self.assertEqual(result.processed, 1)
        self.assertEqual(result.generated, 0)
        self.assertTrue(result.errors, "the ordinary error must have been recorded")

    def test_chunk_worker_stops_at_the_timeout(self):
        from verenigingen.services.billing.bulk_invoice_generation_service import process_invoice_chunk

        with self._submit_raises(JobTimeoutException("t")), self.assertRaises(JobTimeoutException):
            process_invoice_chunk(
                [self.schedule_name], chunk_id=1, total_chunks=1, cutoff_date=getdate(today())
            )

    def test_control_chunk_worker_counts_an_ordinary_error_and_continues(self):
        from verenigingen.services.billing.bulk_invoice_generation_service import process_invoice_chunk

        self.expectErrorLog()
        with self._submit_raises(RuntimeError("ordinary submit failure")):
            chunk = process_invoice_chunk(
                [self.schedule_name], chunk_id=1, total_chunks=1, cutoff_date=getdate(today())
            )
        self.assertEqual(chunk.processed, 1)
        self.assertEqual(chunk.generated, 0)
        self.assertTrue(chunk.errors)


class TestSecureOperationsFailurePathIsNotRun(EnhancedTestCase):
    """W2: the guard must come BEFORE the failure bookkeeping, not after it."""

    def test_a_timeout_writes_no_error_log_and_no_audit_entry(self):
        from verenigingen.utils.secure_operations import SecureOperationResult, secure_document_operation

        todo = frappe.get_doc({"doctype": "ToDo", "description": "job timeout probe 2235 W2"})
        original = SecureOperationResult.add_audit_entry
        audited = []

        def spy(result, operation, *args, **kwargs):
            audited.append(operation)
            return original(result, operation, *args, **kwargs)

        failed_logs = {"method": ["like", "Secure Operation Failed%"]}
        before = frappe.db.count("Error Log", failed_logs)
        with patch.object(todo, "insert", side_effect=JobTimeoutException("t")), patch.object(
            SecureOperationResult, "add_audit_entry", spy
        ):
            with self.assertRaises(JobTimeoutException):
                secure_document_operation(
                    operation="create",
                    doc=todo,
                    justification="2235 probe",
                    required_permissions=["ToDo:create"],
                    allow_system_user=True,
                )
        self.assertNotIn("operation_failed", audited)
        self.assertEqual(frappe.db.count("Error Log", failed_logs), before)

    def test_control_an_ordinary_error_does_write_both(self):
        """The two assertions above can fail: an ordinary error leaves the audit entry and the row."""
        from verenigingen.utils.secure_operations import SecureOperationResult, secure_document_operation

        todo = frappe.get_doc({"doctype": "ToDo", "description": "job timeout probe 2235 W2 control"})
        original = SecureOperationResult.add_audit_entry
        audited = []

        def spy(result, operation, *args, **kwargs):
            audited.append(operation)
            return original(result, operation, *args, **kwargs)

        failed_logs = {"method": ["like", "Secure Operation Failed%"]}
        before = frappe.db.count("Error Log", failed_logs)
        self.expectErrorLog()
        with patch.object(todo, "insert", side_effect=RuntimeError("ordinary")), patch.object(
            SecureOperationResult, "add_audit_entry", spy
        ):
            secure_document_operation(
                operation="create",
                doc=todo,
                justification="2235 probe",
                required_permissions=["ToDo:create"],
                allow_system_user=True,
            )
        self.assertIn("operation_failed", audited)
        self.assertEqual(frappe.db.count("Error Log", failed_logs), before + 1)


class TestSaveWithRetryAttemptCount(EnhancedTestCase):
    """W3: a timeout is ONE attempt; an ordinary error still gets the configured three."""

    def _save(self, error):
        from verenigingen.utils.member_financial_history_manager import MemberFinancialHistoryManager

        member = self.create_test_member(first_name="Retry2235", last_name="Probe")
        manager = MemberFinancialHistoryManager(member, "payment_history")
        with patch.object(member, "update_child_table", side_effect=error) as update, patch(
            "time.sleep"
        ) as sleep:
            try:
                result, raised = manager._save_with_retry(), None
            except Exception as e:
                result, raised = None, e
        return update, sleep, result, raised

    def test_timeout_is_attempted_once(self):
        timeout = JobTimeoutException("t")
        update, sleep, _, raised = self._save(timeout)
        self.assertIs(raised, timeout)
        self.assertEqual(update.call_count, 1)
        sleep.assert_not_called()

    def test_control_ordinary_error_is_attempted_three_times(self):
        self.expectErrorLog()
        update, sleep, result, raised = self._save(RuntimeError("ordinary"))
        self.assertIsNone(raised)
        self.assertIs(result, False)
        self.assertEqual(update.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


class TestBulkInvoiceServiceBelowTheGenerator(EnhancedTestCase):
    """F1: the handlers around the history update, coverage-gap check and eligibility filter."""

    def setUp(self):
        super().setUp()
        from verenigingen.services.billing.bulk_invoice_generation_service import (
            get_bulk_invoice_generation_service,
        )

        self.svc = get_bulk_invoice_generation_service()
        self.member = self.create_test_member(first_name="BulkB2235", last_name="Probe", birth_date="1975-09-09")
        self.create_test_membership(member_name=self.member.name, membership_type_name="Regular Member")
        self.schedule_name = frappe.get_all(
            "Membership Dues Schedule", filters={"member": self.member.name, "status": "Active"}, limit=1
        )[0].name
        frappe.db.set_value(
            "Membership Dues Schedule", self.schedule_name, "next_invoice_date", add_days(today(), -1)
        )

    # --- per-schedule eligibility filter (get_eligible_schedules) -------------------------
    def _eligible(self, error):
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            MembershipDuesSchedule,
        )

        with patch.object(MembershipDuesSchedule, "should_generate_for_cutoff_period", side_effect=error):
            return self.svc.get_eligible_schedules(cutoff_date=getdate(today()), include_details=True)

    def test_eligibility_filter_stops_at_a_timeout(self):
        timeout = JobTimeoutException("t")
        with self.assertRaises(JobTimeoutException) as ctx:
            self._eligible(timeout)
        self.assertIs(ctx.exception, timeout)

    def test_control_eligibility_filter_records_an_ordinary_error_per_schedule(self):
        self.expectErrorLog()
        details = self._eligible(RuntimeError("ordinary"))
        reasons = [m["reason"] for m in details.filtered_members.get("business_logic", [])]
        self.assertTrue(
            any("Error during validation: ordinary" in r for r in reasons),
            "the ordinary error must be recorded against the schedule, as before",
        )

    # --- per-invoice coverage-gap check ----------------------------------------------------
    @staticmethod
    def _invoice_whose_coverage_read_raises(error):
        class Invoice:
            name = "SI-2235-PROBE"

            @property
            def custom_coverage_end_date(self):
                raise error

        return {"invoice_doc": Invoice(), "invoice": "SI-2235-PROBE", "member_id": "M", "schedule": "S"}

    def test_coverage_gap_check_stops_at_a_timeout(self):
        timeout = JobTimeoutException("t")
        with self.assertRaises(JobTimeoutException) as ctx:
            self.svc._detect_coverage_gaps([self._invoice_whose_coverage_read_raises(timeout)], getdate(today()))
        self.assertIs(ctx.exception, timeout)

    def test_control_coverage_gap_check_skips_an_ordinary_error(self):
        self.expectErrorLog()
        gaps, count = self.svc._detect_coverage_gaps(
            [self._invoice_whose_coverage_read_raises(RuntimeError("ordinary"))], getdate(today())
        )
        self.assertEqual((gaps, count), ([], 0))

    # --- bulk payment-history update (per invoice, per member) ------------------------------
    def _history_update(self, patcher):
        data = [{"member_id": self.member.name, "invoice": "SI-2235-NONE"}]
        with patcher:
            return self.svc.bulk_update_payment_history({self.member.name}, data)

    def test_per_invoice_handler_stops_at_a_timeout(self):
        """Raised by the Sales Invoice read inside the history builder: below the manager's own
        (guarded) handlers, so only the per-invoice handler can swallow it."""
        from verenigingen.verenigingen.doctype.member.member import Member

        timeout = JobTimeoutException("t")
        with self.assertRaises(JobTimeoutException) as ctx:
            self._history_update(patch.object(Member, "_get_invoice_with_retry", side_effect=timeout))
        self.assertIs(ctx.exception, timeout)

    def test_control_per_invoice_handler_logs_an_ordinary_error_and_counts_the_member(self):
        self.expectErrorLog("Failed to add invoice")
        patcher = patch(
            "verenigingen.utils.member_financial_history_manager.get_payment_history_manager",
            side_effect=RuntimeError("ordinary"),
        )
        with self.assertErrorLog("Failed to add invoice SI-2235-NONE"):
            self.assertEqual(self._history_update(patcher), 1)

    def test_per_member_handler_stops_at_a_timeout(self):
        from verenigingen.utils.validation_utilities import DocumentExistenceValidator

        timeout = JobTimeoutException("t")
        patcher = patch.object(DocumentExistenceValidator, "check_document_exists", side_effect=timeout)
        with self.assertRaises(JobTimeoutException) as ctx:
            self._history_update(patcher)
        self.assertIs(ctx.exception, timeout)

    def test_control_per_member_handler_logs_an_ordinary_error_and_skips_the_member(self):
        from verenigingen.utils.validation_utilities import DocumentExistenceValidator

        self.expectErrorLog("Error updating payment history for member")
        patcher = patch.object(
            DocumentExistenceValidator, "check_document_exists", side_effect=RuntimeError("ordinary")
        )
        with self.assertErrorLog(f"Error updating payment history for member {self.member.name}"):
            self.assertEqual(self._history_update(patcher), 0)

    # --- the handler around the whole history update in the sequential run -------------------
    def _sequential_with_history_failure(self, error):
        """Real generation; ``check_document_exists`` fails only when called from the history update."""
        import sys

        from verenigingen.services.billing.bulk_invoice_generation_service import BulkGenerationResult
        from verenigingen.utils.validation_utilities import DocumentExistenceValidator

        original = DocumentExistenceValidator.check_document_exists

        def check(*args, **kwargs):
            frame = sys._getframe(1)
            while frame:
                if frame.f_code.co_name == "bulk_update_payment_history":
                    raise error
                frame = frame.f_back
            return original(*args, **kwargs)

        with patch.object(DocumentExistenceValidator, "check_document_exists", check):
            return self.svc._process_sequential(
                [self.schedule_name], getdate(today()), test_mode=False, result=BulkGenerationResult()
            )

    def test_sequential_run_stops_when_the_history_update_times_out(self):
        timeout = JobTimeoutException("t")
        with self.assertRaises(JobTimeoutException) as ctx:
            self._sequential_with_history_failure(timeout)
        self.assertIs(ctx.exception, timeout)

    def test_control_sequential_run_records_an_ordinary_history_failure(self):
        self.expectErrorLog()
        result = self._sequential_with_history_failure(RuntimeError("ordinary"))
        self.assertEqual(result.generated, 1, "an invoice must really have been generated")
        self.assertEqual(result.payment_history_updates, 0)


class TestPaymentHistorySubscriberHandlers(EnhancedTestCase):
    """Sales Invoice doc_events -> emit_invoice_* -> frappe.enqueue(queue="short") -> these handlers."""

    def setUp(self):
        super().setUp()
        from verenigingen.utils.financial_history_batch_processor import FinancialHistoryBatchProcessor

        FinancialHistoryBatchProcessor._payment_queue.clear()
        self._saved_bulk = getattr(frappe.flags, "bulk_invoice_generation", None)
        frappe.flags.bulk_invoice_generation = False
        member = self.create_test_member(first_name="SubH2235", last_name="Probe", birth_date="1990-01-01")
        self.invoice = self.create_test_sales_invoice(member.name)
        self.invoice.submit()
        member.reload()
        self.member = member
        self.event = {"customer": member.customer, "invoice": self.invoice.name}

    def tearDown(self):
        from verenigingen.utils.financial_history_batch_processor import FinancialHistoryBatchProcessor

        frappe.flags.bulk_invoice_generation = self._saved_bulk
        FinancialHistoryBatchProcessor._payment_queue.clear()
        super().tearDown()

    def _call(self, handler, error):
        """The error comes from the batch processor's queue write, the call the handlers make."""
        from verenigingen.events.subscribers import payment_history_subscriber as phs
        from verenigingen.utils.financial_history_batch_processor import FinancialHistoryBatchProcessor

        if handler == "updated":
            from verenigingen.verenigingen.doctype.member.member import Member

            boundary = patch.object(Member, "add_invoice_to_payment_history", side_effect=error)
        else:
            boundary = patch.object(FinancialHistoryBatchProcessor, "queue_payment_operation", side_effect=error)
        with boundary:
            return getattr(phs, f"handle_invoice_{handler}")("e", self.event)

    HANDLERS = ("submitted", "cancelled", "updated")
    LOGGED = {
        "submitted": "Failed to update payment history for member",
        "cancelled": "Failed to remove cancelled invoice",
        "updated": "Failed to update invoice",
    }

    def test_job_timeout_propagates_from_every_handler(self):
        for handler in self.HANDLERS:
            with self.subTest(handler=handler):
                timeout = JobTimeoutException("t")
                with self.assertRaises(JobTimeoutException) as ctx:
                    self._call(handler, timeout)
                self.assertIs(ctx.exception, timeout)

    def test_control_ordinary_error_is_still_logged_and_swallowed(self):
        for handler in self.HANDLERS:
            with self.subTest(handler=handler):
                message = self.LOGGED[handler]
                self.expectErrorLog(message)
                with self.assertErrorLog(message):
                    self.assertIsNone(self._call(handler, RuntimeError("ordinary")))
