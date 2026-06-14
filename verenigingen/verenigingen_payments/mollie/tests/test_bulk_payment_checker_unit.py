"""
Tier-1 unit tests for the pure/static logic in BulkPaymentChecker.

These exercise the stateless helpers that the bulk discovery flow relies on
WITHOUT touching Mollie's HTTP API or the database. Mollie "payment" objects are
the external SDK boundary; here we stand them in with SimpleNamespace stubs that
mirror the shape the production code reads (``payment.amount`` dict,
``payment.status``, ``payment.paid_at``/``created_at`` datetimes, etc.).

Targets (all in
verenigingen/verenigingen_payments/mollie/services/bulk_payment_checker.py):
    - BulkPaymentChecker._filter_payment_by_date
    - BulkPaymentChecker._build_payment_info
    - BulkPaymentChecker._classify_orphaned_payment
    - BulkPaymentChecker._extract_payment_ids_from_transactions

No mocks (no unittest.mock.patch) are used — the inputs are plain data objects,
so this is genuinely pure-function coverage.
"""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker import BulkPaymentChecker


def _payment(
    *,
    pid="tr_test001",
    status="paid",
    amount=None,
    description="Membership dues",
    created_at=None,
    paid_at=None,
    subscription_id=None,
    customer_id=None,
):
    """Build a Mollie-payment-shaped stub object (the SDK boundary)."""
    if amount is None:
        amount = {"value": "25.00", "currency": "EUR"}
    if created_at is None:
        created_at = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=pid,
        status=status,
        amount=amount,
        description=description,
        created_at=created_at,
        paid_at=paid_at,
        subscription_id=subscription_id,
        customer_id=customer_id,
    )


class TestFilterPaymentByDate(unittest.TestCase):
    """BulkPaymentChecker._filter_payment_by_date — returns True to EXCLUDE."""

    def test_no_from_date_keeps_everything(self):
        p = _payment(paid_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
        self.assertFalse(BulkPaymentChecker._filter_payment_by_date(p, None))

    def test_payment_before_from_date_is_excluded(self):
        from_date = datetime(2024, 6, 1, tzinfo=timezone.utc)
        p = _payment(paid_at=datetime(2024, 5, 1, tzinfo=timezone.utc))
        self.assertTrue(BulkPaymentChecker._filter_payment_by_date(p, from_date))

    def test_payment_after_from_date_is_kept(self):
        from_date = datetime(2024, 6, 1, tzinfo=timezone.utc)
        p = _payment(paid_at=datetime(2024, 6, 15, tzinfo=timezone.utc))
        self.assertFalse(BulkPaymentChecker._filter_payment_by_date(p, from_date))

    def test_falls_back_to_created_at_when_no_paid_at(self):
        from_date = datetime(2024, 6, 1, tzinfo=timezone.utc)
        # paid_at None -> uses created_at (which is before from_date) -> excluded
        p = _payment(paid_at=None, created_at=datetime(2024, 5, 20, tzinfo=timezone.utc))
        self.assertTrue(BulkPaymentChecker._filter_payment_by_date(p, from_date))

    def test_naive_payment_date_is_treated_as_utc(self):
        from_date = datetime(2024, 6, 1, tzinfo=timezone.utc)
        # Naive datetime after from_date should be kept (assumed UTC, not crash)
        p = _payment(paid_at=datetime(2024, 6, 15))  # naive
        self.assertFalse(BulkPaymentChecker._filter_payment_by_date(p, from_date))

    def test_payment_with_no_date_is_excluded(self):
        from_date = datetime(2024, 6, 1, tzinfo=timezone.utc)
        p = _payment(paid_at=None, created_at=None)
        self.assertTrue(BulkPaymentChecker._filter_payment_by_date(p, from_date))


class TestBuildPaymentInfo(unittest.TestCase):
    """BulkPaymentChecker._build_payment_info — assembles the result dict."""

    def _idem(self, processed=False, pe=None, bt=None):
        return {"already_processed": processed, "payment_entry": pe, "bank_transaction": bt}

    def test_processable_dues_payment(self):
        p = _payment(status="paid")
        info = BulkPaymentChecker._build_payment_info(p, "dues", self._idem(), "25.00", "EUR", None, None)
        self.assertEqual(info["id"], "tr_test001")
        self.assertEqual(info["payment_type"], "dues")
        self.assertEqual(info["amount_display"], "EUR 25.00")
        self.assertTrue(info["processable"])
        self.assertEqual(info["processing_mode"], "bt_only")

    def test_processable_with_matching_invoice_sets_reconcile_mode(self):
        p = _payment(status="paid")
        matching = {"invoice_name": "SINV-0001"}
        info = BulkPaymentChecker._build_payment_info(p, "dues", self._idem(), "25.00", "EUR", None, matching)
        self.assertEqual(info["processing_mode"], "bt_pe_reconcile")
        self.assertEqual(info["matching_invoice"], matching)

    def test_already_processed_is_not_processable(self):
        p = _payment(status="paid")
        info = BulkPaymentChecker._build_payment_info(
            p, "dues", self._idem(processed=True, pe="PE-1", bt="BT-1"), "25.00", "EUR", None, None
        )
        self.assertFalse(info["processable"])
        self.assertIsNone(info["processing_mode"])
        self.assertTrue(info["already_processed"])
        self.assertEqual(info["payment_entry"], "PE-1")
        self.assertEqual(info["bank_transaction"], "BT-1")

    def test_currency_warning_blocks_processable(self):
        p = _payment(status="paid")
        info = BulkPaymentChecker._build_payment_info(
            p, "dues", self._idem(), "25.00", "USD", "Non-EUR currency: USD.", None
        )
        self.assertFalse(info["processable"])

    def test_non_dues_payment_not_processable(self):
        p = _payment(status="paid")
        info = BulkPaymentChecker._build_payment_info(p, "donation", self._idem(), "25.00", "EUR", None, None)
        self.assertFalse(info["processable"])
        self.assertIsNone(info["processing_mode"])

    def test_unpaid_status_not_processable(self):
        p = _payment(status="open")
        info = BulkPaymentChecker._build_payment_info(p, "dues", self._idem(), "25.00", "EUR", None, None)
        self.assertFalse(info["processable"])

    def test_unknown_amount_display(self):
        p = _payment(status="open")
        info = BulkPaymentChecker._build_payment_info(
            p, "dues", self._idem(), "Unknown", "Unknown", None, None
        )
        self.assertEqual(info["amount_display"], "Unknown")


class TestClassifyOrphanedPayment(unittest.TestCase):
    """BulkPaymentChecker._classify_orphaned_payment — orphan triage logic."""

    def test_paid_eur_with_customer_is_processable_orphaned(self):
        p = _payment(status="paid", customer_id="cst_123")
        info, processable = BulkPaymentChecker._classify_orphaned_payment(p, "tr_x", "dues", "EUR", "25.00")
        self.assertTrue(processable)
        self.assertEqual(info["processing_mode"], "bt_only_orphaned")
        self.assertEqual(info["customer_id"], "cst_123")
        self.assertEqual(info["amount"], "EUR 25.00")

    def test_paid_eur_anonymous_is_processable_anonymous(self):
        p = _payment(status="paid", customer_id=None)
        info, processable = BulkPaymentChecker._classify_orphaned_payment(p, "tr_x", "dues", "EUR", "25.00")
        self.assertTrue(processable)
        self.assertEqual(info["processing_mode"], "bt_only_anonymous")
        self.assertEqual(info["customer_id"], "No customer")

    def test_non_eur_is_not_processable(self):
        p = _payment(status="paid", customer_id="cst_1")
        info, processable = BulkPaymentChecker._classify_orphaned_payment(p, "tr_x", "dues", "USD", "25.00")
        self.assertFalse(processable)
        self.assertIsNone(info["processing_mode"])

    def test_unpaid_is_not_processable(self):
        p = _payment(status="open", customer_id="cst_1")
        info, processable = BulkPaymentChecker._classify_orphaned_payment(p, "tr_x", "dues", "EUR", "25.00")
        self.assertFalse(processable)


class TestExtractPaymentIdsFromTransactions(unittest.TestCase):
    """BulkPaymentChecker._extract_payment_ids_from_transactions — balance-tx parsing."""

    def _tx(self, *, tx_id, created_at, context=None, tx_type="payment", amount_value="25.00"):
        return SimpleNamespace(
            id=tx_id,
            created_at=created_at,
            context=context if context is not None else {},
            type=tx_type,
            amount={"value": amount_value, "currency": "EUR"},
        )

    def test_extracts_payment_id_from_context(self):
        from_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        to_date = datetime(2024, 12, 31, tzinfo=timezone.utc)
        tx = self._tx(
            tx_id="baltr_999",
            created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            context={"paymentId": "tr_abc"},
        )
        ids, txlist = BulkPaymentChecker._extract_payment_ids_from_transactions([tx], from_date, to_date)
        self.assertEqual(ids, {"tr_abc"})
        self.assertEqual(len(txlist), 1)
        self.assertEqual(txlist[0]["payment_id"], "tr_abc")
        self.assertEqual(txlist[0]["transaction_id"], "baltr_999")

    def test_falls_back_to_tx_id_when_it_is_a_payment_id(self):
        from_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        to_date = datetime(2024, 12, 31, tzinfo=timezone.utc)
        tx = self._tx(tx_id="tr_self", created_at=datetime(2024, 6, 1, tzinfo=timezone.utc))
        ids, txlist = BulkPaymentChecker._extract_payment_ids_from_transactions([tx], from_date, to_date)
        self.assertEqual(ids, {"tr_self"})

    def test_string_created_at_is_parsed(self):
        from_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        to_date = datetime(2024, 12, 31, tzinfo=timezone.utc)
        tx = self._tx(
            tx_id="baltr_1",
            created_at="2024-06-01T12:00:00Z",
            context={"paymentId": "tr_str"},
        )
        ids, _ = BulkPaymentChecker._extract_payment_ids_from_transactions([tx], from_date, to_date)
        self.assertEqual(ids, {"tr_str"})

    def test_transaction_outside_date_range_is_skipped(self):
        from_date = datetime(2024, 6, 1, tzinfo=timezone.utc)
        to_date = datetime(2024, 6, 30, tzinfo=timezone.utc)
        tx = self._tx(
            tx_id="baltr_old",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            context={"paymentId": "tr_old"},
        )
        ids, txlist = BulkPaymentChecker._extract_payment_ids_from_transactions([tx], from_date, to_date)
        self.assertEqual(ids, set())
        self.assertEqual(txlist, [])

    def test_non_payment_id_is_ignored(self):
        from_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        to_date = datetime(2024, 12, 31, tzinfo=timezone.utc)
        # context has no paymentId and tx id is not a tr_ id
        tx = self._tx(tx_id="baltr_settlement", created_at=datetime(2024, 6, 1, tzinfo=timezone.utc))
        ids, txlist = BulkPaymentChecker._extract_payment_ids_from_transactions([tx], from_date, to_date)
        self.assertEqual(ids, set())

    def test_transaction_missing_date_is_skipped(self):
        from_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        to_date = datetime(2024, 12, 31, tzinfo=timezone.utc)
        tx = self._tx(tx_id="baltr_nodate", created_at=None, context={"paymentId": "tr_nodate"})
        ids, _ = BulkPaymentChecker._extract_payment_ids_from_transactions([tx], from_date, to_date)
        self.assertEqual(ids, set())

    def test_deduplicates_repeated_payment_ids(self):
        from_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        to_date = datetime(2024, 12, 31, tzinfo=timezone.utc)
        c = datetime(2024, 6, 1, tzinfo=timezone.utc)
        tx1 = self._tx(tx_id="baltr_1", created_at=c, context={"paymentId": "tr_dup"})
        tx2 = self._tx(tx_id="baltr_2", created_at=c, context={"paymentId": "tr_dup"})
        ids, txlist = BulkPaymentChecker._extract_payment_ids_from_transactions(
            [tx1, tx2], from_date, to_date
        )
        self.assertEqual(ids, {"tr_dup"})
        # both transactions still recorded in the list (set only dedups the id set)
        self.assertEqual(len(txlist), 2)


if __name__ == "__main__":
    unittest.main()
