"""
#1235: ``SEPABatchProcessor.process_batch_returns`` must persist a bank return on a
SUBMITTED (docstatus=1) Direct Debit Batch.

A pain.002 return file only exists for a batch that was already collected, i.e.
submitted. The method used to set ``Direct Debit Batch Invoice.status/result_code/
result_message`` and ``Direct Debit Batch.status/batch_log`` in memory and call
``batch.save()``; none of those fields is ``allow_on_submit``, so every real return
raised ``UpdateAfterSubmitError`` and no Failed row ever persisted. The existing
returns coverage builds a Draft batch, where ``validate_update_after_submit`` never
runs, so it could not see this.

The flow here is real end to end: a batch submitted through ``batch.submit()``, a real
pain.002 XML file read through ``parse_sepa_return_file`` ->
``sepa_return_parser.get_rejected_transactions`` -> ``process_batch_returns``. No parser
stub. The return's ``OrgnlEndToEndId`` is ``INV-<invoice>`` (the id the pain.008 writes).
"""

import os

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.services.sepa_batch_processor import SEPABatchProcessor

_PAIN002_NS = "urn:iso:std:iso:20022:tech:xsd:pain.002.001.03"


class TestProcessBatchReturnsOnSubmittedBatch1235(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.eur_company = get_eur_test_company()

    def setUp(self):
        super().setUp()
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory

        self.processor = SEPABatchProcessor()
        self._sepa = SEPATestDataFactory(seed=1235, use_faker=True)
        self.expectErrorLog("Fiscal Year Auto-Creation Error")

    def _really_submitted_batch(self, invoice_count=2):
        batch = self._sepa.create_test_direct_debit_batch(invoice_count=invoice_count)
        batch.sepa_file_generated = 1
        batch.save()
        batch.submit()
        batch.reload()
        self.assertEqual(batch.docstatus, 1, "fixture: the batch must really be submitted")
        return batch

    def _return_file(self, rejected_invoices, accepted_invoices=()):
        """A real pain.002 file: one RJCT TxInfAndSts per rejected invoice (reason AC04),
        one ACSP per accepted invoice."""
        rejected = "".join(
            f"<TxInfAndSts><OrgnlEndToEndId>INV-{name}</OrgnlEndToEndId><TxSts>RJCT</TxSts>"
            "<StsRsnInf><Rsn><Cd>AC04</Cd></Rsn></StsRsnInf></TxInfAndSts>"
            for name in rejected_invoices
        )
        accepted = "".join(
            f"<TxInfAndSts><OrgnlEndToEndId>INV-{name}</OrgnlEndToEndId><TxSts>ACSP</TxSts></TxInfAndSts>"
            for name in accepted_invoices
        )
        body = (
            f'<?xml version="1.0" encoding="UTF-8"?><Document xmlns="{_PAIN002_NS}"><CstmrPmtStsRpt>'
            "<OrgnlGrpInfAndSts><OrgnlMsgId>MSG-1235</OrgnlMsgId></OrgnlGrpInfAndSts>"
            f"<OrgnlPmtInfAndSts><OrgnlPmtInfId>PMT-1235</OrgnlPmtInfId>{rejected}{accepted}"
            "</OrgnlPmtInfAndSts></CstmrPmtStsRpt></Document>"
        )
        path = frappe.get_site_path("private", "files", f"test_1235_{frappe.generate_hash(length=8)}.xml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def _row_state(self, row):
        return frappe.db.get_value(
            "Direct Debit Batch Invoice",
            row.name,
            ["status", "result_code", "result_message"],
            as_dict=True,
        )

    def test_a_return_persists_the_failed_row_and_the_batch_state_on_a_really_submitted_batch(self):
        batch = self._really_submitted_batch(invoice_count=2)
        returned, untouched = batch.invoices[0], batch.invoices[1]
        path = self._return_file([returned.invoice], accepted_invoices=[untouched.invoice])
        untouched_before = self._row_state(untouched)

        failed = self.processor.process_batch_returns(batch.name, path)

        self.assertEqual(failed, 1)
        state = self._row_state(returned)
        self.assertEqual((state.status, state.result_code), ("Failed", "AC04"))
        self.assertTrue(state.result_message, "the bank's reason text must be persisted")
        self.assertEqual(self._row_state(untouched), untouched_before, "a row not returned is unchanged")
        batch.reload()
        self.assertEqual(batch.docstatus, 1)
        self.assertEqual(batch.status, "Partially Failed")
        self.assertIn("Processed 1 returned payments", batch.batch_log or "")

    def test_a_return_for_an_invoice_not_in_the_batch_changes_nothing_on_a_really_submitted_batch(self):
        """Control: an unmatched return must not fail any row nor flip the batch status."""
        batch = self._really_submitted_batch(invoice_count=1)
        status_before = frappe.db.get_value("Direct Debit Batch", batch.name, "status")
        row_before = self._row_state(batch.invoices[0])
        path = self._return_file(["ACC-SINV-NOT-IN-THIS-BATCH"])

        failed = self.processor.process_batch_returns(batch.name, path)

        self.assertEqual(failed, 0)
        self.assertEqual(self._row_state(batch.invoices[0]), row_before)
        self.assertEqual(frappe.db.get_value("Direct Debit Batch", batch.name, "status"), status_before)
