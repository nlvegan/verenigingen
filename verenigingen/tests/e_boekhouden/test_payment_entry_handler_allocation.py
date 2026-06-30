"""
Money-path coverage for the eBoekhouden PaymentEntryHandler.

Targets the allocation / reconciliation surface of
``e_boekhouden/utils/payment_processing/payment_entry_handler.py`` that the
sibling ``test_payment_entry_handler.py`` does not reach:

- ``_allocate_one_to_one`` / ``_allocate_fifo`` allocation arithmetic, including
  ORDER preservation (the zone of the prior ``set()``->``dict.fromkeys()`` bug),
  debit-note sign handling, and the last-allocation floating-point reconciliation
  that makes the reference rows sum EXACTLY to ``paid_amount``.
- ``_allocate_to_invoices`` end-to-end through a real multi-invoice Payment Entry
  submit, asserting persisted reference rows + GL-settled invoices.
- ``_create_payment_entry`` row-driven amount calculation (rows are the source of
  truth) and the top-level/row mismatch warning.
- ``_track_bank_transaction_stats`` counters, ``_determine_bank_account`` cache
  hit, ``_create_bank_transaction_for_payment`` zero-amount skip,
  ``_link_bank_transaction_to_payment`` missing-document guard,
  ``_get_account_from_pattern`` no-match, ``log_bank_transaction_summary``.

These are real integration tests: allocation methods run against a real
``frappe.new_doc("Payment Entry")`` and assert the child reference rows the
algorithm actually produces (no mocking of business logic).

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_payment_entry_handler_allocation
"""

import frappe
from frappe.utils import flt

from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
    PaymentEntryHandler,
)
from verenigingen.tests.e_boekhouden.test_payment_entry_handler import (
    _ensure_current_fiscal_year,
    _persist_cash_ledger_mapping,
    _persist_customer,
    _persist_eur_company,
    _persist_submitted_sales_invoice,
    _setup_cash_account,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestAllocationArithmetic(EnhancedTestCase):
    """Direct, DB-free tests of the allocation algorithms.

    They operate on a real (uninserted) Payment Entry document and inspect the
    ``references`` child rows the algorithm appends. This pins the exact money
    math and, crucially, the ORDER in which allocations map onto invoices.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()

    def _handler(self):
        return PaymentEntryHandler(self.company)

    def _pe(self, paid_amount):
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.paid_amount = paid_amount
        pe.received_amount = paid_amount
        return pe

    @staticmethod
    def _inv(name, grand_total):
        return {
            "name": name,
            "doctype": "Sales Invoice",
            "grand_total": grand_total,
        }

    # ---- _allocate_one_to_one ----

    def test_one_to_one_preserves_order_and_amounts(self):
        """Each row amount must land on its positionally-corresponding invoice.

        Regression guard for the allocation-order class of bug: invoices A,B with
        DISTINCT row amounts must allocate 40->A and 60->B, never swapped.
        """
        pe = self._pe(100.0)
        invoices = [self._inv("SI-A", 100.0), self._inv("SI-B", 100.0)]
        self._handler()._allocate_one_to_one(pe, invoices, [40.0, 60.0])

        self.assertEqual([r.reference_name for r in pe.references], ["SI-A", "SI-B"])
        self.assertEqual([r.allocated_amount for r in pe.references], [40.0, 60.0])
        # Sum must equal paid_amount exactly.
        self.assertEqual(sum(r.allocated_amount for r in pe.references), 100.0)

    def test_one_to_one_last_allocation_absorbs_rounding(self):
        """The LAST allocation is set to paid_amount-sum_so_far so the references
        total matches paid_amount exactly (avoids 504.28+117.92=622.199... GL error)."""
        pe = self._pe(622.20)
        invoices = [self._inv("SI-1", 700.0), self._inv("SI-2", 700.0)]
        self._handler()._allocate_one_to_one(pe, invoices, [504.28, 117.92])

        self.assertEqual(pe.references[0].allocated_amount, 504.28)
        # Last = 622.20 - 504.28 = 117.92, computed as remainder not raw row.
        self.assertEqual(pe.references[1].allocated_amount, 117.92)
        self.assertEqual(flt(sum(r.allocated_amount for r in pe.references), 2), 622.20)

    def test_one_to_one_debit_note_negative_allocation(self):
        """A negative-grand_total invoice (debit note) gets a NEGATIVE allocation
        and outstanding_amount forced to 0 (ERPNext convention)."""
        pe = self._pe(50.0)
        # First a normal invoice, last a debit note so we cover both branches.
        invoices = [self._inv("SI-N", 80.0), self._inv("SI-DN", -30.0)]
        self._handler()._allocate_one_to_one(pe, invoices, [80.0, 30.0])

        normal, debit = pe.references[0], pe.references[1]
        self.assertEqual(normal.allocated_amount, 80.0)
        self.assertEqual(normal.outstanding_amount, 80.0)
        # Debit note is the last row: allocation = -abs(paid_amount-allocated_so_far)
        self.assertLess(debit.allocated_amount, 0)
        self.assertEqual(debit.outstanding_amount, 0)

    def test_one_to_one_no_paid_amount_uses_row_amounts(self):
        """When paid_amount is unset (None) the floating-point fix is skipped and
        each allocation equals its row amount verbatim (incl. the last)."""
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        # leave paid_amount / received_amount unset -> both None
        invoices = [self._inv("SI-X", 100.0), self._inv("SI-Y", 100.0)]
        self._handler()._allocate_one_to_one(pe, invoices, [33.33, 66.67])
        self.assertEqual([r.allocated_amount for r in pe.references], [33.33, 66.67])

    # ---- _allocate_fifo ----

    def test_fifo_caps_each_invoice_at_grand_total(self):
        """FIFO fills invoices in order, capping each at its grand_total and
        carrying the remainder forward; last absorbs the rounding remainder."""
        pe = self._pe(50.0)
        invoices = [self._inv("SI-F1", 30.0), self._inv("SI-F2", 30.0)]
        # No row_amounts -> total_to_allocate falls back to paid_amount (50).
        self._handler()._allocate_fifo(pe, invoices, [])

        self.assertEqual([r.reference_name for r in pe.references], ["SI-F1", "SI-F2"])
        # First capped at 30, second gets remainder 20.
        self.assertEqual(pe.references[0].allocated_amount, 30.0)
        self.assertEqual(pe.references[1].allocated_amount, 20.0)
        self.assertEqual(sum(r.allocated_amount for r in pe.references), 50.0)

    def test_fifo_stops_when_fully_allocated(self):
        """Once remaining hits 0 no further invoices are referenced."""
        pe = self._pe(25.0)
        invoices = [self._inv("SI-G1", 25.0), self._inv("SI-G2", 25.0)]
        self._handler()._allocate_fifo(pe, invoices, [25.0])
        # Second invoice never reached (remaining went to 0 after first).
        self.assertEqual([r.reference_name for r in pe.references], ["SI-G1"])
        self.assertEqual(pe.references[0].allocated_amount, 25.0)

    def test_fifo_uses_row_amount_sum_when_provided(self):
        """With row_amounts, total_to_allocate is their rounded sum (= paid_amount,
        which production sets from the same rows). Only as much as the rows sum is
        allocated, even though each invoice could absorb far more."""
        # paid_amount mirrors production: it equals the row sum (set from rows in
        # _create_payment_entry). The FIFO total is driven by the rows, so only 15
        # is spread across the (much larger) invoices.
        pe = self._pe(15.0)
        invoices = [self._inv("SI-H1", 500.0), self._inv("SI-H2", 500.0)]
        self._handler()._allocate_fifo(pe, invoices, [10.0, 5.0])
        # total_to_allocate = 15; first capped at min(15,500)=15, remaining 0,
        # second invoice never reached.
        self.assertEqual(pe.references[0].allocated_amount, 15.0)
        self.assertEqual(len(pe.references), 1)


class TestPaymentEntryRowAmountCalc(EnhancedTestCase):
    """Row-driven amount calculation in ``_create_payment_entry``."""

    CASH_LEDGER_ID = 770090

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()
        _ensure_current_fiscal_year()
        cls.cash_account = _setup_cash_account(cls.company)
        cls.receivable = frappe.db.get_value("Company", cls.company, "default_receivable_account")
        _persist_cash_ledger_mapping(cls.CASH_LEDGER_ID, cls.cash_account)
        cls.customer = _persist_customer("EBKH PE Alloc Customer")

    def _handler(self):
        h = PaymentEntryHandler(self.company)
        h._current_invoice_numbers = []
        return h

    def test_amount_summed_from_rows_not_top_level(self):
        """Rows are the source of truth: paid_amount = rounded sum of row amounts."""
        h = self._handler()
        mut = {
            "id": 9000001,
            "type": 3,
            "date": frappe.utils.today(),
            "amount": 0,  # top-level zero -> must still sum rows
            "ledgerId": self.CASH_LEDGER_ID,
            "relationId": "REL-ROWS",
            "rows": [{"amount": 504.28}, {"amount": 117.92}],
            "description": "row sum test",
        }
        pe = h._create_payment_entry(
            mutation=mut,
            payment_type="Receive",
            party_type="Customer",
            party=self.customer,
            bank_account=self.cash_account,
        )
        self.assertEqual(pe.paid_amount, 622.20)
        self.assertEqual(pe.received_amount, 622.20)

    def test_top_level_row_mismatch_logged(self):
        """A top-level amount that disagrees with the row total emits a WARNING."""
        h = self._handler()
        mut = {
            "id": 9000002,
            "type": 3,
            "date": frappe.utils.today(),
            "amount": 600.0,  # disagrees with row sum 622.20
            "ledgerId": self.CASH_LEDGER_ID,
            "relationId": "REL-ROWS2",
            "rows": [{"amount": 504.28}, {"amount": 117.92}],
            "description": "mismatch test",
        }
        pe = h._create_payment_entry(
            mutation=mut,
            payment_type="Receive",
            party_type="Customer",
            party=self.customer,
            bank_account=self.cash_account,
        )
        # Rows win regardless of the top-level disagreement.
        self.assertEqual(pe.paid_amount, 622.20)
        self.assertTrue(any("doesn't match row total" in m for m in h.get_debug_log()))


class TestAllocateToInvoicesIntegration(EnhancedTestCase):
    """End-to-end multi-invoice allocation through a REAL submitted Payment Entry."""

    CASH_LEDGER_ID = 770090
    _counter = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()
        _ensure_current_fiscal_year()
        cls.cash_account = _setup_cash_account(cls.company)
        cls.receivable = frappe.db.get_value("Company", cls.company, "default_receivable_account")
        _persist_cash_ledger_mapping(cls.CASH_LEDGER_ID, cls.cash_account)
        cls.customer = _persist_customer("EBKH PE Alloc Int Customer")

    def _uid(self):
        import random

        TestAllocateToInvoicesIntegration._counter += 1
        return (
            (int(frappe.utils.now_datetime().timestamp()) % 2000000) * 1000
            + random.randint(0, 999)
            + TestAllocateToInvoicesIntegration._counter
        )

    def test_multi_invoice_one_to_one_money_math(self):
        """Two invoices, two rows: each invoice settled by its matching row amount,
        references sum exactly to paid_amount, both invoices fully paid."""
        eb1 = f"EB-ALLOC-A-{self._uid()}"
        eb2 = f"EB-ALLOC-B-{self._uid()}"
        si1 = _persist_submitted_sales_invoice(self.company, self.customer, self.receivable, eb1, rate=504.28)
        si2 = _persist_submitted_sales_invoice(self.company, self.customer, self.receivable, eb2, rate=117.92)

        h = PaymentEntryHandler(self.company)
        invoice_numbers = [eb1, eb2]
        h._current_invoice_numbers = invoice_numbers
        mut = {
            "id": self._uid(),
            "type": 3,
            "date": frappe.utils.today(),
            "amount": 622.20,
            "ledgerId": self.CASH_LEDGER_ID,
            "relationId": "REL-MULTI",
            "invoiceNumber": f"{eb1},{eb2}",
            "rows": [{"amount": 504.28}, {"amount": 117.92}],
            "description": "multi-invoice receipt",
        }
        pe = h._create_payment_entry(
            mutation=mut,
            payment_type="Receive",
            party_type="Customer",
            party=self.customer,
            bank_account=self.cash_account,
        )
        h._allocate_and_insert_payment(pe, invoice_numbers, mut, "Customer")
        h._submit_with_floating_point_fix(pe, None)

        saved = frappe.get_doc("Payment Entry", pe.name)
        self.assertEqual(saved.docstatus, 1)
        self.assertEqual(saved.paid_to, self.cash_account)
        self.assertEqual(saved.paid_from, self.receivable)
        self.assertEqual(saved.paid_amount, 622.20)
        self.assertEqual(len(saved.references), 2)
        alloc_by_inv = {r.reference_name: r.allocated_amount for r in saved.references}
        self.assertEqual(alloc_by_inv[si1], 504.28)
        self.assertEqual(alloc_by_inv[si2], 117.92)
        self.assertEqual(flt(sum(r.allocated_amount for r in saved.references), 2), 622.20)
        self.assertEqual(saved.unallocated_amount, 0.0)
        # Both invoices settled.
        self.assertEqual(frappe.db.get_value("Sales Invoice", si1, "outstanding_amount"), 0.0)
        self.assertEqual(frappe.db.get_value("Sales Invoice", si2, "outstanding_amount"), 0.0)


class TestHandlerSupportPaths(EnhancedTestCase):
    """Smaller uncovered branches: stats, cache, bank-transaction guards, summary."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = _persist_eur_company()

    def _handler(self):
        return PaymentEntryHandler(self.company)

    # ---- _track_bank_transaction_stats ----

    def test_stats_created(self):
        h = self._handler()
        h._track_bank_transaction_stats({"id": 1}, "PE-1", "BT-1", existing_bt=False)
        self.assertEqual(h._bank_tx_stats["total_processed"], 1)
        self.assertEqual(h._bank_tx_stats["bank_tx_created"], 1)
        self.assertEqual(h._bank_tx_stats["bank_tx_already_existed"], 0)

    def test_stats_already_existed(self):
        h = self._handler()
        h._track_bank_transaction_stats({"id": 2}, "PE-2", "BT-2", existing_bt=True)
        self.assertEqual(h._bank_tx_stats["bank_tx_already_existed"], 1)
        self.assertEqual(h._bank_tx_stats["bank_tx_created"], 0)

    def test_stats_failure_records_reason(self):
        h = self._handler()
        h._track_bank_transaction_stats(
            {"id": 3}, None, None, existing_bt=False, error=ValueError("boom")
        )
        self.assertEqual(h._bank_tx_stats["bank_tx_failed"], 1)
        self.assertEqual(len(h._bank_tx_stats["failures"]), 1)
        self.assertEqual(h._bank_tx_stats["failures"][0]["mutation_nr"], 3)
        self.assertIn("boom", h._bank_tx_stats["failures"][0]["reason"])

    # ---- _determine_bank_account cache hit ----

    def test_determine_bank_account_cache_hit(self):
        h = self._handler()
        h._ledger_cache["555:Receive"] = "Cached Bank Account"
        # Cache hit returns immediately without any DB resolution.
        self.assertEqual(h._determine_bank_account(555, "Receive"), "Cached Bank Account")

    # ---- _get_account_from_pattern (no configured purpose) ----

    def test_get_account_from_pattern_no_match(self):
        h = self._handler()
        # Description with no mappable purpose -> None.
        self.assertIsNone(h._get_account_from_pattern("generic salary payment", "Pay"))

    # ---- _create_bank_transaction_for_payment zero amount ----

    def test_bank_transaction_zero_amount_skipped(self):
        h = self._handler()
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.paid_amount = 0
        pe.received_amount = 0
        pe.party_type = None
        pe.party = None
        result = h._create_bank_transaction_for_payment({"id": 7}, pe, "Some Bank Account")
        self.assertIsNone(result)
        self.assertEqual(h._bank_tx_stats["bank_tx_skipped_zero_amount"], 1)

    # ---- _link_bank_transaction_to_payment missing PE ----

    def test_link_bank_transaction_missing_payment_entry_raises(self):
        h = self._handler()
        with self.assertRaises(frappe.DoesNotExistError):
            h._link_bank_transaction_to_payment("BT-DOES-NOT-EXIST", "PE-DOES-NOT-EXIST")

    # ---- _find_invoice_by_number guard ----

    def test_find_invoice_by_number_empty_inputs(self):
        h = self._handler()
        self.assertEqual(h._find_invoice_by_number("", "Sales Invoice", "customer", "X"), [])
        self.assertEqual(h._find_invoice_by_number("INV-1", "Sales Invoice", "customer", None), [])

    # ---- log_bank_transaction_summary ----

    def test_log_bank_transaction_summary_formats_counts(self):
        h = self._handler()
        h._bank_tx_stats.update(
            {
                "total_processed": 4,
                "bank_tx_created": 2,
                "bank_tx_already_existed": 1,
                "bank_tx_skipped_zero_amount": 0,
                "bank_tx_failed": 1,
                "failures": [{"mutation_nr": 99, "payment_entry": "PE-X", "reason": "kaboom"}],
            }
        )
        self.expectErrorLog("Bank Transaction Summary")
        summary = h.log_bank_transaction_summary()
        self.assertIn("Total Payment Entries Processed: 4", summary)
        self.assertIn("Bank Transactions Created: 2", summary)
        self.assertIn("Success Rate: 75.0%", summary)  # (2+1)/4
        self.assertIn("Mutation 99", summary)
        self.assertIn("kaboom", summary)
