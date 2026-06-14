"""
Tier-1 unit tests for the orchestration *flow* logic in MolliePaymentOrchestrator.

verenigingen/verenigingen_payments/services/mollie_payment_orchestrator.py

These exercise the real branch logic of:
    - _validate_payment_preconditions (idempotency / status / type / member gates)
    - process_payment (full happy path + partial/error branches)
    - _resolve_invoice / _resolve_invoice_fresh (match / TOCTOU-revalidate / discovery)
    - _create_bank_transaction (config-error guard, party linking)
    - process_orphaned_payment (idempotency, status, anonymous policy)
    - process_bt_only_payment (idempotency, status, member resolution)
    - _find_or_create_customer_from_mollie (existing lookup short-circuit)
    - process_payments_batch (dry-run + tallying)

The orchestrator's real __init__ constructs a MollieClient (needs Mollie Settings
keys) plus a DuesPaymentProcessor and BankTransactionCreator that hit the DB and
Mollie config. The only thing being faked here is that *external SDK / collaborator
boundary*: we build the orchestrator with object.__new__ (bypassing __init__) and
attach lightweight fakes for mollie_client / dues_processor / bt_creator. All of
the decision logic under test is the production code. No unittest.mock is used and
no real Mollie network calls happen, so this file is a Tier-1 *_unit.py.

DB-backed reads (get_processing_status) are stubbed at the same boundary by giving
the orchestrator a fake get_processing_status via a tiny subclass, EXCEPT the
db-integration test module which exercises get_processing_status against real Docs.
"""

import unittest
from types import SimpleNamespace

from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
    MolliePaymentOrchestrator,
    PaymentProcessingResult,
    ProcessingStatus,
)


def _payment(status="paid", amount="25.00", **kw):
    """Build a Mollie-payment stand-in (the SDK boundary).

    Carries a Mollie-shaped amount dict so the real PaymentDataExtractor (which IS
    exercised by process_payment) can read value/currency without raising.
    """
    kw.setdefault("amount", {"value": amount, "currency": "EUR"})
    kw.setdefault("id", "tr_fake")
    return SimpleNamespace(status=status, **kw)


class _FakeDuesProcessor:
    """Stands in for DuesPaymentProcessor (SDK + DB boundary).

    Records calls and returns canned values so the orchestration logic can be
    exercised deterministically.
    """

    def __init__(self, payment_type="dues", member=None):
        self._payment_type = payment_type
        self._member = member
        self.consumer_saved = []
        self.created_pes = []
        self.pe_to_return = None  # set per-test
        self.historical_invoice = None

    def identify_payment_type(self, payment):
        return self._payment_type

    def find_member_for_payment(self, payment):
        return self._member

    def _extract_and_save_consumer_bank_data(self, member_name, payment):
        self.consumer_saved.append((member_name, payment))

    def _create_payment_entry_for_dues(self, member_name, payment, **kwargs):
        self.created_pes.append((member_name, kwargs))
        return self.pe_to_return

    def _get_or_create_historical_invoice(self, member_name, payment_date, payment_amount):
        return self.historical_invoice


class _FakeBTCreator:
    def __init__(self, bt_name="BT-FAKE-1", config=None):
        self.bt_name = bt_name
        self._config = config or {"bank_account": "Mollie", "company": "Test Co"}
        self.linked = []
        self.create_calls = []
        self.link_result = True

    def get_mollie_bank_account_config(self):
        return self._config

    def create_from_mollie_payment(self, **kwargs):
        self.create_calls.append(kwargs)
        return self.bt_name

    def link_payment_entry(self, bt_name, pe_name):
        self.linked.append((bt_name, pe_name))
        return self.link_result


class _FakeMollieClient:
    def __init__(self, payment=None, customer=None):
        self._payment = payment
        self._customer = customer
        self.sdk_client = SimpleNamespace(
            payments=SimpleNamespace(get=lambda pid: self._payment),
            customers=SimpleNamespace(get=lambda cid: self._customer),
        )

    def get_payment(self, payment_id):
        return self._payment


def _make_orchestrator(
    *,
    status=None,
    payment=None,
    dues=None,
    bt=None,
    mollie=None,
):
    """Build an orchestrator with __init__ bypassed and fakes attached.

    A ProcessingStatus can be pinned so get_processing_status returns it without
    touching the DB (the DB path is covered by the integration module).
    """
    orch = object.__new__(MolliePaymentOrchestrator)
    orch.dues_processor = dues or _FakeDuesProcessor()
    orch.bt_creator = bt or _FakeBTCreator()
    orch.mollie_client = mollie or _FakeMollieClient(payment=payment)
    orch._bank_config_cache = None

    if status is not None:
        orch.get_processing_status = lambda payment_id: status
    return orch


class TestValidatePreconditions(unittest.TestCase):
    def test_already_complete_returns_already_processed(self):
        status = ProcessingStatus(
            payment_id="tr_1",
            status="complete",
            bank_transaction="BT-1",
            payment_entry="PE-1",
            sales_invoice="SINV-1",
            member="Mem-1",
        )
        orch = _make_orchestrator(status=status)
        result = PaymentProcessingResult(payment_id="tr_1")
        out = orch._validate_payment_preconditions("tr_1", None, None, result)
        self.assertEqual(out, (None, None, None))
        self.assertEqual(result.status, "already_processed")
        self.assertEqual(result.bank_transaction, "BT-1")
        self.assertEqual(result.member, "Mem-1")

    def test_unpaid_payment_is_skipped(self):
        status = ProcessingStatus(payment_id="tr_1", status="unprocessed")
        orch = _make_orchestrator(status=status, payment=_payment(status="open"))
        result = PaymentProcessingResult(payment_id="tr_1")
        out = orch._validate_payment_preconditions("tr_1", None, None, result)
        self.assertEqual(out, (None, None, None))
        self.assertEqual(result.status, "skipped")
        self.assertIn("open", result.skipped_reason)

    def test_non_dues_payment_is_skipped(self):
        status = ProcessingStatus(payment_id="tr_1", status="unprocessed")
        dues = _FakeDuesProcessor(payment_type="donation")
        orch = _make_orchestrator(status=status, payment=_payment(), dues=dues)
        result = PaymentProcessingResult(payment_id="tr_1")
        out = orch._validate_payment_preconditions("tr_1", _payment(), None, result)
        self.assertEqual(out, (None, None, None))
        self.assertEqual(result.status, "skipped")
        self.assertIn("donation", result.skipped_reason)

    def test_no_member_is_error(self):
        status = ProcessingStatus(payment_id="tr_1", status="unprocessed")
        dues = _FakeDuesProcessor(payment_type="dues", member=None)
        orch = _make_orchestrator(status=status, dues=dues)
        result = PaymentProcessingResult(payment_id="tr_1")
        out = orch._validate_payment_preconditions("tr_1", _payment(), None, result)
        self.assertEqual(out, (None, None, None))
        self.assertEqual(result.status, "error")
        self.assertIn("Cannot determine member", result.error)

    def test_valid_payment_returns_triple(self):
        status = ProcessingStatus(payment_id="tr_1", status="unprocessed", member="Mem-9")
        dues = _FakeDuesProcessor(payment_type="dues")
        orch = _make_orchestrator(status=status, dues=dues)
        result = PaymentProcessingResult(payment_id="tr_1")
        payment = _payment()
        st, pay, member = orch._validate_payment_preconditions("tr_1", payment, None, result)
        self.assertIs(st, status)
        self.assertIs(pay, payment)
        # member resolved from status.member
        self.assertEqual(member, "Mem-9")

    def test_member_fetched_when_status_has_none(self):
        status = ProcessingStatus(payment_id="tr_1", status="unprocessed", member=None)
        dues = _FakeDuesProcessor(payment_type="dues", member="Mem-FOUND")
        orch = _make_orchestrator(status=status, dues=dues)
        result = PaymentProcessingResult(payment_id="tr_1")
        st, pay, member = orch._validate_payment_preconditions("tr_1", _payment(), None, result)
        self.assertEqual(member, "Mem-FOUND")


class TestCreateBankTransaction(unittest.TestCase):
    def test_config_error_returns_none_and_logs(self):
        bt = _FakeBTCreator(config={"error": "no clearing account"})
        orch = _make_orchestrator(bt=bt)
        out = orch._create_bank_transaction(_payment(), "Mem-1")
        self.assertIsNone(out)
        self.assertEqual(bt.create_calls, [])

    def test_create_passes_party_when_member_has_customer(self):
        import frappe

        bt = _FakeBTCreator(bt_name="BT-OK")
        orch = _make_orchestrator(bt=bt)
        # Monkeypatch frappe.db.get_value just for the customer lookup (DB boundary)
        original = frappe.db.get_value
        frappe.db.get_value = lambda *a, **k: "CUST-1"
        try:
            out = orch._create_bank_transaction(_payment(), "Mem-1")
        finally:
            frappe.db.get_value = original
        self.assertEqual(out, "BT-OK")
        self.assertEqual(bt.create_calls[0]["party_type"], "Customer")
        self.assertEqual(bt.create_calls[0]["party"], "CUST-1")


class TestResolveInvoice(unittest.TestCase):
    def test_discovery_mode_no_match_returns_none(self):
        orch = _make_orchestrator()
        # Pin find_matching_invoice to a no-match result (collaborator boundary)
        orch.find_matching_invoice = lambda **kw: SimpleNamespace(
            found=False, invoice_name=None, match_type=None, overlap_warning=None
        )
        result = PaymentProcessingResult(payment_id="tr_1")
        status = ProcessingStatus(payment_id="tr_1")  # no cached SINV
        out = orch._resolve_invoice(status, "Mem-1", None, 25.0, False, result)
        self.assertIsNone(out)
        self.assertTrue(any("No matching invoice" in a for a in result.actions_taken))

    def test_fresh_match_returns_invoice(self):
        orch = _make_orchestrator()
        orch.find_matching_invoice = lambda **kw: SimpleNamespace(
            found=True, invoice_name="SINV-7", match_type="exact", overlap_warning=None
        )
        result = PaymentProcessingResult(payment_id="tr_1")
        status = ProcessingStatus(payment_id="tr_1")
        out = orch._resolve_invoice(status, "Mem-1", None, 25.0, False, result)
        self.assertEqual(out, "SINV-7")
        self.assertTrue(any("Matched invoice SINV-7" in a for a in result.actions_taken))

    def test_cached_invoice_still_payable_is_reused(self):
        import frappe

        orch = _make_orchestrator()
        result = PaymentProcessingResult(payment_id="tr_1")
        status = ProcessingStatus(payment_id="tr_1", sales_invoice="SINV-CACHED")
        original = frappe.db.get_value
        frappe.db.get_value = lambda *a, **k: 25.0  # still outstanding
        try:
            out = orch._resolve_invoice(status, "Mem-1", None, 25.0, False, result)
        finally:
            frappe.db.get_value = original
        self.assertEqual(out, "SINV-CACHED")

    def test_cached_invoice_now_paid_falls_back_to_fresh(self):
        import frappe

        orch = _make_orchestrator()
        orch.find_matching_invoice = lambda **kw: SimpleNamespace(
            found=True, invoice_name="SINV-NEW", match_type="amount", overlap_warning=None
        )
        result = PaymentProcessingResult(payment_id="tr_1")
        status = ProcessingStatus(payment_id="tr_1", sales_invoice="SINV-PAID")
        original = frappe.db.get_value
        frappe.db.get_value = lambda *a, **k: 0.0  # fully paid now
        try:
            out = orch._resolve_invoice(status, "Mem-1", None, 25.0, False, result)
        finally:
            frappe.db.get_value = original
        self.assertEqual(out, "SINV-NEW")
        self.assertTrue(any("now fully paid" in a for a in result.actions_taken))


class TestProcessPaymentFlow(unittest.TestCase):
    """End-to-end orchestration with collaborator boundary faked."""

    def _orch_for_flow(self, status, *, pe_to_return="PE-1", bt_name="BT-1"):
        dues = _FakeDuesProcessor(payment_type="dues", member="Mem-1")
        dues.pe_to_return = pe_to_return
        bt = _FakeBTCreator(bt_name=bt_name)
        orch = _make_orchestrator(status=status, payment=_payment(), dues=dues, bt=bt)
        # Boundary: extractor + invoice match
        orch.find_matching_invoice = lambda **kw: SimpleNamespace(
            found=True, invoice_name="SINV-1", match_type="exact", overlap_warning=None
        )
        return orch, dues, bt

    def test_full_happy_path_creates_bt_pe_and_links(self):
        status = ProcessingStatus(payment_id="tr_1", status="unprocessed", member="Mem-1")
        orch, dues, bt = self._orch_for_flow(status)
        out = orch.process_payment("tr_1")
        self.assertEqual(out.status, "success")
        self.assertEqual(out.bank_transaction, "BT-1")
        self.assertEqual(out.payment_entry, "PE-1")
        self.assertTrue(out.reconciled)
        self.assertEqual(bt.linked, [("BT-1", "PE-1")])

    def test_already_processed_short_circuits(self):
        status = ProcessingStatus(
            payment_id="tr_1",
            status="complete",
            bank_transaction="BT-X",
            payment_entry="PE-X",
            sales_invoice="SINV-X",
        )
        orch, _, _ = self._orch_for_flow(status)
        out = orch.process_payment("tr_1")
        self.assertEqual(out.status, "already_processed")

    def test_pe_creation_fails_marks_partial(self):
        # When an invoice IS present but PE creation returns None, the explicit
        # failed_step branch (which only fires when invoice_name is falsy) is NOT
        # taken; _determine_final_status downgrades to "partial / missing Payment
        # Entry" with failed_step left None. This pins that real behavior.
        status = ProcessingStatus(payment_id="tr_1", status="unprocessed", member="Mem-1")
        orch, dues, bt = self._orch_for_flow(status, pe_to_return=None)
        orch.find_matching_invoice = lambda **kw: SimpleNamespace(
            found=True, invoice_name="SINV-1", match_type="exact", overlap_warning=None
        )
        out = orch.process_payment("tr_1", create_missing_invoice=True)
        self.assertEqual(out.status, "partial")
        self.assertIsNone(out.payment_entry)
        self.assertIn("Payment Entry", out.error)

    def test_pe_failure_with_no_invoice_records_failed_step(self):
        # Recovery mode (create_missing_invoice=True) with NO invoice resolvable:
        # PE returns None AND invoice_name is falsy -> explicit failed_step branch.
        status = ProcessingStatus(payment_id="tr_1", status="unprocessed", member="Mem-1")
        orch, dues, bt = self._orch_for_flow(status, pe_to_return=None)
        # No invoice found and recovery-mode creation also yields nothing.
        orch.find_matching_invoice = lambda **kw: SimpleNamespace(
            found=False, invoice_name=None, match_type=None, overlap_warning=None
        )
        orch._create_invoice_if_safe = lambda **kw: None
        out = orch.process_payment("tr_1", create_missing_invoice=True)
        self.assertEqual(out.status, "partial")
        self.assertEqual(out.failed_step, "create_payment_entry")

    def test_link_failure_records_link_error(self):
        status = ProcessingStatus(payment_id="tr_1", status="unprocessed", member="Mem-1")
        orch, dues, bt = self._orch_for_flow(status)
        bt.link_result = False
        out = orch.process_payment("tr_1")
        # BT and PE both created, but link failed -> still success per _determine_final_status
        self.assertEqual(out.status, "success")
        self.assertFalse(out.reconciled)
        self.assertIsNotNone(out.link_error)


class TestProcessOrphanedPayment(unittest.TestCase):
    def test_existing_bt_is_idempotent(self):
        import frappe

        orch = _make_orchestrator()
        original = frappe.db.get_value
        frappe.db.get_value = lambda *a, **k: "BT-EXISTING"
        try:
            out = orch.process_orphaned_payment("tr_1", payment=_payment())
        finally:
            frappe.db.get_value = original
        self.assertEqual(out.status, "already_processed")
        self.assertEqual(out.bank_transaction, "BT-EXISTING")

    def test_unpaid_payment_skipped(self):
        import frappe

        orch = _make_orchestrator()
        original = frappe.db.get_value
        frappe.db.get_value = lambda *a, **k: None  # no existing BT
        try:
            out = orch.process_orphaned_payment("tr_1", payment=_payment(status="failed"))
        finally:
            frappe.db.get_value = original
        self.assertEqual(out.status, "skipped")

    def test_anonymous_disallowed_no_customer_id_errors(self):
        import frappe

        orch = _make_orchestrator()
        original = frappe.db.get_value
        frappe.db.get_value = lambda *a, **k: None
        try:
            out = orch.process_orphaned_payment(
                "tr_1", payment=_payment(customer_id=None), allow_anonymous=False
            )
        finally:
            frappe.db.get_value = original
        self.assertEqual(out.status, "error")
        self.assertIn("anonymous", out.error.lower())

    def test_anonymous_payment_creates_unlinked_bt(self):
        import frappe

        bt = _FakeBTCreator(bt_name="BT-ANON")
        orch = _make_orchestrator(bt=bt)
        original = frappe.db.get_value
        # First call: existing-BT check -> None. _get_bank_account_config uses bt.get_mollie...
        frappe.db.get_value = lambda *a, **k: None
        try:
            out = orch.process_orphaned_payment("tr_1", payment=_payment(customer_id=None))
        finally:
            frappe.db.get_value = original
        self.assertEqual(out.status, "success")
        self.assertEqual(out.bank_transaction, "BT-ANON")
        self.assertTrue(any("Anonymous payment" in a for a in out.actions_taken))
        # no party link
        self.assertIsNone(bt.create_calls[0]["party"])


class TestProcessBtOnlyPayment(unittest.TestCase):
    def test_existing_bt_is_idempotent(self):
        import frappe

        orch = _make_orchestrator()
        original = frappe.db.get_value
        frappe.db.get_value = lambda *a, **k: "BT-EXISTING"
        try:
            out = orch.process_bt_only_payment("tr_1", payment=_payment())
        finally:
            frappe.db.get_value = original
        self.assertEqual(out.status, "already_processed")

    def test_unpaid_skipped(self):
        import frappe

        orch = _make_orchestrator()
        original = frappe.db.get_value
        frappe.db.get_value = lambda *a, **k: None
        try:
            out = orch.process_bt_only_payment("tr_1", payment=_payment(status="open"))
        finally:
            frappe.db.get_value = original
        self.assertEqual(out.status, "skipped")

    def test_member_resolved_and_bt_created_with_customer(self):
        import frappe

        dues = _FakeDuesProcessor(payment_type="dues", member="Mem-1")
        bt = _FakeBTCreator(bt_name="BT-BTONLY")
        orch = _make_orchestrator(dues=dues, bt=bt)

        calls = {"n": 0}

        def fake_get_value(*a, **k):
            calls["n"] += 1
            # call 1: existing BT check -> None
            if calls["n"] == 1:
                return None
            # subsequent: Member.customer lookup -> CUST-1
            return "CUST-1"

        original = frappe.db.get_value
        frappe.db.get_value = fake_get_value
        try:
            out = orch.process_bt_only_payment("tr_1", payment=_payment())
        finally:
            frappe.db.get_value = original
        self.assertEqual(out.status, "success")
        self.assertEqual(out.member, "Mem-1")
        self.assertEqual(bt.create_calls[0]["party"], "CUST-1")


class TestFindOrCreateCustomerFromMollie(unittest.TestCase):
    def test_existing_customer_short_circuits(self):
        import frappe

        orch = _make_orchestrator()
        result = PaymentProcessingResult(payment_id="tr_1")
        original = frappe.db.get_value
        frappe.db.get_value = lambda *a, **k: "CUST-EXISTING"
        try:
            out = orch._find_or_create_customer_from_mollie("cst_1", _payment(), result)
        finally:
            frappe.db.get_value = original
        self.assertEqual(out, "CUST-EXISTING")
        self.assertTrue(any("Found existing Customer" in a for a in result.actions_taken))


class TestProcessPaymentsBatch(unittest.TestCase):
    def test_dry_run_only_checks_status(self):
        status = ProcessingStatus(payment_id="tr_1", status="unprocessed")
        orch = _make_orchestrator(status=status)
        out = orch.process_payments_batch(["tr_1", "tr_2"], dry_run=True)
        self.assertEqual(out["total_requested"], 2)
        self.assertTrue(out["dry_run"])
        self.assertEqual(len(out["results"]), 2)
        self.assertEqual(out["results"][0]["status"], "dry_run")

    def test_batch_tallies_outcomes(self):
        status = ProcessingStatus(payment_id="x", status="unprocessed", member="Mem-1")
        dues = _FakeDuesProcessor(payment_type="dues", member="Mem-1")
        dues.pe_to_return = "PE-1"
        bt = _FakeBTCreator(bt_name="BT-1")
        orch = _make_orchestrator(status=status, payment=_payment(), dues=dues, bt=bt)
        orch.find_matching_invoice = lambda **kw: SimpleNamespace(
            found=True, invoice_name="SINV-1", match_type="exact", overlap_warning=None
        )
        out = orch.process_payments_batch(["tr_1"])
        self.assertEqual(out["processed"], 1)
        self.assertEqual(out["errors"], 0)


if __name__ == "__main__":
    unittest.main()
