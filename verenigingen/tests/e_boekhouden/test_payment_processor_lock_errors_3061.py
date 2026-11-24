"""#3061: the e-Boekhouden payment processors must not turn a 1213/1205 into a log line.

A 1213 makes the server roll the WHOLE transaction back. A handler that catches it after a
write, records it in ``debug_info`` and carries on goes on to submit a Journal Entry / Payment
Entry against state the server has thrown away (#3008 class). Each test injects a real-shape
lock error at the DRIVER (``Cursor.execute``, same injector as #3029), below every swallowing
layer, and asserts the error reaches the caller AND that the document the handler used to go on
to submit is still a draft.

Probe shortcut, stated: the deadlock is injected, not provoked, and no server ROLLBACK is
issued -- the question under test is only who sees the error and what runs afterwards. Fixtures
set ``overwrite_existing`` / the auto-create setting directly to select the branch under test.
"""

import itertools
from unittest.mock import patch

import frappe
from frappe.utils import nowdate

from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import PaymentEntryHandler
from verenigingen.e_boekhouden.utils.processors.transaction_coordinator import TransactionCoordinator
from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor
from verenigingen.tests.e_boekhouden.test_party_creation_lock_errors_3029 import _lock_error_at_driver_3029
from verenigingen.tests.e_boekhouden.test_payment_processor_sweep import _PayProcBase
from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
    get_bank_transaction_creator,
)

_AUTO_CREATE = "auto_create_parties_from_bank_transactions"


class TestPaymentProcessorLockErrors3061(_PayProcBase):
    _seq_3061 = itertools.count(7361001)

    def setUp(self):
        super().setUp()
        self._saved_auto_3061 = frappe.db.get_single_value("E-Boekhouden Settings", _AUTO_CREATE)
        frappe.db.set_single_value("E-Boekhouden Settings", _AUTO_CREATE, 0)

    def tearDown(self):
        frappe.db.set_single_value("E-Boekhouden Settings", _AUTO_CREATE, self._saved_auto_3061)
        super().tearDown()

    _BOTH_3061 = (1213, 1205)

    def _reaches_caller_3061(self, fragment, startswith, call, codes=_BOTH_3061):
        """Both non-resumable classes must reach the caller. ``call(n)`` builds its fixtures and
        returns the action to run; only the action runs under the injector, so a fixture write
        can never be the statement that takes the hit. ``n`` is fresh per subTest so a second
        run never short-circuits on the first run's leftover document."""
        errors = {1213: frappe.QueryDeadlockError, 1205: frappe.QueryTimeoutError}
        for code in codes:
            error = errors[code]
            with self.subTest(code=code):
                act = call(next(self._seq_3061))
                inject, hits = _lock_error_at_driver_3029(fragment, startswith, code)
                with inject, self.assertRaises(error):
                    act()
                self.assertTrue(hits, "the injection must have fired")

    # --- fixtures ---------------------------------------------------------------------------
    @staticmethod
    def _amount_3061(mut_id):
        """A distinct amount per number: the Bank Transaction creator treats a repeat of the
        same bank account / date / amount as a duplicate and hands back the earlier row, which
        would stop a later subTest from ever reaching the branch it is meant to test."""
        return 100.0 + mut_id % 1000

    def _draft_je_3061(self, mut_id):
        amount = self._amount_3061(mut_id)
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = nowdate()
        je.voucher_type = "Journal Entry"
        je.eboekhouden_mutation_nr = str(mut_id)
        je.cheque_no = f"EB-{mut_id}"
        je.cheque_date = nowdate()
        for account, debit, credit in ((self.bank, amount, 0), (self.income, 0, amount)):
            je.append(
                "accounts",
                {
                    "account": account,
                    "debit_in_account_currency": debit,
                    "credit_in_account_currency": credit,
                    "cost_center": self.cost_center,
                },
            )
        je.insert()
        return je

    def _bank_transaction_3061(self, mut_id):
        amount = self._amount_3061(mut_id)
        return get_bank_transaction_creator().create_from_dict(
            transaction_data={
                "date": nowdate(),
                "amount": amount,
                "currency": "EUR",
                "description": "pre-existing 3061",
                "reference_number": f"EB-{mut_id}",
            },
            bank_account=self.bank_account,
            company=self.company,
            source_type="Probe 3061",
        )

    def _supplier_3061(self):
        name = "EBPS Probe 3061 Supplier"
        if frappe.db.exists("Supplier", name):
            return name
        sup = frappe.new_doc("Supplier")
        sup.supplier_name = name
        sup.supplier_group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name", order_by="name")
        sup.insert()
        return sup.name

    def _bt_call_3061(self, mut_id, je, party_info, overwrite=False):
        return self._processor_3061(overwrite)._create_bank_transaction_for_journal_entry(
            {"id": mut_id, "type": 5, "description": "probe 3061"},
            je,
            self.bank,
            self.bank_account,
            party_info,
        )

    def _processor_3061(self, overwrite=False):
        processor = self._processor()
        processor.overwrite_existing = overwrite
        return processor

    def _docstatus_of_je_3061(self, mut_id):
        return frappe.db.get_value("Journal Entry", {"eboekhouden_mutation_nr": str(mut_id)}, "docstatus")

    # --- _process_money_transfer ------------------------------------------------------------
    def test_a_lock_error_ensuring_the_fiscal_year_does_not_let_the_journal_entry_submit(self):
        self.expectErrorLog("Fiscal Year Auto-Creation Error", "Money Transfer Journal Entry Error")

        def call(n):
            mutation = self._money_mutation(5, self._amount_3061(n), "7300008", n)

            def act():
                try:
                    self._processor().process(mutation)
                finally:
                    # the JE was inserted before the fiscal-year step; the swallow used to submit it
                    self.assertNotEqual(self._docstatus_of_je_3061(n), 1, "JE must not be submitted")

            return act

        self._reaches_caller_3061("BETWEEN year_start_date AND year_end_date", ("SELECT",), call)

    def test_a_lock_error_creating_the_bank_transaction_does_not_let_the_journal_entry_submit(self):
        self.expectErrorLog("Money Transfer Journal Entry Error")

        def call(n):
            mutation = self._money_mutation(5, self._amount_3061(n), "7300008", n)

            def act():
                try:
                    self._processor().process(mutation)
                finally:
                    self.assertNotEqual(self._docstatus_of_je_3061(n), 1, "JE must not be submitted")

            return act

        # 1213 only: ``bank_transaction_creator`` deliberately lets a 1205 fall through to its own
        # generic handler and return None (its comment says so, #2983), so a 1205 never reaches
        # this processor from that insert. Filed separately; not changed here.
        self._reaches_caller_3061("`tabBank Transaction`", ("INSERT",), call, codes=(1213,))

    # --- _create_bank_transaction_for_journal_entry -----------------------------------------
    def _overwrite_delete_reaches_caller_3061(self, code):
        """One code per test: the overwrite branch cancels the existing Bank Transaction before
        the delete is attempted, and the cancelled leftover collides with the next subTest's
        Bank Transaction name."""

        def call(n):
            je = self._draft_je_3061(n)
            self._bank_transaction_3061(n)
            return lambda: self._bt_call_3061(
                n, je, {"party_type": "Supplier", "party_name": "x"}, overwrite=True
            )

        self._reaches_caller_3061("`tabBank Transaction`", ("DELETE",), call, codes=(code,))

    def test_a_deadlock_deleting_the_bank_transaction_in_overwrite_mode_reaches_the_caller(self):
        self._overwrite_delete_reaches_caller_3061(1213)

    def test_a_lock_timeout_deleting_the_bank_transaction_in_overwrite_mode_reaches_the_caller(self):
        self._overwrite_delete_reaches_caller_3061(1205)

    def test_a_lock_error_on_the_relation_id_lookup_reaches_the_caller(self):
        def call(n):
            je = self._draft_je_3061(n)
            return lambda: self._bt_call_3061(
                n, je, {"party_type": "Customer", "party_name": "x", "relation_id": f"3061{n}"}
            )

        self._reaches_caller_3061("`tabCustomer`", ("SELECT",), call)

    def test_a_lock_error_matching_the_party_by_name_with_auto_create_off_reaches_the_caller(self):
        """The handler used to re-raise only when auto-create was on; with it off (this fixture)
        it logged and went on to create the Bank Transaction without a party."""

        def call(n):
            je = self._draft_je_3061(n)
            return lambda: self._bt_call_3061(
                n, je, {"party_type": "Customer", "party_name": f"Probe 3061 {n} BV"}
            )

        self._reaches_caller_3061("`tabCustomer`", ("SELECT",), call)

    def test_a_lock_error_creating_the_bank_transaction_is_not_returned_as_none(self):
        def call(n):
            je = self._draft_je_3061(n)
            return lambda: self._bt_call_3061(n, je, None)

        # 1213 only, see the money-transfer test above for why 1205 cannot reach here.
        self._reaches_caller_3061("`tabBank Transaction`", ("INSERT",), call, codes=(1213,))

    # --- _update_bank_transaction_party -----------------------------------------------------
    def test_a_lock_error_updating_the_bank_transaction_party_reaches_the_caller(self):
        supplier = self._supplier_3061()

        def call(n):
            bt_name = self._bank_transaction_3061(n)
            return lambda: self._processor_3061()._update_bank_transaction_party(
                bt_name, {"party_type": "Supplier", "party_name": supplier}
            )

        self._reaches_caller_3061("`tabBank Transaction`", ("UPDATE",), call)

    def test_a_lock_error_updating_the_party_of_an_existing_bank_transaction_is_not_swallowed_upstream(
        self,
    ):
        """Same write, reached through the creator's existing-BT branch, so the caller's own
        handler is in the path too."""
        supplier = self._supplier_3061()

        def call(n):
            je = self._draft_je_3061(n)
            self._bank_transaction_3061(n)
            return lambda: self._bt_call_3061(n, je, {"party_type": "Supplier", "party_name": supplier})

        self._reaches_caller_3061("`tabBank Transaction`", ("UPDATE",), call)

    # --- payment_entry_handler --------------------------------------------------------------
    def test_a_lock_error_ensuring_the_fiscal_year_does_not_let_the_payment_entry_submit(self):
        self.expectErrorLog("Fiscal Year Auto-Creation Error")

        def call(n):
            pe = frappe.new_doc("Payment Entry")
            pe.payment_type = "Internal Transfer"
            pe.company = self.company
            pe.posting_date = nowdate()
            pe.paid_from = self.bank
            pe.paid_to = self.bank2
            pe.paid_amount = pe.received_amount = 25.0
            pe.source_exchange_rate = pe.target_exchange_rate = 1
            pe.reference_no = f"PROBE-3061-{n}"
            pe.reference_date = nowdate()
            pe.insert()

            def act():
                try:
                    PaymentEntryHandler(self.company)._submit_with_floating_point_fix(pe, None)
                finally:
                    self.assertEqual(frappe.db.get_value("Payment Entry", pe.name, "docstatus"), 0)

            return act

        self._reaches_caller_3061("BETWEEN year_start_date AND year_end_date", ("SELECT",), call)

    # --- TransactionCoordinator.process_mutation: the production route (types 3/4/5/6) -------
    def _coordinator_3061(self):
        return TransactionCoordinator(self.company, cost_center=self.cost_center, mutation_type=5)

    def test_a_lock_error_creating_the_bank_transaction_reaches_the_caller_through_the_coordinator(self):
        """The coordinator's ``except Exception`` used to log the lock error and return None, so
        ``eboekhouden_rest_full_migration``'s ``except NON_RESUMABLE_DB_ERRORS`` (#572) never saw
        it and the caller fell back to legacy processing on a dead transaction. 1213 only: a 1205
        cannot reach the processor from the Bank Transaction insert (see above), so the 1205
        coordinator case drives the fiscal-year SELECT instead."""
        self.expectErrorLog("Money Transfer Journal Entry Error")

        def call(n):
            mutation = self._money_mutation(5, self._amount_3061(n), "7300008", n)
            return lambda: self._coordinator_3061().process_mutation(mutation)

        self._reaches_caller_3061("`tabBank Transaction`", ("INSERT",), call, codes=(1213,))

    def test_a_lock_error_ensuring_the_fiscal_year_reaches_the_caller_through_the_coordinator(self):
        self.expectErrorLog("Fiscal Year Auto-Creation Error", "Money Transfer Journal Entry Error")

        def call(n):
            mutation = self._money_mutation(5, self._amount_3061(n), "7300008", n)
            return lambda: self._coordinator_3061().process_mutation(mutation)

        # 1213 and 1205 both. A 1205 is statement-only (the server keeps the transaction), so a
        # draft Journal Entry inserted before the failing statement can remain; a 1213 rolls it back.
        self._reaches_caller_3061("BETWEEN year_start_date AND year_end_date", ("SELECT",), call)

    def test_an_ordinary_error_through_the_coordinator_is_still_counted_and_returns_none(self):
        """Control: the re-raise is narrow; an ordinary processor failure keeps the old
        contract (stats failed, error logged, None returned)."""
        self.expectErrorLog("eBoekhouden Processing Error")
        coordinator = self._coordinator_3061()
        mutation = self._money_mutation(5, 130.0, "7300008", next(self._seq_3061))
        # Mock justified: ordinary-error control; the lock tests above use the real driver path
        with patch.object(PaymentProcessor, "process", side_effect=ValueError("ordinary")):
            self.assertIsNone(coordinator.process_mutation(mutation))
        self.assertEqual(coordinator.stats["failed"], 1)

    # --- controls ---------------------------------------------------------------------------
    def test_an_ordinary_fiscal_year_failure_is_still_only_a_warning(self):
        """Control: a non-lock error keeps the old contract (warning, then submit), so the
        re-raise is narrow."""
        # Mock justified: ordinary-error control for the handler; the lock tests above are the real path
        with patch(
            "verenigingen.e_boekhouden.utils.invoice_helpers.ensure_fiscal_year_exists",
            side_effect=ValueError("ordinary"),
        ):
            processor = self._processor()
            mutation = self._money_mutation(5, 120.0, "7300008", next(self._seq_3061))
            result = processor.process(mutation)
        self.assertEqual(result.docstatus, 1)
        self.assertTrue(any("Could not ensure fiscal year: ordinary" in m for m in processor.get_debug_info()))

    def test_an_ordinary_party_update_failure_is_still_swallowed(self):
        """Control: a non-lock error in the party update keeps the old contract (logged, no raise)."""
        self.expectErrorLog("Failed to update Bank Transaction party")

        bt_name = self._bank_transaction_3061(next(self._seq_3061))
        # Mock justified: ordinary-error control; the lock tests above use the real driver path
        with patch("frappe.db.set_value", side_effect=ValueError("ordinary")):
            self._processor_3061()._update_bank_transaction_party(
                bt_name, {"party_type": "Supplier", "party_name": self._supplier_3061()}
            )
