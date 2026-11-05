"""#2083: a creator-made DRAFT Bank Transaction enters the reconcile pool; it must not book twice.

Since erpnext version-16 7526af9b2, ``BankTransaction.validate()`` sets every draft to
"Pending". ``bank_transaction_creator`` escalates the CREATE for escalation-eligible roles but never
the SUBMIT, so a user who cannot submit (stock profile: National Board Member) leaves a
draft, and those drafts now match the pool filter in
``reconcile_bank_transactions`` (``status="Pending"``, nothing allocated). The maintainer
ruled to accept that (follow ERPNext's model).

The risk the ruling makes real: the money may ALREADY be booked by a Payment Entry made
elsewhere and never linked to the draft (only a link sets ``allocated_amount`` and keeps a
row out of the pool). The pool must refuse to book it a second
time. The control case (same draft, invoice still unpaid) proves the draft does reach the
pool and the matcher fires, so the refusal is not vacuous.
"""

import frappe
from frappe.utils import flt, today

from verenigingen.tests.payment.test_bank_transaction_reconciliation import BTRBase
from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
    get_bank_transaction_creator,
)


class TestCreatorDraftInReconcilePool(BTRBase):
    def _national_board_member(self):
        """A user holding the stock "Verenigingen National Board Member" profile.

        That profile carries Verenigingen Staff (so the creator may escalate the CREATE)
        but no role with Bank Transaction submit, which makes it the stock profile that
        really produces creator drafts. Staff and Treasurer profiles carry Accounts User
        and submit, so they never leave one.
        """
        email = f"nbm2083.{frappe.generate_hash(length=8)}@test.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "NBM2083",
                "send_welcome_email": 0,
                "role_profiles": [{"role_profile": "Verenigingen National Board Member"}],
            }
        ).insert()
        self.track_doc("User", user.name)
        return user.name

    def _creator_draft(self, deposit, description):
        """A Bank Transaction made by the creator for a user who cannot submit one.

        The creator escalates the CREATE for escalation-eligible roles but never the
        SUBMIT, so this is the real way a creator draft comes about.
        """
        user = self._national_board_member()
        self.assertFalse(frappe.has_permission("Bank Transaction", "submit", user=user))
        # ...nor create one directly: the CREATE goes through the escalation path.
        self.assertFalse(frappe.has_permission("Bank Transaction", "create", user=user))
        # The creator logs the refused SUBMIT that leaves the row in draft.
        self.expectErrorLog("Secure Operation Failed")
        previous_user = frappe.session.user
        frappe.set_user(user)
        try:
            name = get_bank_transaction_creator().create(
                date=today(),
                bank_account=self._eur_bank_account,
                company=self.company,
                deposit=deposit,
                withdrawal=0.0,
                currency="EUR",
                reference_number=f"tr_{frappe.generate_hash(length=10)}",
                description=description,
            )
        finally:
            frappe.set_user(previous_user)
        self.assertTrue(name, "the creator returned no Bank Transaction")
        bt = frappe.get_doc("Bank Transaction", name)
        self.assertEqual(bt.docstatus, 0, "the user cannot submit, so the creator leaves a draft")
        self.assertEqual(bt.status, "Pending", "ERPNext makes every draft Pending (#2083)")
        return bt

    def _submitted_payment_entries(self, invoice_name):
        refs = frappe.get_all(
            "Payment Entry Reference",
            filters={"reference_doctype": "Sales Invoice", "reference_name": invoice_name},
            pluck="parent",
        )
        return sorted(pe for pe in set(refs) if frappe.db.get_value("Payment Entry", pe, "docstatus") == 1)

    def _book_payment(self, invoice, amount=None, reference_no=None):
        """A Payment Entry booked outside the pool and never linked to any draft.

        ``reference_no`` is how the Mollie path ties a Payment Entry to its money: the
        Mollie payment id, which the creator also uses as the draft's reference_number.
        """
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        pe = get_payment_entry(dt="Sales Invoice", dn=invoice.name, party_amount=flt(amount or invoice.grand_total))
        pe.reference_no = reference_no or frappe.generate_hash(length=10)
        pe.reference_date = today()
        pe.mode_of_payment = "Mollie"
        pe.insert()
        pe.submit()
        return pe

    def _comments(self, bt):
        return " ".join(
            c.content or ""
            for c in frappe.get_all(
                "Comment",
                filters={"reference_doctype": "Bank Transaction", "reference_name": bt.name},
                fields=["content"],
            )
        )

    def _run_pool(self):
        self.mgr.reconcile_bank_transactions(
            bank_account=self._eur_bank_account, from_date=today(), to_date=today()
        )

    def test_a_pooled_creator_draft_for_an_unpaid_invoice_is_booked_once(self):
        """Control: the draft reaches the pool and the description match books it."""
        it = self._make_member_with_invoice(first_name="Pool2083Ctl", grand_total=30.0)
        invoice = it["invoice"]
        bt = self._creator_draft(30.0, f"INVOICE {invoice.name}")

        self._run_pool()

        self.assertEqual(len(self._submitted_payment_entries(invoice.name)), 1)
        invoice.reload()
        self.assertEqual(flt(invoice.outstanding_amount), 0.0)
        # Asserted through the pool's own comment, not Bank Transaction.status, which
        # ERPNext owns (#2082).
        self.assertIn("Auto-reconciled", self._comments(bt))

    def test_a_pooled_creator_draft_whose_money_is_already_booked_is_not_booked_again(self):
        it = self._make_member_with_invoice(first_name="Pool2083Paid", grand_total=30.0)
        invoice = it["invoice"]
        # The payment was booked elsewhere and never linked to the draft.
        booked = self._book_payment(invoice)
        bt = self._creator_draft(30.0, f"INVOICE {invoice.name}")
        # The refusal is logged by create_reconciliation before marking Unreconciled.
        self.expectErrorLog("Payment Entry Validation")

        self._run_pool()

        self.assertEqual(
            self._submitted_payment_entries(invoice.name),
            [booked.name],
            "the pool booked an already-paid invoice a second time",
        )
        invoice.reload()
        self.assertEqual(flt(invoice.outstanding_amount), 0.0)
        # The refusal comment names the invoice: proves the pool selected and matched this
        # draft and REFUSED it, rather than never selecting it (which would also book nothing).
        comments = self._comments(bt)
        self.assertIn("Reconciliation failed", comments)
        self.assertIn(invoice.name, comments)

    def test_a_pooled_creator_draft_mirroring_a_booked_partial_payment_is_not_booked_again(self):
        """The same Mollie payment, partially paying the invoice.

        Invoice 30, a Payment Entry of 10 booked for Mollie payment X, and a creator draft of
        10 for the same payment X. Outstanding is 20, so the pool's ``deposit > outstanding``
        guard lets it through. What refuses it is the unique
        ``custom_mollie_idempotency_key`` (hash of reference_no, payment_type, party;
        ``utils/mollie_idempotency_key.py``): the pool's Payment Entry reuses the draft's
        reference_number, so it collides with the one already booked. This test pins that.
        """
        it = self._make_member_with_invoice(first_name="Pool2083Part", grand_total=30.0)
        invoice = it["invoice"]
        bt = self._creator_draft(10.0, f"INVOICE {invoice.name}")
        booked = self._book_payment(invoice, amount=10.0, reference_no=bt.reference_number)
        self.expectErrorLog("Payment Entry Validation")

        self._run_pool()

        self.assertEqual(
            self._submitted_payment_entries(invoice.name),
            [booked.name],
            "the pool booked the same Mollie payment a second time",
        )
        # No half-made Payment Entry of ANY docstatus is left behind either.
        self.assertEqual(
            frappe.get_all(
                "Payment Entry Reference",
                filters={"reference_doctype": "Sales Invoice", "reference_name": invoice.name},
                pluck="parent",
            ),
            [booked.name],
        )
        invoice.reload()
        self.assertEqual(flt(invoice.outstanding_amount), 20.0)
        # Proves the pool selected and tried this draft (and was refused), rather than
        # never selecting it, which would also book nothing.
        self.assertIn("Reconciliation failed", self._comments(bt))

    def test_a_pooled_creator_draft_for_a_second_instalment_is_still_booked(self):
        """Control for the test above: a DIFFERENT earlier payment is not this money.

        Same shape, but the earlier Payment Entry carries another reference. The draft is a
        separate instalment and must be booked, or the guard would block every partial
        payment after the first.
        """
        it = self._make_member_with_invoice(first_name="Pool2083Inst", grand_total=30.0)
        invoice = it["invoice"]
        earlier = self._book_payment(invoice, amount=10.0)
        bt = self._creator_draft(10.0, f"INVOICE {invoice.name}")
        self.assertNotEqual(earlier.reference_no, bt.reference_number)

        self._run_pool()

        self.assertEqual(len(self._submitted_payment_entries(invoice.name)), 2)
        invoice.reload()
        self.assertEqual(flt(invoice.outstanding_amount), 10.0)
        self.assertIn("Auto-reconciled", self._comments(bt))
