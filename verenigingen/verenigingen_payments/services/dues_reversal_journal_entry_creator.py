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
ERPNext's own recompute, and expresses a **partial** refund, which a cancel of the
forward entry cannot (#370, #635).

That recompute is ``update_voucher_outstanding``
(``erpnext/accounts/utils.py:2141``), reached from ``PaymentLedgerEntry.on_update``
-- **not** ``gl_entry.update_outstanding_amt``, which this docstring named until
#649. That function cannot run for a Sales Invoice at all: ``GLEntry.on_update``
gates it on the account NOT being Receivable, and the ``against_voucher`` row
always sits on ``debit_to``. The distinction is not academic -- a sweep for "what
moves a member invoice's outstanding" that starts from GL Entry producers misses
``Unreconcile Payment``, which posts no GL row and calls the recompute directly.

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
from frappe.utils import flt

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
        posting_date,
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
            posting_date: date to post on, already parsed by the caller. Shared
                with the Bank Transaction this entry is reconciled against, so the
                two cannot land on different days when a bad date falls back.
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
            posting_date=posting_date,
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
        """Split the reversal across what the forward payment actually settled.

        Returns ``{"company", "party_type", "party", "credit_account", "debits"}``
        or ``{"error": ...}``. Public so a caller can validate before writing a
        Bank Transaction it would otherwise have to compensate away.

        **The on-account excess unwinds first, then the invoice allocations.**
        The dues route records the whole payment and allocates only the invoice's
        outstanding, so any excess sits in ``unallocated_amount`` as a credit on
        the customer (``create_payment_entry_from_invoice(cash_received=...)``).
        That credit exists *only* because the gateway moved more than the invoice
        could absorb, which is also the most likely reason to refund part of such
        a payment -- so it is the last thing applied and the first thing undone.

        The other order was tried and is wrong for exactly that case: refunding
        the €10 excess of a €60 payment against a €50 invoice took a fully-paid
        invoice to Partly Paid with €10 outstanding *and* left the member holding
        a €10 unapplied credit. Debtors nets to zero either way, but invoice
        outstanding is what drives dunning and dues status. The cost of this
        order is the mirror image and smaller: a partial refund that *should*
        show on the invoice is absorbed by the credit first, which is visible on
        the customer rather than the invoice. A full reversal is identical under
        both orders.

        Amounts are in the entry's own currency and posted only as
        ``*_in_account_currency``; a cross-currency reversal would fail ERPNext's
        multi-currency validation rather than post something wrong.
        """
        from verenigingen.verenigingen_payments.mollie.utils.reversal_idempotency import total_reversed

        amount = flt(amount, 2)
        if amount <= 0:
            return {"error": f"reversal amount {amount} is not positive"}

        pe = frappe.get_doc("Payment Entry", forward_payment_entry)
        if pe.docstatus != 1:
            return {"error": f"forward Payment Entry {pe.name} is at docstatus={pe.docstatus}, not submitted"}

        if not pe.paid_to or not pe.paid_from:
            return {"error": f"forward Payment Entry {pe.name} has no paid_from/paid_to to reverse"}

        # Mollie cannot give back more than it took -- but the check has to be
        # against everything already given back, not just this delivery. A refund
        # and a chargeback get different reversal keys and both book, so two
        # deliveries that each pass a per-delivery check can still sum above the
        # payment. Measured before this guard existed: two €30 reversals of a €50
        # payment left a €50 invoice at €60 outstanding and Overdue, because
        # ERPNext's own over-allocation guard is unreachable for debit-side
        # invoice references (see `total_reversed`).
        paid = flt(pe.paid_amount, 2)
        already = total_reversed(pe.reference_no) if pe.reference_no else 0.0
        if flt(already + amount, 2) > paid:
            return {
                "error": (
                    f"reversal amount {amount} plus {already} already reversed exceeds "
                    f"the payment's {paid}"
                )
            }

        debits: List[Dict[str, Any]] = []
        remaining = amount

        # 1. the unapplied credit the gateway's excess created
        on_account = flt(min(remaining, flt(pe.unallocated_amount, 2)), 2)
        remaining = flt(remaining - on_account, 2)

        # 2. then the invoice allocations, each capped at what it actually took.
        #    Row order is the document's own; only one producer of a Mollie dues
        #    Payment Entry exists today (`create_payment_entry_from_invoice`,
        #    always one invoice), so a multi-invoice entry is unexercised and the
        #    order between several invoices is not a decided policy.
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

        # 3. whatever the two above could not place. `paid_amount` is normally
        #    allocations + unallocated, so this is residue from deductions or
        #    rounding rather than a routine case -- but it has to land somewhere,
        #    or debits and credits do not balance.
        on_account = flt(on_account + remaining, 2)
        if on_account > 0:
            debits.append({"account": pe.paid_from, "amount": on_account})

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
                    "Mollie Dues Reversal Journal Entry Error",
                    f"Dues reversal Journal Entry creation failed for {original_payment_id}: {error_msg}",
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
            # (title, message), not the other way round: log_error only swaps
            # them when the first argument contains a newline, so a single-line
            # message passed first is TRUNCATED into the 140-char title and the
            # real cause is what gets discarded (#602).
            frappe.log_error(
                "Mollie Dues Reversal Journal Entry Error",
                f"Dues reversal Journal Entry creation failed for payment {original_payment_id}: {e}",
            )
            return None


def get_dues_reversal_journal_entry_creator() -> DuesReversalJournalEntryCreator:
    """Factory function to get DuesReversalJournalEntryCreator instance."""
    return DuesReversalJournalEntryCreator()
