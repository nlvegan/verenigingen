"""#2799: the process_batch API ("Submit to Bank") must not downgrade a collected batch.

`DirectDebitBatch.process_batch()` used to db_set status="Submitted" whatever the
batch held, so a Processed batch (every row Successful) was silently reset. The
reset stays available for the retry route (Partially Processed / Failed batches:
Mark as Processed skips Successful rows since #2573 and retries the rest).

Every state below is reached through the REAL flow (module-level
`mark_invoices_as_paid`, then `process_batch`, as Administrator through the same
@critical_api gates). The one probe shortcut is declared where it is used.
"""

import frappe

from verenigingen.tests.sepa.test_batch_processing_service_happy_path import _SubmittedBatchBase
from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
    mark_invoices_as_paid,
    process_batch,
)

REFUSAL = "already collected"


class TestProcessBatchDoesNotDowngradeCollectedBatch2799(_SubmittedBatchBase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        # The module functions log the error they re-raise; those rows are intended.
        self.expectErrorLog("SEPA Direct Debit Batch Processing Error")
        self.expectErrorLog("SEPA Direct Debit Payment Error")

    def _fail_row_invoice(self, batch, row_index):
        """Make one row's collection really fail: cancel its Sales Invoice so the
        Payment Entry creation raises inside mark_batch_invoices_as_paid."""
        invoice = frappe.get_doc("Sales Invoice", batch.invoices[row_index].invoice)
        invoice.flags.ignore_links = True
        invoice.cancel()

    def _row_statuses(self, batch):
        return [
            frappe.db.get_value("Direct Debit Batch Invoice", row.name, "status") for row in batch.invoices
        ]

    def _status(self, batch):
        return frappe.db.get_value("Direct Debit Batch", batch.name, "status")

    def _pe_count(self, batch):
        return frappe.db.count("Payment Entry", {"reference_no": batch.name})

    def test_processed_batch_is_refused_and_left_untouched(self):
        batch = self._submitted_batch(invoice_count=2)
        mark_invoices_as_paid(batch.name)
        self.assertEqual(self._status(batch), "Processed")
        log_before = frappe.db.get_value("Direct Debit Batch", batch.name, "batch_log")
        pe_before = self._pe_count(batch)

        with self.assertRaises(frappe.ValidationError) as ctx:
            process_batch(batch.name)

        self.assertIn(REFUSAL, str(ctx.exception))
        self.assertEqual(self._status(batch), "Processed")
        self.assertEqual(self._row_statuses(batch), ["Successful", "Successful"])
        self.assertEqual(frappe.db.get_value("Direct Debit Batch", batch.name, "batch_log"), log_before)
        self.assertEqual(self._pe_count(batch), pe_before)

    def test_partially_processed_batch_keeps_its_retry_route(self):
        batch = self._submitted_batch(invoice_count=2)
        self._fail_row_invoice(batch, 1)
        mark_invoices_as_paid(batch.name)
        self.assertEqual(self._status(batch), "Partially Processed")
        self.assertEqual(self._row_statuses(batch), ["Successful", "Failed"])
        pe_before = self._pe_count(batch)

        self.assertTrue(process_batch(batch.name))

        # reset to Submitted so Mark as Processed is offered again; the collected row is untouched
        self.assertEqual(self._status(batch), "Submitted")
        self.assertEqual(self._row_statuses(batch), ["Successful", "Failed"])
        self.assertEqual(self._pe_count(batch), pe_before)

        # the retry itself re-attempts only the Failed row (still failing here) and
        # does not re-book the collected one
        mark_invoices_as_paid(batch.name)
        self.assertEqual(self._status(batch), "Partially Processed")
        self.assertEqual(self._row_statuses(batch), ["Successful", "Failed"])
        self.assertEqual(self._pe_count(batch), pe_before)

    def test_failed_batch_keeps_its_retry_route(self):
        batch = self._submitted_batch(invoice_count=1)
        self._fail_row_invoice(batch, 0)
        mark_invoices_as_paid(batch.name)
        self.assertEqual(self._status(batch), "Failed")

        self.assertTrue(process_batch(batch.name))

        self.assertEqual(self._status(batch), "Submitted")

    def test_batch_whose_rows_are_all_collected_is_refused_whatever_its_status(self):
        """Probe shortcut: status is pinned to Submitted by db_set to stand in for a
        batch an earlier (unguarded) process_batch already downgraded. The rows
        come from the real flow, so this pins that the guard looks at the rows and
        not only at status == Processed."""
        batch = self._submitted_batch(invoice_count=2)
        mark_invoices_as_paid(batch.name)
        batch.db_set("status", "Submitted", update_modified=False)

        with self.assertRaises(frappe.ValidationError) as ctx:
            process_batch(batch.name)

        self.assertIn(REFUSAL, str(ctx.exception))
        self.assertEqual(self._status(batch), "Submitted")
        self.assertEqual(self._row_statuses(batch), ["Successful", "Successful"])

    def test_uncollected_submitted_batch_is_still_submitted_for_processing(self):
        """Control: the guard does not refuse an ordinary Pending batch."""
        batch = self._submitted_batch(invoice_count=2)
        self.assertEqual(self._row_statuses(batch), ["Pending", "Pending"])

        self.assertTrue(process_batch(batch.name))

        self.assertEqual(self._status(batch), "Submitted")

    def test_submitted_batch_with_no_rows_is_not_refused_as_collected(self):
        """Control for the `bool(rows)` clause: `all()` over no rows is True, which
        would call an empty batch "fully collected". Probe shortcut: the child rows are
        deleted by hand after submit, because a batch with no rows cannot be built
        through the real flow (this is only a state-shape control)."""
        batch = self._submitted_batch(invoice_count=1)
        frappe.db.delete("Direct Debit Batch Invoice", {"parent": batch.name})
        self.assertEqual(frappe.get_doc("Direct Debit Batch", batch.name).invoices, [])

        self.assertTrue(process_batch(batch.name))

        self.assertEqual(self._status(batch), "Submitted")
