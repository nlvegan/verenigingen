"""
PaymentDataExtractor Documentation Examples Test Suite

This test file extracts and makes executable all the examples from the
PaymentDataExtractor docstrings, ensuring documentation stays accurate
and examples remain functional.

Generated from: payment_data_extractor.py docstring Examples sections
Date: 2025-10-21
Purpose: Convert documentation examples to executable, verifiable tests (Martin Fowler Priority 2)
"""

import unittest
from decimal import Decimal
from unittest.mock import Mock

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
    MollieObjectType,
    get_payment_data_extractor,
)


# ============================================================================
# Mock Mollie Object Factories
# ============================================================================


def create_mock_payment():
    """Mock standard Mollie payment object."""
    payment = Mock()
    payment.id = "tr_abc123"
    payment.amount = {"value": "25.50", "currency": "EUR"}
    payment.description = "Test Payment"
    payment.paid_at = "2025-10-21T10:30:00+00:00"
    return payment


def create_mock_balance_transaction():
    """Mock Mollie balance transaction object."""
    transaction = Mock()
    transaction.id = "baltr_xyz789"

    # Balance transactions use result_amount.decimal_value
    result_amount = Mock()
    result_amount.decimal_value = "15.75"
    result_amount.currency = "EUR"
    transaction.result_amount = result_amount

    initial_amount = Mock()
    initial_amount.decimal_value = "15.75"
    initial_amount.currency = "EUR"
    transaction.initial_amount = initial_amount

    return transaction


def create_mock_settlement():
    """Mock Mollie settlement object."""
    settlement = Mock()
    settlement.id = "stl_def456"

    # Settlements use amount.decimal_value
    amount = Mock()
    amount.decimal_value = "1250.00"
    amount.currency = "EUR"
    settlement.amount = amount

    return settlement


def create_mock_subscription():
    """Mock Mollie subscription object."""
    subscription = Mock()
    subscription.id = "sub_ghi789"

    # Subscriptions can use either amount.value or amount.decimal_value
    amount = Mock()
    amount.value = "50.00"
    amount.decimal_value = "50.00"
    amount.currency = "EUR"
    subscription.amount = amount

    return subscription


def create_mock_subscription_trial():
    """Mock Mollie subscription object with zero trial amount."""
    subscription = Mock()
    subscription.id = "sub_trial123"

    amount = Mock()
    amount.value = "0.00"
    amount.decimal_value = "0.00"
    amount.currency = "EUR"
    subscription.amount = amount

    return subscription


def create_mock_balance():
    """Mock Mollie balance object with available and pending amounts."""
    balance = Mock()
    balance.id = "bal_jkl012"

    # Available amount
    available_amount = Mock()
    available_amount.decimal_value = "1234.56"
    available_amount.currency = "EUR"
    balance.available_amount = available_amount

    # Pending amount
    pending_amount = Mock()
    pending_amount.decimal_value = "567.89"
    pending_amount.currency = "EUR"
    balance.pending_amount = pending_amount

    return balance


# ============================================================================
# Test: extract_amount() Examples
# ============================================================================


class TestExtractAmountExamples(EnhancedTestCase):
    """Tests from extract_amount() docstring Examples section."""

    def test_example_standard_payment(self):
        """
        Example: Standard payment object
        >>> extractor = get_payment_data_extractor()
        >>> amount = extractor.extract_amount(payment)
        >>> print(f"Payment: €{amount:.2f}")
        Payment: €25.50
        """
        extractor = get_payment_data_extractor()
        mock_payment = create_mock_payment()
        amount = extractor.extract_amount(mock_payment)
        self.assertEqual(amount, 25.50)
        self.assertEqual(f"Payment: €{amount:.2f}", "Payment: €25.50")

    def test_example_balance_transaction(self):
        """Example: Balance transaction object"""
        extractor = get_payment_data_extractor()
        mock_transaction = create_mock_balance_transaction()
        amount = extractor.extract_amount(
            mock_transaction,
            source_type="balance_transaction"
        )
        self.assertEqual(amount, 15.75)

    def test_example_balance_transaction_with_enum(self):
        """Example: Balance transaction using MollieObjectType Enum"""
        extractor = get_payment_data_extractor()
        mock_transaction = create_mock_balance_transaction()
        amount = extractor.extract_amount(
            mock_transaction,
            source_type=MollieObjectType.BALANCE_TRANSACTION
        )
        self.assertEqual(amount, 15.75)

    def test_example_settlement(self):
        """Example: Settlement object"""
        extractor = get_payment_data_extractor()
        mock_settlement = create_mock_settlement()
        amount = extractor.extract_amount(
            mock_settlement,
            source_type="settlement"
        )
        self.assertEqual(amount, 1250.00)

    def test_example_subscription_with_zero_allowed(self):
        """Example: Subscription with zero trial amount"""
        extractor = get_payment_data_extractor()
        mock_subscription = create_mock_subscription_trial()
        amount = extractor.extract_amount(
            mock_subscription,
            source_type="subscription",
            allow_zero=True
        )
        self.assertEqual(amount, 0.0)

    def test_example_calculate_total(self):
        """Example: Calculate total from multiple payments"""
        extractor = get_payment_data_extractor()

        payment1 = Mock()
        payment1.amount = {"value": "25.50"}

        payment2 = Mock()
        payment2.amount = {"value": "0.00"}

        payment3 = Mock()
        payment3.amount = {"value": "100.00"}

        total = sum(
            extractor.extract_amount(p, allow_zero=True)
            for p in [payment1, payment2, payment3]
        )
        self.assertEqual(total, 125.50)

    def test_example_validate_payment(self):
        """Example: Validate payment before processing"""
        extractor = get_payment_data_extractor()
        mock_payment = create_mock_payment()

        # Should succeed
        amount = extractor.extract_amount(mock_payment)
        self.assertGreater(amount, 0)

        # Should fail for invalid payment
        invalid_payment = Mock()
        invalid_payment.amount = None
        with self.assertRaises(ValueError):
            extractor.extract_amount(invalid_payment)


# ============================================================================
# Test: extract_amount_as_decimal() Examples
# ============================================================================


class TestExtractAmountAsDecimalExamples(EnhancedTestCase):
    """Tests from extract_amount_as_decimal() docstring Examples section."""

    def test_example_standard_payment(self):
        """Example: Standard payment returning Decimal"""
        extractor = get_payment_data_extractor()
        mock_payment = create_mock_payment()
        amount = extractor.extract_amount_as_decimal(mock_payment)

        self.assertIsInstance(amount, Decimal)
        self.assertEqual(amount, Decimal("25.50"))
        # Decimal formatting may vary (25.5 vs 25.50)
        self.assertTrue(f"Amount: {amount}" in ["Amount: 25.50", "Amount: 25.5"])

    def test_example_balance_transaction(self):
        """Example: Balance transaction with zero allowed"""
        extractor = get_payment_data_extractor()
        mock_transaction = create_mock_balance_transaction()

        net_change = extractor.extract_amount_as_decimal(
            mock_transaction,
            source_type="balance_transaction",
            allow_zero=True
        )

        self.assertIsInstance(net_change, Decimal)
        self.assertEqual(net_change, Decimal("15.75"))

    def test_example_financial_calculations(self):
        """Example: Use in financial calculations"""
        extractor = get_payment_data_extractor()

        settlement1 = Mock()
        settlement1.amount = Mock()
        settlement1.amount.decimal_value = "1250.00"

        settlement2 = Mock()
        settlement2.amount = Mock()
        settlement2.amount.decimal_value = "750.50"

        total = Decimal("0")
        for settlement in [settlement1, settlement2]:
            amount = extractor.extract_amount_as_decimal(
                settlement, source_type="settlement"
            )
            total += amount

        self.assertEqual(total, Decimal("2000.50"))


# ============================================================================
# Test: extract_currency_simple() Examples
# ============================================================================


class TestExtractCurrencySimpleExamples(EnhancedTestCase):
    """Tests from extract_currency_simple() docstring Examples section."""

    def test_example_simple_extraction(self):
        """Example: Simple extraction without validation"""
        extractor = get_payment_data_extractor()
        mock_payment = create_mock_payment()
        currency = extractor.extract_currency_simple(mock_payment)
        self.assertEqual(currency, "EUR")

    def test_example_strict_mode(self):
        """Example: Strict mode raises on failure"""
        extractor = get_payment_data_extractor()
        mock_payment = create_mock_payment()

        # Should succeed
        currency = extractor.extract_currency_simple(mock_payment, strict=True)
        self.assertEqual(currency, "EUR")

        # Should fail for invalid payment - need complete mock with no extractable currency
        invalid_payment = Mock()
        invalid_payment.amount = Mock()
        invalid_payment.amount.currency = None  # Explicitly None
        invalid_payment.amount.value = "25.50"  # Has value but no currency

        with self.assertRaises(ValueError) as cm:
            extractor.extract_currency_simple(invalid_payment, strict=True)
        # Error message varies, just check it raises

    def test_example_custom_fallback(self):
        """Example: Custom fallback"""
        extractor = get_payment_data_extractor()

        payment_no_currency = Mock()
        payment_no_currency.amount = Mock()
        payment_no_currency.amount.currency = None

        currency = extractor.extract_currency_simple(
            payment_no_currency,
            fallback="USD"
        )
        self.assertEqual(currency, "USD")

    def test_example_balance_transaction(self):
        """Example: Balance transaction currency"""
        extractor = get_payment_data_extractor()
        mock_transaction = create_mock_balance_transaction()

        currency = extractor.extract_currency_simple(
            mock_transaction,
            source_type="balance_transaction"
        )
        self.assertEqual(currency, "EUR")


# ============================================================================
# Test: extract_balance_amounts() Examples
# ============================================================================


class TestExtractBalanceAmountsExamples(EnhancedTestCase):
    """Tests from extract_balance_amounts() docstring Examples section."""

    def test_example_basic_extraction(self):
        """Example: Basic balance amounts extraction"""
        extractor = get_payment_data_extractor()
        mock_balance = create_mock_balance()
        amounts = extractor.extract_balance_amounts(mock_balance)

        self.assertEqual(amounts['available'], 1234.56)
        self.assertEqual(amounts['pending'], 567.89)
        self.assertEqual(amounts['currency'], "EUR")
        self.assertEqual(f"Available: €{amounts['available']:.2f}", "Available: €1234.56")
        self.assertEqual(f"Pending: €{amounts['pending']:.2f}", "Pending: €567.89")

    def test_example_multi_currency_summary(self):
        """Example: Multi-currency balance summary"""
        extractor = get_payment_data_extractor()

        # EUR balance
        balance_eur = Mock()
        available_eur = Mock()
        available_eur.decimal_value = "1000.00"
        available_eur.currency = "EUR"
        balance_eur.available_amount = available_eur

        pending_eur = Mock()
        pending_eur.decimal_value = "500.00"
        pending_eur.currency = "EUR"
        balance_eur.pending_amount = pending_eur

        # USD balance
        balance_usd = Mock()
        available_usd = Mock()
        available_usd.decimal_value = "2000.00"
        available_usd.currency = "USD"
        balance_usd.available_amount = available_usd

        pending_usd = Mock()
        pending_usd.decimal_value = "750.00"
        pending_usd.currency = "USD"
        balance_usd.pending_amount = pending_usd

        totals = {"available": {}, "pending": {}}
        for balance in [balance_eur, balance_usd]:
            amounts = extractor.extract_balance_amounts(balance)
            currency = amounts['currency']

            if currency not in totals["available"]:
                totals["available"][currency] = 0
                totals["pending"][currency] = 0

            totals["available"][currency] += amounts['available']
            totals["pending"][currency] += amounts['pending']

        self.assertEqual(totals["available"]["EUR"], 1000.00)
        self.assertEqual(totals["pending"]["EUR"], 500.00)
        self.assertEqual(totals["available"]["USD"], 2000.00)
        self.assertEqual(totals["pending"]["USD"], 750.00)

    def test_example_sufficient_funds_check(self):
        """Example: Check for sufficient funds"""
        extractor = get_payment_data_extractor()
        mock_balance = create_mock_balance()
        amounts = extractor.extract_balance_amounts(mock_balance)

        # High balance should NOT trigger alert
        if amounts['available'] < 100:
            self.fail("Should not trigger low balance alert")

        # Low balance should trigger alert
        low_balance = Mock()
        low_available = Mock()
        low_available.decimal_value = "50.00"
        low_available.currency = "EUR"
        low_balance.available_amount = low_available
        low_balance.pending_amount = None

        low_amounts = extractor.extract_balance_amounts(low_balance)
        self.assertLess(low_amounts['available'], 100)

    def test_example_financial_reconciliation(self):
        """Example: Financial reconciliation"""
        extractor = get_payment_data_extractor()

        # Starting balance
        balance_start = Mock()
        start_available = Mock()
        start_available.decimal_value = "1000.00"
        start_available.currency = "EUR"
        balance_start.available_amount = start_available
        balance_start.pending_amount = None

        # Ending balance
        balance_end = Mock()
        end_available = Mock()
        end_available.decimal_value = "1234.56"
        end_available.currency = "EUR"
        balance_end.available_amount = end_available
        balance_end.pending_amount = None

        start_amounts = extractor.extract_balance_amounts(balance_start)
        end_amounts = extractor.extract_balance_amounts(balance_end)
        change = end_amounts['available'] - start_amounts['available']

        # Use assertAlmostEqual for floating point comparison
        self.assertAlmostEqual(change, 234.56, places=2)
        self.assertEqual(f"Balance changed by: €{change:.2f}", "Balance changed by: €234.56")


# ============================================================================
# Test: MollieObjectType Enum Examples
# ============================================================================


class TestMollieObjectTypeEnumExamples(EnhancedTestCase):
    """Tests from MollieObjectType docstring Examples section."""

    def test_example_enum_usage(self):
        """Example: Using MollieObjectType Enum"""
        extractor = get_payment_data_extractor()
        mock_payment = create_mock_payment()

        amount = extractor.extract_amount(
            mock_payment,
            source_type=MollieObjectType.PAYMENT
        )
        self.assertEqual(amount, 25.50)

    def test_enum_string_conversion(self):
        """Test Enum to string conversion"""
        self.assertEqual(str(MollieObjectType.PAYMENT), "payment")
        self.assertEqual(str(MollieObjectType.BALANCE_TRANSACTION), "balance_transaction")
        self.assertEqual(str(MollieObjectType.SETTLEMENT), "settlement")
        self.assertEqual(str(MollieObjectType.SUBSCRIPTION), "subscription")
        self.assertEqual(str(MollieObjectType.BALANCE), "balance")

    def test_enum_values(self):
        """Test Enum values"""
        self.assertEqual(MollieObjectType.PAYMENT.value, "payment")
        self.assertEqual(MollieObjectType.BALANCE_TRANSACTION.value, "balance_transaction")
        self.assertEqual(MollieObjectType.SETTLEMENT.value, "settlement")
        self.assertEqual(MollieObjectType.SUBSCRIPTION.value, "subscription")
        self.assertEqual(MollieObjectType.BALANCE.value, "balance")


# ============================================================================
# Test: Edge Cases and Error Handling
# ============================================================================


class TestEdgeCasesFromExamples(EnhancedTestCase):
    """Edge cases derived from examples."""

    def test_zero_amount_not_allowed_by_default(self):
        """Zero amounts raise ValueError unless allow_zero=True"""
        extractor = get_payment_data_extractor()

        zero_payment = Mock()
        zero_payment.amount = {"value": "0.00"}

        # Should raise without allow_zero (error message may vary)
        with self.assertRaises(ValueError):
            extractor.extract_amount(zero_payment)

        # Should succeed with allow_zero=True
        amount = extractor.extract_amount(zero_payment, allow_zero=True)
        self.assertEqual(amount, 0.0)

    def test_negative_amount_never_allowed(self):
        """Negative amounts always raise ValueError"""
        extractor = get_payment_data_extractor()

        negative_payment = Mock()
        negative_payment.amount = {"value": "-50.00"}

        # Should raise ValueError (error message may vary)
        with self.assertRaises(ValueError):
            extractor.extract_amount(negative_payment, allow_zero=True)

    def test_missing_currency_fallback(self):
        """Missing currency uses fallback in lenient mode"""
        extractor = get_payment_data_extractor()

        payment_no_currency = Mock()
        payment_no_currency.amount = {"value": "25.50"}

        # Lenient mode - uses EUR fallback
        currency = extractor.extract_currency_simple(payment_no_currency)
        self.assertEqual(currency, "EUR")

        # Custom fallback
        currency = extractor.extract_currency_simple(
            payment_no_currency,
            fallback="USD"
        )
        self.assertEqual(currency, "USD")

        # Strict mode - raises
        with self.assertRaises(ValueError):
            extractor.extract_currency_simple(payment_no_currency, strict=True)


# ============================================================================
# Test: Backward Compatibility (String vs Enum)
# ============================================================================


class TestBackwardCompatibility(EnhancedTestCase):
    """Ensure string and Enum work identically."""

    def test_extract_amount_string_vs_enum(self):
        """String and Enum produce identical results"""
        extractor = get_payment_data_extractor()
        mock_payment = create_mock_payment()

        amount_str = extractor.extract_amount(mock_payment, source_type="payment")
        amount_enum = extractor.extract_amount(mock_payment, source_type=MollieObjectType.PAYMENT)

        self.assertEqual(amount_str, amount_enum)

    def test_extract_currency_string_vs_enum(self):
        """String and Enum produce identical currency"""
        extractor = get_payment_data_extractor()
        mock_payment = create_mock_payment()

        currency_str = extractor.extract_currency_simple(mock_payment, source_type="payment")
        currency_enum = extractor.extract_currency_simple(mock_payment, source_type=MollieObjectType.PAYMENT)

        self.assertEqual(currency_str, currency_enum)

    def test_all_source_types(self):
        """All source types work with both string and Enum"""
        extractor = get_payment_data_extractor()

        # Balance transaction
        mock_transaction = create_mock_balance_transaction()
        amount_str = extractor.extract_amount(mock_transaction, source_type="balance_transaction")
        amount_enum = extractor.extract_amount(mock_transaction, source_type=MollieObjectType.BALANCE_TRANSACTION)
        self.assertEqual(amount_str, amount_enum)

        # Settlement
        mock_settlement = create_mock_settlement()
        amount_str = extractor.extract_amount(mock_settlement, source_type="settlement")
        amount_enum = extractor.extract_amount(mock_settlement, source_type=MollieObjectType.SETTLEMENT)
        self.assertEqual(amount_str, amount_enum)

        # Subscription
        mock_subscription = create_mock_subscription()
        amount_str = extractor.extract_amount(mock_subscription, source_type="subscription")
        amount_enum = extractor.extract_amount(mock_subscription, source_type=MollieObjectType.SUBSCRIPTION)
        self.assertEqual(amount_str, amount_enum)
