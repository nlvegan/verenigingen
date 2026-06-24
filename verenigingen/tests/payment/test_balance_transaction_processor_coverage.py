#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coverage tests for verenigingen_payments/services/balance_transaction_processor.py

Targets the BalanceTransactionProcessor *service* directly (the sibling
test_balance_transaction_processing.py exercises the API wrappers). Focus areas:

- _build_transaction_description: every branch (payment desc / type fallback,
  payment id, settlement id, fee line, gross-vs-net detail).
- _process_single_transaction:
    * the three multi-field idempotency strategies (reference_number by tx id,
      reference_number by payment id, transaction_id field) asserted against
      REAL Bank Transaction rows.
    * the config-error early return (config boundary).
    * the SUCCESS path for both a regular payment (gross amount, deposit
      direction) and a settlement (net amount after fees) - asserting the REAL
      Bank Transaction that gets written has the correct amount/direction/refs.
- process_balance_transactions: aggregation of mixed success / already-processed
  / error results, and the outer client-failure branch.

Seaming the ONE external (Mollie) boundary:
    The processor's only external dependency is the Mollie SDK client
    (BalancesClient). We inject a hand-written fake client onto the processor
    instance (constructor-style injection: `processor.balances_client = fake`)
    that returns REAL BalanceTransaction model objects we fabricate - no Mollie
    HTTP, no frappe.db mocking. For the success path we additionally point the
    BankTransactionCreator config boundary at a REAL Bank Account we create
    (patching get_mollie_bank_account_config, a config/environment seam, exactly
    as the sibling API test does), so creator.create() writes a real BT.
"""

from decimal import Decimal
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.core.models.balance import BalanceTransaction
from verenigingen.verenigingen_payments.services.balance_transaction_processor import (
    BalanceTransactionProcessor,
)


def _make_balance_transaction(
    tx_id="baltr_TESTXYZ",
    tx_type="payment",
    initial_value="10.00",
    result_value="9.71",
    currency="EUR",
    created_at="2024-06-01T10:00:00+00:00",
    context=None,
    deductions=None,
):
    """Build a REAL BalanceTransaction model object from API-shaped dict."""
    data = {
        "resource": "balance_transaction",
        "id": tx_id,
        "type": tx_type,
        "initialAmount": {"value": initial_value, "currency": currency},
        "resultAmount": {"value": result_value, "currency": currency},
        "createdAt": created_at,
        "context": context or {},
    }
    if deductions is not None:
        data["deductions"] = deductions
    return BalanceTransaction(data)


class _FakeBalancesClient:
    """Minimal hand-written stand-in for the Mollie BalancesClient SDK.

    Records the args it is called with and returns pre-seeded model objects.
    This is the external-API seam - NOT a frappe.db mock.
    """

    def __init__(self, transactions=None, raise_on_list=None):
        self._transactions = transactions or []
        self._raise_on_list = raise_on_list
        self.list_calls = []

    def list_balance_transactions(self, balance_id, from_date=None, until_date=None, limit=250):
        self.list_calls.append(
            {"balance_id": balance_id, "from_date": from_date, "until_date": until_date, "limit": limit}
        )
        if self._raise_on_list:
            raise self._raise_on_list
        return list(self._transactions)


class TestBuildTransactionDescription(EnhancedTestCase):
    """Pure-helper tests for _build_transaction_description (no DB writes)."""

    def setUp(self):
        super().setUp()
        self.processor = BalanceTransactionProcessor()
        # Replace the real Mollie client with a fake so __init__'s client is inert.
        self.processor.balances_client = _FakeBalancesClient()

    def test_uses_payment_description_when_present(self):
        desc = self.processor._build_transaction_description(
            transaction_type="payment",
            payment_id=None,
            settlement_id=None,
            initial_amount=10.0,
            result_amount=10.0,
            deductions=0.0,
            payment_description="Lidmaatschap 2024",
        )
        self.assertTrue(desc.startswith("Lidmaatschap 2024"))

    def test_falls_back_to_titlecased_type_when_no_payment_description(self):
        desc = self.processor._build_transaction_description(
            transaction_type="outgoing-transfer",
            payment_id=None,
            settlement_id=None,
            initial_amount=5.0,
            result_amount=5.0,
            deductions=0.0,
            payment_description=None,
        )
        # 'outgoing-transfer' -> 'Outgoing Transfer'
        self.assertEqual(desc, "Mollie Outgoing Transfer")

    def test_appends_payment_id_reference(self):
        desc = self.processor._build_transaction_description(
            "payment", "tr_PAYID123", None, 10.0, 10.0, 0.0, "Donation"
        )
        self.assertIn("| tr_PAYID123", desc)

    def test_appends_settlement_reference(self):
        desc = self.processor._build_transaction_description(
            "settlement", None, "stl_SET999", 100.0, 97.0, 3.0, None
        )
        self.assertIn("Settlement: stl_SET999", desc)

    def test_appends_fee_line_when_deductions_present(self):
        desc = self.processor._build_transaction_description(
            "settlement", None, "stl_X", 100.0, 97.0, -3.50, None
        )
        # abs() of fee, two decimals
        self.assertIn("Fees: EUR 3.50", desc)

    def test_no_fee_line_when_deductions_negligible(self):
        desc = self.processor._build_transaction_description(
            "payment", "tr_X", None, 10.0, 10.0, 0.0, "Pay"
        )
        self.assertNotIn("Fees:", desc)

    def test_appends_gross_net_detail_when_they_differ(self):
        desc = self.processor._build_transaction_description(
            "settlement", None, "stl_Y", 100.0, 97.0, -3.0, None
        )
        self.assertIn("Gross: EUR 100.00", desc)
        self.assertIn("Net: EUR 97.00", desc)

    def test_no_gross_net_detail_when_equal(self):
        desc = self.processor._build_transaction_description(
            "payment", "tr_Z", None, 10.0, 10.0, 0.0, "Pay"
        )
        self.assertNotIn("Gross:", desc)


class TestProcessSingleTransactionIdempotency(EnhancedTestCase):
    """Idempotency strategies against REAL Bank Transaction rows."""

    def setUp(self):
        super().setUp()
        self.processor = BalanceTransactionProcessor()
        self.processor.balances_client = _FakeBalancesClient()

    def _make_bank_transaction(self, reference_number=None, transaction_id=None,
                               deposit=10.0, description="Existing BT"):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = frappe.utils.today()
        bt.deposit = deposit
        bt.withdrawal = 0.0
        bt.currency = "EUR"
        if reference_number:
            bt.reference_number = reference_number
        if transaction_id:
            bt.transaction_id = transaction_id
        bt.description = description
        bt.insert(ignore_permissions=True)
        self._track_test_document("Bank Transaction", bt.name)
        return bt

    def test_strategy1_existing_by_balance_tx_reference(self):
        """A balance tx whose ID is already a reference_number is already_processed."""
        ref = "baltr_S1_001"
        bt = self._make_bank_transaction(reference_number=ref, transaction_id=ref)
        tx = _make_balance_transaction(tx_id=ref, context={})
        result = self.processor._process_single_transaction(tx)
        self.assertEqual(result["status"], "already_processed")
        self.assertEqual(result["bank_transaction"], bt.name)
        self.assertIn("reference_number", result["message"])

    def test_strategy2_existing_by_payment_id_reference(self):
        """A new balance tx whose payment_id already maps to a BT (created by the
        dues processor) is detected via reference_number=payment_id and NOT
        duplicated."""
        payment_id = "tr_S2_PAY"
        bt = self._make_bank_transaction(reference_number=payment_id)
        tx = _make_balance_transaction(
            tx_id="baltr_S2_NEW", context={"paymentId": payment_id}
        )
        result = self.processor._process_single_transaction(tx)
        self.assertEqual(result["status"], "already_processed")
        self.assertEqual(result["bank_transaction"], bt.name)
        self.assertIn(payment_id, result["message"])

    def test_strategy3_existing_by_transaction_id_field(self):
        """The unique transaction_id field is also consulted (payment_id priority)."""
        payment_id = "tr_S3_PAY"
        # No matching reference_number, but the transaction_id field carries payment_id.
        bt = self._make_bank_transaction(
            reference_number="some-other-ref-s3", transaction_id=payment_id
        )
        tx = _make_balance_transaction(
            tx_id="baltr_S3_NEW", context={"payment_id": payment_id}
        )
        result = self.processor._process_single_transaction(tx)
        self.assertEqual(result["status"], "already_processed")
        self.assertEqual(result["bank_transaction"], bt.name)
        self.assertIn("transaction_id field", result["message"])

    def test_config_error_returns_error_status(self):
        """With Mollie GL config unavailable, a brand-new tx returns a config error
        and creates NO Bank Transaction."""
        tx = _make_balance_transaction(tx_id="baltr_CFGERR", context={})
        with patch(
            "verenigingen.verenigingen_payments.services.bank_transaction_creator."
            "BankTransactionCreator.get_mollie_bank_account_config",
            return_value={"error": "Configuration validation failed: clearing account not set"},
        ):
            result = self.processor._process_single_transaction(tx)
        self.assertEqual(result["status"], "error")
        self.assertIn("Configuration", result["error"])
        self.assertFalse(frappe.db.exists("Bank Transaction", {"reference_number": "baltr_CFGERR"}))


class TestProcessSingleTransactionSuccess(EnhancedTestCase):
    """Success path: a real Bank Transaction is created with the right
    amount/direction/reference. Points the config boundary at a real Bank Account.
    """

    def setUp(self):
        super().setUp()
        self.processor = BalanceTransactionProcessor()
        self.processor.balances_client = _FakeBalancesClient()
        self.company = frappe.get_list("Company", limit=1)[0].name
        self.bank_account = self._ensure_bank_account()
        self._config = {"bank_account": self.bank_account, "company": self.company}
        self._cleanup_bank_transactions()

    def tearDown(self):
        self._cleanup_bank_transactions()
        super().tearDown()

    def _ensure_bank_account(self):
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        bank = get_or_create_unknown_bank()
        iban = "NL44RABO0123456789"
        existing = frappe.db.get_value("Bank Account", {"bank_account_no": iban}, "name")
        if existing:
            return existing
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"BalTx Test Account {self.uid}"
        ba.bank = bank
        ba.company = self.company
        ba.bank_account_no = iban
        ba.iban = iban
        ba.insert(ignore_permissions=True)
        self.created_records.append(("Bank Account", ba.name))
        return ba.name

    def _cleanup_bank_transactions(self):
        """The creator's secure-operation audit logger commits, so BTs survive
        rollback; scrub ours so counts stay deterministic across tests."""
        for bt in frappe.get_all(
            "Bank Transaction", filters={"bank_account": self.bank_account}, fields=["name"]
        ):
            doc = frappe.get_doc("Bank Transaction", bt.name)
            if doc.docstatus == 1:
                doc.cancel()
            doc.delete(ignore_permissions=True)
        frappe.db.commit()

    def _config_patch(self):
        return patch(
            "verenigingen.verenigingen_payments.services.bank_transaction_creator."
            "BankTransactionCreator.get_mollie_bank_account_config",
            return_value=dict(self._config),
        )

    def test_regular_payment_records_gross_amount_as_deposit(self):
        """A non-settlement payment records the GROSS (initial) amount as a deposit.

        initial=12.00 (gross), result=11.65 (net after per-payment fee). For a
        regular payment the BT is recorded at the gross 12.00, not the net.
        """
        ref = "baltr_OK_PAY"
        tx = _make_balance_transaction(
            tx_id=ref,
            tx_type="payment",
            initial_value="12.00",
            result_value="11.65",
            context={"paymentId": "tr_OKPAY", "paymentDescription": "Member dues"},
        )
        with self._config_patch():
            result = self.processor._process_single_transaction(tx)
        self.assertEqual(result["status"], "success", result.get("error"))
        bt = frappe.get_doc("Bank Transaction", result["bank_transaction"])
        # Gross amount recorded, deposit direction (positive initial).
        self.assertEqual(float(bt.deposit), 12.00)
        self.assertEqual(float(bt.withdrawal), 0.0)
        # Payment transactions key off payment_id for cross-API idempotency.
        self.assertEqual(bt.reference_number, "tr_OKPAY")
        self.assertEqual(bt.transaction_id, "tr_OKPAY")
        self.assertEqual(result["amount"], 12.00)

    def test_settlement_records_net_amount_after_fees(self):
        """A settlement (settlementId in context) records the NET (result) amount,
        because that's what actually hits the real bank account, and surfaces fees.

        initial=100.00 gross, result=97.00 net, deductions total -3.00.
        """
        ref = "baltr_OK_SET"
        tx = _make_balance_transaction(
            tx_id=ref,
            tx_type="settlement",
            initial_value="100.00",
            result_value="97.00",
            context={"settlementId": "stl_OK999"},
            deductions=[{"amount": {"value": "-3.00", "currency": "EUR"}}],
        )
        with self._config_patch():
            result = self.processor._process_single_transaction(tx)
        self.assertEqual(result["status"], "success", result.get("error"))
        bt = frappe.get_doc("Bank Transaction", result["bank_transaction"])
        # NET amount recorded (97.00), not gross (100.00).
        self.assertEqual(float(bt.deposit), 97.00)
        self.assertEqual(result["amount"], 97.00)
        # Settlement keys off settlement_id.
        self.assertEqual(bt.reference_number, "stl_OK999")
        self.assertEqual(bt.transaction_id, "stl_OK999")
        # Fees surfaced for settlements.
        self.assertEqual(result["fees"], -3.00)
        self.assertIn("Fees: EUR 3.00", bt.description)

    def test_negative_initial_payment_records_as_withdrawal(self):
        """A regular payment with a negative gross amount (e.g. refund/chargeback)
        is recorded as a withdrawal."""
        ref = "baltr_OK_NEG"
        tx = _make_balance_transaction(
            tx_id=ref,
            tx_type="refund",
            initial_value="-8.00",
            result_value="-8.00",
            context={"paymentId": "tr_NEG"},
        )
        with self._config_patch():
            result = self.processor._process_single_transaction(tx)
        self.assertEqual(result["status"], "success", result.get("error"))
        bt = frappe.get_doc("Bank Transaction", result["bank_transaction"])
        self.assertEqual(float(bt.withdrawal), 8.00)
        self.assertEqual(float(bt.deposit), 0.0)


class TestProcessBalanceTransactionsAggregation(EnhancedTestCase):
    """process_balance_transactions: aggregate counts and outer error branch.

    Uses the injected fake client (external seam). The 'processed' branch needs
    Mollie GL config which the bare test site lacks, so we drive a MIXED batch of
    already-processed (real BT exists) + error (config missing) transactions and
    assert the aggregation, then a separate client-failure case.
    """

    def setUp(self):
        super().setUp()
        self.processor = BalanceTransactionProcessor()

    def _make_bank_transaction(self, reference_number):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = frappe.utils.today()
        bt.deposit = 5.0
        bt.withdrawal = 0.0
        bt.currency = "EUR"
        bt.reference_number = reference_number
        bt.transaction_id = reference_number
        bt.description = "Pre-existing"
        bt.insert(ignore_permissions=True)
        self._track_test_document("Bank Transaction", bt.name)
        return bt

    def test_aggregates_already_processed_and_errors(self):
        existing_ref = "baltr_AGG_DUP"
        self._make_bank_transaction(existing_ref)
        already = _make_balance_transaction(tx_id=existing_ref, context={})
        new_err = _make_balance_transaction(tx_id="baltr_AGG_NEW", context={})

        self.processor.balances_client = _FakeBalancesClient(transactions=[already, new_err])
        with patch(
            "verenigingen.verenigingen_payments.services.bank_transaction_creator."
            "BankTransactionCreator.get_mollie_bank_account_config",
            return_value={"error": "Configuration validation failed: not set"},
        ):
            result = self.processor.process_balance_transactions(balance_id="bal_X", limit=10)

        self.assertEqual(result["total_transactions"], 2)
        self.assertEqual(result["already_processed"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(len(result["results"]), 2)
        # The fake client received our balance_id.
        self.assertEqual(self.processor.balances_client.list_calls[0]["balance_id"], "bal_X")

    def test_empty_list_returns_clean_zero_counts(self):
        self.processor.balances_client = _FakeBalancesClient(transactions=[])
        result = self.processor.process_balance_transactions(balance_id="bal_EMPTY", limit=10)
        self.assertEqual(result["total_transactions"], 0)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["already_processed"], 0)
        self.assertEqual(result["errors"], 0)
        self.assertNotIn("error", result)

    def test_client_failure_is_captured_in_outer_error(self):
        """If the Mollie client raises, the outer try/except records a top-level
        error and returns the zero-count skeleton (does not propagate)."""
        self.processor.balances_client = _FakeBalancesClient(
            raise_on_list=RuntimeError("mollie unreachable")
        )
        # The processor logs the client failure via frappe.log_error before
        # surfacing it as a structured top-level error (not raised). Register that
        # expected Error Log title so the automatic tearDown check ignores it.
        self.expectErrorLog("Balance Transaction Processing Error")
        result = self.processor.process_balance_transactions(balance_id="bal_FAIL", limit=10)
        self.assertEqual(result["total_transactions"], 0)
        self.assertEqual(result["processed"], 0)
        self.assertIn("error", result)
        self.assertIn("mollie unreachable", result["error"])
