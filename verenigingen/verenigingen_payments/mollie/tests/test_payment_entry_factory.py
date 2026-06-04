"""
Payment Entry Factory Unit Tests
================================

Tests for the PaymentEntryFactory class to ensure:
- Input validation (mollie_data shape, required fields)
- Decimal arithmetic handling
- Idempotency behavior
- Orphan cleanup on submit failure
- Edge cases and error handling
"""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import PaymentContext
from verenigingen.verenigingen_payments.mollie.services.shared.payment_entry_factory import (
    PAYMENT_ENTRY_REMARKS_MAX_LENGTH,
    PAYMENT_ENTRY_TITLE_MAX_LENGTH,
    MollieDataValidationError,
    PaymentEntryFactory,
)


class TestPaymentEntryFactoryValidation(unittest.TestCase):
    """Tests for input validation in PaymentEntryFactory."""

    def setUp(self):
        self.factory = PaymentEntryFactory()

    def test_validate_mollie_data_missing_payment_id(self):
        """Test validation fails when payment_id is missing."""
        mollie_data = {"amount": "100.00"}

        with self.assertRaises(MollieDataValidationError) as ctx:
            self.factory._validate_and_extract_mollie_data(mollie_data)

        self.assertIn("payment_id", str(ctx.exception))

    def test_validate_mollie_data_missing_amount(self):
        """Test validation fails when amount is missing."""
        mollie_data = {"payment_id": "tr_test123"}

        with self.assertRaises(MollieDataValidationError) as ctx:
            self.factory._validate_and_extract_mollie_data(mollie_data)

        self.assertIn("amount", str(ctx.exception))

    def test_validate_mollie_data_invalid_type(self):
        """Test validation fails when mollie_data is not a dict."""
        with self.assertRaises(MollieDataValidationError) as ctx:
            self.factory._validate_and_extract_mollie_data("not a dict")

        self.assertIn("dictionary", str(ctx.exception))

    def test_validate_mollie_data_invalid_payment_id_type(self):
        """Test validation fails when payment_id is not a string."""
        mollie_data = {"payment_id": 12345, "amount": "100.00"}

        with self.assertRaises(MollieDataValidationError) as ctx:
            self.factory._validate_and_extract_mollie_data(mollie_data)

        self.assertIn("string", str(ctx.exception))

    def test_validate_mollie_data_invalid_amount_value(self):
        """Test validation fails when amount is not numeric."""
        mollie_data = {"payment_id": "tr_test123", "amount": "not_a_number"}

        with self.assertRaises(MollieDataValidationError) as ctx:
            self.factory._validate_and_extract_mollie_data(mollie_data)

        self.assertIn("Invalid amount", str(ctx.exception))

    def test_validate_mollie_data_zero_amount(self):
        """Test validation fails when amount is zero."""
        mollie_data = {"payment_id": "tr_test123", "amount": "0.00"}

        with self.assertRaises(MollieDataValidationError) as ctx:
            self.factory._validate_and_extract_mollie_data(mollie_data)

        self.assertIn("positive", str(ctx.exception))

    def test_validate_mollie_data_negative_amount(self):
        """Test validation fails when amount is negative."""
        mollie_data = {"payment_id": "tr_test123", "amount": "-10.00"}

        with self.assertRaises(MollieDataValidationError) as ctx:
            self.factory._validate_and_extract_mollie_data(mollie_data)

        self.assertIn("positive", str(ctx.exception))


class TestPaymentEntryFactoryDecimalHandling(unittest.TestCase):
    """Tests for Decimal arithmetic in PaymentEntryFactory."""

    def setUp(self):
        self.factory = PaymentEntryFactory()

    def test_amount_converted_to_decimal(self):
        """Test that amount is converted to Decimal correctly."""
        mollie_data = {"payment_id": "tr_test123", "amount": "100.50"}

        payment_id, amount = self.factory._validate_and_extract_mollie_data(mollie_data)

        self.assertIsInstance(amount, Decimal)
        self.assertEqual(amount, Decimal("100.50"))

    def test_amount_from_float_string(self):
        """Test that float string amount is converted correctly."""
        mollie_data = {"payment_id": "tr_test123", "amount": "99.99"}

        _, amount = self.factory._validate_and_extract_mollie_data(mollie_data)

        self.assertEqual(amount, Decimal("99.99"))

    def test_amount_quantized_to_two_decimals(self):
        """Test that amount is quantized to 2 decimal places."""
        mollie_data = {"payment_id": "tr_test123", "amount": "100.555"}

        _, amount = self.factory._validate_and_extract_mollie_data(mollie_data)

        # ROUND_HALF_UP: 100.555 -> 100.56
        self.assertEqual(amount, Decimal("100.56"))

    def test_amount_from_integer_string(self):
        """Test that integer string amount is converted correctly."""
        mollie_data = {"payment_id": "tr_test123", "amount": "100"}

        _, amount = self.factory._validate_and_extract_mollie_data(mollie_data)

        self.assertEqual(amount, Decimal("100.00"))

    def test_amount_from_numeric_value(self):
        """Test that numeric (float/int) amount is converted correctly."""
        # Test with float
        mollie_data = {"payment_id": "tr_test123", "amount": 50.25}

        _, amount = self.factory._validate_and_extract_mollie_data(mollie_data)

        self.assertEqual(amount, Decimal("50.25"))

        # Test with int
        mollie_data["amount"] = 75
        _, amount = self.factory._validate_and_extract_mollie_data(mollie_data)

        self.assertEqual(amount, Decimal("75.00"))


class TestPaymentEntryFactorySanitization(unittest.TestCase):
    """Tests for title and remarks sanitization."""

    def setUp(self):
        self.factory = PaymentEntryFactory()

    def test_sanitize_title_removes_extra_whitespace(self):
        """Test that excessive whitespace is normalized."""
        title = "Customer   Name  -   Reference"

        result = self.factory._sanitize_title(title)

        self.assertEqual(result, "Customer Name - Reference")

    def test_sanitize_title_truncates_long_strings(self):
        """Test that long titles are truncated with ellipsis."""
        title = "A" * 200

        result = self.factory._sanitize_title(title)

        self.assertEqual(len(result), PAYMENT_ENTRY_TITLE_MAX_LENGTH)
        self.assertTrue(result.endswith("..."))

    def test_sanitize_title_empty_string(self):
        """Test that empty title returns default."""
        result = self.factory._sanitize_title("")

        self.assertEqual(result, "Payment")

    def test_sanitize_remarks_truncates_long_strings(self):
        """Test that long remarks are truncated with ellipsis."""
        remarks = "B" * 600

        result = self.factory._sanitize_remarks(remarks)

        self.assertEqual(len(result), PAYMENT_ENTRY_REMARKS_MAX_LENGTH)
        self.assertTrue(result.endswith("..."))


class TestPaymentEntryFactoryReferenceDateHandling(unittest.TestCase):
    """Tests for reference_date extraction from mollie_data."""

    def setUp(self):
        self.factory = PaymentEntryFactory()

    def test_reference_date_from_paid_at(self):
        """Test that paid_at is used when available."""
        mollie_data = {"paid_at": "2025-01-15T10:30:00+00:00"}

        result = self.factory._get_reference_date(mollie_data)

        self.assertEqual(result.year, 2025)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 15)

    def test_reference_date_fallback_to_today(self):
        """Test that today is used when paid_at is missing."""
        mollie_data = {}

        result = self.factory._get_reference_date(mollie_data)

        self.assertEqual(result, frappe.utils.getdate())

    def test_reference_date_invalid_paid_at_fallback(self):
        """Test that today is used when paid_at is invalid."""
        mollie_data = {"paid_at": "invalid-date"}

        result = self.factory._get_reference_date(mollie_data)

        self.assertEqual(result, frappe.utils.getdate())


class TestPaymentEntryFactoryIdempotency(EnhancedTestCase):
    """Tests for idempotency behavior in PaymentEntryFactory."""

    def setUp(self):
        super().setUp()
        self.pe_factory = PaymentEntryFactory()

    def test_payment_entry_exists_returns_true_for_existing(self):
        """Test _payment_entry_exists returns True when PE exists."""
        # Create a submitted Payment Entry
        pe = self.create_test_payment_entry(
            paid_amount=100.0, reference_no="tr_idempotency_test_001", submit=True
        )

        result = self.pe_factory._payment_entry_exists("tr_idempotency_test_001")

        self.assertTrue(result)

    def test_payment_entry_exists_returns_false_for_nonexistent(self):
        """Test _payment_entry_exists returns False when PE doesn't exist."""
        result = self.pe_factory._payment_entry_exists("tr_nonexistent_payment_id")

        self.assertFalse(result)

    def test_payment_entry_exists_ignores_cancelled(self):
        """Test _payment_entry_exists ignores cancelled PEs (docstatus=2)."""
        # Create and then cancel a Payment Entry
        pe = self.create_test_payment_entry(
            paid_amount=100.0, reference_no="tr_cancelled_test_001", submit=True
        )
        pe.cancel()

        result = self.pe_factory._payment_entry_exists("tr_cancelled_test_001")

        self.assertFalse(result)


class TestPaymentEntryFactoryOrphanCleanup(unittest.TestCase):
    """Unit tests for orphan cleanup behavior when submit fails.

    Note: This is a pure unit test (not integration) because testing orphan cleanup
    requires simulating a submit failure, which can only be done via mocking.
    """

    def setUp(self):
        self.factory = PaymentEntryFactory()

    def test_handle_orphan_cleanup_calls_delete_doc(self):
        """Test that _handle_orphan_cleanup properly deletes the orphaned PE."""
        mock_pe = MagicMock()
        mock_pe.name = "ACC-PAY-TEST-ORPHAN"

        context = PaymentContext(
            payment_type="donation", target_doctype="Donation", target_name="DON-TEST-001"
        )

        mollie_data = {"payment_id": "tr_orphan_test_002", "amount": "50.00"}
        submit_error = Exception("Submit failed: period closed")

        # Patch frappe functions at module level
        target_module = "verenigingen.verenigingen_payments.mollie.services.shared.payment_entry_factory"
        with patch(f"{target_module}.frappe.delete_doc") as mock_delete:
            with patch(f"{target_module}.frappe.log_error"):
                with patch(f"{target_module}.frappe.db.exists", return_value=False):
                    self.factory._handle_orphan_cleanup(mock_pe, submit_error, context, mollie_data)

                    # Verify delete_doc was called for cleanup
                    mock_delete.assert_called_once_with("Payment Entry", "ACC-PAY-TEST-ORPHAN", force=True)

    def test_handle_orphan_cleanup_logs_error(self):
        """Test that _handle_orphan_cleanup creates an error log."""
        mock_pe = MagicMock()
        mock_pe.name = "ACC-PAY-TEST-ORPHAN"

        context = PaymentContext(
            payment_type="donation", target_doctype="Donation", target_name="DON-TEST-001"
        )

        mollie_data = {"payment_id": "tr_orphan_test_003", "amount": "75.00"}
        submit_error = Exception("Period is closed")

        target_module = "verenigingen.verenigingen_payments.mollie.services.shared.payment_entry_factory"
        with patch(f"{target_module}.frappe.delete_doc"):
            with patch(f"{target_module}.frappe.log_error") as mock_log_error:
                with patch(f"{target_module}.frappe.db.exists", return_value=False):
                    with patch(f"{target_module}.frappe.utils.now_datetime", return_value="2025-01-15"):
                        with patch(f"{target_module}.frappe.as_json", return_value="{}"):
                            self.factory._handle_orphan_cleanup(mock_pe, submit_error, context, mollie_data)

                            # Verify log_error was called with appropriate title
                            mock_log_error.assert_called_once()
                            call_kwargs = mock_log_error.call_args[1]
                            self.assertIn("Payment Entry Orphan Cleanup", call_kwargs["title"])
                            self.assertIn("ACC-PAY-TEST-ORPHAN", call_kwargs["message"])
                            self.assertIn("tr_orphan_test_003", call_kwargs["message"])


class TestPaymentEntryFactoryIntegration(EnhancedTestCase):
    """Integration tests for PaymentEntryFactory with real database operations."""

    def setUp(self):
        super().setUp()
        self.pe_factory = PaymentEntryFactory()

    def test_decimal_amount_roundtrip(self):
        """Test that Decimal amounts are correctly stored and retrieved."""
        # Create a Payment Entry with a specific Decimal amount
        test_amount = Decimal("123.45")

        pe = self.create_test_payment_entry(
            paid_amount=float(test_amount),  # Convert to float for test factory
            reference_no="tr_decimal_roundtrip_test",
            submit=True,
        )

        # Reload and verify
        pe.reload()

        # Frappe stores as float, but should be accurate to 2 decimals
        self.assertAlmostEqual(float(pe.paid_amount), float(test_amount), places=2)
        self.assertAlmostEqual(float(pe.received_amount), float(test_amount), places=2)


if __name__ == "__main__":
    unittest.main()
