"""
Unit tests for verenigingen/e_boekhouden/utils/invoice_classifier.py

InvoiceClassifier is pure logic: it inspects mutation line items (rows/Regels)
and returns an immutable InvoiceClassification. No DB or HTTP is required for
the happy paths; the only DB touch is the error path (no line items) which logs
a mutation error before raising.

Run with:
    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_invoice_classifier
"""

import unittest

from verenigingen.e_boekhouden.utils.invoice_classifier import (
    InvoiceClassifier,
    InvoiceType,
    ProcessingStrategy,
    get_invoice_classifier,
)


class TestInvoiceClassifierNormal(unittest.TestCase):
    """All-positive line items → NORMAL / STANDARD."""

    def setUp(self):
        self.classifier = InvoiceClassifier()

    def test_single_positive_item(self):
        result = self.classifier.classify({"rows": [{"amount": 100, "quantity": 1}]})
        self.assertEqual(result.invoice_type, InvoiceType.NORMAL)
        self.assertEqual(result.processing_strategy, ProcessingStrategy.STANDARD)
        self.assertEqual(result.net_amount, 100)
        self.assertEqual(result.positive_item_count, 1)
        self.assertEqual(result.negative_item_count, 0)
        self.assertFalse(result.should_set_is_return)
        self.assertFalse(result.requires_consolidation)

    def test_multiple_positive_items(self):
        result = self.classifier.classify(
            {"rows": [{"amount": 50, "quantity": 2}, {"amount": 30, "quantity": 1}]}
        )
        self.assertEqual(result.invoice_type, InvoiceType.NORMAL)
        self.assertEqual(result.net_amount, 130)
        self.assertEqual(result.positive_item_count, 2)

    def test_quantity_multiplies_amount(self):
        result = self.classifier.classify({"rows": [{"amount": 10, "quantity": 3}]})
        self.assertEqual(result.net_amount, 30)


class TestInvoiceClassifierCreditNote(unittest.TestCase):
    """All-negative line items → PURE_CREDIT_NOTE / CREDIT_NOTE."""

    def setUp(self):
        self.classifier = InvoiceClassifier()

    def test_single_negative_item(self):
        result = self.classifier.classify({"rows": [{"amount": -100, "quantity": 1}]})
        self.assertEqual(result.invoice_type, InvoiceType.PURE_CREDIT_NOTE)
        self.assertEqual(result.processing_strategy, ProcessingStrategy.CREDIT_NOTE)
        self.assertEqual(result.net_amount, -100)
        self.assertEqual(result.negative_item_count, 1)
        self.assertEqual(result.positive_item_count, 0)
        self.assertTrue(result.should_set_is_return)
        self.assertFalse(result.requires_consolidation)

    def test_multiple_negative_items(self):
        result = self.classifier.classify(
            {"rows": [{"amount": -50, "quantity": 1}, {"amount": -25, "quantity": 2}]}
        )
        self.assertEqual(result.invoice_type, InvoiceType.PURE_CREDIT_NOTE)
        self.assertEqual(result.net_amount, -100)
        self.assertEqual(result.negative_item_count, 2)


class TestInvoiceClassifierMixed(unittest.TestCase):
    """Both positive and negative line items → MIXED / CONSOLIDATE."""

    def setUp(self):
        self.classifier = InvoiceClassifier()

    def test_mixed_net_positive(self):
        result = self.classifier.classify(
            {"rows": [{"amount": 100, "quantity": 1}, {"amount": -30, "quantity": 1}]}
        )
        self.assertEqual(result.invoice_type, InvoiceType.MIXED)
        self.assertEqual(result.processing_strategy, ProcessingStrategy.CONSOLIDATE)
        self.assertEqual(result.net_amount, 70)
        self.assertTrue(result.requires_consolidation)
        # is_return is set AFTER consolidation, not before
        self.assertFalse(result.should_set_is_return)

    def test_mixed_net_negative(self):
        result = self.classifier.classify(
            {"rows": [{"amount": 30, "quantity": 1}, {"amount": -100, "quantity": 1}]}
        )
        self.assertEqual(result.invoice_type, InvoiceType.MIXED)
        self.assertEqual(result.net_amount, -70)
        self.assertTrue(result.requires_consolidation)

    def test_mixed_counts(self):
        result = self.classifier.classify(
            {
                "rows": [
                    {"amount": 100, "quantity": 1},
                    {"amount": 50, "quantity": 1},
                    {"amount": -30, "quantity": 1},
                ]
            }
        )
        self.assertEqual(result.positive_item_count, 2)
        self.assertEqual(result.negative_item_count, 1)
        self.assertEqual(result.total_item_count, 3)


class TestInvoiceClassifierZeroAndEdge(unittest.TestCase):
    """Zero-amount and tolerance edge cases."""

    def setUp(self):
        self.classifier = InvoiceClassifier()

    def test_all_zero_items(self):
        # Amounts below tolerance count as zero items → all-zero net → ZERO_AMOUNT
        result = self.classifier.classify({"rows": [{"amount": 0, "quantity": 1}]})
        self.assertEqual(result.invoice_type, InvoiceType.ZERO_AMOUNT)
        self.assertEqual(result.processing_strategy, ProcessingStrategy.STANDARD)
        self.assertEqual(result.net_amount, 0)

    def test_below_tolerance_counts_as_zero(self):
        # 0.005 < default tolerance 0.01 → zero item, NORMAL branch but net ~0
        result = self.classifier.classify({"rows": [{"amount": 0.005, "quantity": 1}]})
        self.assertEqual(result.positive_item_count, 0)
        self.assertEqual(result.negative_item_count, 0)
        self.assertEqual(result.invoice_type, InvoiceType.ZERO_AMOUNT)

    def test_custom_tolerance(self):
        classifier = InvoiceClassifier(tolerance=1.0)
        # amount 0.5 < tolerance 1.0 → treated as zero item
        result = classifier.classify({"rows": [{"amount": 0.5, "quantity": 1}]})
        self.assertEqual(result.positive_item_count, 0)

    def test_dutch_field_names(self):
        # SOAP-style Regels with Prijs/Aantal field names
        result = self.classifier.classify({"Regels": [{"Prijs": -25, "Aantal": 2}]})
        self.assertEqual(result.invoice_type, InvoiceType.PURE_CREDIT_NOTE)
        self.assertEqual(result.net_amount, -50)

    def test_debug_info_populated(self):
        debug = []
        self.classifier.classify({"rows": [{"amount": 100, "quantity": 1}]}, debug)
        self.assertTrue(len(debug) > 0)
        self.assertTrue(any("InvoiceClassifier" in m for m in debug))


class TestInvoiceClassifierNoItems(unittest.TestCase):
    """No line items raises ValueError (and logs a mutation error)."""

    def setUp(self):
        self.classifier = InvoiceClassifier()

    def test_empty_rows_raises(self):
        with self.assertRaises(ValueError):
            self.classifier.classify({"id": 42, "rows": []})

    def test_missing_rows_raises(self):
        with self.assertRaises(ValueError):
            self.classifier.classify({"id": 7})

    def test_error_message_contains_mutation_id(self):
        try:
            self.classifier.classify({"id": 12345})
            self.fail("expected ValueError")
        except ValueError as e:
            self.assertIn("12345", str(e))


class TestGetInvoiceClassifierSingleton(unittest.TestCase):
    """get_invoice_classifier returns a shared instance."""

    def test_returns_classifier(self):
        c = get_invoice_classifier()
        self.assertIsInstance(c, InvoiceClassifier)

    def test_singleton_identity(self):
        self.assertIs(get_invoice_classifier(), get_invoice_classifier())


if __name__ == "__main__":
    unittest.main()
