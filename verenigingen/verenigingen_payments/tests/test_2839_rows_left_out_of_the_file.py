"""
#2839 (review round): a batch row the XML generator leaves out of the file (undeterminable
SeqTp, or an invalid debtor IBAN) must be recorded as left out. Before, it stayed "Pending"
in the Direct Debit Batch Invoice table, so `mark_invoices_as_paid` later booked a Payment
Entry and marked the invoice Paid although the bank was never asked for the debit, and the
batch totals still counted it.

Real flow: a submitted Direct Debit Batch of two real invoices, one row corrupted by a RAW
write (the other writers the batch builders no longer allow), the file regenerated through
SEPAXMLGenerationService, then mark_invoices_as_paid. The corruption is a probe shortcut: it
stands in for "whatever wrote a bad row", it is not a reachable user flow.
"""

import xml.etree.ElementTree as ET

import frappe
from frappe.utils import flt

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_configuration import apply_sepa_test_configuration
from verenigingen.verenigingen_payments.api.sepa_batch_ui import get_open_batch_invoice_names
from verenigingen.verenigingen_payments.services.sepa_xml_generation_service import SEPAXMLGenerationService
from verenigingen.verenigingen_payments.utils.sepa_constants import ROW_NOT_IN_FILE_CODE

_NS = "{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}"
_DOCTYPE = "Direct Debit Batch Invoice"


class Test2839RowsLeftOutOfTheFile(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        apply_sepa_test_configuration()
        self._sepa = SEPATestDataFactory(seed=283901, use_faker=True)
        batch = self._sepa.create_test_direct_debit_batch(invoice_count=2)
        batch.submit()
        self.batch_name = batch.name
        rows = frappe.get_all(_DOCTYPE, filters={"parent": batch.name}, fields=["name"], order_by="idx asc")
        self.good_row, self.bad_row = [r.name for r in rows]

    def _row(self, name):
        return frappe.db.get_value(
            _DOCTYPE,
            name,
            ["invoice", "status", "result_code", "result_message", "amount", "sequence_type", "iban"],
            as_dict=True,
        )

    def _regenerate(self):
        batch = frappe.get_doc("Direct Debit Batch", self.batch_name)
        service = SEPAXMLGenerationService()
        xml_string = service.xml_adapter.generate_xml_for_batch(
            batch, f"MSG-{self.batch_name}", f"PMT-{self.batch_name}"
        )
        return batch, ET.fromstring(xml_string)

    def _corrupt_sequence(self):
        frappe.db.set_value(_DOCTYPE, self.bad_row, "sequence_type", "CORE")  # raw: no Select check

    def _corrupt_iban(self):
        frappe.db.set_value(_DOCTYPE, self.bad_row, "iban", "NL00BANK0000000000")

    def _payment_entries(self, invoice):
        return frappe.get_all("Payment Entry Reference", filters={"reference_name": invoice}, pluck="parent")

    def _assert_left_out_and_never_booked(self, cause):
        self.expectErrorLog("SEPA XML Adapter - Transaction Build Error")
        good, bad = self._row(self.good_row), self._row(self.bad_row)
        batch, root = self._regenerate()
        txs = root.findall(f".//{_NS}DrctDbtTxInf")
        self.assertEqual(len(txs), 1, f"{cause}: the file must hold only the good row")

        # Recorded on the row, with the invoice and the reason, and on the batch.
        left_out = self._row(self.bad_row)
        self.assertEqual((left_out.status, left_out.result_code), ("Failed", ROW_NOT_IN_FILE_CODE), cause)
        self.assertIn("Not in the SEPA file", left_out.result_message)
        self.assertEqual(self._row(self.good_row).status, "Pending")
        batch.reload()
        self.assertIn(bad.invoice, batch.batch_log or "")
        self.assertNotIn(good.invoice, batch.batch_log or "")

        # Totals equal the file's content (the bank credits the control sum).
        self.assertEqual(batch.entry_count, 1)
        self.assertEqual(flt(batch.total_amount), flt(good.amount))
        self.assertEqual(flt(root.find(f".//{_NS}GrpHdr/{_NS}CtrlSum").text), flt(good.amount))

        # The real consequence: marking paid books the sent row only.
        outstanding_before = flt(frappe.db.get_value("Sales Invoice", bad.invoice, "outstanding_amount"))
        batch.mark_invoices_as_paid()
        self.assertEqual(self._row(self.good_row).status, "Successful")
        self.assertEqual(self._payment_entries(bad.invoice), [], f"{cause}: a PE was booked for a debit never sent")
        self.assertEqual(
            flt(frappe.db.get_value("Sales Invoice", bad.invoice, "outstanding_amount")), outstanding_before
        )
        self.assertEqual(self._row(self.bad_row).result_code, ROW_NOT_IN_FILE_CODE)
        self.assertNotEqual(frappe.db.get_value("Direct Debit Batch", batch.name, "status"), "Processed")

        # The left-out invoice is collectable again; the sent one is not.
        open_names = get_open_batch_invoice_names()
        self.assertNotIn(bad.invoice, open_names)
        self.assertIn(good.invoice, open_names)

    def test_premise_before_corruption_both_rows_ship_and_pay(self):
        _, root = self._regenerate()
        self.assertEqual(len(root.findall(f".//{_NS}DrctDbtTxInf")), 2)
        self.assertEqual(self._row(self.bad_row).status, "Pending")
        self.assertIn(self._row(self.bad_row).invoice, get_open_batch_invoice_names())

    def test_undeterminable_sequence_type_row_is_never_booked_as_paid(self):
        self._corrupt_sequence()
        self._assert_left_out_and_never_booked("SeqTp")

    def test_invalid_iban_row_is_never_booked_as_paid(self):
        self._corrupt_iban()
        self._assert_left_out_and_never_booked("IBAN")

    def test_regeneration_that_includes_the_row_again_releases_it(self):
        self.expectErrorLog("SEPA XML Adapter - Transaction Build Error")
        self._corrupt_sequence()
        self._regenerate()
        frappe.db.set_value(_DOCTYPE, self.bad_row, "sequence_type", "RCUR")
        batch, root = self._regenerate()
        self.assertEqual(len(root.findall(f".//{_NS}DrctDbtTxInf")), 2)
        row = self._row(self.bad_row)
        self.assertEqual((row.status, row.result_code), ("Pending", None))
        self.assertEqual(batch.entry_count, 2)

    def test_regeneration_does_not_unmark_a_collected_row(self):
        self.expectErrorLog("SEPA XML Adapter - Transaction Build Error")
        batch, _ = self._regenerate()
        batch.mark_invoices_as_paid()
        self._corrupt_sequence()
        self._regenerate()
        self.assertEqual(self._row(self.bad_row).status, "Successful")

    def test_full_reconciliation_ignores_a_left_out_row(self):
        self.expectErrorLog("SEPA XML Adapter - Transaction Build Error")
        from verenigingen.verenigingen_payments.api import sepa_reconciliation

        self._corrupt_sequence()
        batch, _ = self._regenerate()
        # Make phase 1 refuse every row it is given (no customer on either member), so the
        # answer names exactly the rows the reconciliation considered, and nothing is written.
        for member in frappe.get_all(_DOCTYPE, filters={"parent": batch.name}, pluck="member"):
            frappe.db.set_value("Member", member, "customer", None)
        result = sepa_reconciliation.reconcile_full_sepa_batch(frappe._dict(name="BT-S2839"), batch)
        self.assertEqual(result["type"], "validation_failed")
        self.assertEqual(
            [e["invoice"] for e in result["validation_errors"]],
            [self._row(self.good_row).invoice],
            "the left-out row must not be among the items considered",
        )
