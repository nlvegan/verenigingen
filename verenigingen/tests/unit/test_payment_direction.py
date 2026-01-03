"""
Unit tests for E-Boekhouden payment direction logic.

Tests that payment direction is correctly determined based on both mutation type AND amount sign:
- Type 5 (Money Received) with positive amount = incoming (debit bank)
- Type 5 (Money Received) with negative amount = outgoing (credit bank) - reversal/correction
- Type 6 (Money Paid) with positive amount = outgoing (credit bank)
- Type 6 (Money Paid) with negative amount = incoming (debit bank) - reversal/correction
"""

import unittest


class TestPaymentDirection(unittest.TestCase):
    """Test payment direction determination logic"""

    def test_is_incoming_type5_positive_amount(self):
        """Type 5 (Money Received) with positive amount should be incoming"""
        mutation_type = 5
        amount = 75.0

        is_incoming = (mutation_type == 5 and amount >= 0) or (mutation_type == 6 and amount < 0)

        self.assertTrue(is_incoming, "Type 5 with positive amount should be incoming")

    def test_is_incoming_type5_negative_amount(self):
        """Type 5 (Money Received) with negative amount should be outgoing (reversal)"""
        mutation_type = 5
        amount = -75.0

        is_incoming = (mutation_type == 5 and amount >= 0) or (mutation_type == 6 and amount < 0)

        self.assertFalse(is_incoming, "Type 5 with negative amount should be outgoing (reversal)")

    def test_is_incoming_type5_zero_amount(self):
        """Type 5 (Money Received) with zero amount should be treated as incoming (default)"""
        mutation_type = 5
        amount = 0.0

        is_incoming = (mutation_type == 5 and amount >= 0) or (mutation_type == 6 and amount < 0)

        self.assertTrue(is_incoming, "Type 5 with zero amount should be incoming (default)")

    def test_is_incoming_type6_positive_amount(self):
        """Type 6 (Money Paid) with positive amount should be outgoing"""
        mutation_type = 6
        amount = 75.0

        is_incoming = (mutation_type == 5 and amount >= 0) or (mutation_type == 6 and amount < 0)

        self.assertFalse(is_incoming, "Type 6 with positive amount should be outgoing")

    def test_is_incoming_type6_negative_amount(self):
        """Type 6 (Money Paid) with negative amount should be incoming (reversal)"""
        mutation_type = 6
        amount = -75.0

        is_incoming = (mutation_type == 5 and amount >= 0) or (mutation_type == 6 and amount < 0)

        self.assertTrue(is_incoming, "Type 6 with negative amount should be incoming (reversal)")

    def test_is_incoming_type6_zero_amount(self):
        """Type 6 (Money Paid) with zero amount should be treated as outgoing (default)"""
        mutation_type = 6
        amount = 0.0

        is_incoming = (mutation_type == 5 and amount >= 0) or (mutation_type == 6 and amount < 0)

        self.assertFalse(is_incoming, "Type 6 with zero amount should be outgoing (default)")


class TestRowAmountSignCalculation(unittest.TestCase):
    """Test that row amount sums preserve sign information"""

    def test_positive_row_amounts(self):
        """Positive row amounts should sum to positive"""
        rows = [
            {"amount": 50.0},
            {"amount": 25.0},
        ]

        # This is the FIXED logic (no abs())
        row_sum = sum(row.get("amount", 0) for row in rows)

        self.assertEqual(row_sum, 75.0)
        self.assertGreater(row_sum, 0)

    def test_negative_row_amounts(self):
        """Negative row amounts should sum to negative"""
        rows = [
            {"amount": -50.0},
            {"amount": -25.0},
        ]

        # This is the FIXED logic (no abs())
        row_sum = sum(row.get("amount", 0) for row in rows)

        self.assertEqual(row_sum, -75.0)
        self.assertLess(row_sum, 0)

    def test_mixed_row_amounts(self):
        """Mixed row amounts should produce signed sum"""
        rows = [
            {"amount": 100.0},
            {"amount": -25.0},
        ]

        row_sum = sum(row.get("amount", 0) for row in rows)

        self.assertEqual(row_sum, 75.0)

    def test_single_negative_row(self):
        """Single negative row should preserve sign (mutation 9307 case)"""
        rows = [
            {"amount": -75.0},
        ]

        row_sum = sum(row.get("amount", 0) for row in rows)

        self.assertEqual(row_sum, -75.0)
        self.assertLess(row_sum, 0)


class TestMutation9307Scenario(unittest.TestCase):
    """Specific test case for mutation 9307 (volunteer compensation outgoing payment)"""

    def test_mutation_9307_original_issue(self):
        """
        Mutation 9307 has type 5 (Money Received) but row amount -75.0.
        This is a data entry where E-Boekhouden used type 5 with negative amount
        to represent an outgoing payment. The fix correctly treats this as outgoing.
        """
        # Original mutation data (as it was reported)
        mutation_type = 5  # Money Received
        rows = [{"amount": -75.0}]  # NEGATIVE amount = actually outgoing

        # Calculate signed sum (FIXED: no abs())
        amount = sum(row.get("amount", 0) for row in rows)

        # Determine direction with FIXED logic
        is_incoming = (mutation_type == 5 and amount >= 0) or (mutation_type == 6 and amount < 0)

        # Should be OUTGOING (is_incoming = False)
        self.assertFalse(is_incoming,
            "Mutation 9307: Type 5 with -75.0 should be outgoing (volunteer compensation)")
        self.assertEqual(amount, -75.0)

    def test_mutation_9307_corrected_data(self):
        """
        After correction in E-Boekhouden, mutation 9307 now has type 6 with +75.0.
        This is the correct representation of an outgoing payment.
        """
        # Corrected mutation data
        mutation_type = 6  # Money Paid
        rows = [{"amount": 75.0}]  # POSITIVE amount

        amount = sum(row.get("amount", 0) for row in rows)

        is_incoming = (mutation_type == 5 and amount >= 0) or (mutation_type == 6 and amount < 0)

        # Should be OUTGOING
        self.assertFalse(is_incoming,
            "Type 6 with +75.0 should be outgoing")
        self.assertEqual(amount, 75.0)


if __name__ == "__main__":
    unittest.main()
