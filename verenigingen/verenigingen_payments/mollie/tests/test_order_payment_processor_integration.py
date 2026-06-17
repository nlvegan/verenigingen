"""
Integration tests (Tier-2) for OrderPaymentProcessor
(verenigingen/verenigingen_payments/mollie/services/order_payment_processor.py).

LIVE: OrderPaymentProcessor is constructed by payment_type_router.py and
webhook_wrapper_service_unified.py and dispatched to for 'Bestelling'
(WooCommerce/shop) payments.

Credential-free pattern (matches test_dues_payment_processor_integration.py):
    __init__ builds a real MollieClient and a BankTransactionCreator. The
    methods under test are DB-driven (find_sales_invoice_by_number,
    attempt_auto_reconciliation), pure (extract_invoice_number, via the real
    centralized PaymentPatterns), or delegate to collaborators
    (create_bank_transaction -> bank_tx_creator; process_order_payment ->
    mollie_client.sdk_client + the above). We bypass __init__ via
    object.__new__() and attach SimpleNamespace fakes ONLY at the two SDK/
    collaborator boundaries (the Mollie SDK and the bank-transaction creator),
    never mocking the processor logic itself. The invoice-lookup and
    reconciliation methods run against REAL Sales Invoice records.
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.order_payment_processor import (
    OrderPaymentProcessor,
)


def _bare_processor():
    """OrderPaymentProcessor without __init__ (no MollieClient built)."""
    return object.__new__(OrderPaymentProcessor)


def _payment(**kwargs):
    defaults = dict(
        id="tr_order_test",
        status="paid",
        amount={"value": "49.95", "currency": "EUR"},
        description="Bestelling 2025-55986",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestExtractInvoiceNumber(EnhancedTestCase):
    """extract_invoice_number — delegates to the real centralized PaymentPatterns."""

    def test_extract_year_prefixed_number(self):
        proc = _bare_processor()
        self.assertEqual(proc.extract_invoice_number("Bestelling 2025-55986"), "2025-55986")

    def test_extract_bare_number(self):
        proc = _bare_processor()
        self.assertEqual(proc.extract_invoice_number("Bestelling 12345"), "12345")

    def test_no_match_returns_none(self):
        proc = _bare_processor()
        self.assertIsNone(proc.extract_invoice_number("Donation for the cause"))


class TestFindSalesInvoiceByNumber(EnhancedTestCase):
    """find_sales_invoice_by_number — real Sales Invoice DB lookups."""

    def test_unknown_number_returns_none(self):
        proc = _bare_processor()
        token = frappe.generate_hash()[:10]
        self.assertIsNone(proc.find_sales_invoice_by_number(f"NOPE-{token}"))

    def test_exact_name_match(self):
        proc = _bare_processor()
        # Find any submitted Sales Invoice on the site and look it up by name.
        existing = frappe.db.get_value("Sales Invoice", {"docstatus": 1}, "name")
        if not existing:
            self.skipTest("No submitted Sales Invoice on this site to match by name")
        self.assertEqual(proc.find_sales_invoice_by_number(existing), existing)

    def test_draft_invoice_not_matched(self):
        # find_sales_invoice_by_number only matches docstatus=1; a draft name
        # must NOT resolve.
        proc = _bare_processor()
        draft = frappe.db.get_value("Sales Invoice", {"docstatus": 0}, "name")
        if not draft:
            self.skipTest("No draft Sales Invoice on this site")
        self.assertIsNone(proc.find_sales_invoice_by_number(draft))


class TestAttemptAutoReconciliation(EnhancedTestCase):
    """attempt_auto_reconciliation — real Sales Invoice resolution + guards."""

    def test_invoice_not_found(self):
        proc = _bare_processor()
        token = frappe.generate_hash()[:10]
        result = proc.attempt_auto_reconciliation("BT-nonexistent", f"NOPE-{token}")
        self.assertFalse(result["reconciled"])
        self.assertIn("not found", result["message"].lower())
        self.assertIsNone(result["invoice"])

    def test_already_paid_invoice_short_circuits(self):
        proc = _bare_processor()
        # A fully-paid (outstanding<=0) submitted invoice short-circuits before
        # ever loading the Bank Transaction, so the BT name can be a dummy.
        paid = frappe.db.get_value("Sales Invoice", {"docstatus": 1, "outstanding_amount": ["<=", 0]}, "name")
        if not paid:
            self.skipTest("No fully-paid submitted Sales Invoice on this site")
        result = proc.attempt_auto_reconciliation("BT-dummy", paid)
        self.assertFalse(result["reconciled"])
        self.assertEqual(result["invoice"], paid)
        self.assertIn("already fully paid", result["message"])


class TestCreateBankTransaction(EnhancedTestCase):
    """create_bank_transaction — collaborator (bank_tx_creator) boundary stubbed."""

    def test_config_error_returns_none(self):
        # When the bank-account config reports an error, no Bank Transaction is
        # created and None is returned.
        proc = _bare_processor()
        proc.bank_tx_creator = SimpleNamespace(
            get_mollie_bank_account_config=lambda: {"error": "no clearing account"}
        )
        self.assertIsNone(proc.create_bank_transaction(_payment(), "2025-55986"))

    def test_passes_invoice_hint_to_creator(self):
        # On a healthy config, create_bank_transaction forwards the resolved
        # bank account/company and an "Invoice: <n>" hint to the creator and
        # returns its Bank Transaction name.
        proc = _bare_processor()
        captured = {}

        def _create_from_mollie_payment(payment, bank_account, company, additional_description):
            captured["bank_account"] = bank_account
            captured["company"] = company
            captured["additional_description"] = additional_description
            return "BT-CREATED-001"

        proc.bank_tx_creator = SimpleNamespace(
            get_mollie_bank_account_config=lambda: {"bank_account": "Mollie BA", "company": "Test Co"},
            create_from_mollie_payment=_create_from_mollie_payment,
        )

        result = proc.create_bank_transaction(_payment(), "2025-55986")
        self.assertEqual(result, "BT-CREATED-001")
        self.assertEqual(captured["bank_account"], "Mollie BA")
        self.assertEqual(captured["company"], "Test Co")
        self.assertEqual(captured["additional_description"], "Invoice: 2025-55986")

    def test_no_invoice_number_omits_hint(self):
        proc = _bare_processor()
        captured = {}

        def _create_from_mollie_payment(payment, bank_account, company, additional_description):
            captured["additional_description"] = additional_description
            return "BT-CREATED-002"

        proc.bank_tx_creator = SimpleNamespace(
            get_mollie_bank_account_config=lambda: {"bank_account": "BA", "company": "Co"},
            create_from_mollie_payment=_create_from_mollie_payment,
        )
        proc.create_bank_transaction(_payment(), None)
        self.assertIsNone(captured["additional_description"])


class TestProcessOrderPayment(EnhancedTestCase):
    """process_order_payment — orchestration over the (stubbed) SDK + creator."""

    def _processor(self, payment, *, creator):
        proc = _bare_processor()
        proc.mollie_client = SimpleNamespace(
            sdk_client=SimpleNamespace(payments=SimpleNamespace(get=lambda pid: payment))
        )
        proc.bank_tx_creator = creator
        return proc

    def test_unpaid_payment_skipped(self):
        # Non-paid payments are skipped before any bank-transaction work.
        creator = SimpleNamespace(
            get_mollie_bank_account_config=lambda: (_ for _ in ()).throw(
                AssertionError("config must not be read for skipped payments")
            )
        )
        proc = self._processor(_payment(status="open"), creator=creator)
        result = proc.process_order_payment("tr_open")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["payment_type"], "order")
        self.assertIn("not 'paid'", result["message"])

    def test_paid_payment_creates_bank_transaction(self):
        creator = SimpleNamespace(
            get_mollie_bank_account_config=lambda: {"bank_account": "BA", "company": "Co"},
            create_from_mollie_payment=lambda payment, bank_account, company, additional_description: "BT-OK",
        )
        proc = self._processor(_payment(description="Bestelling 2025-55986"), creator=creator)
        result = proc.process_order_payment("tr_paid")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["invoice_number"], "2025-55986")
        self.assertEqual(result["bank_transaction"], "BT-OK")
        self.assertIn("2025-55986", result["message"])

    def test_bank_transaction_failure_is_error(self):
        creator = SimpleNamespace(
            get_mollie_bank_account_config=lambda: {"error": "misconfigured"},
        )
        proc = self._processor(_payment(), creator=creator)
        result = proc.process_order_payment("tr_paid")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "Failed to create Bank Transaction")

    def test_paid_without_invoice_number_still_succeeds(self):
        captured = {}

        def _create(payment, bank_account, company, additional_description):
            captured["hint"] = additional_description
            return "BT-NOINV"

        creator = SimpleNamespace(
            get_mollie_bank_account_config=lambda: {"bank_account": "BA", "company": "Co"},
            create_from_mollie_payment=_create,
        )
        proc = self._processor(_payment(description="random shop payment"), creator=creator)
        result = proc.process_order_payment("tr_paid")

        self.assertEqual(result["status"], "success")
        self.assertIsNone(result["invoice_number"])
        self.assertIsNone(captured["hint"])
        self.assertIn("Manual reconciliation required", result["message"])
