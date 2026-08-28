"""
A refunded or charged-back Mollie **dues** payment must reach the ledger.

``process_reversal_webhook`` derives what the forward payment booked and, before
this module, dispatched only for ``booked_type == "donation"``. Everything else
took the else-branch and answered ``not_implemented`` -- so a refunded membership
payment left the Sales Invoice showing Paid, with the money gone (#635, the other
half of #370).

**Why a Journal Entry and not a reversing Payment Entry.** ERPNext refuses a
Payment Entry reference row whose allocation exceeds the invoice's
``outstanding_amount``, and refuses a negative one below it
(``payment_entry.py`` ``validate_allocated_amount_with_latest_data``), so on a
fully-paid invoice -- ``outstanding == 0`` -- *both* directions throw. A Journal
Entry debiting the invoice's ``debit_to`` with ``reference_type="Sales Invoice"``
restores ``outstanding_amount``, and unlike a cancel of the forward entry it can
express a **partial** refund, which is what Mollie actually sends most often.

Assertions are on **GL Entry rows**, not on ``docstatus``: ``db_update()`` runs
before ``on_submit``, so a submit that throws leaves ``docstatus = 1`` behind a
half-posted ledger (#382).

Run:
    bench --site test_site_1 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_dues_reversal_booking
"""

from decimal import Decimal

import frappe
from frappe.utils import flt, getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.test_donation_refund_journal_entry_creator_coverage import (
    COMPANY,
    _RefundFixtureMixin,
)
from verenigingen.tests.support.mollie_settings import (
    pin_mollie_clearing_account,
    pin_verenigingen_settings,
)
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)
from verenigingen.verenigingen_payments.mollie.utils.reversal_idempotency import (
    build_reversal_key,
    find_booked_payment,
)
from verenigingen.verenigingen_payments.services.payment import payment_entry_service


class _DuesReversalFixture(_RefundFixtureMixin, EnhancedTestCase):
    """A real forward dues booking: Sales Invoice + allocated Payment Entry.

    The forward artefact is built through ``create_payment_entry_from_invoice``
    -- the same service every dues route uses -- rather than hand-assembled, so
    the reversal is tested against the shape production actually writes.
    """

    #: Cash the gateway moved. Equal to the allocation unless a subclass raises it.
    CASH_RECEIVED = None
    INVOICE_AMOUNT = 50.0

    def setUp(self):
        super().setUp()
        self.ensure_mode_of_payment("Mollie", "Bank")

        self.clearing_account = self._ensure_clearing_account()
        self.bank_account = self._ensure_bank_account(self.clearing_account)
        self.receivable = frappe.get_value(
            "Account", {"company": COMPANY, "account_type": "Receivable", "is_group": 0}, "name"
        )

        pin_verenigingen_settings(self, company=COMPANY)
        pin_mollie_clearing_account(self, self.clearing_account)

        self.customer = self._make_customer()
        self.invoice = self._make_invoice(self.INVOICE_AMOUNT)
        self.payment_id = f"tr_dues_{frappe.generate_hash(length=8)}"
        self.forward_pe = self._make_forward_payment_entry()

    # ---- fixtures ----------------------------------------------------------

    def _make_customer(self):
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"Dues Reversal {frappe.generate_hash(length=6)}"
        customer.customer_type = "Individual"
        customer.insert(ignore_permissions=True)
        self.track_test_record("Customer", customer.name)
        return customer.name

    def _make_item(self):
        item_code = f"Dues Reversal Item {frappe.generate_hash(length=5)}"
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = item_code
        item.item_group = (
            "Services"
            if frappe.db.exists("Item Group", "Services")
            else frappe.get_value("Item Group", {"is_group": 0}, "name")
        )
        item.stock_uom = "Unit" if frappe.db.exists("UOM", "Unit") else frappe.get_value("UOM", {}, "name")
        item.is_stock_item = 0
        item.insert(ignore_permissions=True)
        self.track_test_record("Item", item.name)
        return item_code

    def _make_invoice(self, amount):
        # ERPNext's standard chart leaves account_type EMPTY on income leaves, so
        # resolve by root_type -- {"account_type": "Income Account"} matches only
        # rows some other fixture planted.
        income = frappe.get_value("Company", COMPANY, "default_income_account") or frappe.get_value(
            "Account", {"company": COMPANY, "root_type": "Income", "is_group": 0}, "name"
        )
        inv = frappe.new_doc("Sales Invoice")
        inv.customer = self.customer
        inv.company = COMPANY
        # Keep document currency and receivable-account currency aligned; a fresh
        # site's selling price list can otherwise default the invoice to USD.
        inv.currency = frappe.get_value("Company", COMPANY, "default_currency")
        inv.debit_to = self.receivable
        inv.append("items", {"item_code": self._make_item(), "qty": 1, "rate": amount, "income_account": income})
        inv.flags.ignore_permissions = True
        inv.insert(ignore_permissions=True)
        inv.submit()
        self.track_test_record("Sales Invoice", inv.name)
        return inv.name

    def _make_forward_payment_entry(self):
        kwargs = {}
        if self.CASH_RECEIVED is not None:
            kwargs["cash_received"] = Decimal(str(self.CASH_RECEIVED))
        pe = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=self.invoice,
            amount=Decimal(str(self.INVOICE_AMOUNT)),
            posting_date=getdate(),
            reference_no=self.payment_id,
            reference_date=getdate(),
            mode_of_payment="Mollie",
            bank_account=self.clearing_account,
            **kwargs,
        )
        self.track_test_record("Payment Entry", pe.name)
        return pe.name

    # ---- helpers -----------------------------------------------------------

    def _reverse(self, amount, reversal_type="refund", reversal_id=None):
        reversal_id = reversal_id or f"re_dues_{frappe.generate_hash(length=8)}"
        result = UnifiedWebhookWrapperService().process_reversal_webhook(
            payment_id=self.payment_id,
            reversal_id=reversal_id,
            amount=amount,
            reversal_type=reversal_type,
            reversal_date=getdate(),
        )
        return reversal_id, result

    def _journal_entries_for(self, reversal_id, reversal_type="refund"):
        key = build_reversal_key(self.payment_id, reversal_type, reversal_id)
        return frappe.get_all("Journal Entry", filters={"cheque_no": key, "docstatus": ["!=", 2]}, pluck="name")

    def _gl_rows(self, journal_entry_name):
        return frappe.get_all(
            "GL Entry",
            filters={"voucher_type": "Journal Entry", "voucher_no": journal_entry_name, "is_cancelled": 0},
            fields=["account", "debit", "credit", "against_voucher_type", "against_voucher", "party"],
        )

    def _bank_transactions_for(self, reversal_id, reversal_type="refund"):
        key = build_reversal_key(self.payment_id, reversal_type, reversal_id)
        return frappe.get_all(
            "Bank Transaction", filters={"reference_number": key, "docstatus": ["!=", 2]}, pluck="name"
        )

    def _outstanding(self):
        return flt(frappe.db.get_value("Sales Invoice", self.invoice, "outstanding_amount"))


class TestDuesReversalBooksAgainstTheInvoice(_DuesReversalFixture):
    def test_the_forward_booking_is_recognised_as_dues(self):
        """Guard the premise: if this is not "dues", the rest tests nothing."""
        self.assertEqual(
            find_booked_payment(self.payment_id),
            ("dues", "Payment Entry", self.forward_pe),
            "fixture problem, not the defect: the forward Payment Entry is not derived as dues",
        )
        self.assertEqual(self._outstanding(), 0.0, "the fixture invoice should start fully paid")

    def test_a_full_refund_restores_the_whole_outstanding_amount(self):
        reversal_id, result = self._reverse(self.INVOICE_AMOUNT)
        self.assertEqual(result.get("status"), "success", f"dues reversal did not book: {result}")

        jes = self._journal_entries_for(reversal_id)
        self.assertEqual(len(jes), 1, f"expected exactly one reversing Journal Entry, got {jes}")

        self.assertEqual(
            self._outstanding(),
            self.INVOICE_AMOUNT,
            "the refund must restore the invoice's outstanding amount",
        )

        rows = self._gl_rows(jes[0])
        receivable = [r for r in rows if r["account"] == self.receivable]
        clearing = [r for r in rows if r["account"] == self.clearing_account]
        self.assertEqual(len(receivable), 1, f"one receivable leg expected, got {rows}")
        self.assertEqual(len(clearing), 1, f"one clearing leg expected, got {rows}")

        self.assertEqual(flt(receivable[0]["debit"]), self.INVOICE_AMOUNT)
        self.assertEqual(receivable[0]["against_voucher_type"], "Sales Invoice")
        self.assertEqual(
            receivable[0]["against_voucher"],
            self.invoice,
            "the receivable leg must point at the invoice, or the outstanding is never restored",
        )
        self.assertEqual(receivable[0]["party"], self.customer)
        self.assertEqual(
            flt(clearing[0]["credit"]),
            self.INVOICE_AMOUNT,
            "the clearing account must be CREDITED -- the money leaves",
        )

    def test_a_partial_refund_restores_only_that_part(self):
        reversal_id, result = self._reverse(20.0)
        self.assertEqual(result.get("status"), "success", f"partial dues reversal did not book: {result}")
        self.assertEqual(self._outstanding(), 20.0)

        rows = self._gl_rows(self._journal_entries_for(reversal_id)[0])
        receivable = [r for r in rows if r["account"] == self.receivable]
        self.assertEqual(flt(receivable[0]["debit"]), 20.0)
        self.assertEqual(receivable[0]["against_voucher"], self.invoice)

    def test_a_chargeback_books_the_same_way(self):
        reversal_id, result = self._reverse(
            self.INVOICE_AMOUNT, reversal_type="chargeback", reversal_id=f"chb_{frappe.generate_hash(length=8)}"
        )
        self.assertEqual(result.get("status"), "success", f"chargeback did not book: {result}")
        self.assertEqual(len(self._journal_entries_for(reversal_id, "chargeback")), 1)
        self.assertEqual(self._outstanding(), self.INVOICE_AMOUNT)

    def test_a_redelivery_does_not_book_a_second_time(self):
        reversal_id, first = self._reverse(self.INVOICE_AMOUNT)
        self.assertEqual(first.get("status"), "success", f"first delivery did not book: {first}")

        second = UnifiedWebhookWrapperService().process_reversal_webhook(
            payment_id=self.payment_id,
            reversal_id=reversal_id,
            amount=self.INVOICE_AMOUNT,
            reversal_type="refund",
            reversal_date=getdate(),
        )
        self.assertTrue(second.get("idempotent"), f"the redelivery was not recognised: {second}")
        self.assertEqual(len(self._journal_entries_for(reversal_id)), 1, "the redelivery booked again")
        self.assertEqual(
            self._outstanding(),
            self.INVOICE_AMOUNT,
            "a redelivery must not restore the outstanding amount twice",
        )

    def test_a_reversal_larger_than_the_payment_is_refused(self):
        """Mollie cannot refund more than it took; booking it would invent money."""
        self.expectErrorLog("Mollie Dues Reversal Not Bookable")
        reversal_id, result = self._reverse(self.INVOICE_AMOUNT + 1)
        self.assertNotEqual(result.get("status"), "success", f"an over-refund was booked: {result}")
        # Refusing is only half of it: nothing may have posted, and no bank line may
        # be left behind for a booking that never happened.
        self.assertEqual(self._journal_entries_for(reversal_id), [])
        self.assertEqual(self._outstanding(), 0.0, "the refused reversal still moved the invoice")
        self.assertEqual(self._bank_transactions_for(reversal_id), [])

    def test_the_reversal_leaves_a_reconciled_withdrawal_on_the_clearing_account(self):
        """The forward dues booking was Bank Transaction + Payment Entry, reconciled.

        Its reversal has to leave the clearing account with a bank line too, or the
        account's GL balance moves with nothing on the statement side to match it.
        """
        reversal_id, result = self._reverse(self.INVOICE_AMOUNT)
        self.assertEqual(result.get("status"), "success", f"dues reversal did not book: {result}")

        bts = self._bank_transactions_for(reversal_id)
        self.assertEqual(len(bts), 1, f"expected one withdrawal for the reversal, got {bts}")
        bt = frappe.get_doc("Bank Transaction", bts[0])
        self.assertEqual(flt(bt.withdrawal), self.INVOICE_AMOUNT, "the bank line must be a withdrawal")
        self.assertEqual(flt(bt.deposit or 0), 0.0)

        je = self._journal_entries_for(reversal_id)[0]
        linked = [(row.payment_document, row.payment_entry) for row in bt.payment_entries]
        self.assertIn(
            ("Journal Entry", je),
            linked,
            f"the withdrawal must be reconciled against the entry that booked it, got {linked}",
        )


class TestDuesReversalWithUnallocatedCash(_DuesReversalFixture):
    """The dues route records the whole payment, not only what the invoice took.

    ``_create_payment_entry_for_dues`` passes ``cash_received=<full amount>`` while
    allocating only the invoice's outstanding, so the excess sits in
    ``unallocated_amount`` as a credit on the customer. Reversing the full payment
    has to undo both halves, or the credit survives a refund that took it back.
    """

    INVOICE_AMOUNT = 50.0
    CASH_RECEIVED = 60.0

    def test_the_excess_is_reversed_as_well_as_the_invoice_allocation(self):
        reversal_id, result = self._reverse(60.0)
        self.assertEqual(result.get("status"), "success", f"dues reversal did not book: {result}")

        rows = self._gl_rows(self._journal_entries_for(reversal_id)[0])
        receivable = [r for r in rows if r["account"] == self.receivable]
        clearing = [r for r in rows if r["account"] == self.clearing_account]

        self.assertEqual(
            flt(sum(flt(r["debit"]) for r in receivable)),
            60.0,
            "the whole refund must be debited to the receivable",
        )
        self.assertEqual(flt(clearing[0]["credit"]), 60.0)

        against_invoice = [r for r in receivable if r["against_voucher"] == self.invoice]
        self.assertEqual(
            flt(sum(flt(r["debit"]) for r in against_invoice)),
            50.0,
            "only what the invoice actually took may be restored to it",
        )
        self.assertEqual(self._outstanding(), 50.0)
