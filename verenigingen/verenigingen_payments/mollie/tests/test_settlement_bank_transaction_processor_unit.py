"""
Tier-1 unit tests for SettlementBankTransactionProcessor.

verenigingen/verenigingen_payments/services/settlement_bank_transaction_processor.py
(0% coverage at start; this code path had likely never executed.)

The processor's __init__ builds a SettlementsClient + SettlementCache +
DuesPaymentProcessor + BankTransactionCreator, all of which need live Mollie
config / API keys. Everything under test here is *business logic* — settlement →
reconciliation math, description building, idempotency, the deposit orchestration,
and batch filtering. The ONLY boundary faked is the Mollie SDK clients
(SettlementsClient / settlement_cache / bank_tx_creator); we build the processor
with object.__new__ and attach fakes. No unittest.mock. Real Settlement model
objects (core.models.settlement.Settlement) are constructed from dict data, so the
Amount/decimal_value parsing and get_total_* helpers run for real.

DB-touching branches (_validate_configuration, _check_existing_bank_transaction)
are covered against real Frappe in the integration module.
"""

import unittest
from decimal import Decimal

from verenigingen.verenigingen_payments.core.models.settlement import Settlement
from verenigingen.verenigingen_payments.services.settlement_bank_transaction_processor import (
    SettlementBankTransactionProcessor,
)


def _settlement(
    sid="stl_test1",
    reference="1234.5678.90",
    status="paidout",
    amount_value="100.00",
    settled_at="2025-01-15T10:00:00+00:00",
):
    """Build a real Settlement model object from Mollie-shaped dict data."""
    return Settlement(
        {
            "id": sid,
            "reference": reference,
            "status": status,
            "settledAt": settled_at,
            "amount": {"value": amount_value, "currency": "EUR"},
        }
    )


class _FakeSettlementsClient:
    """Boundary stub for SettlementsClient (the Mollie API)."""

    def __init__(self, payments=None, refunds=None, chargebacks=None, captures=None, settlements=None):
        self._payments = payments or []
        self._refunds = refunds or []
        self._chargebacks = chargebacks or []
        self._captures = captures or []
        self._settlements = settlements or []

    def list_settlement_payments(self, settlement_id, **kw):
        return self._payments

    def list_settlement_refunds(self, settlement_id, **kw):
        return self._refunds

    def list_settlement_chargebacks(self, settlement_id, **kw):
        return self._chargebacks

    def list_settlement_captures(self, settlement_id, **kw):
        return self._captures

    def list_settlements(self, **kw):
        return self._settlements


class _FakeCache:
    def __init__(self, settlement=None):
        self._settlement = settlement

    def get_settlement(self, settlement_id=None, bank_reference=None):
        return self._settlement


class _FakeBTCreator:
    def __init__(self, bt_name="BT-SETTLE-1"):
        self.bt_name = bt_name
        self.calls = []

    def create_from_settlement(self, **kwargs):
        self.calls.append(kwargs)
        return self.bt_name


def _make_processor(*, settlements_client=None, cache=None, bt=None):
    proc = object.__new__(SettlementBankTransactionProcessor)
    proc.settlements_client = settlements_client or _FakeSettlementsClient()
    proc.settlement_cache = cache or _FakeCache()
    proc.bank_tx_creator = bt or _FakeBTCreator()
    proc.dues_processor = None  # not used by the tested paths
    return proc


class TestGetSettlement(unittest.TestCase):
    def test_no_identifiers_returns_error(self):
        proc = _make_processor()
        out = proc._get_settlement(None, None)
        self.assertEqual(out["status"], "error")
        self.assertIn("Must provide", out["error"])

    def test_not_found_returns_error(self):
        proc = _make_processor(cache=_FakeCache(settlement=None))
        out = proc._get_settlement("stl_missing", None)
        self.assertEqual(out["status"], "error")
        self.assertIn("not found", out["error"])

    def test_found_returns_settlement(self):
        s = _settlement()
        proc = _make_processor(cache=_FakeCache(settlement=s))
        out = proc._get_settlement("stl_test1", None)
        self.assertIs(out, s)


class TestCheckExistingBankTransaction(unittest.TestCase):
    def test_no_existing_returns_false(self):
        import frappe

        proc = _make_processor()
        original = frappe.db.get_value
        frappe.db.get_value = lambda *a, **k: None
        try:
            out = proc._check_existing_bank_transaction("stl_test1")
        finally:
            frappe.db.get_value = original
        self.assertFalse(out["exists"])
        self.assertIsNone(out["name"])

    def test_existing_returns_true_and_name(self):
        import frappe

        proc = _make_processor()
        original = frappe.db.get_value
        frappe.db.get_value = lambda *a, **k: "ACC-BANK-TXN-001"
        try:
            out = proc._check_existing_bank_transaction("stl_test1")
        finally:
            frappe.db.get_value = original
        self.assertTrue(out["exists"])
        self.assertEqual(out["name"], "ACC-BANK-TXN-001")


class TestReconcileSettlementFromObject(unittest.TestCase):
    def test_reconciled_when_components_match_amount(self):
        # 3 payments of 40 = 120 gross; settlement amount 120 -> reconciled
        payments = [{"settlementAmount": {"value": "40.00"}} for _ in range(3)]
        client = _FakeSettlementsClient(payments=payments)
        proc = _make_processor(settlements_client=client)
        s = _settlement(amount_value="120.00")
        rec = proc._reconcile_settlement_from_object(s)
        self.assertEqual(rec["components"]["payments"]["count"], 3)
        self.assertEqual(rec["components"]["payments"]["total"], 120.0)
        self.assertTrue(rec["reconciled"])
        self.assertEqual(rec["discrepancy"], 0.0)

    def test_discrepancy_reflects_fees(self):
        # gross 100 payments, settlement only 97 -> discrepancy -3 (fees), not reconciled
        payments = [{"settlementAmount": {"value": "100.00"}}]
        client = _FakeSettlementsClient(payments=payments)
        proc = _make_processor(settlements_client=client)
        s = _settlement(amount_value="97.00")
        rec = proc._reconcile_settlement_from_object(s)
        self.assertAlmostEqual(rec["discrepancy"], -3.0, places=2)
        self.assertFalse(rec["reconciled"])

    def test_refunds_and_chargebacks_subtracted(self):
        payments = [{"settlementAmount": {"value": "100.00"}}]
        refunds = [{"settlementAmount": {"value": "10.00"}}]
        chargebacks = [{"settlementAmount": {"value": "5.00"}}]
        client = _FakeSettlementsClient(payments=payments, refunds=refunds, chargebacks=chargebacks)
        proc = _make_processor(settlements_client=client)
        # calculated = 100 - 10 - 5 = 85; settlement 85 -> reconciled
        s = _settlement(amount_value="85.00")
        rec = proc._reconcile_settlement_from_object(s)
        self.assertEqual(rec["components"]["refunds"]["count"], 1)
        self.assertEqual(rec["components"]["chargebacks"]["count"], 1)
        self.assertEqual(rec["calculated_total"], 85.0)
        self.assertTrue(rec["reconciled"])


class TestBuildSettlementDescription(unittest.TestCase):
    def _reconciliation(self, payments=0, refunds=0, chargebacks=0, discrepancy=0.0):
        return {
            "components": {
                "payments": {"count": payments, "total": 0.0},
                "refunds": {"count": refunds, "total": 0.0},
                "chargebacks": {"count": chargebacks, "total": 0.0},
                "captures": {"count": 0, "total": 0.0},
            },
            "discrepancy": discrepancy,
        }

    def test_no_transactions(self):
        proc = _make_processor()
        s = _settlement(reference="REF-1")
        desc = proc._build_settlement_description(s, self._reconciliation())
        self.assertIn("REF-1", desc)
        self.assertIn("no transactions", desc)

    def test_lists_components(self):
        proc = _make_processor()
        s = _settlement(reference="REF-2")
        desc = proc._build_settlement_description(
            s, self._reconciliation(payments=3, refunds=1, chargebacks=2)
        )
        self.assertIn("3 payments", desc)
        self.assertIn("1 refunds", desc)
        self.assertIn("2 chargebacks", desc)

    def test_fees_appended_when_discrepancy(self):
        proc = _make_processor()
        s = _settlement()
        desc = proc._build_settlement_description(s, self._reconciliation(payments=1, discrepancy=-2.50))
        self.assertIn("Fees: EUR 2.50", desc)

    def test_no_fees_when_negligible_discrepancy(self):
        proc = _make_processor()
        s = _settlement()
        desc = proc._build_settlement_description(s, self._reconciliation(payments=1, discrepancy=0.005))
        self.assertNotIn("Fees", desc)


class TestProcessSettlementDeposit(unittest.TestCase):
    """End-to-end orchestration of process_settlement_deposit (collaborators faked)."""

    def _proc(self, settlement, *, payments=None, existing_bt=None, bt_name="BT-OK"):
        client = _FakeSettlementsClient(payments=payments or [])
        proc = _make_processor(
            settlements_client=client,
            cache=_FakeCache(settlement=settlement),
            bt=_FakeBTCreator(bt_name=bt_name),
        )
        # Boundary: config validation + existing-BT check + commit are DB ops;
        # pin them so the orchestration is exercised deterministically.
        proc._validate_configuration = lambda: {
            "status": "valid",
            "bank_account": "Mollie",
            "company": "Test Co",
            "mollie_bank_account_gl": "Mollie - TC",
        }
        proc._check_existing_bank_transaction = lambda sid: {
            "exists": bool(existing_bt),
            "name": existing_bt,
        }
        proc._link_payment_entries = lambda *a, **k: 0
        return proc

    def _no_commit(self):
        """Replace frappe.db.commit with a no-op (don't pollute the test DB)."""
        import frappe

        original = frappe.db.commit
        frappe.db.commit = lambda *a, **k: None
        return original

    def test_missing_identifiers_error(self):
        proc = self._proc(None)
        # _get_settlement will be called with both None
        proc.settlement_cache = _FakeCache(settlement=None)
        out = proc.process_settlement_deposit(settlement_id=None, bank_reference=None)
        self.assertEqual(out["status"], "error")

    def test_already_processed(self):
        s = _settlement()
        proc = self._proc(s, existing_bt="BT-EXISTING")
        out = proc.process_settlement_deposit(settlement_id="stl_test1")
        self.assertEqual(out["status"], "already_processed")
        self.assertEqual(out["bank_transaction"], "BT-EXISTING")

    def test_config_error_short_circuits(self):
        s = _settlement()
        proc = self._proc(s)
        proc._validate_configuration = lambda: {"status": "error", "error": "no GL"}
        out = proc.process_settlement_deposit(settlement_id="stl_test1")
        self.assertEqual(out["status"], "error")
        self.assertIn("no GL", out["error"])

    def test_success_creates_bank_transaction(self):
        s = _settlement(amount_value="100.00")
        payments = [{"settlementAmount": {"value": "100.00"}}]
        proc = self._proc(s, payments=payments, bt_name="BT-NEW")
        orig_commit = self._no_commit()
        try:
            out = proc.process_settlement_deposit(settlement_id="stl_test1")
        finally:
            import frappe

            frappe.db.commit = orig_commit
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["bank_transaction"], "BT-NEW")
        self.assertEqual(out["amount"], 100.0)
        self.assertEqual(out["currency"], "EUR")
        self.assertIn("reconciliation_details", out)
        # The nested reconciliation block is assembled by the SUT from the real
        # reconciliation math (1 payment of 100 == settlement 100 -> reconciled).
        self.assertEqual(out["reconciliation_details"]["payments_count"], 1)
        self.assertTrue(out["reconciliation_details"]["reconciled"])

    def test_bt_creation_failure_returns_error(self):
        s = _settlement()
        proc = self._proc(s)
        proc.bank_tx_creator = _FakeBTCreator(bt_name=None)  # creation fails
        orig_commit = self._no_commit()
        try:
            out = proc.process_settlement_deposit(settlement_id="stl_test1")
        finally:
            import frappe

            frappe.db.commit = orig_commit
        self.assertEqual(out["status"], "error")
        self.assertIn("Failed to create Bank Transaction", out["error"])


class TestBatchProcessRecentSettlements(unittest.TestCase):
    def test_only_paidout_settlements_processed(self):
        paidout = _settlement(sid="stl_paid", status="paidout")
        open_one = _settlement(sid="stl_open", status="open")
        client = _FakeSettlementsClient(settlements=[paidout, open_one])
        proc = _make_processor(settlements_client=client)

        processed_ids = []

        def fake_process(settlement_id=None, bank_reference=None):
            processed_ids.append(settlement_id)
            return {"status": "success"}

        proc.process_settlement_deposit = fake_process
        out = proc.batch_process_recent_settlements(days=7)
        self.assertEqual(out["total_settlements"], 2)
        self.assertEqual(out["processed"], 1)
        # only the paidout settlement was forwarded to process_settlement_deposit
        self.assertEqual(processed_ids, ["stl_paid"])

    def test_tallies_already_processed_and_errors(self):
        s1 = _settlement(sid="stl_1", status="paidout")
        s2 = _settlement(sid="stl_2", status="paidout")
        s3 = _settlement(sid="stl_3", status="paidout")
        client = _FakeSettlementsClient(settlements=[s1, s2, s3])
        proc = _make_processor(settlements_client=client)

        outcomes = {"stl_1": "success", "stl_2": "already_processed", "stl_3": "error"}
        proc.process_settlement_deposit = lambda settlement_id=None, **k: {"status": outcomes[settlement_id]}
        out = proc.batch_process_recent_settlements()
        self.assertEqual(out["processed"], 1)
        self.assertEqual(out["already_processed"], 1)
        self.assertEqual(out["errors"], 1)


if __name__ == "__main__":
    unittest.main()
