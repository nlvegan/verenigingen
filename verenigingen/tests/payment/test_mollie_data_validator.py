"""
Coverage for the centralized Mollie data validator.

Target: verenigingen/verenigingen_payments/mollie/utils/data_validator.py

MollieDataValidator validates Mollie customer/subscription data shapes and
status-transition rules. It is pure-Python (the only Frappe touchpoints are
_() translation, getdate/nowdate, and the validate hook which reads a real
Customer doc). The validator logic runs entirely for real here.
"""

import unittest

from verenigingen.verenigingen_payments.mollie.utils.data_validator import (
    MollieDataValidator,
    get_mollie_validator,
)


class TestMollieDataValidatorIds(unittest.TestCase):
    def setUp(self):
        self.v = MollieDataValidator()

    def test_valid_customer_and_subscription_ids(self):
        data = {
            "custom_mollie_customer_id": "cst_8wmqcHMN4U",
            "custom_mollie_subscription_id": "sub_8JfeQp27NT",
        }
        is_valid, errors, warnings = self.v.validate_customer_data(data)
        self.assertTrue(is_valid, errors)
        self.assertEqual(errors, [])

    def test_invalid_customer_id_rejected(self):
        is_valid, errors, _ = self.v.validate_customer_data({"custom_mollie_customer_id": "bogus"})
        self.assertFalse(is_valid)
        self.assertTrue(any("customer ID" in e for e in errors))

    def test_invalid_subscription_id_rejected(self):
        is_valid, errors, _ = self.v.validate_customer_data(
            {"custom_mollie_subscription_id": "sub_short"}
        )
        self.assertFalse(is_valid)
        self.assertTrue(any("subscription ID" in e for e in errors))

    def test_empty_data_is_valid(self):
        is_valid, errors, warnings = self.v.validate_customer_data({})
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])


class TestMollieDataValidatorStatus(unittest.TestCase):
    """The status / payment-date validation is reached only via the
    'custom_subscription_status' key. This pins the bug fix where the guard
    previously checked 'subscription_status' (never present) so the value at
    'custom_subscription_status' was never validated."""

    def setUp(self):
        self.v = MollieDataValidator()

    def test_invalid_status_value_now_rejected(self):
        # Regression for the key-mismatch bug: before the fix this returned
        # is_valid=True because the guard checked the wrong key and the status
        # was never validated.
        is_valid, errors, _ = self.v.validate_customer_data(
            {"custom_subscription_status": "totally_invalid"}
        )
        self.assertFalse(is_valid)
        self.assertTrue(any("Invalid subscription status" in e for e in errors))

    def test_valid_status_value_accepted(self):
        is_valid, errors, _ = self.v.validate_customer_data({"custom_subscription_status": "active"})
        self.assertTrue(is_valid, errors)

    def test_payment_date_in_past_warns_for_active(self):
        is_valid, errors, warnings = self.v.validate_customer_data(
            {"custom_subscription_status": "active", "custom_next_payment_date": "2000-01-01"}
        )
        self.assertTrue(is_valid)
        self.assertTrue(any("in the past" in w for w in warnings))

    def test_payment_date_set_for_canceled_warns(self):
        is_valid, errors, warnings = self.v.validate_customer_data(
            {"custom_subscription_status": "canceled", "custom_next_payment_date": "2099-01-01"}
        )
        self.assertTrue(is_valid)
        self.assertTrue(any("Consider clearing the date" in w for w in warnings))

    def test_invalid_payment_date_format_errors_for_active(self):
        is_valid, errors, _ = self.v.validate_customer_data(
            {"custom_subscription_status": "active", "custom_next_payment_date": "not-a-date"}
        )
        self.assertFalse(is_valid)
        self.assertTrue(any("Invalid next payment date" in e for e in errors))


class TestMollieDataValidatorTransitions(unittest.TestCase):
    def setUp(self):
        self.v = MollieDataValidator()

    def test_none_or_empty_status_allows_initial_set(self):
        self.assertTrue(self.v.validate_status_transition(None, "active"))
        self.assertTrue(self.v.validate_status_transition("", "active"))

    def test_same_state_allowed(self):
        self.assertTrue(self.v.validate_status_transition("active", "active"))

    def test_valid_transition(self):
        self.assertTrue(self.v.validate_status_transition("active", "canceled"))
        self.assertTrue(self.v.validate_status_transition("inactive", "active"))
        self.assertTrue(self.v.validate_status_transition("suspended", "active"))

    def test_invalid_transition_from_terminal_state(self):
        self.assertFalse(self.v.validate_status_transition("canceled", "active"))
        self.assertTrue(any("Invalid subscription status transition" in e for e in self.v.errors))

    def test_invalid_transition_active_to_inactive(self):
        self.assertFalse(self.v.validate_status_transition("active", "inactive"))


class TestMollieValidatorFactory(unittest.TestCase):
    def test_factory_returns_fresh_instance(self):
        a = get_mollie_validator()
        b = get_mollie_validator()
        self.assertIsInstance(a, MollieDataValidator)
        self.assertIsNot(a, b)
        # Each instance has its own error/warning accumulators.
        a.errors.append("x")
        self.assertEqual(b.errors, [])


if __name__ == "__main__":
    unittest.main()
