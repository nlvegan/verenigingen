"""
Integration tests for the CENTRAL MUTATION-TYPE DISPATCHER
``_process_single_mutation`` in
``e_boekhouden/utils/eboekhouden_rest_full_migration.py``.

``_process_single_mutation`` is the money-path router: given a fetched mutation
it decides which ERPNext financial document to create based on the eBoekhouden
``type`` field (1=Purchase Invoice, 2=Sales Invoice, 3/4=Customer/Supplier
Payment, 5/6=Money Received/Paid, else=Journal Entry). Existing suites test the
individual creators (``_create_journal_entry`` / ``_create_payment_entry`` /
``_create_money_transfer_payment_entry``) DIRECTLY, but do NOT exercise the
routing DECISION for the payment family (types 3/4/5/6). The most interesting
branch is the credit-note-refund detection:

    type in (3, 4) AND (main amount < 0 OR first row amount < 0)
                    AND invoiceNumber present   ->  Journal Entry (refund)
    otherwise                                    ->  Payment Entry

A regression that dropped the ``invoiceNumber`` guard, or routed on
``is_negative`` alone, or swapped the JE/PE targets, would silently mis-book
refunds. These tests pin that decision by asserting the DOCTYPE the dispatcher
actually produces plus the financial correctness of the produced document.

Reuses the fully-provisioned EUR payment company / bank / party fixtures from
``test_rest_migration_payments`` (``_PaymentTestBase``). The only mocked
boundary is the eBoekhouden REST *iterator* (its real ``__init__`` loads an
api_token that is absent in CI); ``fetch_mutation_detail`` is faked to return
the canned mutation. Everything else — accounts, ledger mappings, JE/PE
creation, submission — is real.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_rest_full_migration_dispatch_coverage
"""

from unittest.mock import patch

import frappe
from frappe.utils import flt, today

from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import (
    _create_payment_entry,
    _process_single_mutation,
)
from verenigingen.tests.e_boekhouden.test_rest_migration_payments import (
    BANK_LEDGER,
    EXPENSE_LEDGER,
    INCOME_LEDGER,
    _PaymentTestBase,
    _persist_ledger_mapping,
)

# Ledger ids PRIVATE to this suite that resolve to the payment company's
# receivable / payable accounts, so refund Journal Entries can carry parties.
RECEIVABLE_LEDGER = 800310
PAYABLE_LEDGER = 800410

# eboekhouden_rest_iterator import path patched inside _process_single_mutation.
_ITERATOR_PATH = "verenigingen.e_boekhouden.utils.eboekhouden_rest_iterator.EBoekhoudenRESTIterator"


class _FakeIterator:
    """Replaces the EBoekhoudenRESTIterator CLASS. Constructing it
    (``EBoekhoudenRESTIterator()``) returns this same instance (``__call__``),
    and ``fetch_mutation_detail`` returns the canned detail (or None to force
    the summary-data fallback)."""

    def __init__(self, detail):
        self._detail = detail

    def __call__(self):
        return self

    def fetch_mutation_detail(self, mutation_id):
        return self._detail


class _DispatchBase(_PaymentTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Extra ledger mappings (payment base only maps bank/income/expense) so
        # refund JE rows land on party-carrying receivable/payable accounts.
        _persist_ledger_mapping(RECEIVABLE_LEDGER, cls.receivable)
        _persist_ledger_mapping(PAYABLE_LEDGER, cls.payable)
        frappe.db.commit()

    def _dispatch(self, mutation, detail=None):
        """Run the dispatcher with the iterator faked to return ``detail``
        (defaults to the mutation itself)."""
        fake = _FakeIterator(mutation if detail is None else detail)
        with patch(_ITERATOR_PATH, new=fake):
            return _process_single_mutation(mutation, self.company, self.cost_center, [])


class TestPaymentFamilyDispatch(_DispatchBase):
    # ---- credit-note refund (negative + invoiceNumber) -> Journal Entry ----

    def test_type3_negative_amount_with_invoice_routes_to_journal_entry(self):
        """A customer refund (type 3, negative amount, invoice ref) must become a
        balanced Journal Entry — NOT a Payment Entry."""
        mut = {
            "id": self._uid(),
            "type": 3,
            "date": today(),
            "amount": -75.0,
            "ledgerId": BANK_LEDGER,  # main -> bank offset leg
            "relationId": "REL-CUST-1",
            "invoiceNumber": "CN-REFUND-3",
            "description": "Customer credit-note refund",
            "rows": [{"ledgerId": RECEIVABLE_LEDGER, "amount": -75.0, "description": "refund line"}],
        }
        result = self._dispatch(mut)

        self.assertEqual(result.doctype, "Journal Entry")
        saved = frappe.get_doc("Journal Entry", result.name)
        self.assertEqual(saved.docstatus, 1)
        # Refund JE stores the invoice number for manual reconciliation.
        self.assertEqual(saved.eboekhouden_invoice_number, "CN-REFUND-3")
        # Two legs (receivable row + bank offset), balanced.
        self.assertEqual(flt(saved.total_debit, 2), flt(saved.total_credit, 2))
        self.assertEqual(flt(saved.total_debit, 2), 75.0)
        # Receivable leg carries the Customer party.
        recv = [a for a in saved.accounts if a.account == self.receivable]
        self.assertEqual(len(recv), 1)
        self.assertEqual(recv[0].party_type, "Customer")
        self.assertEqual(recv[0].party, self.customer)
        # Bank offset present.
        self.assertTrue(any(a.account == self.bank for a in saved.accounts))

    def test_type4_negative_amount_with_invoice_routes_to_journal_entry(self):
        """A supplier refund (type 4, negative, invoice ref) also routes to a JE
        and carries the Supplier party on the payable leg."""
        mut = {
            "id": self._uid(),
            "type": 4,
            "date": today(),
            "amount": -40.0,
            "ledgerId": BANK_LEDGER,
            "relationId": "REL-SUPP-1",
            "invoiceNumber": "CN-REFUND-4",
            "description": "Supplier credit-note refund",
            "rows": [{"ledgerId": PAYABLE_LEDGER, "amount": -40.0, "description": "refund line"}],
        }
        result = self._dispatch(mut)

        self.assertEqual(result.doctype, "Journal Entry")
        saved = frappe.get_doc("Journal Entry", result.name)
        self.assertEqual(saved.docstatus, 1)
        self.assertEqual(flt(saved.total_debit, 2), 40.0)
        self.assertEqual(flt(saved.total_debit, 2), flt(saved.total_credit, 2))
        pay = [a for a in saved.accounts if a.account == self.payable]
        self.assertEqual(len(pay), 1)
        self.assertEqual(pay[0].party_type, "Supplier")
        self.assertEqual(pay[0].party, self.supplier)

    def test_type3_positive_main_but_negative_row_with_invoice_routes_to_je(self):
        """The refund detector ORs main-amount and first-row-amount. A zero/positive
        top-level amount whose first row is negative (with invoice ref) is still a
        refund -> Journal Entry. Guards the ``row_amount < 0`` OR-branch."""
        mut = {
            "id": self._uid(),
            "type": 3,
            "date": today(),
            "amount": 0,  # positive/zero top-level ...
            "ledgerId": BANK_LEDGER,
            "relationId": "REL-CUST-1",
            "invoiceNumber": "CN-ROW-NEG",
            "description": "Refund detected via row sign",
            "rows": [{"ledgerId": RECEIVABLE_LEDGER, "amount": -55.0, "description": "neg row"}],
        }
        result = self._dispatch(mut)

        self.assertEqual(result.doctype, "Journal Entry")
        saved = frappe.get_doc("Journal Entry", result.name)
        self.assertEqual(saved.docstatus, 1)
        self.assertEqual(flt(saved.total_debit, 2), 55.0)
        self.assertEqual(flt(saved.total_debit, 2), flt(saved.total_credit, 2))

    # ---- normal payment (else branch) -> Payment Entry ----

    def test_type3_positive_amount_with_invoice_routes_to_payment_entry(self):
        """An ordinary customer receipt (type 3, POSITIVE amount) routes to a
        Payment Entry even WITH an invoice ref. Proves ``is_negative`` — not just
        the invoice ref — is required to divert to a refund JE."""
        mut = {
            "id": self._uid(),
            "type": 3,
            "date": today(),
            "amount": 90.0,
            "ledgerId": BANK_LEDGER,
            "relationId": "REL-CUST-1",
            "invoiceNumber": "INV-POS-90",
            "description": "Normal customer receipt with invoice",
            "rows": [{"ledgerId": INCOME_LEDGER, "amount": 90.0, "description": "row"}],
        }
        result = self._dispatch(mut)

        self.assertEqual(result.doctype, "Payment Entry")
        saved = frappe.get_doc("Payment Entry", result.name)
        self.assertEqual(saved.docstatus, 1)
        self.assertEqual(saved.payment_type, "Receive")
        self.assertEqual(saved.party_type, "Customer")
        self.assertEqual(saved.party, self.customer)
        self.assertEqual(saved.paid_to, self.bank)
        self.assertEqual(flt(saved.received_amount, 2), 90.0)

    def test_type4_positive_amount_routes_to_payment_entry(self):
        """Ordinary supplier payment (type 4, positive, no invoice) -> Payment Entry
        (Pay). Guards the type-4 else arm."""
        mut = {
            "id": self._uid(),
            "type": 4,
            "date": today(),
            "amount": 30.0,
            "ledgerId": BANK_LEDGER,
            "relationId": "REL-SUPP-1",
            "invoiceNumber": "",
            "description": "Normal supplier payment",
            "rows": [{"ledgerId": EXPENSE_LEDGER, "amount": 30.0, "description": "row"}],
        }
        result = self._dispatch(mut)

        self.assertEqual(result.doctype, "Payment Entry")
        saved = frappe.get_doc("Payment Entry", result.name)
        self.assertEqual(saved.docstatus, 1)
        self.assertEqual(saved.payment_type, "Pay")
        self.assertEqual(saved.party, self.supplier)
        self.assertEqual(saved.paid_from, self.bank)

    # ---- money transfer (types 5/6) -> Journal Entry ----

    def test_type5_money_received_routes_to_money_transfer_je(self):
        """Type 5 (money received) routes to _create_money_transfer_payment_entry,
        which produces a balanced Journal Entry (bank debited, income credited)."""
        mut = {
            "id": self._uid(),
            "type": 5,
            "date": today(),
            "amount": 150.0,
            "ledgerId": BANK_LEDGER,
            "invoiceNumber": "",
            "description": "rente ontvangen",  # no party keyword -> DB-only, no live API
            "rows": [{"ledgerId": INCOME_LEDGER, "amount": 150.0, "description": "income row"}],
        }
        result = self._dispatch(mut)

        self.assertEqual(result.doctype, "Journal Entry")
        saved = frappe.get_doc("Journal Entry", result.name)
        self.assertEqual(saved.docstatus, 1)
        bank = [a for a in saved.accounts if a.account == self.bank]
        income = [a for a in saved.accounts if a.account == self.income]
        self.assertEqual(flt(bank[0].debit_in_account_currency, 2), 150.0)
        self.assertEqual(flt(income[0].credit_in_account_currency, 2), 150.0)
        self.assertEqual(flt(saved.total_debit, 2), flt(saved.total_credit, 2))

    # ---- summary-data fallback + already-imported early return ----

    def test_iterator_returns_none_falls_back_to_summary_data(self):
        """When fetch_mutation_detail returns None, the dispatcher falls back to the
        summary mutation dict it was handed and still books it."""
        mut = {
            "id": self._uid(),
            "type": 6,
            "date": today(),
            "amount": 25.0,
            "ledgerId": BANK_LEDGER,
            "invoiceNumber": "",
            "description": "bankkosten",
            "rows": [{"ledgerId": EXPENSE_LEDGER, "amount": 25.0, "description": "fee"}],
        }
        # Iterator returns None -> dispatcher falls back to the summary mutation.
        with patch(_ITERATOR_PATH, new=_FakeIterator(None)):
            result = _process_single_mutation(mut, self.company, self.cost_center, [])

        self.assertEqual(result.doctype, "Journal Entry")
        saved = frappe.get_doc("Journal Entry", result.name)
        self.assertEqual(saved.docstatus, 1)
        # Bank credited (money out) for a type-6 paid transfer.
        bank = [a for a in saved.accounts if a.account == self.bank]
        self.assertEqual(flt(bank[0].credit_in_account_currency, 2), 25.0)

    def test_already_imported_payment_entry_is_returned_before_api_call(self):
        """If a Payment Entry already exists for the mutation nr, the dispatcher
        returns it via the early-return path (no API/creation)."""
        mut_id = self._uid()
        create_mut = {
            "id": mut_id,
            "type": 3,
            "date": today(),
            "amount": 65.0,
            "ledgerId": BANK_LEDGER,
            "relationId": "REL-CUST-1",
            "invoiceNumber": "",
            "description": "pre-existing receipt",
            "rows": [{"ledgerId": INCOME_LEDGER, "amount": 65.0, "description": "row"}],
        }
        pe = _create_payment_entry(create_mut, self.company, self.cost_center, [])

        # Dispatch with a DIFFERENT-shaped detail; the early return must win so the
        # canned detail is never consulted.
        result = self._dispatch({"id": mut_id, "type": 3}, detail={"id": mut_id, "type": 99})
        self.assertEqual(result.doctype, "Payment Entry")
        self.assertEqual(result.name, pe.name)
