"""
Unit tests for pure helper functions extracted from eboekhouden_rest_full_migration.py

These test the refactored helper functions that have no (or minimal) external dependencies.
All functions under test are pure: they take input, return output, and only use frappe.utils.flt.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_pure_helpers
"""

import unittest

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _calculate_opening_balance_debit_credit,
    _categorize_batch_errors,
    _convert_mutation_detail_amount,
    _convert_regels_for_credit_note,
    _detect_credit_note_improved,
)


class TestCalculateOpeningBalanceDebitCredit(unittest.TestCase):
    """Test opening balance debit/credit calculation by root type."""

    def test_asset_positive_amount(self):
        """Positive asset → debit (natural balance)"""
        debit, credit = _calculate_opening_balance_debit_credit(1000.0, "Asset")
        self.assertEqual(debit, 1000.0)
        self.assertEqual(credit, 0)

    def test_asset_negative_amount(self):
        """Negative asset → credit (contra-natural)"""
        debit, credit = _calculate_opening_balance_debit_credit(-500.0, "Asset")
        self.assertEqual(debit, 0)
        self.assertEqual(credit, 500.0)

    def test_liability_positive_amount(self):
        """Positive liability → credit (natural balance)"""
        debit, credit = _calculate_opening_balance_debit_credit(2000.0, "Liability")
        self.assertEqual(debit, 0)
        self.assertEqual(credit, 2000.0)

    def test_liability_negative_amount(self):
        """Negative liability → debit (contra-natural)"""
        debit, credit = _calculate_opening_balance_debit_credit(-750.0, "Liability")
        self.assertEqual(debit, 750.0)
        self.assertEqual(credit, 0)

    def test_equity_positive_amount(self):
        """Positive equity → credit (same as liability)"""
        debit, credit = _calculate_opening_balance_debit_credit(3000.0, "Equity")
        self.assertEqual(debit, 0)
        self.assertEqual(credit, 3000.0)

    def test_equity_negative_amount(self):
        """Negative equity → debit"""
        debit, credit = _calculate_opening_balance_debit_credit(-100.0, "Equity")
        self.assertEqual(debit, 100.0)
        self.assertEqual(credit, 0)

    def test_zero_amount_asset(self):
        """Zero amount → both zero"""
        debit, credit = _calculate_opening_balance_debit_credit(0, "Asset")
        self.assertEqual(debit, 0)
        self.assertEqual(credit, 0)

    def test_zero_amount_liability(self):
        """Zero amount → both zero"""
        debit, credit = _calculate_opening_balance_debit_credit(0, "Liability")
        self.assertEqual(debit, 0)
        self.assertEqual(credit, 0)

    def test_small_decimal_amounts(self):
        """Small amounts are rounded to 2 decimal places via frappe.utils.flt"""
        # 0.005 rounds to 0.0 with flt(..., 2) (banker's rounding)
        debit, credit = _calculate_opening_balance_debit_credit(0.005, "Asset")
        self.assertEqual(debit, 0.0)
        self.assertEqual(credit, 0)

        # 0.015 rounds to 0.01 or 0.02 depending on rounding mode
        debit, credit = _calculate_opening_balance_debit_credit(1.555, "Asset")
        self.assertAlmostEqual(debit, 1.56, places=2)
        self.assertEqual(credit, 0)

    def test_debit_credit_never_both_nonzero(self):
        """For any input, at most one of debit/credit should be nonzero"""
        test_cases = [
            (100, "Asset"),
            (-100, "Asset"),
            (100, "Liability"),
            (-100, "Liability"),
            (100, "Equity"),
            (-100, "Equity"),
            (0, "Asset"),
        ]
        for amount, root_type in test_cases:
            debit, credit = _calculate_opening_balance_debit_credit(amount, root_type)
            self.assertTrue(
                debit == 0 or credit == 0,
                f"Both debit ({debit}) and credit ({credit}) nonzero for amount={amount}, root_type={root_type}",
            )


class TestCategorizeBatchErrors(unittest.TestCase):
    """Test batch error categorization."""

    def test_empty_errors(self):
        """Empty list returns empty dict"""
        result = _categorize_batch_errors([])
        self.assertEqual(result, {})

    def test_stock_account_error(self):
        """Stock account errors are categorized correctly"""
        errors = ["Stock accounts can only be updated via Stock Transactions"]
        result = _categorize_batch_errors(errors)
        self.assertIn("Stock Account Updates (Fixed - now creates Stock Reconciliations)", result)
        self.assertEqual(len(result["Stock Account Updates (Fixed - now creates Stock Reconciliations)"]), 1)

    def test_payment_allocation_error_fully_paid(self):
        """'already been fully paid' is a payment allocation issue"""
        errors = ["Invoice INV-001 has already been fully paid"]
        result = _categorize_batch_errors(errors)
        self.assertIn("Payment Allocation Issues", result)

    def test_payment_allocation_error_outstanding(self):
        """'cannot be greater than outstanding amount' is a payment allocation issue"""
        errors = ["Amount cannot be greater than outstanding amount of 500"]
        result = _categorize_batch_errors(errors)
        self.assertIn("Payment Allocation Issues", result)

    def test_missing_reference_error(self):
        """'Could not find' is a missing reference"""
        errors = ["Could not find Customer CUST-001"]
        result = _categorize_batch_errors(errors)
        self.assertIn("Missing References", result)

    def test_duplicate_entry_error(self):
        """'already exists' is a duplicate entry"""
        errors = ["Journal Entry JV-00123 already exists"]
        result = _categorize_batch_errors(errors)
        self.assertIn("Duplicate Entries", result)

    def test_other_error(self):
        """Unrecognized errors go to 'Other Errors'"""
        errors = ["Something unexpected happened"]
        result = _categorize_batch_errors(errors)
        self.assertIn("Other Errors", result)

    def test_mixed_errors(self):
        """Multiple error types are categorized separately"""
        errors = [
            "Stock accounts can only be updated via Stock Transactions",
            "Invoice INV-001 has already been fully paid",
            "Could not find Supplier SUP-001",
            "Journal Entry JV-123 already exists",
            "Random error",
        ]
        result = _categorize_batch_errors(errors)
        self.assertEqual(len(result), 5)
        for category, category_errors in result.items():
            self.assertEqual(len(category_errors), 1)

    def test_multiple_same_category(self):
        """Multiple errors of the same type accumulate"""
        errors = [
            "Could not find Customer CUST-001",
            "Could not find Supplier SUP-002",
            "Could not find Account ACC-003",
        ]
        result = _categorize_batch_errors(errors)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result["Missing References"]), 3)


class TestDetectCreditNoteImproved(unittest.TestCase):
    """Test credit note detection from mutation data."""

    def setUp(self):
        self.debug_info = []

    def test_negative_main_amount(self):
        """Negative main amount → credit note"""
        mutation = {"amount": -100.50}
        is_credit, total = _detect_credit_note_improved(mutation, self.debug_info)
        self.assertTrue(is_credit)
        self.assertEqual(total, -100.50)

    def test_positive_main_amount(self):
        """Positive main amount → not a credit note"""
        mutation = {"amount": 250.00}
        is_credit, total = _detect_credit_note_improved(mutation, self.debug_info)
        self.assertFalse(is_credit)
        self.assertEqual(total, 250.00)

    def test_zero_amount_no_rows(self):
        """Zero amount with no line items → not a credit note"""
        mutation = {"amount": 0}
        is_credit, total = _detect_credit_note_improved(mutation, self.debug_info)
        self.assertFalse(is_credit)
        self.assertEqual(total, 0)

    def test_zero_amount_all_negative_rows(self):
        """Zero main amount + all negative line items → credit note"""
        mutation = {
            "amount": 0,
            "rows": [
                {"amount": -50, "quantity": 1},
                {"amount": -30, "quantity": 1},
            ],
        }
        is_credit, total = _detect_credit_note_improved(mutation, self.debug_info)
        self.assertTrue(is_credit)
        self.assertEqual(total, -80)

    def test_zero_amount_all_positive_rows(self):
        """Zero main amount + all positive line items → not a credit note"""
        mutation = {
            "amount": 0,
            "rows": [
                {"amount": 50, "quantity": 1},
                {"amount": 30, "quantity": 1},
            ],
        }
        is_credit, total = _detect_credit_note_improved(mutation, self.debug_info)
        self.assertFalse(is_credit)
        self.assertEqual(total, 80)

    def test_zero_amount_mixed_rows_not_credit_note(self):
        """Zero main amount + mixed positive/negative items → NOT credit note"""
        mutation = {
            "amount": 0,
            "rows": [
                {"amount": 100, "quantity": 1},
                {"amount": -30, "quantity": 1},
            ],
        }
        is_credit, total = _detect_credit_note_improved(mutation, self.debug_info)
        self.assertFalse(is_credit)
        self.assertEqual(total, 70)

    def test_dutch_field_names(self):
        """Handles Dutch field names (Prijs, Aantal) from SOAP API"""
        mutation = {
            "amount": 0,
            "Regels": [
                {"Prijs": -25, "Aantal": 2},
            ],
        }
        is_credit, total = _detect_credit_note_improved(mutation, self.debug_info)
        self.assertTrue(is_credit)
        self.assertEqual(total, -50)

    def test_quantity_multiplied_by_amount(self):
        """Line item total = amount × quantity"""
        mutation = {
            "amount": 0,
            "rows": [
                {"amount": -10, "quantity": 3},
            ],
        }
        is_credit, total = _detect_credit_note_improved(mutation, self.debug_info)
        self.assertTrue(is_credit)
        self.assertEqual(total, -30)

    def test_missing_amount_field(self):
        """Missing amount field defaults to 0"""
        mutation = {}
        is_credit, total = _detect_credit_note_improved(mutation, self.debug_info)
        self.assertFalse(is_credit)
        self.assertEqual(total, 0)

    def test_debug_info_populated(self):
        """Debug info list gets messages appended"""
        mutation = {"amount": -100}
        _detect_credit_note_improved(mutation, self.debug_info)
        self.assertTrue(len(self.debug_info) > 0)
        self.assertIn("Credit note detected", self.debug_info[0])


class TestConvertRegelsForCreditNote(unittest.TestCase):
    """Test credit note line item conversion."""

    def setUp(self):
        self.debug_info = []

    def test_empty_regels(self):
        """Empty list returns unchanged"""
        result = _convert_regels_for_credit_note([], "sales", self.debug_info)
        self.assertEqual(result, [])

    def test_none_regels(self):
        """None returns unchanged"""
        result = _convert_regels_for_credit_note(None, "sales", self.debug_info)
        self.assertIsNone(result)

    def test_negative_amount_converted_to_positive(self):
        """Negative amounts become positive"""
        regels = [{"amount": -100, "quantity": 1}]
        result = _convert_regels_for_credit_note(regels, "sales", self.debug_info)
        self.assertEqual(result[0]["amount"], 100)

    def test_positive_amount_unchanged(self):
        """Positive amounts stay positive"""
        regels = [{"amount": 50, "quantity": 1}]
        result = _convert_regels_for_credit_note(regels, "sales", self.debug_info)
        self.assertEqual(result[0]["amount"], 50)

    def test_positive_quantity_becomes_negative(self):
        """Positive quantities become negative (ERPNext is_return requirement)"""
        regels = [{"amount": 100, "quantity": 2}]
        result = _convert_regels_for_credit_note(regels, "sales", self.debug_info)
        self.assertEqual(result[0]["quantity"], -2)

    def test_negative_quantity_stays_negative(self):
        """Already-negative quantities stay negative"""
        regels = [{"amount": 100, "quantity": -3}]
        result = _convert_regels_for_credit_note(regels, "sales", self.debug_info)
        self.assertEqual(result[0]["quantity"], -3)

    def test_dutch_field_names(self):
        """Handles Dutch field names (Prijs, Aantal)"""
        regels = [{"Prijs": -75, "Aantal": 2}]
        result = _convert_regels_for_credit_note(regels, "purchase", self.debug_info)
        self.assertEqual(result[0]["Prijs"], 75)
        self.assertEqual(result[0]["Aantal"], -2)

    def test_original_not_modified(self):
        """Original regels list is not modified (returns copies)"""
        regels = [{"amount": -100, "quantity": 1}]
        original_amount = regels[0]["amount"]
        _convert_regels_for_credit_note(regels, "sales", self.debug_info)
        self.assertEqual(regels[0]["amount"], original_amount)

    def test_multiple_rows(self):
        """Multiple rows are all converted"""
        regels = [
            {"amount": -50, "quantity": 1},
            {"amount": -30, "quantity": 2},
            {"amount": -20, "quantity": 1},
        ]
        result = _convert_regels_for_credit_note(regels, "sales", self.debug_info)
        self.assertEqual(len(result), 3)
        for row in result:
            self.assertGreater(row["amount"], 0)
            self.assertLess(row["quantity"], 0)

    def test_missing_quantity_defaults_to_negative_one(self):
        """When quantity field is missing, defaults to 1.0 then stored as 'Aantal' (Dutch fallback)"""
        regels = [{"amount": -100}]
        result = _convert_regels_for_credit_note(regels, "sales", self.debug_info)
        self.assertEqual(result[0]["amount"], 100)
        # When "quantity" key is absent, function falls back to "Aantal" field name
        self.assertEqual(result[0]["Aantal"], -1.0)


class TestConvertMutationDetailAmount(unittest.TestCase):
    """Test mutation detail amount conversion for credit notes."""

    def setUp(self):
        self.debug_info = []

    def test_negative_amount_to_positive(self):
        """Negative amount is converted to positive"""
        detail = {"amount": -500}
        result = _convert_mutation_detail_amount(detail, self.debug_info)
        self.assertEqual(result["amount"], 500)

    def test_positive_amount_unchanged(self):
        """Positive amount stays the same"""
        detail = {"amount": 200}
        result = _convert_mutation_detail_amount(detail, self.debug_info)
        self.assertEqual(result["amount"], 200)

    def test_dutch_field_name(self):
        """Handles Dutch 'Bedrag' field name"""
        detail = {"Bedrag": -300}
        result = _convert_mutation_detail_amount(detail, self.debug_info)
        self.assertEqual(result["Bedrag"], 300)

    def test_none_input(self):
        """None input returns None"""
        result = _convert_mutation_detail_amount(None, self.debug_info)
        self.assertIsNone(result)

    def test_original_not_modified(self):
        """Original dict is not modified"""
        detail = {"amount": -100}
        _convert_mutation_detail_amount(detail, self.debug_info)
        self.assertEqual(detail["amount"], -100)

    def test_zero_amount_unchanged(self):
        """Zero amount stays zero"""
        detail = {"amount": 0}
        result = _convert_mutation_detail_amount(detail, self.debug_info)
        self.assertEqual(result["amount"], 0)


if __name__ == "__main__":
    unittest.main()
