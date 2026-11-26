"""#3195: the PaymentEntryHandler Bank Transaction create/link steps must not absorb or convert a 1213/1205.

A 1213 makes the server roll the WHOLE transaction back. ``_create_bank_transaction_for_payment``
used to log it and return None (the caller then submitted the Payment Entry without a Bank
Transaction) and ``_link_bank_transaction_to_payment`` converted it into ``frappe.ValidationError``
(losing the class, so no caller's ``except NON_RESUMABLE_DB_ERRORS`` could fire). Each test injects a
real-shape lock error at the DRIVER (``Cursor.execute``, the #3029 injector), below every swallowing
layer, and asserts the original class reaches the caller.

Probe shortcut, stated: the deadlock is injected, not provoked, and no server ROLLBACK is issued;
the question under test is only which class the caller sees. Controls use a patched ordinary error.
"""

import itertools
from unittest.mock import patch

import frappe
from frappe.utils import nowdate

from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import PaymentEntryHandler
from verenigingen.e_boekhouden.utils.security_helper import atomic_migration_operation
from verenigingen.tests.e_boekhouden.test_party_creation_lock_errors_3029 import _lock_error_at_driver_3029
from verenigingen.tests.e_boekhouden.test_payment_processor_sweep import _PayProcBase

_ERRORS_3195 = {1213: frappe.QueryDeadlockError, 1205: frappe.QueryTimeoutError}


class TestPaymentEntryHandlerLockErrors3195(_PayProcBase):
    _seq_3195 = itertools.count(7395001)

    def _handler_3195(self):
        return PaymentEntryHandler(self.company)

    def _payment_entry_stub_3195(self):
        return frappe._dict(
            payment_type="Receive",
            paid_amount=21.0,
            received_amount=21.0,
            posting_date=nowdate(),
            party_type=None,
            party=None,
        )

    def _draft_bank_transaction_3195(self, n):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = nowdate()
        bt.bank_account = self.bank_account
        bt.company = self.company
        bt.deposit = 25.0
        bt.withdrawal = 0
        bt.currency = "EUR"
        bt.reference_number = f"EB-PE-{n}"
        bt.description = "link 3195"
        bt.status = "Unreconciled"
        bt.unallocated_amount = 25.0
        bt.allocated_amount = 0
        bt.insert()
        return bt

    def _draft_payment_entry_3195(self, n):
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Internal Transfer"
        pe.company = self.company
        pe.posting_date = nowdate()
        pe.paid_from = self.bank
        pe.paid_to = self.bank2
        pe.paid_amount = pe.received_amount = 25.0
        pe.source_exchange_rate = pe.target_exchange_rate = 1
        pe.reference_no = f"PROBE-3195-{n}"
        pe.reference_date = nowdate()
        pe.insert()
        return pe

    def _create_call_3195(self, n):
        return lambda: self._handler_3195()._create_bank_transaction_for_payment(
            {"id": n, "description": "create 3195"}, self._payment_entry_stub_3195(), self.bank_account
        )

    def _link_call_3195(self, n):
        bt = self._draft_bank_transaction_3195(n)
        pe = self._draft_payment_entry_3195(n)
        return lambda: self._handler_3195()._link_bank_transaction_to_payment(bt.name, pe.name)

    def _reaches_caller_3195(self, fragment, startswith, build, codes=(1213, 1205)):
        """``build(n)`` makes fixtures and returns the action; only the action runs under the
        injector, so a fixture write can never be the statement that takes the hit."""
        for code in codes:
            with self.subTest(code=code):
                act = build(next(self._seq_3195))
                inject, hits = _lock_error_at_driver_3029(fragment, startswith, code)
                with inject, self.assertRaises(_ERRORS_3195[code]):
                    act()
                self.assertTrue(hits, "the injection must have fired")

    # --- _create_bank_transaction_for_payment ------------------------------------------------
    def test_a_deadlock_creating_the_bank_transaction_is_not_returned_as_none(self):
        # 1213 only: bank_transaction_creator deliberately lets a 1205 fall to its own generic
        # handler and return None (#2983 choice, see #3195 / #3061); not changed here.
        self.expectErrorLog("E-Boekhouden Bank Transaction Creation")
        self._reaches_caller_3195("`tabBank Transaction`", ("INSERT",), self._create_call_3195, codes=(1213,))

    def test_a_lock_timeout_from_the_creator_still_returns_none(self):
        """Control: 1213 only is re-raised. A 1205 rolls back just its statement and the creator
        never emits one today (#2983), so the handler keeps its old contract for it. NOT
        driver-injected: the creator's raise is stood in for."""
        self.expectErrorLog("E-Boekhouden Bank Transaction Creation")
        n = next(self._seq_3195)
        # Mock justified: the creator cannot emit a 1205 today; pins that the re-raise is 1213-only
        with patch(
            "verenigingen.verenigingen_payments.services.bank_transaction_creator."
            "BankTransactionCreator.create_from_dict",
            side_effect=frappe.QueryTimeoutError("injected"),
        ):
            self.assertIsNone(self._create_call_3195(n)())

    def test_an_ordinary_error_creating_the_bank_transaction_still_returns_none(self):
        """Control: the re-raise is narrow; an ordinary failure keeps the log-and-None contract."""
        self.expectErrorLog("E-Boekhouden Bank Transaction Creation")
        n = next(self._seq_3195)
        # Mock justified: ordinary-error control; the lock test above uses the real driver path
        with patch(
            "verenigingen.verenigingen_payments.services.bank_transaction_creator."
            "BankTransactionCreator.create_from_dict",
            side_effect=ValueError("ordinary"),
        ):
            self.assertIsNone(self._create_call_3195(n)())

    # --- _link_bank_transaction_to_payment ---------------------------------------------------
    def test_a_deadlock_linking_the_bank_transaction_keeps_its_class(self):
        self.expectErrorLog("E-Boekhouden Bank Transaction Linking")
        self._reaches_caller_3195("`tabBank Transaction`", ("UPDATE",), self._link_call_3195, codes=(1213,))

    def test_a_lock_timeout_linking_inside_the_atomic_operation_rolls_the_draft_payment_entry_back(self):
        """1205 keeps the ValidationError path so atomic_migration_operation rolls its savepoint
        back. Re-raising the 1205 class would skip that rollback and strand the draft Payment
        Entry that `_allocate_and_insert_payment` wrote (#3354)."""
        self.expectErrorLog("E-Boekhouden Bank Transaction Linking")
        n = next(self._seq_3195)
        bt = self._draft_bank_transaction_3195(n)
        inject = hits = None
        with self.assertRaises(frappe.ValidationError):
            with atomic_migration_operation("payment_processing"):
                pe = self._draft_payment_entry_3195(n)
                frappe.db.set_value("Payment Entry", pe.name, "eboekhouden_mutation_nr", str(n))
                inject, hits = _lock_error_at_driver_3029("`tabBank Transaction`", ("UPDATE",), 1205)
                with inject:
                    self._handler_3195()._link_bank_transaction_to_payment(bt.name, pe.name)
        self.assertTrue(hits, "the injection must have fired")
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"eboekhouden_mutation_nr": str(n)}),
            "the draft Payment Entry must be rolled back with the savepoint",
        )

    def test_an_ordinary_error_linking_the_bank_transaction_is_still_a_validation_error(self):
        """Control: a non-lock error is still converted to ValidationError."""
        self.expectErrorLog("E-Boekhouden Bank Transaction Linking")
        act = self._link_call_3195(next(self._seq_3195))
        # Mock justified: ordinary-error control; the lock test above uses the real driver path
        with patch("verenigingen.utils.secure_operations.secure_document_operation", side_effect=ValueError("ordinary")):
            with self.assertRaises(frappe.ValidationError):
                act()
