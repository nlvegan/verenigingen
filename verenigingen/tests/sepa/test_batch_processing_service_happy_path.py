"""
Coverage for BatchProcessingService paths the existing pipeline test
(``test_dd_batch_pipeline_coverage.py``) deliberately leaves out: it only covers
the submit-state GUARD branches. This module drives the methods that require a
*submitted* batch and real payment entries.

FIXED (mark_batch_invoices_as_paid succeeds on a submitted batch):
  ``mark_batch_invoices_as_paid`` requires ``docstatus == 1`` (it throws on a draft
  batch). It mutates the child ``Direct Debit Batch Invoice`` rows
  (status/result_code/result_message -- NONE of which are ``allow_on_submit``) and
  the parent ``status``/``batch_log`` fields. Previously a final ``batch_doc.save()``
  raised ``UpdateAfterSubmitError`` AFTER the Payment Entries were already created,
  leaving the batch and its rows un-updated. The service now persists those tracking
  fields via ``db_set(..., update_modified=False)`` (the sanctioned post-submit
  pattern) with no ``save()`` and no extra commit, so the Payment Entries and the
  status writes stay atomic within the request transaction. The test below pins the
  success path (parent + child rows updated, Payment Entries created, no exception).

- ``process_batch_submission`` success: with the SEPA file flagged generated the
  status flips to Submitted and True is returned. This path works and is covered.

Real-DB integration tests (no mocks). Submitted batches / payment entries commit
past the FrappeTestCase rollback, so committed docs are tracked and force-deleted.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.services.batch_processing_service import (
    batch_processing_service,
)


class _SubmittedBatchBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.eur_company = get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.service = batch_processing_service
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

        self._sepa = SEPATestDataFactory(seed=5150, use_faker=True)
        self._committed = []
        # Submitting dated invoices triggers eBoekhouden's benign FY auto-create log
        # on the shared test DB (a known test-artifact, not a SEPA bug).
        self.expectErrorLog("Fiscal Year Auto-Creation Error")

    def tearDown(self):
        for doctype, name in reversed(self._committed):
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _track(self, doctype, name):
        self._committed.append((doctype, name))

    def _submitted_batch(self, invoice_count=1):
        """A docstatus==1 EUR Direct Debit Batch with real submitted invoices.

        create_test_direct_debit_batch builds FRST/EUR rows whose mandates have no
        prior usage; setting sepa_file_generated lets on_submit pass its guard."""
        batch = self._sepa.create_test_direct_debit_batch(invoice_count=invoice_count)
        self._track("Direct Debit Batch", batch.name)
        batch.sepa_file_generated = 1
        batch.save()
        batch.submit()
        return batch


class TestMarkBatchInvoicesAsPaidSucceedsOnSubmit(_SubmittedBatchBase):
    """mark_batch_invoices_as_paid marks a SUBMITTED batch paid without raising:
    it creates the Payment Entries, then persists the parent status + child row
    status fields via db_set (no save() -> no UpdateAfterSubmitError)."""

    def test_marking_a_submitted_batch_paid_succeeds(self):
        batch = self._submitted_batch(invoice_count=1)
        self.assertEqual(batch.docstatus, 1)

        pe_before = frappe.db.count("Payment Entry")
        success_count = self.service.mark_batch_invoices_as_paid(batch)

        # All invoices marked paid; one Payment Entry created.
        self.assertEqual(success_count, 1)
        self.assertEqual(frappe.db.count("Payment Entry"), pe_before + 1)

        # Parent status persisted to the DB (all rows successful -> Processed).
        self.assertEqual(
            frappe.db.get_value("Direct Debit Batch", batch.name, "status"), "Processed"
        )

        # Child row status persisted to the DB.
        row = batch.invoices[0]
        self.assertEqual(
            frappe.db.get_value("Direct Debit Batch Invoice", row.name, "status"), "Successful"
        )
        self.assertEqual(
            frappe.db.get_value("Direct Debit Batch Invoice", row.name, "result_code"), "PDNG"
        )

        # A Payment Entry exists referencing this batch.
        self.assertTrue(
            frappe.db.exists("Payment Entry", {"reference_no": batch.name}),
            "A Payment Entry referencing the batch must have been created",
        )


class TestProcessBatchSubmissionSuccess(_SubmittedBatchBase):
    def test_success_path_flips_status_to_submitted(self):
        # A draft batch with the SEPA file flagged generated submits successfully
        # (the placeholder bank step is a no-op that returns True).
        batch = self._sepa.create_test_direct_debit_batch(invoice_count=1)
        self._track("Direct Debit Batch", batch.name)
        batch.sepa_file_generated = 1
        batch.save()

        result = self.service.process_batch_submission(batch)
        self.assertTrue(result)
        batch.reload()
        self.assertEqual(batch.status, "Submitted")
        self.assertIn("submitted", (batch.batch_log or "").lower())
