"""
Tests for the eBoekhouden payment-processing engine helpers.

Covers the decision/parsing/validation surface of:
- ``e_boekhouden/utils/payment_processing/payment_entry_handler.py``
  (PaymentEntryHandler): invoice-number parsing, row reference extraction,
  payment-type/refund determination, remarks generation, direction validation.
- ``e_boekhouden/utils/processors/payment_processor.py`` (PaymentProcessor):
  ``can_process`` routing for payment mutation types incl. refund/credit-note
  edge cases, gateway-adjustment no-ops, bank-name extraction.

These are real integration tests against a EUR company. They exercise the pure
and DB-backed decision logic that does NOT require a live eBoekhouden HTTP
connection (no actual Payment Entry is submitted, which would need fully
configured ledgers/invoices/bank accounts).

Run with:
    bench --site test_site_2 run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_payment_entry_handler
"""

import frappe

from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
    PaymentEntryHandler,
)
from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _persist_eur_company():
    """Return a EUR company name, creating a dedicated test company if needed."""
    existing = frappe.db.get_value("Company", {"default_currency": "EUR"}, "name")
    if existing:
        return existing

    company = frappe.new_doc("Company")
    company.company_name = "EBKH EUR Test Co"
    company.abbr = "EETC"
    company.default_currency = "EUR"
    company.country = "Netherlands"
    company.insert(ignore_permissions=True)
    return company.name


class TestPaymentEntryHandlerHelpers(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()

    def _handler(self):
        return PaymentEntryHandler(self.company)

    # ---- _parse_invoice_numbers ----

    def test_parse_invoice_numbers_none(self):
        self.assertEqual(self._handler()._parse_invoice_numbers(None), [])

    def test_parse_invoice_numbers_empty_string(self):
        self.assertEqual(self._handler()._parse_invoice_numbers(""), [])

    def test_parse_invoice_numbers_csv_trims_and_drops_blanks(self):
        self.assertEqual(self._handler()._parse_invoice_numbers("A, B ,C,"), ["A", "B", "C"])

    def test_parse_invoice_numbers_coerces_int(self):
        self.assertEqual(self._handler()._parse_invoice_numbers(123), ["123"])

    # ---- _is_valid_invoice_reference ----

    def test_valid_invoice_reference_good(self):
        self.assertTrue(self._handler()._is_valid_invoice_reference("INV-001"))

    def test_valid_invoice_reference_with_allowed_chars(self):
        self.assertTrue(self._handler()._is_valid_invoice_reference("2025/01_A.1"))

    def test_valid_invoice_reference_too_short(self):
        self.assertFalse(self._handler()._is_valid_invoice_reference("A"))

    def test_valid_invoice_reference_bad_chars(self):
        self.assertFalse(self._handler()._is_valid_invoice_reference("bad space!"))

    def test_valid_invoice_reference_too_long(self):
        self.assertFalse(self._handler()._is_valid_invoice_reference("X" * 51))

    # ---- _extract_invoice_references_from_rows ----

    def test_extract_refs_from_rows_rest(self):
        refs = self._handler()._extract_invoice_references_from_rows(
            {"rows": [{"invoiceNumber": "REF1"}, {"factuurNummer": "REF2"}]}
        )
        self.assertIn("REF1", refs)
        self.assertIn("REF2", refs)

    def test_extract_refs_from_regels_soap(self):
        refs = self._handler()._extract_invoice_references_from_rows({"Regels": [{"FactuurNummer": "REG1"}]})
        self.assertEqual(refs, ["REG1"])

    def test_extract_refs_dedupes(self):
        refs = self._handler()._extract_invoice_references_from_rows(
            {"rows": [{"invoiceNumber": "DUP"}, {"factuurNummer": "DUP"}]}
        )
        self.assertEqual(refs.count("DUP"), 1)

    def test_extract_refs_ignores_invalid(self):
        refs = self._handler()._extract_invoice_references_from_rows(
            {"rows": [{"invoiceNumber": "has space"}]}
        )
        self.assertEqual(refs, [])

    def test_extract_refs_empty(self):
        self.assertEqual(self._handler()._extract_invoice_references_from_rows({}), [])

    def test_extract_refs_handles_non_dict_rows(self):
        # Defensive: non-dict entries are skipped without error
        refs = self._handler()._extract_invoice_references_from_rows({"rows": ["not-a-dict"]})
        self.assertEqual(refs, [])

    # ---- _determine_payment_type ----

    def test_determine_type3_positive_receive(self):
        pt, party, refund = self._handler()._determine_payment_type({"id": 1, "type": 3}, 100.0, 3)
        self.assertEqual((pt, party, refund), ("Receive", "Customer", False))

    def test_determine_type3_negative_is_refund(self):
        pt, party, refund = self._handler()._determine_payment_type({"id": 2, "type": 3}, -100.0, 3)
        self.assertEqual((pt, party, refund), ("Pay", "Customer", True))

    def test_determine_type4_positive_pay(self):
        pt, party, refund = self._handler()._determine_payment_type({"id": 3, "type": 4}, 100.0, 4)
        self.assertEqual((pt, party, refund), ("Pay", "Supplier", False))

    def test_determine_type4_negative_is_refund(self):
        pt, party, refund = self._handler()._determine_payment_type({"id": 4, "type": 4}, -100.0, 4)
        self.assertEqual((pt, party, refund), ("Receive", "Supplier", True))

    def test_determine_type4_gateway_adjustment_keeps_pay(self):
        pt, party, refund = self._handler()._determine_payment_type(
            {"id": 5, "type": 4, "_original_amount": 200}, -150.0, 4
        )
        # Gateway adjustments are not treated as refunds
        self.assertEqual((pt, party, refund), ("Pay", "Supplier", False))

    # ---- _validate_payment_direction ----

    def test_validate_direction_correct_passes(self):
        # Should not raise
        self._handler()._validate_payment_direction(3, 100.0, "Receive", "Customer")
        self._handler()._validate_payment_direction(4, 100.0, "Pay", "Supplier")

    def test_validate_direction_wrong_type_raises(self):
        with self.assertRaises(frappe.ValidationError):
            self._handler()._validate_payment_direction(3, 100.0, "Pay", "Customer")

    def test_validate_direction_wrong_party_raises(self):
        with self.assertRaises(frappe.ValidationError):
            self._handler()._validate_payment_direction(3, 100.0, "Receive", "Supplier")

    def test_validate_direction_non_payment_type_noop(self):
        # Type 7 is not validated -> returns without raising
        self._handler()._validate_payment_direction(7, 100.0, "Pay", "Supplier")

    # ---- _generate_remarks ----

    def test_generate_remarks_contains_key_fields(self):
        remarks = self._handler()._generate_remarks(
            {
                "id": 42,
                "type": 3,
                "invoiceNumber": "INV-1",
                "description": "Membership",
                "rows": [{}, {}],
                "ledgerId": 1100,
                "relationId": 5001,
            },
            "Bank - X",
            "Customer A",
        )
        self.assertIn("Mutation 42", remarks)
        self.assertIn("Customer Payment", remarks)
        self.assertIn("INV-1", remarks)
        self.assertIn("Row count: 2", remarks)
        self.assertIn("1100", remarks)

    def test_generate_remarks_supplier_label(self):
        remarks = self._handler()._generate_remarks({"id": 7, "type": 4, "ledgerId": 1}, "Bank", "Supplier B")
        self.assertIn("Supplier Payment", remarks)

    # ---- _get_or_create_party ----

    def test_get_or_create_party_no_relation_id(self):
        self.assertIsNone(self._handler()._get_or_create_party(None, "Customer", "desc"))

    # ---- _determine_bank_account error path ----

    def test_determine_bank_account_no_ledger_raises(self):
        with self.assertRaises(frappe.ValidationError):
            self._handler()._determine_bank_account(None, "Receive")

    # ---- debug log ----

    def test_debug_log_accumulates(self):
        h = self._handler()
        h._log("a message")
        self.assertTrue(any("a message" in line for line in h.get_debug_log()))


class TestPaymentProcessorRouting(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()

    def _processor(self):
        return PaymentProcessor(self.company)

    # ---- can_process ----

    def test_cannot_process_non_payment_type(self):
        self.assertFalse(self._processor().can_process({"id": 1, "type": 2}))

    def test_can_process_type5_money_received(self):
        self.assertTrue(self._processor().can_process({"id": 2, "type": 5}))

    def test_can_process_type6_money_paid(self):
        self.assertTrue(self._processor().can_process({"id": 3, "type": 6}))

    def test_can_process_type3_positive(self):
        self.assertTrue(self._processor().can_process({"id": 4, "type": 3, "amount": 100}))

    def test_type3_negative_without_invoice_forwarded(self):
        # Generic refund -> forwarded to JournalProcessor (False)
        self.assertFalse(self._processor().can_process({"id": 5, "type": 3, "amount": -50}))

    def test_type3_negative_with_invoice_claimed(self):
        # Credit note payment -> Payment Entry (True)
        self.assertTrue(
            self._processor().can_process({"id": 6, "type": 3, "amount": -50, "invoiceNumber": "X"})
        )

    def test_can_process_type4_positive(self):
        self.assertTrue(self._processor().can_process({"id": 7, "type": 4, "amount": 100}))

    def test_can_process_type4_negative_refund(self):
        self.assertTrue(self._processor().can_process({"id": 8, "type": 4, "amount": -100}))

    def test_negative_row_amount_warning_logged(self):
        p = self._processor()
        p.can_process({"id": 9, "type": 3, "amount": 100, "rows": [{"amount": -5}]})
        self.assertTrue(any("NEGATIVE row amount" in m for m in p.get_debug_info()))

    # ---- get_payment_type ----

    def test_get_payment_type_receive(self):
        self.assertEqual(self._processor().get_payment_type({"type": 3}), "Receive")

    def test_get_payment_type_pay(self):
        self.assertEqual(self._processor().get_payment_type({"type": 4}), "Pay")

    def test_enhanced_processing_enabled(self):
        self.assertTrue(self._processor().is_enhanced_processing_enabled())

    # ---- gateway adjustment (no-op when not type 4 / unconfigured) ----

    def test_gateway_adjustment_false_for_non_type4(self):
        self.assertFalse(self._processor()._is_payment_gateway_adjustment({"id": 1, "type": 3}))

    def test_gateway_adjustment_false_when_unconfigured(self):
        # Settings have no gateway account/prefix on the test site -> not an adjustment
        self.assertFalse(
            self._processor()._is_payment_gateway_adjustment(
                {"id": 1, "type": 4, "ledgerId": 1, "invoiceNumber": "X"}
            )
        )

    def test_adjust_gateway_amount_noop_non_type4(self):
        mutation = {"id": 2, "type": 3, "amount": 50}
        self.assertEqual(self._processor()._adjust_payment_gateway_amount(mutation), mutation)

    def test_adjust_gateway_amount_noop_when_unconfigured(self):
        mutation = {"id": 3, "type": 4, "amount": 50, "ledgerId": 1, "invoiceNumber": "X"}
        self.assertEqual(self._processor()._adjust_payment_gateway_amount(mutation), mutation)

    # ---- _extract_bank_name_from_account ----

    def test_extract_bank_name_empty(self):
        self.assertIsNone(self._processor()._extract_bank_name_from_account(""))

    def test_extract_bank_name_unknown_supplier(self):
        # Bank name not present as a Supplier -> None (avoids link validation errors)
        self.assertIsNone(
            self._processor()._extract_bank_name_from_account("1100 - NonexistentBankXYZ - 123 - NVV")
        )
