"""
Dues Reversal Journal Entry Creator Service

Books a refunded or charged-back membership-dues payment back to the ledger.

Architecture:
    Mollie reversal webhook → Bank Transaction → Journal Entry → invoice restored
                              (withdrawal)       (Debit: Receivable / Credit: Mollie Clearing)

**Why a Journal Entry, and not a reversing Payment Entry.** A dues payment is
booked as a Payment Entry allocated to a Sales Invoice, so reversing it "in kind"
looks natural -- but ERPNext refuses it. ``validate_allocated_amount_with_latest_data``
throws when a positive allocation exceeds ``outstanding_amount`` *and* when a
negative one falls below it, so on a fully-paid invoice (``outstanding == 0``)
both directions throw. A Journal Entry debiting the invoice's ``debit_to`` with
``reference_type="Sales Invoice"`` restores ``outstanding_amount`` through
ERPNext's own ``update_outstanding_amt``, and expresses a **partial** refund,
which a cancel of the forward entry cannot (#370, #635).

**Why not cancel the forward Payment Entry**, despite the SEPA-return precedent:
a cancel re-posts GL at the original date (which fails once the period is closed,
and chargeback windows run long), strips the entry from its reconciled Bank
Transaction leaving a real settled deposit permanently unreconciled, cannot do
partials, and is self-erasing -- the "was this booked as dues?" predicate keys on
that Payment Entry being ``docstatus = 1``, so cancelling it makes Mollie's next
delivery report "original payment not found".

This is deliberately a **sibling** of ``DonationRefundJournalEntryCreator`` rather
than a shared base. Both end at a Journal Entry, and that is a consequence of
ERPNext's model, not a unifying principle: a donation reversal debits *income*
and carries no invoice reference, this one debits a *receivable* and is only
useful because it does carry one. Merging them would have to reintroduce the
difference as a flag on every line.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import flt, getdate, nowdate

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.verenigingen_payments.services.journal_entry_booking_support import (
    discard_unposted_journal_entry,
    find_journal_entry_by_reference,
    reconcile_bank_transaction_with_journal_entry,
)


class DuesReversalJournalEntryCreator:
    """Reverse a dues payment against the invoice it settled."""

    def create_reversal_journal_entry(
        self,
        legs: Dict[str, Any],
        reversal_id: str,
        amount: float,
        reversal_date: Optional[str],
        forward_payment_entry: str,
        original_payment_id: str,
        bank_transaction_name: Optional[str] = None,
        reversal_type: str = "refund",
        description: Optional[str] = None,
    ) -> Optional[str]:
        """Book the reversal. Returns the Journal Entry name, or None on failure.

        Args:
            legs: what to post, from :meth:`build_legs`. Passed in rather than
                derived here because the caller has to validate *before* it writes
                the Bank Transaction this entry is reconciled against -- a booking
                refused at this point would have to be compensated away instead.
            reversal_id: Mollie reversal id (``re_...`` / ``chb_...``).
            amount: Reversal amount, positive. May be less than the payment.
            reversal_date: Date of the reversal (ISO string, date, or None).
            forward_payment_entry: The submitted Payment Entry the dues payment
                booked, for the narration. Every account, party and allocation was
                read off it by :meth:`build_legs`: what the forward payment posted
                is a recorded fact, and re-deriving it from Mollie months later can
                disagree with the booking being reversed (#370).
            original_payment_id: Mollie payment id (``tr_...``).
            bank_transaction_name: Withdrawal to reconcile this entry against.
            reversal_type: ``"refund"`` or ``"chargeback"``. Lands in the reference
                key and in the narration -- a chargeback filed under a refund key
                collides with the refund on the same payment and hides one of them
                from the idempotency lookup.
            description: Caller-built detail; for a chargeback the Mollie reason.
        """
        from verenigingen.verenigingen_payments.mollie.utils.reversal_idempotency import (
            build_reversal_key,
        )

        reference_number = build_reversal_key(original_payment_id, reversal_type, reversal_id)

        existing_je = find_journal_entry_by_reference(reference_number)
        if existing_je:
            frappe.logger().info(
                f"Dues reversal Journal Entry already exists for {reversal_id}: {existing_je}"
            )
            if bank_transaction_name:
                reconcile_bank_transaction_with_journal_entry(bank_transaction_name, existing_je, flt(amount))
            return existing_je

        return self._create_journal_entry(
            legs=legs,
            posting_date=self._posting_date(reversal_date),
            reference_number=reference_number,
            reversal_id=reversal_id,
            reversal_type=reversal_type,
            original_payment_id=original_payment_id,
            forward_payment_entry=forward_payment_entry,
            description=description,
            bank_transaction_name=bank_transaction_name,
        )

    # ------------------------------------------------------------------
    # What to post
    # ------------------------------------------------------------------

    def build_legs(self, forward_payment_entry: str, amount: float) -> Dict[str, Any]:
        """Split the reversal across the invoices the forward payment settled.

        Returns ``{"company", "party_type", "party", "credit_account", "debits"}``
        or ``{"error": ...}``. Public so a caller can validate before writing a
        Bank Transaction it would otherwise have to compensate away.

        **Invoice first, remainder on account.** The dues route records the whole
        payment and allocates only the invoice's outstanding, so any excess sits
        in ``unallocated_amount`` as a credit on the customer
        (``create_payment_entry_from_invoice(cash_received=...)``). A reversal has
        to be able to undo both halves. It reduces the invoice allocations first,
        up to what each actually took, and puts what is left on the party account
        with no reference -- which is what removes the credit. Restoring what is
        owed is the useful half, so it goes first; eating the on-account credit
        first would leave a partial refund invisible on the invoice.
        """
        amount = flt(amount, 2)
        if amount <= 0:
            return {"error": f"reversal amount {amount} is not positive"}

        pe = frappe.get_doc("Payment Entry", forward_payment_entry)
        if pe.docstatus != 1:
            return {"error": f"forward Payment Entry {pe.name} is at docstatus={pe.docstatus}, not submitted"}

        paid = flt(pe.paid_amount, 2)
        if amount > paid:
            # Mollie cannot give back more than it took. Booking it would invent
            # money on the receivable and on the clearing account.
            return {"error": f"reversal amount {amount} exceeds the payment's {paid}"}

        if not pe.paid_to or not pe.paid_from:
            return {"error": f"forward Payment Entry {pe.name} has no paid_from/paid_to to reverse"}

        debits: List[Dict[str, Any]] = []
        remaining = amount
        for ref in pe.get("references") or []:
            if remaining <= 0:
                break
            if ref.reference_doctype != "Sales Invoice":
                continue
            take = flt(min(remaining, flt(ref.allocated_amount, 2)), 2)
            if take <= 0:
                continue
            # ERPNext matches the row's account against the invoice's own
            # `debit_to` (journal_entry.validate_reference_doc), so read it from
            # the invoice rather than assuming it equals the entry's paid_from.
            debit_to = frappe.db.get_value("Sales Invoice", ref.reference_name, "debit_to")
            if not debit_to:
                return {"error": f"Sales Invoice {ref.reference_name} has no debit_to account"}
            debits.append(
                {
                    "account": debit_to,
                    "amount": take,
                    "reference_type": "Sales Invoice",
                    "reference_name": ref.reference_name,
                }
            )
            remaining = flt(remaining - take, 2)

        if remaining > 0:
            debits.append({"account": pe.paid_from, "amount": remaining})

        return {
            "company": pe.company,
            "party_type": pe.party_type,
            "party": pe.party,
            "credit_account": pe.paid_to,
            "debits": debits,
        }

    # ------------------------------------------------------------------
    # Writing it
    # ------------------------------------------------------------------

    @staticmethod
    def _posting_date(reversal_date):
        if isinstance(reversal_date, str):
            try:
                from dateutil import parser

                return parser.parse(reversal_date).date()
            except (ValueError, TypeError, ImportError):
                return nowdate()
        return getdate(reversal_date) if reversal_date else nowdate()

    def _create_journal_entry(
        self,
        legs: Dict[str, Any],
        posting_date,
        reference_number: str,
        reversal_id: str,
        reversal_type: str,
        original_payment_id: str,
        forward_payment_entry: str,
        description: Optional[str],
        bank_transaction_name: Optional[str],
    ) -> Optional[str]:
        """Create and submit the reversing entry.

        Accounting entries (the mirror of the forward "Receive"):
            Debit:  the invoice's receivable, referencing that invoice
            Credit: the account the payment landed in (the entry's ``paid_to``)
        """
        try:
            remark_parts = [f"Dues {reversal_type.upper()}: {reversal_id}"]
            remark_parts.append(f"Original Payment: {original_payment_id}")
            remark_parts.append(f"Reverses: {forward_payment_entry}")
            if description:
                remark_parts.append(description)

            je = frappe.new_doc("Journal Entry")
            je.voucher_type = "Journal Entry"
            je.company = legs["company"]
            je.posting_date = posting_date
            je.cheque_no = reference_number  # Journal Entry carries the reversal key here
            je.cheque_date = posting_date
            je.user_remark = " | ".join(remark_parts)

            total = 0.0
            for debit in legs["debits"]:
                row = {
                    "account": debit["account"],
                    "party_type": legs["party_type"],
                    "party": legs["party"],
                    "debit_in_account_currency": flt(debit["amount"]),
                    "credit_in_account_currency": 0,
                    "user_remark": (
                        f"{reversal_type.capitalize()} {reversal_id}"
                        + (f" against {debit['reference_name']}" if debit.get("reference_name") else "")
                    ),
                }
                if debit.get("reference_name"):
                    row["reference_type"] = debit["reference_type"]
                    row["reference_name"] = debit["reference_name"]
                je.append("accounts", row)
                total = flt(total + flt(debit["amount"]), 2)

            je.append(
                "accounts",
                {
                    "account": legs["credit_account"],
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": flt(total),
                    "user_remark": f"{reversal_type.capitalize()} paid out: {reversal_id}",
                },
            )

            create_result = secure_document_operation(
                operation="create",
                doc=je,
                justification=(
                    f"Mollie dues {reversal_type} Journal Entry for payment {original_payment_id} "
                    f"({reversal_type}: {reversal_id})"
                ),
                required_permissions=["Journal Entry:create"],
                allow_system_user=True,
            )
            if not create_result.success:
                error_msg = ", ".join(create_result.errors) if create_result.errors else "Unknown error"
                frappe.logger().error(f"Failed to create dues reversal Journal Entry: {error_msg}")
                frappe.log_error(
                    f"Dues reversal Journal Entry creation failed for {original_payment_id}: {error_msg}",
                    "Mollie Dues Reversal Journal Entry Error",
                )
                return None

            je = create_result.document

            submit_result = secure_document_operation(
                operation="submit",
                doc=je,
                justification=f"Mollie dues {reversal_type} Journal Entry submission for {original_payment_id}",
                required_permissions=["Journal Entry:submit"],
                allow_system_user=True,
            )
            if not submit_result.success:
                return discard_unposted_journal_entry(
                    je.name,
                    subject=f"Mollie dues {reversal_type} of payment {original_payment_id}",
                    error_message=(
                        ", ".join(submit_result.errors) if submit_result.errors else "Unknown error"
                    ),
                )

            frappe.logger().info(
                f"Created and submitted dues reversal Journal Entry {je.name} for payment {original_payment_id}"
            )

            if bank_transaction_name:
                reconcile_bank_transaction_with_journal_entry(bank_transaction_name, je.name, flt(total))

            return je.name

        except Exception as e:  # swallow-ok: caller-checks
            # None is the contract, not a shrug: the caller wrote a Bank Transaction
            # before calling this and withdraws it on exactly this return value, so
            # raising here would leave a phantom withdrawal on the clearing account
            # for money that was never booked out. The cause is not lost -- it goes
            # to the Error Log below, and the webhook answers non-2xx.
            frappe.logger().error(f"Failed to create dues reversal Journal Entry: {e}")
            frappe.log_error(
                f"Dues reversal Journal Entry creation failed for payment {original_payment_id}: {e}",
                "Mollie Dues Reversal Journal Entry Error",
            )
            return None


def get_dues_reversal_journal_entry_creator() -> DuesReversalJournalEntryCreator:
    """Factory function to get DuesReversalJournalEntryCreator instance."""
    return DuesReversalJournalEntryCreator()
