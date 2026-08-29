"""Two more producers of the #645 class: a credit note, and Payment Reconciliation (#649).

#645 named the class -- "a voucher that moves a member invoice's `outstanding_amount`
without dispatching `on_update_after_submit` on that invoice" -- and fixed the Journal
Entry producer. Two more reach a member's receivable:

* **A credit note.** When a return Sales Invoice carries `return_against` and
  `update_outstanding_for_self` is off, ERPNext posts the customer GL row with
  `against_voucher = return_against` (`sales_invoice.py:1675-1676`), so it is the ORIGINAL
  invoice whose outstanding moves. This app's Sales Invoice route queues a refresh for
  `event_data["invoice"]` -- the credit note -- and the original's history row keeps the
  pre-credit figure.

* **Payment Reconciliation.** `reconcile_against_document` sets
  `ignore_validate_update_after_submit` and calls `.save()` on the submitted payment
  (`erpnext/accounts/utils.py:554`, plus `:728` inside
  `update_reference_in_journal_entry`), so allocating a previously unallocated payment
  to a member's invoice dispatches only `on_update_after_submit` -- an event this app
  registered nothing for on EITHER doctype. The Journal Entry half is not in #649's
  body: its grep found the Payment Entry call and stopped.

* **Unreconcile Payment.** `UnreconcilePayment.on_submit` calls
  `update_voucher_outstanding` DIRECTLY, once per allocation row, and unlinks the
  reference with raw query-builder updates. No GL row, no Payment Entry save, no
  Journal Entry save -- so it is invisible both to the three registrations above and to
  the scoping query below.

That last one is why the scoping evidence in #649 is weaker than it reads. On veg11,
`SELECT DISTINCT voucher_type FROM tabGL Entry WHERE against_voucher_type='Sales Invoice'
AND against_voucher <> voucher_no AND is_cancelled = 0` returns Payment Entry only -- but
it selects GL rows, and Unreconcile Payment writes none, so a producer could never have
appeared in it. All four are reachable from the desk.

The properties proved here are the ones #645 established. The first three are proved
for EVERY producer below; the payload is producer-independent -- once a drain runs it
does not care what moved the figure -- so it is proved once, for Payment Reconciliation,
rather than three times:

* **the premise** -- the voucher really does move the ORIGINAL invoice's outstanding.
  Asserted first and separately, because every dispatch test below is vacuous if it does
  not: a hook that fires for a voucher that changed nothing proves nothing.
* **the dispatch** -- driven through a real `submit()` / `cancel()` / `reconcile()`, so a
  registration that exists but is never dispatched still fails.
* **the argument** -- the (member, customer) PAIR, never the member alone. See
  `drains_for_this_member`.
* **the payload** -- the refresh OVERWRITES the original invoice's stale row.
"""

from unittest.mock import patch

import frappe
from frappe.utils import flt, today

from verenigingen.tests.support.invoice_payments import build_eur_membership_invoice
from verenigingen.tests.support.payment_history_fixtures import (
    MemberPaymentHistoryFixture,
    PaidInvoiceFixture,
)
from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company


class _UnpaidInvoiceFixture(MemberPaymentHistoryFixture):
    """An UNPAID EUR invoice, which is what a credit note needs.

    Not `PaidInvoiceFixture`: on a fully paid invoice the outstanding is 0, and
    `validate_against_voucher_outstanding` FLIPS `update_outstanding_for_self` to 1 as
    soon as the credit note's total exceeds the original's outstanding
    (`accounts_controller.py:220`). ERPNext would then book the credit note against
    itself, the original's outstanding would never move, and every assertion below
    would pass or fail for a reason that has nothing to do with this app.
    """

    MEMBER_FIRST_NAME = "CreditNoteHistory"
    INVOICE_AMOUNT = 42.0

    def setUp(self):
        super().setUp()
        self.invoice = build_eur_membership_invoice(self, self.member.customer, rate=self.INVOICE_AMOUNT)

    def credit_note(self, submit=True):
        """A full credit note against `self.invoice`, built the way the desk builds one.

        `update_outstanding_for_self` is set to 0 EXPLICITLY because the DocType field
        defaults to **1** -- a fresh credit note carries its own outstanding and leaves
        the original alone. Unchecking the box is what puts `return_against` into the
        customer GL row (`sales_invoice.py:1675-1676`), and it is a one-click desk action the
        field's own description invites ("Credit Note will update it's own outstanding
        amount, even if 'Return Against' is specified"). #649's body describes the
        condition but not the default, and a fixture that trusted the default tests
        nothing: measured, `note.update_outstanding_for_self` came back 1 and the
        original invoice's outstanding never moved.
        """
        from erpnext.controllers.sales_and_purchase_return import make_return_doc

        note = make_return_doc("Sales Invoice", self.invoice.name)
        note.posting_date = today()
        note.set_posting_time = 1
        note.update_outstanding_for_self = 0
        note.insert()
        self.track_test_record("Sales Invoice", note.name)
        if submit:
            note.submit()
        return note

    def _original_outstanding(self):
        return flt(frappe.db.get_value("Sales Invoice", self.invoice.name, "outstanding_amount"))


class TestCreditNoteRefreshesTheOriginalInvoicesHistory(_UnpaidInvoiceFixture):
    def test_the_credit_note_moves_the_original_invoices_outstanding(self):
        """The premise, asserted on its own so the dispatch tests cannot be vacuous.

        `update_outstanding_for_self` is checked too: if ERPNext had flipped it, the
        credit note would carry its own outstanding and the original's would be
        untouched -- and this suite would be testing nothing.
        """
        self.assertEqual(self._original_outstanding(), self.INVOICE_AMOUNT)

        note = self.credit_note()

        self.assertFalse(
            note.update_outstanding_for_self,
            "ERPNext booked the credit note against itself, so nothing below is about "
            "the original invoice",
        )
        self.assertEqual(
            self._original_outstanding(),
            0.0,
            "the credit note must move the ORIGINAL invoice's outstanding",
        )

    def test_submitting_the_credit_note_asks_for_a_refresh(self):
        """The dispatch half, driven through a real submit."""
        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            self.credit_note()

        self.assertEqual(
            self.drains_for_this_member(enqueue),
            self.expected_drain,
            "submitting a credit note against a member's invoice must queue a "
            "payment-history drain for that member AND that member's customer",
        )

    def test_cancelling_the_credit_note_asks_for_a_refresh(self):
        """Cancelling gives the original invoice its outstanding back, so it is the
        same defect in the other direction."""
        note = self.credit_note()

        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            note.cancel()

        self.assertEqual(self.drains_for_this_member(enqueue), self.expected_drain)
        self.assertEqual(
            self._original_outstanding(),
            self.INVOICE_AMOUNT,
            "cancelling the credit note must restore the original invoice's outstanding",
        )

    def test_the_drain_replaces_the_original_invoices_stale_row(self):
        """The payload half: the refresh has to overwrite the ORIGINAL invoice's row.

        The row under test is the original's, not the credit note's -- the credit note
        gets a row of its own and refreshing only that one is exactly the defect.
        """
        # Scoped to this one test rather than the fixture: `expectErrorLog` is
        # permissive, and only this test drains. Set class-wide it would also excuse the
        # credit note submit path and this handler's own `except` if either started
        # logging that title. The drain walks every submitted invoice for the customer,
        # the credit note among them, and `validate_entry` rejects its negative
        # `amount` -- the row still lands, stamped "Draft" while the document's
        # docstatus is 1. Measured, and a separate defect (#653); this suite's subject
        # is the ORIGINAL invoice's row.
        self.expectErrorLog("Payment History Validation Error")

        self.drain()
        row = self.history_row(self.invoice.name)
        self.assertEqual(flt(row.outstanding_amount), self.INVOICE_AMOUNT)
        self.assertEqual(row.payment_status, "Unpaid")

        self.credit_note()
        self.drain()

        row = self.history_row(self.invoice.name)
        self.assertEqual(
            flt(row.outstanding_amount),
            0.0,
            "the member's payment history still carries the pre-credit-note figure",
        )
        # "Credited", not "Paid": ERPNext marks the fully-credited original
        # "Credit Note Issued", and reporting that as Paid made a WAIVED membership
        # invoice read exactly like one the member had paid (#653). This assertion said
        # "Paid" when the row was merely fresh rather than right.
        self.assertEqual(row.payment_status, "Credited")

    def test_an_ordinary_invoice_does_not_ask_for_a_credit_note_refresh(self):
        """The guard against over-firing.

        Every membership invoice submit would otherwise pay for a customer-wide drain
        on top of the per-invoice refresh the event route already queues. A submit that
        moved no OTHER invoice's outstanding must not reach this handler at all.
        """
        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            build_eur_membership_invoice(self, self.member.customer, rate=10.0)

        self.assertEqual(self.drains_for_this_member(enqueue), set())


class _ReconciliationFixture(MemberPaymentHistoryFixture):
    """An unpaid invoice plus an unallocated payment, the state the tool reconciles."""

    MEMBER_FIRST_NAME = "ReconHistory"
    INVOICE_AMOUNT = 42.0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A Payment Entry needs somewhere to receive into, and building it from a test
        # BODY would commit that test's in-flight fixtures.
        get_eur_bank_account(get_eur_test_company())

    def setUp(self):
        super().setUp()
        # Resolved here rather than in the shared base: `get_eur_test_company()` builds a
        # 94-account company, and the handler-only suites must not pay for it.
        self.company = get_eur_test_company()
        self.invoice = build_eur_membership_invoice(self, self.member.customer, rate=self.INVOICE_AMOUNT)
        self.payment = self._unallocated_payment(self.INVOICE_AMOUNT)

    def _unallocated_payment(self, amount):
        """A submitted Receive with NO references -- money in, not yet attributed.

        This is the state Payment Reconciliation exists for, and the reason the Payment
        Entry `on_submit` route does not already cover it: at submit time the payment
        names no invoice, so the drain it queues finds nothing to correct.
        """
        from erpnext.accounts.doctype.journal_entry.journal_entry import get_default_bank_cash_account

        bank = get_default_bank_cash_account(self.company, "Bank")
        if not bank or not bank.get("account"):
            self.fail(f"{self.company} has no default bank account, so this fixture cannot pay")

        payment = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "company": self.company,
                "party_type": "Customer",
                "party": self.member.customer,
                "posting_date": today(),
                "paid_amount": amount,
                "received_amount": amount,
                "paid_from": self.invoice.debit_to,
                "paid_to": bank["account"],
                "paid_from_account_currency": "EUR",
                "paid_to_account_currency": "EUR",
                "source_exchange_rate": 1,
                "target_exchange_rate": 1,
                "reference_no": f"RECON-{frappe.generate_hash(length=8)}",
                "reference_date": today(),
            }
        )
        payment.insert()
        payment.submit()
        self.track_test_record("Payment Entry", payment.name)
        return payment

    def _reconcile(self):
        """Run the real Payment Reconciliation tool over this member's receivable."""
        reconciliation = frappe.new_doc("Payment Reconciliation")
        reconciliation.company = self.company
        reconciliation.party_type = "Customer"
        reconciliation.party = self.member.customer
        reconciliation.receivable_payable_account = self.invoice.debit_to
        reconciliation.get_unreconciled_entries()

        self.assertTrue(reconciliation.get("invoices"), "the tool found no invoice to reconcile")
        self.assertTrue(reconciliation.get("payments"), "the tool found no payment to reconcile")

        reconciliation.allocate_entries(
            frappe._dict(
                {
                    "invoices": [row.as_dict() for row in reconciliation.invoices],
                    "payments": [row.as_dict() for row in reconciliation.payments],
                }
            )
        )
        reconciliation.reconcile()

    def _original_outstanding(self):
        return flt(frappe.db.get_value("Sales Invoice", self.invoice.name, "outstanding_amount"))


class TestPaymentReconciliationRefreshesPaymentHistory(_ReconciliationFixture):
    def test_reconciling_moves_the_invoices_outstanding(self):
        """The premise. Also pins the gap the `on_submit` route leaves: the payment was
        submitted with no reference, so nothing about it named this invoice until now."""
        self.assertEqual(self._original_outstanding(), self.INVOICE_AMOUNT)

        self._reconcile()

        self.assertEqual(self._original_outstanding(), 0.0)

    def test_reconciling_asks_for_a_refresh(self):
        """The dispatch half, driven through the real tool rather than through the
        `.save()` it happens to call -- so a fix wired to the wrong event still fails."""
        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            self._reconcile()

        self.assertEqual(self.drains_for_this_member(enqueue), self.expected_drain)

    def test_the_drain_replaces_the_stale_row_after_reconciliation(self):
        """The payload half."""
        self.drain()
        self.assertEqual(flt(self.history_row(self.invoice.name).outstanding_amount), self.INVOICE_AMOUNT)

        self._reconcile()
        self.drain()

        row = self.history_row(self.invoice.name)
        self.assertEqual(flt(row.outstanding_amount), 0.0)
        self.assertEqual(row.payment_status, "Paid")

    def test_saving_a_submitted_payment_entry_asks_for_a_refresh(self):
        """The narrow route, isolated: `on_update_after_submit` on Payment Entry.

        `reconcile_against_document` reaches it through `.save()` on a submitted
        document (`erpnext/accounts/utils.py:554`). Asserted separately from the
        end-to-end test above because the tool has other ways to fail, and this pins
        WHICH event the fix has to be registered on.

        erpnext passes `ignore_permissions=True` there and this does not: the bypass is
        about who may save, and copying it into a test would hide a permission defect on
        the very path being pinned. `run_post_save_methods` does not read the flag, so
        the dispatch under test is identical either way.
        """
        payment = frappe.get_doc("Payment Entry", self.payment.name)
        payment.flags.ignore_validate_update_after_submit = True
        payment.remarks = "reconciled"

        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            payment.save()

        self.assertEqual(self.drains_for_this_member(enqueue), self.expected_drain)


class TestJournalEntryReconciliationRefreshesPaymentHistory(_ReconciliationFixture):
    """The sibling #649's grep missed: reconciling a JOURNAL ENTRY payment.

    `update_reference_in_journal_entry` (`erpnext/accounts/utils.py:728`) saves the
    submitted Journal Entry, and the #645 fix registered `on_submit`/`on_cancel` only --
    so the entry that gains a reference to a member's invoice after the fact reaches
    nothing.

    Not an exact twin of the Payment Entry case, which is why it gets its own end-to-end
    test rather than being assumed covered by one: `reconcile_against_document` passes
    `do_not_save=True` for a Payment Entry and saves once itself (`utils.py:554`), while
    for a Journal Entry it lets `update_reference_in_journal_entry` save AND then saves
    again -- so this event fires N+1 times for N rows. Redundant, not wrong; the drain is
    idempotent, and it is not deduplicated away because `deduplicate=True` is inert under
    `enqueue_after_commit=True` (#648). The assertions below are on the SET of pairs, so
    they hold either way and do not pin a count this suite does not own.
    """

    MEMBER_FIRST_NAME = "JEReconHistory"

    def _unallocated_payment(self, amount):
        """A submitted Journal Entry crediting the member's receivable, naming NO invoice.

        The Journal Entry shape of an unattributed payment: money against the party, no
        `reference_name`, so Payment Reconciliation has something to allocate.
        """
        from erpnext.accounts.doctype.journal_entry.journal_entry import (
            get_default_bank_cash_account,
        )

        bank = get_default_bank_cash_account(self.company, "Bank")
        if not bank or not bank.get("account"):
            self.fail(f"{self.company} has no default bank account, so this fixture cannot pay")

        entry = frappe.new_doc("Journal Entry")
        entry.voucher_type = "Journal Entry"
        entry.company = self.company
        entry.posting_date = today()
        entry.append(
            "accounts",
            {
                "account": self.invoice.debit_to,
                "party_type": "Customer",
                "party": self.member.customer,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": amount,
            },
        )
        entry.append(
            "accounts",
            {
                "account": bank["account"],
                "debit_in_account_currency": amount,
                "credit_in_account_currency": 0,
            },
        )
        entry.insert()
        self.track_test_record("Journal Entry", entry.name)
        entry.submit()
        return entry

    def test_reconciling_a_journal_entry_payment_moves_the_invoices_outstanding(self):
        """The premise."""
        self.assertEqual(self._original_outstanding(), self.INVOICE_AMOUNT)

        self._reconcile()

        self.assertEqual(self._original_outstanding(), 0.0)

    def test_reconciling_a_journal_entry_payment_asks_for_a_refresh(self):
        """The dispatch half, driven through the real tool.

        The test the first round of this fix did not have: it asserted only the narrow
        `.save()` below, which would have passed even if reconciliation reached a
        Journal Entry by some path that dispatched nothing.
        """
        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            self._reconcile()

        self.assertEqual(self.drains_for_this_member(enqueue), self.expected_drain)

    def test_saving_a_submitted_journal_entry_asks_for_a_refresh(self):
        """The narrow route, isolated: `on_update_after_submit` on Journal Entry."""
        entry = frappe.get_doc("Journal Entry", self.payment.name)
        entry.flags.ignore_validate_update_after_submit = True
        entry.user_remark = "reconciled"

        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            entry.save()

        self.assertEqual(self.drains_for_this_member(enqueue), self.expected_drain)


class TestUnreconcilePaymentRefreshesPaymentHistory(PaidInvoiceFixture):
    """The producer a GL-shaped grep can never find (#649, found in review).

    `UnreconcilePayment.on_submit` calls `update_voucher_outstanding` DIRECTLY, once per
    allocation row, and unlinks the reference with raw query-builder updates. It posts no
    GL row, saves no Payment Entry and saves no Journal Entry -- so none of the other
    registrations sees it, and the member's history keeps saying Paid on an invoice that
    is owed again.

    That is also why #649's scoping query on veg11 could not have found it: it selected
    `tabGL Entry` rows, and this doctype writes none.
    """

    MEMBER_FIRST_NAME = "UnreconHistory"

    def _unreconcile(self, payment_name):
        doc = frappe.new_doc("Unreconcile Payment")
        doc.company = self.company
        doc.voucher_type = "Payment Entry"
        doc.voucher_no = payment_name
        doc.add_references()
        self.assertTrue(
            [a for a in doc.allocations if a.reference_name == self.invoice.name],
            "the tool found no allocation against this member's invoice",
        )
        doc.insert()
        self.track_test_record("Unreconcile Payment", doc.name)
        doc.submit()
        return doc

    def test_unreconciling_puts_the_invoices_outstanding_back(self):
        """The premise. The fixture's invoice is fully paid, so outstanding is 0."""
        self.assertEqual(
            flt(frappe.db.get_value("Sales Invoice", self.invoice.name, "outstanding_amount")), 0.0
        )

        self._unreconcile(self.forward_payment.name)

        self.assertEqual(
            flt(frappe.db.get_value("Sales Invoice", self.invoice.name, "outstanding_amount")),
            self.INVOICE_AMOUNT,
            "unreconciling must give the invoice its outstanding back",
        )

    def test_unreconciling_asks_for_a_refresh(self):
        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            self._unreconcile(self.forward_payment.name)

        self.assertEqual(self.drains_for_this_member(enqueue), self.expected_drain)
