"""
Unit Tests for Mollie Common Helper Utilities
==============================================

Tests the consolidated utility functions extracted from payment_gateways.py
to eliminate code duplication and provide reusable Mollie integration helpers.

Test Coverage:
- Error/success response formatting
- Frequency to interval conversion
- Amount validation
- Member lookup utilities
- Error logging utilities

Following Enhanced Test Factory patterns with proper field validation.
"""

import unittest
from decimal import Decimal

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.utils.common_helpers import (
    convert_frequency_to_mollie_interval,
    create_error_response,
    create_success_response,
    format_mollie_amount,
    format_mollie_amount_string,
    get_member_by_customer_id,
    get_member_by_subscription_id,
    get_members_by_customer,
    get_mollie_currency,
    is_long_interval,
    is_valid_mollie_interval,
    validate_mollie_amount,
    validate_mollie_interval,
)


class TestResponseFormatting(FrappeTestCase):
    """Test standardized response formatting utilities"""

    def test_create_error_response_simple(self):
        """Test simple error response creation"""
        response = create_error_response("Test error message")

        self.assertEqual(response["status"], "error")
        self.assertIn("message", response)
        self.assertEqual(response["message"], "Test error message")

    def test_create_error_response_with_details(self):
        """Test error response with additional details"""
        response = create_error_response(
            "Payment failed", {"code": "INSUFFICIENT_FUNDS", "transaction_id": "tx_123"}
        )

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["message"], "Payment failed")
        self.assertEqual(response["code"], "INSUFFICIENT_FUNDS")
        self.assertEqual(response["transaction_id"], "tx_123")

    def test_create_error_response_with_exception(self):
        """Test error response handles exception objects"""
        try:
            raise ValueError("Test exception")
        except ValueError as e:
            response = create_error_response(str(e))

        self.assertEqual(response["status"], "error")
        self.assertIn("Test exception", response["message"])

    def test_create_success_response_simple(self):
        """Test simple success response creation"""
        response = create_success_response("Operation completed")

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["message"], "Operation completed")

    def test_create_success_response_with_data(self):
        """Test success response with additional data"""
        response = create_success_response("Payment created", {"payment_id": "tr_abc123", "amount": 25.50})

        self.assertEqual(response["status"], "success")
        self.assertEqual(response["message"], "Payment created")
        self.assertEqual(response["payment_id"], "tr_abc123")
        self.assertEqual(response["amount"], 25.50)

    def test_create_error_response_filters_status_override(self):
        """Test that error response filters out status key override attempts"""
        response = create_error_response(
            "Payment failed", {"status": "success", "reason": "test"}  # status should be filtered
        )

        self.assertEqual(response["status"], "error")  # Should stay "error"
        self.assertEqual(response["message"], "Payment failed")
        self.assertEqual(response["reason"], "test")  # Other keys preserved
        self.assertNotIn("success", str(response))  # Override value not present

    def test_create_success_response_filters_status_override(self):
        """Test that success response filters out status key override attempts"""
        response = create_success_response(
            "Payment created", {"status": "error", "payment_id": "tr_123"}  # status should be filtered
        )

        self.assertEqual(response["status"], "success")  # Should stay "success"
        self.assertEqual(response["message"], "Payment created")
        self.assertEqual(response["payment_id"], "tr_123")  # Other keys preserved

    def test_create_error_response_filters_message_override(self):
        """Test that error response filters out message key override attempts"""
        response = create_error_response(
            "Original message", {"message": "Malicious override", "code": "ERR_001"}
        )

        self.assertEqual(response["status"], "error")
        self.assertEqual(response["message"], "Original message")  # Original preserved
        self.assertEqual(response["code"], "ERR_001")  # Other keys preserved


class TestFrequencyConversion(FrappeTestCase):
    """Test billing frequency to Mollie interval conversion"""

    def test_convert_monthly_frequency(self):
        """Test Monthly converts to 1 month"""
        result = convert_frequency_to_mollie_interval("Monthly")
        self.assertEqual(result, "1 month")

    def test_convert_quarterly_frequency(self):
        """Test Quarterly converts to 3 months"""
        result = convert_frequency_to_mollie_interval("Quarterly")
        self.assertEqual(result, "3 months")

    def test_convert_semiannual_frequency(self):
        """Test Semi-Annual converts to 6 months"""
        result = convert_frequency_to_mollie_interval("Semi-Annual")
        self.assertEqual(result, "6 months")

    def test_convert_annual_frequency(self):
        """Test Annual converts to 12 months"""
        result = convert_frequency_to_mollie_interval("Annual")
        self.assertEqual(result, "12 months")

    def test_convert_donation_select_vocabulary(self):
        """Donation.recurring_frequency Select values map to valid Mollie intervals.

        Regression: Yearly/Weekly/Bi-weekly/Daily previously fell through to the
        default '1 month', so e.g. a Yearly donor would be billed monthly.
        """
        cases = {
            "Daily": "1 day",
            "Weekly": "1 week",
            "Bi-weekly": "2 weeks",  # case-insensitive: normalized to 'Bi-Weekly'
            "Monthly": "1 month",
            "Quarterly": "3 months",
            "Yearly": "12 months",
        }
        for freq, expected in cases.items():
            self.assertEqual(convert_frequency_to_mollie_interval(freq), expected, msg=freq)

    def test_convert_direct_interval_passthrough(self):
        """Test direct interval formats pass through unchanged"""
        intervals = ["1 month", "3 months", "6 months", "12 months"]
        for interval in intervals:
            result = convert_frequency_to_mollie_interval(interval)
            self.assertEqual(result, interval)

    def test_convert_unknown_frequency_defaults_to_monthly(self):
        """Test unknown frequency defaults to monthly with warning"""
        result = convert_frequency_to_mollie_interval("Unknown")
        self.assertEqual(result, "1 month")

    def test_is_long_interval_detection(self):
        """Test detection of quarterly or longer intervals"""
        self.assertFalse(is_long_interval("1 month"))
        self.assertTrue(is_long_interval("3 months"))
        self.assertTrue(is_long_interval("6 months"))
        self.assertTrue(is_long_interval("12 months"))


class TestAmountValidation(FrappeTestCase):
    """Test Mollie amount validation and normalization"""

    def test_validate_positive_integer(self):
        """Test validation of positive integer amounts"""
        result = validate_mollie_amount(50)
        # validate_mollie_amount returns Decimal (quantized to 2 places) for monetary
        # precision; this is the documented contract, not float.
        self.assertEqual(result, Decimal("50.00"))
        self.assertIsInstance(result, Decimal)

    def test_validate_positive_float(self):
        """Test validation of positive float amounts"""
        result = validate_mollie_amount(25.50)
        self.assertEqual(result, 25.50)

    def test_validate_string_number(self):
        """Test validation converts string numbers to float"""
        result = validate_mollie_amount("42.75")
        self.assertEqual(result, 42.75)

    def test_validate_decimal_object(self):
        """Test validation handles Decimal objects"""
        result = validate_mollie_amount(Decimal("15.99"))
        # Returns a Decimal (the documented contract), so compare against Decimal.
        self.assertEqual(result, Decimal("15.99"))
        self.assertIsInstance(result, Decimal)

    def test_validate_zero_amount_raises_error(self):
        """Test zero amount raises ValueError"""
        with self.assertRaises(ValueError) as context:
            validate_mollie_amount(0)
        self.assertIn("positive", str(context.exception).lower())

    def test_validate_negative_amount_raises_error(self):
        """Test negative amount raises ValueError"""
        with self.assertRaises(ValueError) as context:
            validate_mollie_amount(-10.50)
        self.assertIn("positive", str(context.exception).lower())

    def test_validate_invalid_format_raises_error(self):
        """Test invalid format raises ValueError"""
        with self.assertRaises(ValueError):
            validate_mollie_amount("not_a_number")

    def test_validate_none_raises_error(self):
        """Test None raises ValueError"""
        with self.assertRaises(ValueError):
            validate_mollie_amount(None)


class TestAmountFormatting(FrappeTestCase):
    """Test Mollie amount formatting utilities"""

    def test_format_mollie_amount_with_float(self):
        """Test formatting float amount with default EUR currency"""
        result = format_mollie_amount(25.5)

        self.assertEqual(result["value"], "25.50")
        self.assertEqual(result["currency"], "EUR")

    def test_format_mollie_amount_with_integer(self):
        """Test formatting integer amount"""
        result = format_mollie_amount(42)

        self.assertEqual(result["value"], "42.00")
        self.assertEqual(result["currency"], "EUR")

    def test_format_mollie_amount_with_string(self):
        """Test formatting string amount"""
        result = format_mollie_amount("15.99")

        self.assertEqual(result["value"], "15.99")
        self.assertEqual(result["currency"], "EUR")

    def test_format_mollie_amount_with_custom_currency(self):
        """Test formatting with custom currency"""
        result = format_mollie_amount(100, "USD")

        self.assertEqual(result["value"], "100.00")
        self.assertEqual(result["currency"], "USD")

    def test_format_mollie_amount_with_decimal(self):
        """Test formatting Decimal object"""
        result = format_mollie_amount(Decimal("33.75"))

        self.assertEqual(result["value"], "33.75")
        self.assertEqual(result["currency"], "EUR")

    def test_format_mollie_amount_validates_negative(self):
        """Test formatting rejects negative amounts"""
        with self.assertRaises(ValueError):
            format_mollie_amount(-10.50)

    def test_format_mollie_amount_validates_zero(self):
        """Test formatting rejects zero amount"""
        with self.assertRaises(ValueError):
            format_mollie_amount(0)

    def test_format_mollie_amount_string_simple(self):
        """Test string formatting for metadata"""
        result = format_mollie_amount_string(25.5)
        self.assertEqual(result, "25.50")

    def test_format_mollie_amount_string_with_integer(self):
        """Test string formatting with integer"""
        result = format_mollie_amount_string(100)
        self.assertEqual(result, "100.00")

    def test_format_mollie_amount_string_validates(self):
        """Test string formatting validates amount"""
        with self.assertRaises(ValueError):
            format_mollie_amount_string(-5)


class TestCurrencyConfiguration(FrappeTestCase):
    """Test currency configuration utility"""

    def test_get_mollie_currency_returns_eur(self):
        """Test currency returns EUR for Dutch association management"""
        currency = get_mollie_currency()
        self.assertEqual(currency, "EUR")


class TestMemberLookupUtilities(EnhancedTestCase):
    """Test member lookup utilities with test data"""

    def test_get_member_by_subscription_id_not_found(self):
        """Test lookup returns None for non-existent subscription"""
        result = get_member_by_subscription_id("sub_nonexistent_123")
        self.assertIsNone(result)

    def test_get_member_by_subscription_id_with_test_member(self):
        """Test lookup finds member by subscription ID"""
        # Create test member with subscription ID
        member = self.create_test_member(first_name="Test", last_name="Subscriber")

        # Set subscription ID
        test_subscription_id = "sub_test_lookup_123"
        member.db_set("mollie_subscription_id", test_subscription_id)

        # Test lookup
        result = get_member_by_subscription_id(test_subscription_id)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], member.name)

    def test_get_member_by_subscription_id_with_custom_fields(self):
        """Test lookup with custom field selection"""
        member = self.create_test_member(first_name="Field", last_name="Test")

        test_subscription_id = "sub_test_fields_456"
        member.db_set("mollie_subscription_id", test_subscription_id)
        member.db_set("mollie_customer_id", "cst_test_789")

        # Lookup with custom fields
        result = get_member_by_subscription_id(test_subscription_id, fields=["name", "mollie_customer_id"])

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], member.name)
        self.assertEqual(result["mollie_customer_id"], "cst_test_789")

    def test_get_member_by_customer_id_not_found(self):
        """Test lookup returns None for non-existent customer"""
        result = get_member_by_customer_id("cst_nonexistent_999")
        self.assertIsNone(result)

    def test_get_member_by_customer_id_with_test_member(self):
        """Test lookup finds member by Mollie customer ID"""
        import time

        unique_suffix = str(int(time.time() * 1000))[-6:]  # Last 6 digits of timestamp

        member = self.create_test_member(first_name=f"Customer{unique_suffix}", last_name="Test")

        test_customer_id = "cst_test_customer_abc"
        member.db_set("mollie_customer_id", test_customer_id)

        result = get_member_by_customer_id(test_customer_id)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], member.name)

    def test_get_members_by_customer_not_found(self):
        """Test lookup returns empty list for non-existent customer"""
        result = get_members_by_customer("CUST-NONEXISTENT-001")
        self.assertEqual(result, [])

    def test_get_members_by_customer_with_test_member(self):
        """Test lookup finds members by Customer doctype"""
        import time

        unique_suffix = str(int(time.time() * 1000))[-6:]  # Last 6 digits of timestamp

        member = self.create_test_member(first_name=f"Linked{unique_suffix}", last_name="Customer")

        # Member should have customer field populated by factory
        if member.customer:
            result = get_members_by_customer(member.customer)
            self.assertGreater(len(result), 0)

            # Find our test member in results
            found = any(m["name"] == member.name for m in result)
            self.assertTrue(found, "Test member not found in customer lookup")

    def test_get_member_by_subscription_id_empty_string(self):
        """Test lookup handles empty string gracefully"""
        result = get_member_by_subscription_id("")
        self.assertIsNone(result)

    def test_get_member_by_customer_id_none_value(self):
        """Test lookup handles None value gracefully"""
        result = get_member_by_customer_id(None)
        self.assertIsNone(result)


class TestMollieUtilityIntegration(EnhancedTestCase):
    """Integration tests for Mollie utility chains"""

    def test_complete_payment_creation_with_utilities(self):
        """Test realistic payment creation using multiple utilities"""
        # This mimics what CompletePaymentService does in production

        # Step 1: Validate and format amount (typical payment flow)
        raw_amount = "25.50"
        validated = validate_mollie_amount(raw_amount)
        formatted = format_mollie_amount(validated, "EUR")

        # Step 2: Create payment data structure matching Mollie API format
        payment_data = {
            "amount": formatted,
            "description": "Integration Test Payment",
            "metadata": {"test": "integration"},
        }

        # Step 3: Verify complete structure
        self.assertEqual(payment_data["amount"]["value"], "25.50")
        self.assertEqual(payment_data["amount"]["currency"], "EUR")
        self.assertIsInstance(payment_data["amount"], dict)

        # Step 4: Test success response handling (webhook simulation)
        success = create_success_response(
            "Payment created",
            {"payment_id": "tr_test_integration_123", "checkout_url": "https://example.com/checkout"},
        )

        self.assertEqual(success["status"], "success")
        self.assertEqual(success["payment_id"], "tr_test_integration_123")
        self.assertIn("checkout_url", success)

        # Step 5: Test error response handling
        error = create_error_response(
            "Payment failed", {"reason": "insufficient_funds", "payment_id": "tr_failed_123"}
        )

        self.assertEqual(error["status"], "error")
        self.assertEqual(error["reason"], "insufficient_funds")

    def test_subscription_setup_with_member_lookup(self):
        """Test subscription creation flow with member lookup integration"""
        import time

        unique_suffix = str(int(time.time() * 1000))[-6:]

        # Create test member with unique name
        member = self.create_test_member(first_name=f"SubTest{unique_suffix}", last_name="Integration")

        # Set up Mollie IDs (simulating subscription setup)
        test_customer_id = f"cst_integration_{unique_suffix}"
        test_subscription_id = f"sub_integration_{unique_suffix}"

        member.db_set("mollie_customer_id", test_customer_id)
        member.db_set("mollie_subscription_id", test_subscription_id)

        # Test the actual subscription creation workflow

        # Step 1: Convert frequency (from Dues Schedule)
        frequency = "Quarterly"
        interval = convert_frequency_to_mollie_interval(frequency)
        self.assertEqual(interval, "3 months")

        # Step 2: Validate and format subscription amount
        subscription_amount = 75.00
        validated_amount = validate_mollie_amount(subscription_amount)
        formatted_amount = format_mollie_amount(validated_amount)

        self.assertEqual(formatted_amount["value"], "75.00")
        self.assertEqual(formatted_amount["currency"], "EUR")

        # Step 3: Verify member lookups work in both directions
        by_customer = get_member_by_customer_id(test_customer_id)
        by_subscription = get_member_by_subscription_id(test_subscription_id)

        self.assertIsNotNone(by_customer, "Member lookup by customer ID failed")
        self.assertIsNotNone(by_subscription, "Member lookup by subscription ID failed")
        self.assertEqual(by_customer["name"], member.name)
        self.assertEqual(by_subscription["name"], member.name)

        # Step 4: Test complete subscription data structure
        subscription_data = {
            "amount": formatted_amount,
            "interval": interval,
            "description": f"Quarterly subscription for {member.full_name}",
            "metadata": {"member_id": member.name, "frequency": frequency},
        }

        self.assertEqual(subscription_data["interval"], "3 months")
        self.assertEqual(subscription_data["amount"]["value"], "75.00")

    def test_error_handling_through_utility_chain(self):
        """Test error handling propagates correctly through utility stack"""

        # Test Case 1: Negative amount handling
        with self.assertRaises(ValueError) as context:
            validate_mollie_amount(-10)

        error_response = create_error_response(
            str(context.exception), {"invalid_amount": -10, "field": "amount"}
        )

        self.assertEqual(error_response["status"], "error")
        self.assertIn("positive", error_response["message"])
        self.assertEqual(error_response["invalid_amount"], -10)

        # Test Case 2: Below minimum amount handling
        with self.assertRaises(ValueError) as context:
            validate_mollie_amount(0.005)  # Below €0.01 minimum

        error_response = create_error_response(
            str(context.exception), {"invalid_amount": 0.005, "minimum": 0.01}
        )

        self.assertEqual(error_response["status"], "error")
        self.assertIn("at least", error_response["message"])
        self.assertEqual(error_response["minimum"], 0.01)

        # Test Case 3: Invalid frequency with warning
        unknown_frequency = "BiMonthly"  # Not in frequency map
        result = convert_frequency_to_mollie_interval(unknown_frequency)

        # Should default to monthly but still return valid result
        self.assertEqual(result, "1 month")

        # Test Case 4: Member not found scenario
        nonexistent_sub_id = "sub_does_not_exist_999"
        member_result = get_member_by_subscription_id(nonexistent_sub_id)

        self.assertIsNone(member_result, "Should return None for non-existent member")

        # Create appropriate error response
        error = create_error_response(
            "Member not found for subscription", {"subscription_id": nonexistent_sub_id}
        )

        self.assertEqual(error["status"], "error")
        self.assertEqual(error["subscription_id"], nonexistent_sub_id)

    def test_case_insensitive_frequency_integration(self):
        """Test case-insensitive frequency handling in realistic scenarios"""
        # Simulate various input formats that might come from forms/API

        test_cases = [
            ("monthly", "1 month"),
            ("QUARTERLY", "3 months"),
            ("Semi-Annual", "6 months"),
            ("annual", "12 months"),
            ("  Monthly  ", "1 month"),  # With whitespace
        ]

        for input_freq, expected_interval in test_cases:
            result = convert_frequency_to_mollie_interval(input_freq)
            self.assertEqual(result, expected_interval, f"Failed for input: '{input_freq}'")

            # Verify it can be used in complete workflow
            amount = format_mollie_amount(50.00)

            subscription_data = {"amount": amount, "interval": result}

            self.assertEqual(subscription_data["interval"], expected_interval)
            self.assertEqual(subscription_data["amount"]["value"], "50.00")

    def test_response_security_integration(self):
        """Test that response security prevents override in realistic scenarios"""

        # Scenario 1: Malicious attempt to override error to success
        try:
            validate_mollie_amount(-100)
        except ValueError as e:
            # Attacker tries to override status in details
            malicious_response = create_error_response(
                str(e),
                {
                    "status": "success",  # Should be filtered
                    "message": "Override attempt",  # Should be filtered
                    "amount": -100,  # Should be preserved
                },
            )

            # Verify security worked
            self.assertEqual(malicious_response["status"], "error")  # Not overridden
            self.assertIn("positive", malicious_response["message"])  # Original message
            self.assertEqual(malicious_response["amount"], -100)  # Other data preserved

        # Scenario 2: Accidental override in success response
        payment_data = {"payment_id": "tr_123", "status": "pending"}
        success_response = create_success_response(
            "Payment created", payment_data  # Contains conflicting "status"
        )

        # Verify protection
        self.assertEqual(success_response["status"], "success")  # Not overridden to "pending"
        self.assertEqual(success_response["payment_id"], "tr_123")  # Other data preserved


class TestMollieIntervalValidation(FrappeTestCase):
    """The interval grammar Mollie actually enforces.

    Measured against the Mollie test API (a customer with a real directdebit
    mandate, one subscription create per candidate, all cancelled afterwards),
    not read off the docs. Units are day / week / month only; "1 year" is
    refused with 422 "The interval unit is invalid".
    """

    ACCEPTED = [
        "1 day",
        "7 days",
        "14 days",
        "1 week",
        "2 weeks",
        "1 month",
        "3 months",
        "6 months",
        "12 months",
    ]
    REFUSED = ["1 year", "2 years", "0 months", "banana", "", "   ", "month", "3", None]

    def test_accepts_every_interval_mollie_returned_201_for(self):
        for interval in self.ACCEPTED:
            with self.subTest(interval=interval):
                self.assertTrue(is_valid_mollie_interval(interval))

    def test_refuses_every_interval_mollie_returned_422_for(self):
        for interval in self.REFUSED:
            with self.subTest(interval=interval):
                self.assertFalse(is_valid_mollie_interval(interval))

    def test_validate_throws_on_a_year_unit_and_says_what_to_use_instead(self):
        with self.assertRaises(frappe.ValidationError) as cm:
            validate_mollie_interval("1 year")

        message = str(cm.exception)
        self.assertIn("1 year", message)
        self.assertIn("12 months", message, "the error must name the working spelling")

    def test_validate_passes_a_good_interval_through_unchanged(self):
        self.assertEqual(validate_mollie_interval("3 months"), "3 months")


def run_tests():
    """Helper function to run tests from console"""
    import sys

    # Run tests with verbosity
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    unittest.main()
