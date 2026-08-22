#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEPA XML Adapter Unit Tests

Tests for the SEPAXMLAdapter service that bridges Direct Debit Batch documents
with the EnhancedSEPAXMLGenerator.

Focus Areas:
- Transaction building from batch invoices
- Mandate sign date lookup with DB fallback
- Mandate data caching
- Sequence type mapping
- XML generation via adapter
"""

import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from verenigingen.tests.harness_logger import get_harness_logger
from verenigingen.verenigingen_payments.services.sepa_xml_adapter import (
    BatchValidationSummary,
    SEPAXMLAdapter,
    get_sepa_xml_adapter,
)
from verenigingen.verenigingen_payments.utils.sepa_xml_enhanced_generator import (
    SEPASequenceType,
)


class TestSEPAXMLAdapter(FrappeTestCase):
    """Unit tests for SEPAXMLAdapter"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.adapter = SEPAXMLAdapter()

    def tearDown(self):
        """Clean up after tests"""
        super().tearDown()
        self.adapter.clear_cache()

    def test_sequence_type_mapping(self):
        """Test mapping of sequence type strings to enums"""
        test_cases = [
            ("FRST", SEPASequenceType.FRST),
            ("RCUR", SEPASequenceType.RCUR),
            ("OOFF", SEPASequenceType.OOFF),
            ("FNAL", SEPASequenceType.FNAL),
            ("CORE", SEPASequenceType.RCUR),  # CORE defaults to RCUR
            ("", SEPASequenceType.RCUR),  # Empty defaults to RCUR
            (None, SEPASequenceType.RCUR),  # None defaults to RCUR
            ("INVALID", SEPASequenceType.RCUR),  # Unknown defaults to RCUR
        ]

        for type_str, expected in test_cases:
            result = self.adapter._get_sequence_type(type_str)
            self.assertEqual(result, expected, f"Expected {expected} for '{type_str}', got {result}")

    def test_mandate_sign_date_from_invoice_item(self):
        """Test mandate sign date extraction from invoice item field"""
        mock_invoice = MagicMock()
        mock_invoice.mandate_sign_date = date(2024, 6, 15)
        mock_invoice.mandate_reference = "MAND-001"
        mock_invoice.member = None

        result_date, used_fallback = self.adapter._get_mandate_sign_date(mock_invoice)

        self.assertEqual(result_date, date(2024, 6, 15))
        self.assertFalse(used_fallback)

    def test_mandate_sign_date_from_invoice_item_string(self):
        """Test mandate sign date extraction when stored as string"""
        mock_invoice = MagicMock()
        mock_invoice.mandate_sign_date = "2024-06-15"
        mock_invoice.mandate_reference = "MAND-001"
        mock_invoice.member = None

        result_date, used_fallback = self.adapter._get_mandate_sign_date(mock_invoice)

        # getdate returns a date object from string
        self.assertEqual(result_date, date(2024, 6, 15))
        self.assertFalse(used_fallback)

    def test_mandate_sign_date_caching(self):
        """Test that mandate sign dates are cached"""
        # Pre-populate cache
        self.adapter._mandate_cache["MAND-001"] = {"sign_date": date(2024, 3, 10)}

        mock_invoice = MagicMock()
        mock_invoice.mandate_sign_date = None
        mock_invoice.mandate_reference = "MAND-001"
        mock_invoice.member = None

        result_date, used_fallback = self.adapter._get_mandate_sign_date(mock_invoice)

        self.assertEqual(result_date, date(2024, 3, 10))
        self.assertFalse(used_fallback)

    def test_mandate_sign_date_fallback_to_today(self):
        """Test mandate sign date falls back to today when no mandate found"""
        mock_invoice = MagicMock()
        mock_invoice.mandate_sign_date = None
        mock_invoice.mandate_reference = "NONEXISTENT-MANDATE"
        mock_invoice.member = None

        with patch.object(frappe.db, "get_value", return_value=None):
            result_date, used_fallback = self.adapter._get_mandate_sign_date(mock_invoice)

        self.assertEqual(result_date, date.today())
        self.assertTrue(used_fallback)  # Should indicate fallback was used

    def test_clear_cache(self):
        """Test cache clearing"""
        self.adapter._mandate_cache["MAND-001"] = {"sign_date": date(2024, 1, 1)}
        self.adapter._mandate_cache["MAND-002"] = {"sign_date": date(2024, 2, 2)}

        self.assertEqual(len(self.adapter._mandate_cache), 2)

        self.adapter.clear_cache()

        self.assertEqual(len(self.adapter._mandate_cache), 0)

    def test_build_transaction_basic(self):
        """Test basic transaction building from invoice item"""
        mock_invoice = MagicMock()
        mock_invoice.invoice = "INV-2024-001"
        mock_invoice.amount = 50.00
        mock_invoice.currency = "EUR"
        mock_invoice.member_name = "Jan de Vries"
        mock_invoice.iban = "NL91ABNA0417164300"
        mock_invoice.bic = "ABNANL2A"
        mock_invoice.mandate_reference = "MAND-001"
        mock_invoice.mandate_sign_date = date(2024, 1, 15)
        mock_invoice.member = "MEM-001"
        mock_invoice.sequence_type = "RCUR"

        transaction = self.adapter._build_transaction(mock_invoice, SEPASequenceType.RCUR)

        self.assertIsNotNone(transaction)
        # EndToEndId should NOT double-prefix if invoice already has INV- prefix
        self.assertEqual(transaction.end_to_end_id, "INV-2024-001")
        self.assertEqual(transaction.amount, Decimal("50.00"))
        self.assertEqual(transaction.currency, "EUR")
        self.assertEqual(transaction.debtor.name, "Jan de Vries")
        self.assertEqual(transaction.debtor.iban, "NL91ABNA0417164300")
        self.assertEqual(transaction.mandate.mandate_id, "MAND-001")
        self.assertEqual(transaction.mandate.date_of_signature, date(2024, 1, 15))
        self.assertEqual(transaction.sequence_type, SEPASequenceType.RCUR)

    def test_build_transaction_uses_invoice_sequence_type(self):
        """Test that invoice-level sequence type overrides batch default"""
        mock_invoice = MagicMock()
        mock_invoice.invoice = "INV-2024-001"
        mock_invoice.amount = 50.00
        mock_invoice.currency = "EUR"
        mock_invoice.member_name = "Jan de Vries"
        mock_invoice.iban = "NL91ABNA0417164300"
        mock_invoice.bic = None
        mock_invoice.mandate_reference = "MAND-001"
        mock_invoice.mandate_sign_date = date(2024, 1, 15)
        mock_invoice.member = None
        mock_invoice.sequence_type = "FRST"  # Invoice has FRST

        transaction = self.adapter._build_transaction(
            mock_invoice, SEPASequenceType.RCUR  # Batch default is RCUR
        )

        # Invoice-level FRST should override batch RCUR
        self.assertEqual(transaction.sequence_type, SEPASequenceType.FRST)

    def test_singleton_instance(self):
        """Test that get_sepa_xml_adapter returns singleton"""
        adapter1 = get_sepa_xml_adapter()
        adapter2 = get_sepa_xml_adapter()

        self.assertIs(adapter1, adapter2)

    def test_end_to_end_id_no_double_prefix(self):
        """Test that EndToEndId doesn't double-prefix INV-"""
        mock_invoice = MagicMock()
        mock_invoice.invoice = "INV-2024-001"  # Already has INV- prefix
        mock_invoice.amount = 50.00
        mock_invoice.currency = "EUR"
        mock_invoice.member_name = "Test Member"
        mock_invoice.iban = "NL91ABNA0417164300"
        mock_invoice.bic = None
        mock_invoice.mandate_reference = "MAND-001"
        mock_invoice.mandate_sign_date = date(2024, 1, 15)
        mock_invoice.member = None
        mock_invoice.sequence_type = None

        self.adapter._validation_summary = None  # Reset
        transaction = self.adapter._build_transaction(mock_invoice, SEPASequenceType.RCUR)

        # Should NOT be INV-INV-2024-001
        self.assertEqual(transaction.end_to_end_id, "INV-2024-001")

    def test_end_to_end_id_adds_prefix_when_missing(self):
        """Test that EndToEndId adds INV- prefix when not present"""
        mock_invoice = MagicMock()
        mock_invoice.invoice = "2024-001"  # No INV- prefix
        mock_invoice.amount = 50.00
        mock_invoice.currency = "EUR"
        mock_invoice.member_name = "Test Member"
        mock_invoice.iban = "NL91ABNA0417164300"
        mock_invoice.bic = None
        mock_invoice.mandate_reference = "MAND-001"
        mock_invoice.mandate_sign_date = date(2024, 1, 15)
        mock_invoice.member = None
        mock_invoice.sequence_type = None

        self.adapter._validation_summary = None  # Reset
        transaction = self.adapter._build_transaction(mock_invoice, SEPASequenceType.RCUR)

        # Should add prefix
        self.assertEqual(transaction.end_to_end_id, "INV-2024-001")


class TestBatchValidationSummary(FrappeTestCase):
    """Tests for BatchValidationSummary dataclass"""

    def test_validation_summary_initialization(self):
        """Test default values"""
        summary = BatchValidationSummary()

        self.assertEqual(summary.total_invoices, 0)
        self.assertEqual(summary.successful_transactions, 0)
        self.assertEqual(summary.skipped_transactions, 0)
        self.assertEqual(summary.missing_mandate_dates, 0)
        self.assertEqual(summary.skipped_invoice_details, [])

    def test_has_issues_false_when_clean(self):
        """Test has_issues returns False when no issues"""
        summary = BatchValidationSummary(
            total_invoices=10,
            successful_transactions=10,
        )

        self.assertFalse(summary.has_issues)

    def test_has_issues_true_when_skipped(self):
        """Test has_issues returns True when transactions skipped"""
        summary = BatchValidationSummary(
            total_invoices=10,
            successful_transactions=9,
            skipped_transactions=1,
        )

        self.assertTrue(summary.has_issues)

    def test_has_issues_true_when_missing_dates(self):
        """Test has_issues returns True when mandate dates missing"""
        summary = BatchValidationSummary(
            total_invoices=10,
            successful_transactions=10,
            missing_mandate_dates=2,
        )

        self.assertTrue(summary.has_issues)

    def test_add_skipped(self):
        """Test adding skipped transaction details"""
        summary = BatchValidationSummary()

        summary.add_skipped("INV-001", "Missing IBAN")
        summary.add_skipped("INV-002", "Invalid amount")

        self.assertEqual(summary.skipped_transactions, 2)
        self.assertEqual(len(summary.skipped_invoice_details), 2)
        self.assertEqual(summary.skipped_invoice_details[0]["invoice"], "INV-001")
        self.assertEqual(summary.skipped_invoice_details[0]["reason"], "Missing IBAN")


class TestSEPAXMLAdapterIntegration(FrappeTestCase):
    """Integration tests for SEPA XML adapter with database"""

    @classmethod
    def setUpClass(cls):
        """Set up SEPA configuration for testing"""
        super().setUpClass()
        cls._setup_sepa_test_configuration()

    @classmethod
    def _setup_sepa_test_configuration(cls):
        """Configure SEPA settings for testing"""
        try:
            # Try to get payments settings
            settings = frappe.get_single("Verenigingen Payments Settings")
            settings.creditor_id = "NL12ZZZ123456789"
            settings.company_iban = "NL91ABNA0417164300"
            settings.company_bic = "ABNANL2A"
            settings.company_account_holder = "Test Vereniging"
            settings.save()
            frappe.db.commit()
        except Exception as e:
            # get_harness_logger, NOT frappe.logger(): the settings written here are
            # what the assertions below depend on; a bare logger sends the reason to
            # logs/frappe.log, which CI does not upload.
            get_harness_logger("sepa-xml-adapter").warning("SEPA test configuration setup failed: %s", e)

    def test_prefetch_mandate_data(self):
        """Test bulk prefetching of mandate data"""
        adapter = SEPAXMLAdapter()

        # Create mock invoices
        mock_invoices = []
        for i in range(3):
            mock_inv = MagicMock()
            mock_inv.mandate_sign_date = None  # No sign date on invoice
            mock_inv.mandate_reference = f"MAND-TEST-{i}"
            mock_invoices.append(mock_inv)

        # Should not fail even with no mandates in DB
        adapter._prefetch_mandate_data(mock_invoices)

        # Cache should still be empty if no mandates exist
        # but the method should complete without error

    def test_mandate_sign_date_not_hardcoded(self):
        """
        Test that mandate sign date is NOT hardcoded to 2023-01-01.

        This is the key fix that this consolidation addresses.
        """
        adapter = SEPAXMLAdapter()

        # Test with actual date on invoice item
        mock_invoice = MagicMock()
        mock_invoice.mandate_sign_date = date(2024, 8, 20)
        mock_invoice.mandate_reference = "MAND-001"
        mock_invoice.member = None

        # _get_mandate_sign_date returns (sign_date, used_fallback).
        result, used_fallback = adapter._get_mandate_sign_date(mock_invoice)

        # Should NOT be 2023-01-01
        self.assertNotEqual(result, date(2023, 1, 1))
        # Should be the actual date (and not a today() fallback)
        self.assertEqual(result, date(2024, 8, 20))
        self.assertFalse(used_fallback)


class TestSEPAXMLAdapterXMLGeneration(FrappeTestCase):
    """Tests for XML generation via adapter"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.adapter = SEPAXMLAdapter()

    def test_xml_contains_correct_mandate_sign_date(self):
        """
        Test that generated XML contains correct mandate sign dates.

        This is the critical test that verifies the fix for the hardcoded
        DtOfSgntr = "2023-01-01" issue.
        """
        # Create a mock batch document
        mock_batch = MagicMock()
        mock_batch.name = "BATCH-TEST-001"
        mock_batch.batch_date = date.today()
        mock_batch.batch_type = "CORE"  # SEPA scheme -> LclInstrm
        mock_batch.sequence_type = "RCUR"  # SEPA sequence -> SeqTp (adapter reads this)
        mock_batch.entry_count = 1
        mock_batch.total_amount = 50.00

        # Create mock invoice with specific sign date
        mock_invoice = MagicMock()
        mock_invoice.invoice = "INV-2024-001"
        mock_invoice.amount = 50.00
        mock_invoice.currency = "EUR"
        mock_invoice.member_name = "Test Member"
        mock_invoice.iban = "NL91ABNA0417164300"
        mock_invoice.bic = "ABNANL2A"
        mock_invoice.mandate_reference = "MAND-TEST-001"
        mock_invoice.mandate_sign_date = date(2024, 6, 15)  # Specific date
        mock_invoice.member = None
        mock_invoice.sequence_type = "RCUR"

        mock_batch.invoices = [mock_invoice]

        # Mock SEPA configuration
        mock_settings = {
            "organization_name": "Test Vereniging",
            "iban": "NL91ABNA0417164300",
            "bic": "ABNANL2A",
            "creditor_id": "NL12ZZZ123456789",
        }

        # Patch only the settings source. The adapter then builds a real
        # SEPACreditor from this dict via _build_creditor_from_settings; the
        # previous code additionally stubbed that builder to a bare MagicMock,
        # whose .name failed the SEPA character-set regex during validation.
        from verenigingen.verenigingen_payments.services.sepa_configuration_service import (
            sepa_config_service,
        )

        with patch.object(sepa_config_service, "get_sepa_settings", return_value=mock_settings):
            try:
                xml_string = self.adapter.generate_xml_for_batch(
                    batch_doc=mock_batch,
                    message_id="MSG-TEST-001",
                    payment_info_id="PMT-TEST-001",
                )

                # Parse XML and verify sign date
                root = ET.fromstring(xml_string)

                # Find DtOfSgntr elements
                ns = {"sepa": "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"}
                sign_dates = root.findall(".//sepa:DtOfSgntr", ns) or root.findall(
                    ".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}DtOfSgntr"
                )

                self.assertGreater(len(sign_dates), 0, "No DtOfSgntr element found in XML")

                # Verify the date is correct (2024-06-15), NOT the hardcoded 2023-01-01
                for sign_date_elem in sign_dates:
                    self.assertEqual(
                        sign_date_elem.text, "2024-06-15", f"Expected 2024-06-15, got {sign_date_elem.text}"
                    )
                    # Most importantly: NOT the old hardcoded value
                    self.assertNotEqual(
                        sign_date_elem.text,
                        "2023-01-01",
                        "DtOfSgntr still contains hardcoded 2023-01-01 value!",
                    )

            except Exception as e:
                # If configuration is incomplete, skip the test with informative message
                if "Missing required SEPA settings" in str(e):
                    self.skipTest(f"SEPA configuration incomplete: {str(e)}")
                raise

    def _mock_invoice(self, invoice_id, iban, member_name="Test Member"):
        inv = MagicMock()
        inv.invoice = invoice_id
        inv.amount = 50.00
        inv.currency = "EUR"
        inv.member_name = member_name
        inv.iban = iban
        inv.bic = "ABNANL2A"
        inv.mandate_reference = f"MAND-{invoice_id}"
        inv.mandate_sign_date = date(2024, 6, 15)
        inv.member = None
        inv.sequence_type = "RCUR"
        return inv

    def test_one_invalid_debtor_iban_skips_only_that_row(self):
        """A single bad debtor IBAN must skip ONLY that transaction, not abort the
        whole batch.

        Regression: debtor IBANs were validated only at the final XML-build step,
        which accumulated errors and raised for the ENTIRE batch ("SEPA validation
        failed: ... Invalid debtor IBAN"), so one bad IBAN stopped every other
        member's debit. The IBAN is now validated per-transaction so the offending
        row is skipped into the validation summary and the batch still generates.
        """
        mock_batch = MagicMock()
        mock_batch.name = "BATCH-IBAN-001"
        mock_batch.batch_date = date.today()
        mock_batch.batch_type = "CORE"
        mock_batch.sequence_type = "RCUR"
        mock_batch.entry_count = 2
        mock_batch.total_amount = 100.00
        mock_batch.invoices = [
            self._mock_invoice("INV-VALID-001", "NL91ABNA0417164300", "Valid Member"),
            self._mock_invoice("INV-BADIBAN-002", "NL00BANK0000000000", "Bad Iban Member"),
        ]

        mock_settings = {
            "organization_name": "Test Vereniging",
            "iban": "NL91ABNA0417164300",
            "bic": "ABNANL2A",
            "creditor_id": "NL12ZZZ123456789",
        }
        from verenigingen.verenigingen_payments.services.sepa_configuration_service import (
            sepa_config_service,
        )

        with patch.object(sepa_config_service, "get_sepa_settings", return_value=mock_settings):
            xml_string = self.adapter.generate_xml_for_batch(
                batch_doc=mock_batch,
                message_id="MSG-IBAN-001",
                payment_info_id="PMT-IBAN-001",
            )

        # Batch generated despite the bad IBAN, with exactly the one valid transaction.
        root = ET.fromstring(xml_string)
        txns = root.findall(".//{urn:iso:std:iso:20022:tech:xsd:pain.008.001.08}DrctDbtTxInf")
        self.assertEqual(len(txns), 1, "Only the valid-IBAN transaction should be in the XML")
        self.assertIn("NL91ABNA0417164300", xml_string)
        self.assertNotIn("NL00BANK0000000000", xml_string)
        # The bad row is recorded as skipped, not silently dropped.
        self.assertEqual(self.adapter._validation_summary.skipped_transactions, 1)


if __name__ == "__main__":
    unittest.main()
