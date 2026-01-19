"""
Tests for eBoekhouden Transaction Type Classification

Tests the mapping of eBoekhouden mutation types (numeric and text) to ERPNext document types,
processor routing logic, and payment reference type determination.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_transaction_type_classification
"""

import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

from verenigingen.e_boekhouden.utils.eboekhouden_transaction_type_mapper import (
    TRANSACTION_TYPE_MAPPING,
    get_erpnext_document_type,
    get_payment_entry_reference_type,
    simplify_migration_process,
)
from verenigingen.tests.e_boekhouden.fixtures import (
    MUTATION_SOAP_CAMELCASE_FACTUUR_ONTVANGEN,
    MUTATION_SOAP_CAMELCASE_FACTUUR_VERSTUURD,
    MUTATION_SOAP_FACTUURBETALING_ONTVANGEN,
    MUTATION_SOAP_FACTUURBETALING_VERSTUURD,
    MUTATION_SOAP_FACTUUR_ONTVANGEN,
    MUTATION_SOAP_FACTUUR_VERSTUURD,
    MUTATION_SOAP_GELD_ONTVANGEN,
    MUTATION_SOAP_MEMORIAAL,
    MUTATION_TYPE_0_OPENING_BALANCE,
    MUTATION_TYPE_1_PURCHASE_INVOICE,
    MUTATION_TYPE_2_SALES_INVOICE,
    MUTATION_TYPE_3_CUSTOMER_PAYMENT,
    MUTATION_TYPE_3_NEGATIVE_NO_INVOICE,
    MUTATION_TYPE_3_NEGATIVE_ROW_AMOUNT,
    MUTATION_TYPE_3_NEGATIVE_WITH_INVOICE,
    MUTATION_TYPE_4_NEGATIVE_REFUND,
    MUTATION_TYPE_4_POSITIVE_NORMAL,
    MUTATION_TYPE_4_SUPPLIER_PAYMENT,
    MUTATION_TYPE_5_MONEY_RECEIVED,
    MUTATION_TYPE_6_MONEY_SENT,
    MUTATION_TYPE_7_MEMORIAL,
)


class TestNumericTypeMappingRestApi(unittest.TestCase):
    """Test numeric type mapping from REST API (types 0-7)"""

    def test_type_0_opening_balance(self):
        """Type 0 (Opening Balance) should map to Journal Entry"""
        result = get_erpnext_document_type(0)
        self.assertEqual(result, "Journal Entry")

    def test_type_1_purchase_invoice(self):
        """Type 1 (Invoice received) should map to Purchase Invoice"""
        result = get_erpnext_document_type(1)
        self.assertEqual(result, "Purchase Invoice")

    def test_type_2_sales_invoice(self):
        """Type 2 (Invoice sent) should map to Sales Invoice"""
        result = get_erpnext_document_type(2)
        self.assertEqual(result, "Sales Invoice")

    def test_type_3_customer_payment(self):
        """Type 3 (Invoice payment received) should map to Payment Entry"""
        result = get_erpnext_document_type(3)
        self.assertEqual(result, "Payment Entry")

    def test_type_4_supplier_payment(self):
        """Type 4 (Invoice payment sent) should map to Payment Entry"""
        result = get_erpnext_document_type(4)
        self.assertEqual(result, "Payment Entry")

    def test_type_5_money_received(self):
        """Type 5 (Money received) should map to Journal Entry"""
        result = get_erpnext_document_type(5)
        self.assertEqual(result, "Journal Entry")

    def test_type_6_money_sent(self):
        """Type 6 (Money sent) should map to Journal Entry"""
        result = get_erpnext_document_type(6)
        self.assertEqual(result, "Journal Entry")

    def test_type_7_memorial(self):
        """Type 7 (General journal entry) should map to Journal Entry"""
        result = get_erpnext_document_type(7)
        self.assertEqual(result, "Journal Entry")


class TestTextTypeMappingSoapApi(unittest.TestCase):
    """Test text type mapping from SOAP API (Dutch transaction types)"""

    def test_factuur_ontvangen(self):
        """'Factuur ontvangen' should map to Purchase Invoice"""
        result = get_erpnext_document_type("Factuur ontvangen")
        self.assertEqual(result, "Purchase Invoice")

    def test_factuur_verstuurd(self):
        """'Factuur verstuurd' should map to Sales Invoice"""
        result = get_erpnext_document_type("Factuur verstuurd")
        self.assertEqual(result, "Sales Invoice")

    def test_factuurbetaling_ontvangen(self):
        """'Factuurbetaling ontvangen' should map to Payment Entry"""
        result = get_erpnext_document_type("Factuurbetaling ontvangen")
        self.assertEqual(result, "Payment Entry")

    def test_factuurbetaling_verstuurd(self):
        """'Factuurbetaling verstuurd' should map to Payment Entry"""
        result = get_erpnext_document_type("Factuurbetaling verstuurd")
        self.assertEqual(result, "Payment Entry")

    def test_geld_ontvangen(self):
        """'Geld ontvangen' should map to Journal Entry"""
        result = get_erpnext_document_type("Geld ontvangen")
        self.assertEqual(result, "Journal Entry")

    def test_geld_verstuurd(self):
        """'Geld verstuurd' should map to Journal Entry"""
        result = get_erpnext_document_type("Geld verstuurd")
        self.assertEqual(result, "Journal Entry")

    def test_memoriaal(self):
        """'Memoriaal' should map to Journal Entry"""
        result = get_erpnext_document_type("Memoriaal")
        self.assertEqual(result, "Journal Entry")

    def test_english_invoice_received(self):
        """'Invoice received' should map to Purchase Invoice"""
        result = get_erpnext_document_type("Invoice received")
        self.assertEqual(result, "Purchase Invoice")

    def test_english_invoice_sent(self):
        """'Invoice sent' should map to Sales Invoice"""
        result = get_erpnext_document_type("Invoice sent")
        self.assertEqual(result, "Sales Invoice")


class TestCamelCaseTypeMappingSoapApi(unittest.TestCase):
    """Test CamelCase type mapping (normalized SOAP types)"""

    def test_factuur_ontvangen_camelcase(self):
        """'FactuurOntvangen' should map to Purchase Invoice"""
        result = get_erpnext_document_type("FactuurOntvangen")
        self.assertEqual(result, "Purchase Invoice")

    def test_factuur_verstuurd_camelcase(self):
        """'FactuurVerstuurd' should map to Sales Invoice"""
        result = get_erpnext_document_type("FactuurVerstuurd")
        self.assertEqual(result, "Sales Invoice")

    def test_factuurbetaling_ontvangen_camelcase(self):
        """'FactuurbetalingOntvangen' should map to Payment Entry"""
        result = get_erpnext_document_type("FactuurbetalingOntvangen")
        self.assertEqual(result, "Payment Entry")

    def test_factuurbetaling_verstuurd_camelcase(self):
        """'FactuurbetalingVerstuurd' should map to Payment Entry"""
        result = get_erpnext_document_type("FactuurbetalingVerstuurd")
        self.assertEqual(result, "Payment Entry")

    def test_geld_ontvangen_camelcase(self):
        """'GeldOntvangen' should map to Journal Entry"""
        result = get_erpnext_document_type("GeldOntvangen")
        self.assertEqual(result, "Journal Entry")

    def test_geld_uitgegeven_camelcase(self):
        """'GeldUitgegeven' should map to Journal Entry"""
        result = get_erpnext_document_type("GeldUitgegeven")
        self.assertEqual(result, "Journal Entry")

    def test_begin_balans_camelcase(self):
        """'BeginBalans' should map to Journal Entry"""
        result = get_erpnext_document_type("BeginBalans")
        self.assertEqual(result, "Journal Entry")


class TestFallbackAndEdgeCases(unittest.TestCase):
    """Test fallback behavior and edge cases"""

    def test_unknown_type_defaults_to_journal_entry(self):
        """Unknown transaction types should default to Journal Entry"""
        result = get_erpnext_document_type("Unknown Type XYZ")
        self.assertEqual(result, "Journal Entry")

    def test_unknown_numeric_type_raises_error(self):
        """Unknown numeric types raise AttributeError (code bug - tries to call .lower() on int)

        Note: This test documents current behavior. The code should be fixed to handle
        unknown numeric types gracefully by returning "Journal Entry" instead of raising.
        """
        with self.assertRaises(AttributeError):
            get_erpnext_document_type(99)

    def test_none_value_defaults_to_journal_entry(self):
        """None value should default to Journal Entry"""
        result = get_erpnext_document_type(None)
        self.assertEqual(result, "Journal Entry")

    def test_empty_string_defaults_to_journal_entry(self):
        """Empty string should default to Journal Entry"""
        result = get_erpnext_document_type("")
        self.assertEqual(result, "Journal Entry")

    def test_partial_match_factuur_ontvangen(self):
        """Partial match 'factuur ontvangen' in string should work"""
        result = get_erpnext_document_type("Some prefix factuur ontvangen suffix")
        self.assertEqual(result, "Purchase Invoice")

    def test_partial_match_factuur_verstuurd(self):
        """Partial match 'factuur verstuurd' in string should work"""
        result = get_erpnext_document_type("Some prefix factuur verstuurd suffix")
        self.assertEqual(result, "Sales Invoice")

    def test_partial_match_factuurbetaling(self):
        """Partial match 'factuurbetaling' in string should work"""
        result = get_erpnext_document_type("Prefix factuurbetaling suffix")
        self.assertEqual(result, "Payment Entry")

    def test_partial_match_memoriaal(self):
        """Partial match 'memoriaal' in string should work"""
        result = get_erpnext_document_type("Prefix memoriaal suffix")
        self.assertEqual(result, "Journal Entry")


class TestPaymentReferenceType(unittest.TestCase):
    """Test payment reference type determination"""

    def test_type_3_references_sales_invoice(self):
        """Type 3 (payment received) should reference Sales Invoice"""
        result = get_payment_entry_reference_type(3)
        self.assertEqual(result, "Sales Invoice")

    def test_type_4_references_purchase_invoice(self):
        """Type 4 (payment sent) should reference Purchase Invoice"""
        result = get_payment_entry_reference_type(4)
        self.assertEqual(result, "Purchase Invoice")

    def test_type_0_returns_none(self):
        """Type 0 (opening balance) should return None (not a payment)"""
        result = get_payment_entry_reference_type(0)
        self.assertIsNone(result)

    def test_type_1_returns_none(self):
        """Type 1 (purchase invoice) should return None"""
        result = get_payment_entry_reference_type(1)
        self.assertIsNone(result)

    def test_type_2_returns_none(self):
        """Type 2 (sales invoice) should return None"""
        result = get_payment_entry_reference_type(2)
        self.assertIsNone(result)

    def test_text_ontvangen_references_sales(self):
        """Text with 'ontvangen' should reference Sales Invoice"""
        result = get_payment_entry_reference_type("Factuurbetaling ontvangen")
        self.assertEqual(result, "Sales Invoice")

    def test_text_verstuurd_references_purchase(self):
        """Text with 'verstuurd' should reference Purchase Invoice"""
        result = get_payment_entry_reference_type("Factuurbetaling verstuurd")
        self.assertEqual(result, "Purchase Invoice")

    def test_text_received_references_sales(self):
        """Text with 'received' should reference Sales Invoice"""
        result = get_payment_entry_reference_type("Invoice payment received")
        self.assertEqual(result, "Sales Invoice")

    def test_text_sent_references_purchase(self):
        """Text with 'sent' should reference Purchase Invoice"""
        result = get_payment_entry_reference_type("Invoice payment sent")
        self.assertEqual(result, "Purchase Invoice")

    def test_none_returns_none(self):
        """None value should return None"""
        result = get_payment_entry_reference_type(None)
        self.assertIsNone(result)

    def test_empty_string_returns_none(self):
        """Empty string should return None"""
        result = get_payment_entry_reference_type("")
        self.assertIsNone(result)


class TestSimplifyMigrationProcess(unittest.TestCase):
    """Test the simplify_migration_process function"""

    def test_rest_api_type_field(self):
        """Should use 'type' field from REST API"""
        mutation = {"type": 2, "id": 1001}
        result = simplify_migration_process(mutation)

        self.assertEqual(result["document_type"], "Sales Invoice")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["transaction_type"], 2)

    def test_soap_api_soort_field(self):
        """Should use 'Soort' field from SOAP API"""
        mutation = {"Soort": "Factuur verstuurd", "MutatieNr": "1001"}
        result = simplify_migration_process(mutation)

        self.assertEqual(result["document_type"], "Sales Invoice")
        self.assertEqual(result["confidence"], "high")

    def test_soap_api_mutatietype_field(self):
        """Should use 'MutatieType' field from SOAP API"""
        mutation = {"MutatieType": "FactuurOntvangen", "MutatieNr": "1001"}
        result = simplify_migration_process(mutation)

        self.assertEqual(result["document_type"], "Purchase Invoice")
        self.assertEqual(result["confidence"], "high")

    def test_missing_type_field_low_confidence(self):
        """Missing type field should return low confidence"""
        mutation = {"id": 1001, "description": "No type field"}
        result = simplify_migration_process(mutation)

        self.assertEqual(result["document_type"], "Journal Entry")
        self.assertEqual(result["confidence"], "low")

    def test_payment_entry_includes_reference_info(self):
        """Payment entries should include reference type info"""
        mutation = {"type": 3, "id": 1001}  # Customer payment
        result = simplify_migration_process(mutation)

        self.assertEqual(result["document_type"], "Payment Entry")
        self.assertEqual(result["reference_type"], "Sales Invoice")
        self.assertTrue(result["needs_invoice_link"])

    def test_type_0_opening_balance_allowed(self):
        """Type 0 (opening balance) should be recognized"""
        mutation = {"type": 0, "id": 1001}
        result = simplify_migration_process(mutation)

        self.assertEqual(result["document_type"], "Journal Entry")
        self.assertEqual(result["confidence"], "high")


class TestProcessorCanProcess(unittest.TestCase):
    """Test processor can_process() methods for routing edge cases"""

    def setUp(self):
        """Set up mock processors"""
        # We need to patch frappe for processor initialization
        self.frappe_patcher = patch("verenigingen.e_boekhouden.utils.processors.base_processor.frappe")
        self.mock_frappe = self.frappe_patcher.start()
        self.mock_frappe.db.get_value.return_value = "Default Cost Center"

    def tearDown(self):
        """Clean up patches"""
        self.frappe_patcher.stop()

    def test_invoice_processor_type_1(self):
        """InvoiceProcessor should accept type 1 (Purchase Invoice)"""
        from verenigingen.e_boekhouden.utils.processors.invoice_processor import InvoiceProcessor

        processor = InvoiceProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_TYPE_1_PURCHASE_INVOICE)

        self.assertTrue(processor.can_process(mutation))

    def test_invoice_processor_type_2(self):
        """InvoiceProcessor should accept type 2 (Sales Invoice)"""
        from verenigingen.e_boekhouden.utils.processors.invoice_processor import InvoiceProcessor

        processor = InvoiceProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_TYPE_2_SALES_INVOICE)

        self.assertTrue(processor.can_process(mutation))

    def test_invoice_processor_rejects_type_3(self):
        """InvoiceProcessor should reject type 3 (Payment)"""
        from verenigingen.e_boekhouden.utils.processors.invoice_processor import InvoiceProcessor

        processor = InvoiceProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_TYPE_3_CUSTOMER_PAYMENT)

        self.assertFalse(processor.can_process(mutation))

    def test_journal_processor_type_0(self):
        """JournalProcessor should accept type 0 (Opening Balance)"""
        from verenigingen.e_boekhouden.utils.processors.journal_processor import JournalProcessor

        processor = JournalProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_TYPE_0_OPENING_BALANCE)

        self.assertTrue(processor.can_process(mutation))

    def test_journal_processor_type_7(self):
        """JournalProcessor should accept type 7 (Memorial)"""
        from verenigingen.e_boekhouden.utils.processors.journal_processor import JournalProcessor

        processor = JournalProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_TYPE_7_MEMORIAL)

        self.assertTrue(processor.can_process(mutation))

    def test_journal_processor_type_3_negative_no_invoice(self):
        """JournalProcessor should accept type 3 negative without invoice (generic refund)"""
        from verenigingen.e_boekhouden.utils.processors.journal_processor import JournalProcessor

        processor = JournalProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_TYPE_3_NEGATIVE_NO_INVOICE)

        self.assertTrue(processor.can_process(mutation))

    def test_journal_processor_rejects_type_4(self):
        """JournalProcessor should reject type 4 (all go to PaymentProcessor)"""
        from verenigingen.e_boekhouden.utils.processors.journal_processor import JournalProcessor

        processor = JournalProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_TYPE_4_SUPPLIER_PAYMENT)

        self.assertFalse(processor.can_process(mutation))


class TestPaymentProcessorRouting(unittest.TestCase):
    """Test PaymentProcessor routing for various payment scenarios"""

    def setUp(self):
        """Set up mock processors"""
        self.frappe_patcher = patch("verenigingen.e_boekhouden.utils.processors.payment_processor.frappe")
        self.mock_frappe = self.frappe_patcher.start()
        self.mock_frappe.db.get_value.return_value = "Default Cost Center"
        self.mock_frappe.get_single.return_value = MagicMock(
            get=MagicMock(return_value=None)  # No gateway config
        )

    def tearDown(self):
        """Clean up patches"""
        self.frappe_patcher.stop()

    def test_payment_processor_type_3_normal(self):
        """PaymentProcessor should accept type 3 normal payment"""
        from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor

        with patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        ) as mock_base_frappe:
            mock_base_frappe.db.get_value.return_value = "Default Cost Center"

            processor = PaymentProcessor(company="Test Company")
            mutation = deepcopy(MUTATION_TYPE_3_CUSTOMER_PAYMENT)

            self.assertTrue(processor.can_process(mutation))

    def test_payment_processor_type_4_normal(self):
        """PaymentProcessor should accept type 4 normal payment"""
        from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor

        with patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        ) as mock_base_frappe:
            mock_base_frappe.db.get_value.return_value = "Default Cost Center"

            processor = PaymentProcessor(company="Test Company")
            mutation = deepcopy(MUTATION_TYPE_4_SUPPLIER_PAYMENT)

            self.assertTrue(processor.can_process(mutation))

    def test_payment_processor_type_4_negative_refund(self):
        """PaymentProcessor should accept type 4 negative (supplier refund)"""
        from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor

        with patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        ) as mock_base_frappe:
            mock_base_frappe.db.get_value.return_value = "Default Cost Center"

            processor = PaymentProcessor(company="Test Company")
            mutation = deepcopy(MUTATION_TYPE_4_NEGATIVE_REFUND)

            self.assertTrue(processor.can_process(mutation))

    def test_payment_processor_type_5_money_received(self):
        """PaymentProcessor should accept type 5 (money received)"""
        from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor

        with patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        ) as mock_base_frappe:
            mock_base_frappe.db.get_value.return_value = "Default Cost Center"

            processor = PaymentProcessor(company="Test Company")
            mutation = deepcopy(MUTATION_TYPE_5_MONEY_RECEIVED)

            self.assertTrue(processor.can_process(mutation))

    def test_payment_processor_type_6_money_sent(self):
        """PaymentProcessor should accept type 6 (money sent)"""
        from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor

        with patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        ) as mock_base_frappe:
            mock_base_frappe.db.get_value.return_value = "Default Cost Center"

            processor = PaymentProcessor(company="Test Company")
            mutation = deepcopy(MUTATION_TYPE_6_MONEY_SENT)

            self.assertTrue(processor.can_process(mutation))

    def test_payment_processor_rejects_type_3_negative_no_invoice(self):
        """PaymentProcessor should reject type 3 negative without invoice (generic refund)"""
        from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor

        with patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        ) as mock_base_frappe:
            mock_base_frappe.db.get_value.return_value = "Default Cost Center"

            processor = PaymentProcessor(company="Test Company")
            mutation = deepcopy(MUTATION_TYPE_3_NEGATIVE_NO_INVOICE)

            # Type 3 negative WITHOUT invoice ref should go to JournalProcessor
            self.assertFalse(processor.can_process(mutation))

    def test_payment_processor_accepts_type_3_negative_with_invoice(self):
        """PaymentProcessor should accept type 3 negative WITH invoice (credit note)"""
        from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor

        with patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        ) as mock_base_frappe:
            mock_base_frappe.db.get_value.return_value = "Default Cost Center"

            processor = PaymentProcessor(company="Test Company")
            mutation = deepcopy(MUTATION_TYPE_3_NEGATIVE_WITH_INVOICE)

            # Type 3 negative WITH invoice ref should be processed as Payment Entry
            self.assertTrue(processor.can_process(mutation))

    def test_payment_processor_rejects_invoice_types(self):
        """PaymentProcessor should reject invoice types (1, 2)"""
        from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor

        with patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        ) as mock_base_frappe:
            mock_base_frappe.db.get_value.return_value = "Default Cost Center"

            processor = PaymentProcessor(company="Test Company")

            self.assertFalse(processor.can_process(deepcopy(MUTATION_TYPE_1_PURCHASE_INVOICE)))
            self.assertFalse(processor.can_process(deepcopy(MUTATION_TYPE_2_SALES_INVOICE)))


class TestTransactionTypeMappingCompleteness(unittest.TestCase):
    """Test that the transaction type mapping is complete"""

    def test_all_numeric_types_0_to_7_mapped(self):
        """All numeric types 0-7 should be in the mapping"""
        for type_num in range(8):
            self.assertIn(
                type_num,
                TRANSACTION_TYPE_MAPPING,
                f"Numeric type {type_num} missing from TRANSACTION_TYPE_MAPPING",
            )

    def test_all_dutch_text_types_mapped(self):
        """All common Dutch text types should be mapped"""
        dutch_types = [
            "Factuur ontvangen",
            "Factuur verstuurd",
            "Factuurbetaling ontvangen",
            "Factuurbetaling verstuurd",
            "Geld ontvangen",
            "Geld verstuurd",
            "Memoriaal",
        ]

        for text_type in dutch_types:
            self.assertIn(
                text_type,
                TRANSACTION_TYPE_MAPPING,
                f"Dutch type '{text_type}' missing from TRANSACTION_TYPE_MAPPING",
            )

    def test_mapping_values_are_valid_doctypes(self):
        """All mapping values should be valid ERPNext document types"""
        valid_doctypes = {"Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry"}

        for key, value in TRANSACTION_TYPE_MAPPING.items():
            self.assertIn(
                value,
                valid_doctypes,
                f"Mapping value '{value}' for key '{key}' is not a valid doctype",
            )


if __name__ == "__main__":
    unittest.main()
