"""
Real tests for the bank-transaction reconciliation matching logic.

Instantiates the real PaymentReconciliationManager (which loads Verenigingen
Settings + the Mollie configuration service - no mocking) and exercises its
amount / decimal / reference-extraction / description-pattern matching helpers.
Also covers the module-level end-to-end-id helpers.

No business logic is mocked; inputs are plain dicts shaped exactly like the
Bank Transaction rows and Mollie payment payloads these functions receive.

Covers verenigingen/verenigingen_payments/utils/bank_transaction_reconciliation.py:
    - PaymentReconciliationManager._safe_decimal
    - PaymentReconciliationManager._validate_transaction_amount
    - PaymentReconciliationManager._extract_invoice_reference
    - PaymentReconciliationManager._is_mollie_payment_processed /
      _mark_mollie_payment_processed
    - PaymentReconciliationManager.match_by_batch_reference (no-match path)
    - PaymentReconciliationManager.match_by_description (no-match path)
    - handle_payment_rejection / mark_payment_successful e2e-id parsing
"""

from decimal import Decimal

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
    PaymentReconciliationManager,
)


class TestReconciliationDecimalHelpers(EnhancedTestCase):
    """_safe_decimal and _validate_transaction_amount precision logic."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # One manager instance for the whole class - construction is expensive
        # (validates Mollie GL accounts) and these helpers are stateless.
        cls.mgr = PaymentReconciliationManager()

    def test_safe_decimal_from_float_and_int(self):
        self.assertEqual(self.mgr._safe_decimal(12.5), Decimal("12.5"))
        self.assertEqual(self.mgr._safe_decimal(100), Decimal("100"))

    def test_safe_decimal_from_none_is_zero(self):
        self.assertEqual(self.mgr._safe_decimal(None), Decimal("0"))

    def test_safe_decimal_strips_currency_symbols(self):
        self.assertEqual(self.mgr._safe_decimal("€1234.56"), Decimal("1234.56"))
        self.assertEqual(self.mgr._safe_decimal("-75.50"), Decimal("-75.50"))

    def test_safe_decimal_unparseable_string_is_zero(self):
        self.assertEqual(self.mgr._safe_decimal("abc"), Decimal("0"))
        self.assertEqual(self.mgr._safe_decimal(""), Decimal("0"))

    def test_validate_exact_match(self):
        ok, kind, diff = self.mgr._validate_transaction_amount(Decimal("10"), Decimal("10"))
        self.assertTrue(ok)
        self.assertEqual(kind, "exact_match")
        self.assertEqual(diff, Decimal("0"))

    def test_validate_within_tolerance(self):
        ok, kind, diff = self.mgr._validate_transaction_amount(
            Decimal("100.05"), Decimal("100"), tolerance_percent=1.0
        )
        self.assertTrue(ok)
        self.assertEqual(kind, "within_tolerance")

    def test_validate_outside_tolerance(self):
        ok, kind, diff = self.mgr._validate_transaction_amount(
            Decimal("150"), Decimal("100"), tolerance_percent=1.0
        )
        self.assertFalse(ok)
        self.assertEqual(kind, "outside_tolerance")
        self.assertEqual(diff, Decimal("50"))


class TestReconciliationInvoiceExtraction(EnhancedTestCase):
    """_extract_invoice_reference from Mollie payment metadata / description."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mgr = PaymentReconciliationManager()

    def test_metadata_invoice_id_preferred(self):
        ref = self.mgr._extract_invoice_reference(
            {"metadata": {"invoice_id": "ACC-INV-2024-0007"}, "description": "ignored SI-1111-1111"}
        )
        self.assertEqual(ref, "ACC-INV-2024-0007")

    def test_description_si_pattern(self):
        ref = self.mgr._extract_invoice_reference({"description": "Payment for SI-2024-0012"})
        self.assertEqual(ref, "SI-2024-0012")

    def test_description_acc_inv_pattern(self):
        ref = self.mgr._extract_invoice_reference({"description": "Invoice ACC-INV-2025-0099 paid"})
        self.assertEqual(ref, "ACC-INV-2025-0099")

    def test_generic_invoice_label_pattern(self):
        ref = self.mgr._extract_invoice_reference({"description": "Invoice: ABC-123"})
        self.assertEqual(ref, "ABC-123")

    def test_no_reference_returns_none(self):
        self.assertIsNone(self.mgr._extract_invoice_reference({"description": "just a thank you"}))
        self.assertIsNone(self.mgr._extract_invoice_reference({}))


class TestReconciliationDuplicateTracking(EnhancedTestCase):
    """_is_mollie_payment_processed / _mark_mollie_payment_processed in-memory cache."""

    def setUp(self):
        super().setUp()
        self.mgr = PaymentReconciliationManager()

    def test_unprocessed_payment_not_flagged(self):
        self.assertFalse(self.mgr._is_mollie_payment_processed("tr_neverseen_xyz"))

    def test_marking_then_checking_returns_true(self):
        pid = "tr_marked_abc123"
        self.mgr._mark_mollie_payment_processed(pid)
        self.assertTrue(self.mgr._is_mollie_payment_processed(pid))


class TestReconciliationMatchingNoMatch(EnhancedTestCase):
    """Matching strategies return None when nothing matches (DB-backed, real)."""

    def setUp(self):
        super().setUp()
        self.mgr = PaymentReconciliationManager()

    def test_batch_reference_no_pattern_returns_none(self):
        txn = {"description": "Some unrelated text", "deposit": 100}
        self.assertIsNone(self.mgr.match_by_batch_reference(txn))

    def test_batch_reference_nonexistent_batch_returns_none(self):
        txn = {"description": "BATCH-DOESNOTEXIST-9999", "deposit": 100}
        self.assertIsNone(self.mgr.match_by_batch_reference(txn))

    def test_amount_and_reference_missing_returns_none(self):
        self.assertIsNone(self.mgr.match_by_amount_and_reference({"deposit": 0, "reference_number": ""}))

    def test_description_no_known_pattern_returns_none(self):
        txn = {"description": "random deposit", "deposit": 0}
        self.assertIsNone(self.mgr.match_by_description(txn))

    def test_description_invoice_pattern_unknown_invoice_returns_none(self):
        txn = {"description": "INVOICE NO-SUCH-INVOICE-123", "deposit": 0}
        self.assertIsNone(self.mgr.match_by_description(txn))


class TestEndToEndIdParsing(EnhancedTestCase):
    """handle_payment_rejection / mark_payment_successful parse the E2E id."""

    def test_handle_rejection_invalid_e2e_id_is_noop(self):
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
            handle_payment_rejection,
        )

        # An id without the E2E- prefix should be ignored (no exception, no retry).
        self.assertIsNone(handle_payment_rejection("NOTANID", "AC04", "Account closed"))

    def test_mark_successful_invalid_e2e_id_is_noop(self):
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
            mark_payment_successful,
        )

        self.assertIsNone(mark_payment_successful("NOTANID"))

    def test_mark_successful_unknown_invoice_raises_does_not_exist(self):
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
            mark_payment_successful,
        )

        # A well-formed E2E id pointing at a non-existent invoice should surface a
        # DoesNotExistError from frappe.get_doc (real behaviour, not swallowed).
        with self.assertRaises(frappe.DoesNotExistError):
            mark_payment_successful("E2E-NO-SUCH-INVOICE-9999")


class TestReconciliationSummary(EnhancedTestCase):
    """get_reconciliation_summary returns a well-formed dict with a rate."""

    def test_summary_structure_and_rate_bounds(self):
        from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
            get_reconciliation_summary,
        )

        summary = get_reconciliation_summary()
        for key in ("total_transactions", "reconciled", "pending", "unmatched", "reconciliation_rate"):
            self.assertIn(key, summary)
        self.assertGreaterEqual(summary["reconciliation_rate"], 0)
        self.assertLessEqual(summary["reconciliation_rate"], 100)
