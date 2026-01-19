"""
Tests for eBoekhouden Import Error Handling

Tests graceful handling of:
- Malformed mutation data
- Duplicate detection
- Account/ledger mapping failures
- Amount validation failures
- Payment gateway edge cases
- PII masking in error logs

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_import_error_handling
"""

import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

from frappe.exceptions import DuplicateEntryError

from verenigingen.e_boekhouden.utils.data_integrity import (
    _mask_value,
    _should_mask_field,
    insert_with_duplicate_handling,
    mask_pii_in_mutation,
    submit_with_duplicate_handling,
)
from verenigingen.tests.e_boekhouden.fixtures import (
    MUTATION_EMPTY_ROWS,
    MUTATION_INVALID_AMOUNT,
    MUTATION_MISSING_DATE,
    MUTATION_MISSING_ID,
    MUTATION_MISSING_TYPE,
    MUTATION_MOLLIE_ADJUSTMENT,
    MUTATION_MOLLIE_FIRST_PAYMENT,
    MUTATION_NULL_ROWS,
    MUTATION_ROW_MISSING_LEDGER,
    MUTATION_ROW_SUM_MISMATCH,
    MUTATION_TYPE_3_NEGATIVE_ROW_AMOUNT,
    MUTATION_WITH_DUTCH_PII_FIELDS,
    MUTATION_WITH_PII,
    get_all_malformed_mutations,
)


class TestMalformedMutationData(unittest.TestCase):
    """Test handling of malformed mutation data"""

    def setUp(self):
        """Set up mock processors"""
        self.frappe_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        )
        self.mock_frappe = self.frappe_patcher.start()
        self.mock_frappe.db.get_value.return_value = "Default Cost Center"

    def tearDown(self):
        """Clean up patches"""
        self.frappe_patcher.stop()

    def test_missing_id_handled(self):
        """Test that missing ID field is handled gracefully"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_MISSING_ID)

        # Should not raise an exception when getting amount
        result = processor.get_amount(mutation)
        self.assertEqual(result, 100.0)

    def test_missing_date_handled(self):
        """Test that missing date field returns empty string"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_MISSING_DATE)

        result = processor.get_posting_date(mutation)
        self.assertEqual(result, "")

    def test_missing_type_defaults_to_journal_entry(self):
        """Test that missing type field defaults to Journal Entry"""
        from verenigingen.e_boekhouden.utils.eboekhouden_transaction_type_mapper import (
            simplify_migration_process,
        )

        mutation = deepcopy(MUTATION_MISSING_TYPE)
        result = simplify_migration_process(mutation)

        self.assertEqual(result["document_type"], "Journal Entry")
        self.assertEqual(result["confidence"], "low")

    def test_empty_rows_array(self):
        """Test handling of empty rows array"""
        mutation = deepcopy(MUTATION_EMPTY_ROWS)
        rows = mutation.get("rows", [])

        self.assertEqual(len(rows), 0)

    def test_null_rows_handled(self):
        """Test handling of null rows field"""
        mutation = deepcopy(MUTATION_NULL_ROWS)
        rows = mutation.get("rows") or []

        self.assertEqual(len(rows), 0)

    def test_invalid_amount_returns_zero(self):
        """Test that invalid amount returns 0.0"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_INVALID_AMOUNT)

        # Should return 0.0 for non-numeric amount
        result = processor.get_amount(mutation)
        self.assertEqual(result, 0.0)


class TestDuplicateDetection(unittest.TestCase):
    """Test duplicate detection and handling"""

    @patch("verenigingen.e_boekhouden.utils.data_integrity.frappe")
    def test_insert_with_duplicate_handling_success(self, mock_frappe):
        """Test successful insert (no duplicate)"""
        mock_doc = MagicMock()
        mock_doc.doctype = "Journal Entry"
        mock_doc.eboekhouden_mutation_nr = "12345"

        result_doc, was_duplicate = insert_with_duplicate_handling(mock_doc)

        mock_doc.insert.assert_called_once()
        self.assertEqual(result_doc, mock_doc)
        self.assertFalse(was_duplicate)

    @patch("verenigingen.e_boekhouden.utils.data_integrity.frappe")
    def test_insert_with_duplicate_handling_race_condition(self, mock_frappe):
        """Test duplicate insert handling (race condition)"""
        mock_doc = MagicMock()
        mock_doc.doctype = "Journal Entry"
        mock_doc.eboekhouden_mutation_nr = "12345"
        mock_doc.insert.side_effect = DuplicateEntryError()

        mock_frappe.db.get_value.return_value = "JE-00001"
        mock_existing = MagicMock()
        mock_frappe.get_doc.return_value = mock_existing

        result_doc, was_duplicate = insert_with_duplicate_handling(mock_doc)

        mock_frappe.db.get_value.assert_called_once_with(
            "Journal Entry",
            {"eboekhouden_mutation_nr": "12345"},
            "name",
        )
        self.assertEqual(result_doc, mock_existing)
        self.assertTrue(was_duplicate)

    @patch("verenigingen.e_boekhouden.utils.data_integrity.frappe")
    def test_submit_with_duplicate_handling_new_doc(self, mock_frappe):
        """Test submit_with_duplicate_handling for new document"""
        mock_doc = MagicMock()
        mock_doc.doctype = "Journal Entry"
        mock_doc.eboekhouden_mutation_nr = "12345"

        result_doc, was_duplicate = submit_with_duplicate_handling(mock_doc)

        mock_doc.insert.assert_called_once()
        mock_doc.submit.assert_called_once()
        self.assertEqual(result_doc, mock_doc)
        self.assertFalse(was_duplicate)

    @patch("verenigingen.e_boekhouden.utils.data_integrity.frappe")
    def test_submit_with_duplicate_handling_existing_doc(self, mock_frappe):
        """Test submit_with_duplicate_handling for existing document (race condition)"""
        mock_doc = MagicMock()
        mock_doc.doctype = "Journal Entry"
        mock_doc.eboekhouden_mutation_nr = "12345"
        mock_doc.insert.side_effect = DuplicateEntryError()

        mock_frappe.db.get_value.return_value = "JE-00001"
        mock_existing = MagicMock()
        mock_frappe.get_doc.return_value = mock_existing

        result_doc, was_duplicate = submit_with_duplicate_handling(mock_doc)

        # Submit should NOT be called for existing doc
        mock_doc.submit.assert_not_called()
        self.assertEqual(result_doc, mock_existing)
        self.assertTrue(was_duplicate)


class TestBaseProcessorDuplicateCheck(unittest.TestCase):
    """Test base processor duplicate check method"""

    def setUp(self):
        """Set up mock processors"""
        self.frappe_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        )
        self.mock_frappe = self.frappe_patcher.start()
        self.mock_frappe.db.get_value.return_value = None  # No duplicate by default

    def tearDown(self):
        """Clean up patches"""
        self.frappe_patcher.stop()

    def test_check_duplicate_returns_none_when_not_found(self):
        """Test that check_duplicate returns None when no duplicate exists"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        result = processor.check_duplicate("12345", "Journal Entry")

        self.assertIsNone(result)

    def test_check_duplicate_returns_name_when_found(self):
        """Test that check_duplicate returns document name when found"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        self.mock_frappe.db.get_value.return_value = "JE-00001"

        processor = TestProcessor(company="Test Company")
        result = processor.check_duplicate("12345", "Journal Entry")

        self.assertEqual(result, "JE-00001")


class TestPiiMaskingInErrorLogs(unittest.TestCase):
    """Test PII masking in error logs"""

    def test_mask_value_none(self):
        """Test None value handling"""
        self.assertIsNone(_mask_value(None))

    def test_mask_value_short(self):
        """Test values 4 characters or shorter"""
        self.assertEqual(_mask_value("ab"), "***")
        self.assertEqual(_mask_value("abc"), "***")
        self.assertEqual(_mask_value("abcd"), "***")

    def test_mask_value_longer(self):
        """Test values longer than 4 characters"""
        self.assertEqual(_mask_value("john@example.com"), "jo***om")
        self.assertEqual(_mask_value("0612345678"), "06***78")
        self.assertEqual(_mask_value("NL91ABNA0417164300"), "NL***00")

    def test_mask_value_non_string(self):
        """Test that non-string values are converted"""
        self.assertEqual(_mask_value(12345), "12***45")

    def test_should_mask_field_exact_matches(self):
        """Test exact field name matches"""
        self.assertTrue(_should_mask_field("email"))
        self.assertTrue(_should_mask_field("phone"))
        self.assertTrue(_should_mask_field("mobile"))
        self.assertTrue(_should_mask_field("iban"))
        self.assertTrue(_should_mask_field("address"))
        self.assertTrue(_should_mask_field("name"))

    def test_should_mask_field_dutch_names(self):
        """Test Dutch field name variations"""
        self.assertTrue(_should_mask_field("emailadres"))
        self.assertTrue(_should_mask_field("telefoon"))
        self.assertTrue(_should_mask_field("telefoonnummer"))
        self.assertTrue(_should_mask_field("adres"))
        self.assertTrue(_should_mask_field("straat"))
        self.assertTrue(_should_mask_field("voornaam"))
        self.assertTrue(_should_mask_field("achternaam"))
        self.assertTrue(_should_mask_field("bankrekeningnummer"))
        self.assertTrue(_should_mask_field("btwnummer"))
        self.assertTrue(_should_mask_field("kvknummer"))
        self.assertTrue(_should_mask_field("bsn"))

    def test_should_mask_field_case_insensitive(self):
        """Test case-insensitive matching"""
        self.assertTrue(_should_mask_field("EMAIL"))
        self.assertTrue(_should_mask_field("Email"))
        self.assertTrue(_should_mask_field("PHONE"))
        self.assertTrue(_should_mask_field("IBAN"))

    def test_should_mask_field_partial_matches(self):
        """Test that partial matches work"""
        self.assertTrue(_should_mask_field("customer_email"))
        self.assertTrue(_should_mask_field("contact_phone"))
        self.assertTrue(_should_mask_field("billing_address"))

    def test_should_not_mask_non_pii_fields(self):
        """Test that non-PII fields are not masked"""
        self.assertFalse(_should_mask_field("amount"))
        self.assertFalse(_should_mask_field("date"))
        self.assertFalse(_should_mask_field("id"))
        self.assertFalse(_should_mask_field("description"))
        self.assertFalse(_should_mask_field("type"))
        self.assertFalse(_should_mask_field("ledgerId"))

    def test_mask_pii_in_mutation_simple(self):
        """Test masking simple mutation with PII fields"""
        mutation = {
            "id": 12345,
            "amount": 100.50,
            "email": "john@example.com",
            "phone": "0612345678",
            "description": "Test transaction",
        }

        masked = mask_pii_in_mutation(mutation)

        # Non-PII fields unchanged
        self.assertEqual(masked["id"], 12345)
        self.assertEqual(masked["amount"], 100.50)
        self.assertEqual(masked["description"], "Test transaction")

        # PII fields masked
        self.assertEqual(masked["email"], "jo***om")
        self.assertEqual(masked["phone"], "06***78")

    def test_mask_pii_in_mutation_nested(self):
        """Test masking nested mutation structures"""
        mutation = {
            "id": 12345,
            "relation": {
                "name": "John Doe",
                "email": "john@example.com",
                "address": "123 Main Street",
            },
        }

        masked = mask_pii_in_mutation(mutation)

        self.assertEqual(masked["relation"]["name"], "Jo***oe")
        self.assertEqual(masked["relation"]["email"], "jo***om")
        self.assertEqual(masked["relation"]["address"], "12***et")

    def test_mask_pii_in_mutation_list(self):
        """Test masking mutation with list of nested dicts"""
        mutation = {
            "id": 12345,
            "rows": [
                {"ledgerId": 1000, "name": "John Doe"},
                {"ledgerId": 2000, "name": "Jane Smith"},
            ],
        }

        masked = mask_pii_in_mutation(mutation)

        self.assertEqual(masked["rows"][0]["ledgerId"], 1000)
        self.assertEqual(masked["rows"][0]["name"], "Jo***oe")
        self.assertEqual(masked["rows"][1]["name"], "Ja***th")

    def test_mask_pii_original_unchanged(self):
        """Test that original mutation is not modified"""
        mutation = {
            "id": 12345,
            "email": "john@example.com",
        }

        masked = mask_pii_in_mutation(mutation)

        # Original unchanged
        self.assertEqual(mutation["email"], "john@example.com")
        # Masked version changed
        self.assertEqual(masked["email"], "jo***om")

    def test_mask_pii_empty_and_none(self):
        """Test empty and None mutation handling"""
        self.assertEqual(mask_pii_in_mutation({}), {})
        self.assertIsNone(mask_pii_in_mutation(None))

    def test_mask_pii_fixture_with_pii(self):
        """Test masking fixture with PII"""
        mutation = deepcopy(MUTATION_WITH_PII)
        masked = mask_pii_in_mutation(mutation)

        # Check that PII fields are masked
        self.assertIn("***", masked["email"])
        self.assertIn("***", masked["phone"])
        self.assertIn("***", masked["iban"])
        self.assertIn("***", masked["address"])

        # Check nested relation
        self.assertIn("***", masked["relation"]["name"])
        self.assertIn("***", masked["relation"]["email"])

    def test_mask_pii_fixture_dutch_fields(self):
        """Test masking fixture with Dutch PII field names"""
        mutation = deepcopy(MUTATION_WITH_DUTCH_PII_FIELDS)
        masked = mask_pii_in_mutation(mutation)

        # Check that Dutch PII fields are masked
        self.assertIn("***", masked["emailadres"])
        self.assertIn("***", masked["telefoon"])
        self.assertIn("***", masked["telefoonnummer"])
        self.assertIn("***", masked["adres"])
        self.assertIn("***", masked["voornaam"])
        self.assertIn("***", masked["achternaam"])
        self.assertIn("***", masked["bankrekeningnummer"])
        self.assertIn("***", masked["btwnummer"])
        self.assertIn("***", masked["kvknummer"])
        self.assertIn("***", masked["bsn"])


class TestNegativeRowAmountWarning(unittest.TestCase):
    """Test warning for negative row amounts (unsigned assumption violation)"""

    def setUp(self):
        """Set up patches"""
        self.frappe_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.payment_processor.frappe"
        )
        self.mock_frappe = self.frappe_patcher.start()
        self.mock_frappe.db.get_value.return_value = None
        self.mock_frappe.get_single.return_value = MagicMock(
            get=MagicMock(return_value=None)
        )

        self.base_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        )
        self.mock_base_frappe = self.base_patcher.start()
        self.mock_base_frappe.db.get_value.return_value = "Default Cost Center"

        self.log_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.payment_processor.safe_log_mutation_error"
        )
        self.mock_log = self.log_patcher.start()

    def tearDown(self):
        """Clean up patches"""
        self.frappe_patcher.stop()
        self.base_patcher.stop()
        self.log_patcher.stop()

    def test_negative_row_amount_logs_warning(self):
        """Test that negative row amount triggers warning log"""
        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        processor = PaymentProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_TYPE_3_NEGATIVE_ROW_AMOUNT)

        # Call can_process to trigger the warning check
        processor.can_process(mutation)

        # Check debug_info contains warning
        debug_info = processor.get_debug_info()
        warning_found = any("WARNING" in msg or "negative" in msg.lower() for msg in debug_info)

        self.assertTrue(
            warning_found,
            f"Expected warning about negative row amount. Debug info: {debug_info}",
        )


class TestPaymentGatewayEdgeCases(unittest.TestCase):
    """Test payment gateway (Mollie) edge cases"""

    def setUp(self):
        """Set up patches"""
        self.frappe_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.payment_processor.frappe"
        )
        self.mock_frappe = self.frappe_patcher.start()
        self.mock_frappe.utils.flt = lambda x, precision=None: round(float(x or 0), precision or 2)

        self.base_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        )
        self.mock_base_frappe = self.base_patcher.start()
        self.mock_base_frappe.db.get_value.return_value = "Default Cost Center"

    def tearDown(self):
        """Clean up patches"""
        self.frappe_patcher.stop()
        self.base_patcher.stop()

    def test_gateway_not_configured_skips_logic(self):
        """Test that gateway logic is skipped when not configured"""
        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        # Settings without gateway config
        mock_settings = MagicMock()
        mock_settings.get.return_value = None
        self.mock_frappe.get_single.return_value = mock_settings

        processor = PaymentProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_MOLLIE_FIRST_PAYMENT)

        # Should return False (not detected as gateway adjustment)
        result = processor._is_payment_gateway_adjustment(mutation)

        self.assertFalse(result)

    def test_gateway_configured_detects_adjustment(self):
        """Test that gateway adjustment is detected when configured"""
        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        # Settings with gateway config
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key: {
            "payment_gateway_virtual_account": "1150 - Mollie Virtual - NVV",
            "payment_gateway_invoice_prefix": "MOLLIE-",
        }.get(key)
        self.mock_frappe.get_single.return_value = mock_settings

        # Mock ledger mapping lookup - this is the only db.get_value in payment_processor
        # (cost center lookup happens in base_processor which has its own patch)
        self.mock_frappe.db.get_value.return_value = "1150"  # Gateway ledger lookup

        # Mock invoice exists and is paid
        self.mock_frappe.get_all.return_value = [
            {"name": "PINV-00001", "grand_total": 100.00, "outstanding_amount": 0}
        ]

        # Mock flt for outstanding amount check
        self.mock_frappe.utils.flt = lambda x, precision=None: round(float(x or 0), precision or 2)

        processor = PaymentProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_MOLLIE_ADJUSTMENT)
        mutation["ledgerId"] = 1150  # Match the gateway ledger (as int to match str conversion)

        result = processor._is_payment_gateway_adjustment(mutation)

        # Should detect as adjustment (invoice already paid)
        self.assertTrue(result)

    def test_gateway_invoice_not_found_processes_normally(self):
        """Test that mutation processes normally if gateway invoice not found"""
        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        # Settings with gateway config
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda key: {
            "payment_gateway_virtual_account": "1150 - Mollie Virtual - NVV",
            "payment_gateway_invoice_prefix": "MOLLIE-",
        }.get(key)
        self.mock_frappe.get_single.return_value = mock_settings

        # Mock ledger mapping lookup
        self.mock_frappe.db.get_value.side_effect = [
            "Default Cost Center",  # Cost center lookup
            "1150",  # Gateway ledger lookup
        ]

        # Mock invoice NOT found
        self.mock_frappe.get_all.return_value = []

        processor = PaymentProcessor(company="Test Company")
        mutation = deepcopy(MUTATION_MOLLIE_FIRST_PAYMENT)
        mutation["ledgerId"] = 1150

        result = processor._is_payment_gateway_adjustment(mutation)

        # Should not be detected as adjustment (invoice not found)
        self.assertFalse(result)


class TestErrorFormatting(unittest.TestCase):
    """Test error formatting for logging"""

    def setUp(self):
        """Set up mock processors"""
        self.frappe_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        )
        self.mock_frappe = self.frappe_patcher.start()
        self.mock_frappe.db.get_value.return_value = "Default Cost Center"

    def tearDown(self):
        """Clean up patches"""
        self.frappe_patcher.stop()

    def test_format_error_includes_mutation_info(self):
        """Test that format_error includes mutation info"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {
            "MutatieNr": "12345",
            "Datum": "2025-01-15",
            "Omschrijving": "Test transaction",
        }
        error = ValueError("Test error")

        result = processor.format_error(mutation, error)

        self.assertEqual(result["mutation_id"], "12345")
        self.assertEqual(result["date"], "2025-01-15")
        self.assertEqual(result["description"], "Test transaction")
        self.assertEqual(result["error_type"], "ValueError")
        self.assertEqual(result["error_message"], "Test error")

    def test_format_error_handles_missing_fields(self):
        """Test that format_error handles missing mutation fields"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {}  # Empty mutation
        error = RuntimeError("Another error")

        result = processor.format_error(mutation, error)

        self.assertEqual(result["mutation_id"], "Unknown")
        self.assertEqual(result["date"], "Unknown")
        self.assertEqual(result["description"], "Unknown")
        self.assertEqual(result["error_type"], "RuntimeError")


class TestMutationValidation(unittest.TestCase):
    """Test mutation validation"""

    def setUp(self):
        """Set up mock processors"""
        self.frappe_patcher = patch(
            "verenigingen.e_boekhouden.utils.processors.base_processor.frappe"
        )
        self.mock_frappe = self.frappe_patcher.start()
        self.mock_frappe.db.get_value.return_value = "Default Cost Center"

    def tearDown(self):
        """Clean up patches"""
        self.frappe_patcher.stop()

    def test_validate_mutation_valid(self):
        """Test validation passes for valid mutation"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {
            "MutatieNr": "12345",
            "Datum": "2025-01-15",
            "Omschrijving": "Test transaction",
        }

        is_valid, error_msg = processor.validate_mutation(mutation)

        self.assertTrue(is_valid)
        self.assertEqual(error_msg, "")

    def test_validate_mutation_missing_mutation_nr(self):
        """Test validation fails for missing MutatieNr"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {
            "Datum": "2025-01-15",
            "Omschrijving": "Test transaction",
        }

        is_valid, error_msg = processor.validate_mutation(mutation)

        self.assertFalse(is_valid)
        self.assertIn("MutatieNr", error_msg)

    def test_validate_mutation_missing_datum(self):
        """Test validation fails for missing Datum"""
        from verenigingen.e_boekhouden.utils.processors.base_processor import (
            BaseTransactionProcessor,
        )

        class TestProcessor(BaseTransactionProcessor):
            def can_process(self, mutation):
                return True

            def process(self, mutation):
                return None

        processor = TestProcessor(company="Test Company")
        mutation = {
            "MutatieNr": "12345",
            "Omschrijving": "Test transaction",
        }

        is_valid, error_msg = processor.validate_mutation(mutation)

        self.assertFalse(is_valid)
        self.assertIn("Datum", error_msg)


if __name__ == "__main__":
    unittest.main()
