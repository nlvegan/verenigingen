"""#3074: a Rolled Back Direct Debit Batch is REFUSED by every re-process path.

Maintainer ruling (2026-11-20): re-collection happens only through a NEW batch. After
#3021 the rolled-back rows are Pending, so without a guard "Mark as Processed" would book
NEW Payment Entries for them from the OLD batch (and the rollback already cancelled the
mandate usage rows, so FRST/RCUR sequencing would skew).

Probe shortcut, stated: the Rolled Back state is written with ``frappe.db.set_value`` on
the batch status, exactly the call ``SEPARollbackManager._rollback_batch_status`` makes;
the rows stay Pending (the post-#3021 state, and what a freshly batched row has). The
rollback manager's own flow is covered in tests/payment/test_sepa_rollback_manager.py.
"""

import frappe

from verenigingen.tests.sepa.test_batch_processing_service_happy_path import _SubmittedBatchBase
from verenigingen.verenigingen_payments.doctype.direct_debit_batch import direct_debit_batch as ddb_module
from verenigingen.verenigingen_payments.services.sepa_batch_processor import SEPABatchProcessor

REFUSAL = "rolled back"


class TestRolledBackBatchRefused3074(_SubmittedBatchBase):
    def setUp(self):
        super().setUp()
        self.batch = self._submitted_batch(invoice_count=2)
        self.row_names = [r.name for r in self.batch.invoices]
        frappe.db.set_value(
            "Direct Debit Batch", self.batch.name, "status", "Rolled Back", update_modified=False
        )
        self.batch.reload()
        self.pe_before = frappe.db.count("Payment Entry")

    def _assert_untouched(self):
        """Nothing was booked, no row moved, the batch is still Rolled Back."""
        self.assertEqual(frappe.db.count("Payment Entry"), self.pe_before)
        self.assertEqual(frappe.db.get_value("Direct Debit Batch", self.batch.name, "status"), "Rolled Back")
        for name in self.row_names:
            self.assertEqual(frappe.db.get_value("Direct Debit Batch Invoice", name, "status"), "Pending")

    def test_the_service_refuses_mark_as_processed(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service.mark_batch_invoices_as_paid(self.batch)
        self.assertIn(REFUSAL, str(ctx.exception))
        self._assert_untouched()

    def test_a_stale_in_memory_doc_is_still_refused(self):
        """The writers of Rolled Back use db.set_value, so a doc loaded earlier says Submitted."""
        stale = frappe.get_doc("Direct Debit Batch", self.batch.name)
        stale.status = "Submitted"
        with self.assertRaises(frappe.ValidationError):
            self.service.mark_batch_invoices_as_paid(stale)
        self._assert_untouched()

    def test_the_whitelisted_mark_invoices_as_paid_api_refuses(self):
        self.expectErrorLog("SEPA Direct Debit Payment Error")
        with self.assertRaises(frappe.ValidationError) as ctx:
            ddb_module.mark_invoices_as_paid(self.batch.name)
        self.assertIn(REFUSAL, str(ctx.exception))
        self._assert_untouched()

    def test_the_doc_method_refuses(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.batch.mark_invoices_as_paid()
        self.assertIn(REFUSAL, str(ctx.exception))
        self._assert_untouched()

    def test_process_batch_does_not_reopen_it_as_submitted(self):
        self.expectErrorLog("SEPA Direct Debit Batch Error")
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.batch.process_batch()
        self.assertIn(REFUSAL, str(ctx.exception))
        self._assert_untouched()

    def test_the_whitelisted_process_batch_api_refuses(self):
        self.expectErrorLog("SEPA Direct Debit Batch Processing Error")
        with self.assertRaises(frappe.ValidationError) as ctx:
            ddb_module.process_batch(self.batch.name)
        self.assertIn(REFUSAL, str(ctx.exception))
        self._assert_untouched()

    def test_process_batch_submission_refuses(self):
        self.expectErrorLog("SEPA Direct Debit Batch Error")
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service.process_batch_submission(self.batch)
        self.assertIn(REFUSAL, str(ctx.exception))
        self._assert_untouched()

    def test_a_return_file_does_not_overwrite_the_rolled_back_status(self):
        # The path never exists: the refusal must come before the file is read.
        self.expectErrorLog("SEPA Return Processing Error")
        with self.assertRaises(frappe.ValidationError) as ctx:
            SEPABatchProcessor().process_batch_returns(self.batch.name, "/nonexistent/return.xml")
        self.assertIn(REFUSAL, str(ctx.exception))
        self._assert_untouched()

    def test_bank_reconciliation_by_batch_name_refuses(self):
        from verenigingen.verenigingen_payments.api import sepa_reconciliation

        with self.assertRaises(frappe.ValidationError) as ctx:
            sepa_reconciliation.process_sepa_transaction_conservative("NO-SUCH-BANK-TXN", self.batch.name)
        self.assertIn(REFUSAL, str(ctx.exception))
        self._assert_untouched()

    def test_a_status_edit_cannot_move_it_out_of_rolled_back(self):
        """frappe.client.set_value-style write: status is allow_on_submit, so a save would pass."""
        self.batch.status = "Submitted"
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.batch.save()
        self.assertIn(REFUSAL, str(ctx.exception))
        self._assert_untouched()

    def test_control_a_submitted_batch_is_still_marked_processed(self):
        """The guard keys on Rolled Back only: the same batch, status Submitted, still collects."""
        frappe.db.set_value("Direct Debit Batch", self.batch.name, "status", "Submitted", update_modified=False)
        self.batch.reload()
        self.assertEqual(self.service.mark_batch_invoices_as_paid(self.batch), len(self.row_names))
        self.assertEqual(frappe.db.count("Payment Entry"), self.pe_before + len(self.row_names))
        self.assertEqual(frappe.db.get_value("Direct Debit Batch", self.batch.name, "status"), "Processed")
