"""
Coverage for BatchProcessingService paths the existing pipeline test
(``test_dd_batch_pipeline_coverage.py``) deliberately leaves out: it only covers
the submit-state GUARD branches. This module drives the methods that require a
*submitted* batch and real payment entries.

FLAGGED PRODUCTION BUG (mark_batch_invoices_as_paid is broken for its only valid
input):
  ``mark_batch_invoices_as_paid`` first requires ``docstatus == 1`` (it throws on
  a draft batch). It then mutates the child ``Direct Debit Batch Invoice`` rows
  (status/result_code/result_message -- NONE of which are ``allow_on_submit``) and
  the parent ``batch_log`` field (also not ``allow_on_submit``), and finally calls
  ``batch_doc.save()``. On a submitted document that ``save()`` raises
  ``UpdateAfterSubmitError``. So the method *always* fails on the only batch state
  it accepts: it creates the Payment Entries (side effects already committed) and
  THEN blows up before recording success on the batch -- leaving the batch and its
  invoice rows un-updated while money-side payment entries exist. This is a real
  money-path defect; it needs a design decision (db_set / allow_on_submit / restructure)
  so it is FLAGGED, not fixed here. The test below pins the current failure so the
  regression -- or a fix -- is detectable.

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


class TestMarkBatchInvoicesAsPaidIsBrokenOnSubmit(_SubmittedBatchBase):
    """FLAGGED BUG: mark_batch_invoices_as_paid raises UpdateAfterSubmitError on the
    only batch state it accepts (a submitted batch), because its final
    batch_doc.save() mutates non-allow_on_submit fields (batch_log + child
    status/result_code). It creates the Payment Entries first, so this is a
    money-path defect, not a benign no-op."""

    def test_marking_a_submitted_batch_paid_raises_update_after_submit(self):
        from frappe.exceptions import UpdateAfterSubmitError

        batch = self._submitted_batch(invoice_count=1)
        self.assertEqual(batch.docstatus, 1)
        with self.assertRaises(UpdateAfterSubmitError):
            self.service.mark_batch_invoices_as_paid(batch)


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
