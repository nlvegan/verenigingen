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
