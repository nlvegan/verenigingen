"""
The three things every Mollie Journal-Entry booker has to do the same way.

Donations, donation reversals and dues reversals post different entries -- one
recognises income, one un-recognises it, one restores a receivable against its
invoice -- but they all have to answer "has this reference already been booked?",
clean up after a submit that did not post, and link the entry to its bank line.
Those three were copied into each creator, and a copy-pasted helper is where a
fix goes to die: #370 was fixed in one copy of the bank-line lookup and not the
other, which is how a reversal came to be booked twice.

Only the identical parts live here. What each creator posts stays with it.
"""

from typing import Optional

import frappe
from frappe.utils import flt

from verenigingen.verenigingen_payments.utils.bank_transaction_status import RECONCILED, record_pool_outcome


def find_journal_entry_by_reference(reference_number: str) -> Optional[str]:
    """Name of a live Journal Entry carrying this reference key, or None.

    ``docstatus != 2``: a cancelled entry is one that was explicitly undone, so
    the key is free again, while a *draft* is work already in flight and counting
    it as absent is what produces the second booking.

    A pure lookup. A booker asking "has this been booked?" must call
    :func:`resolve_journal_entry_by_reference` instead, which also tries to
    finish a draft: this one answers "a draft claims the key" forever (#2535).
    """
    if not reference_number:
        return None
    return frappe.db.get_value(
        "Journal Entry", {"cheque_no": reference_number, "docstatus": ["!=", 2]}, "name"
    )


def resolve_journal_entry_by_reference(
    reference_number: str, expected_amount: Optional[float]
) -> Optional[str]:
    """Like ``find_journal_entry_by_reference``, but a stranded draft is finished first.

    A draft claims the key, so without this a charge whose Journal Entry never
    got past insert (a worker killed between insert and submit, or a submit
    refused before anything was written) read as booked forever: the webhook and
    the recovery sweep both answered "already processed" and nothing posted
    (#2535). Same shape as ``BankTransactionCreator._resolve_existing_bank_transaction``
    (#383): retry the submit of the existing draft, then answer with whatever the
    lookup now says.

    The retry is a real submit, so the outcome is one of three, all reported:
    it posts (the key stays claimed, now by a live entry); it fails after the
    docstatus write (``discard_unposted_journal_entry`` cancels it, the key is
    free and this returns None so the caller books afresh); or it fails before
    anything is written (the draft stays, an Error Log row says so, and this
    still returns its name so a second entry is never created beside it).

    ``expected_amount`` is REQUIRED: the payment amount the caller already holds.
    A draft whose ``total_debit`` differs (a hand-edited leftover) is NOT
    submitted: it is reported and left, still claiming the key, so staff decide.
    A caller that cannot supply an amount passes ``None`` and the draft is
    likewise left alone (fail closed): there is no "skip the check".
    """
    name = find_journal_entry_by_reference(reference_number)
    if name and frappe.db.get_value("Journal Entry", name, "docstatus") == 0:
        if _draft_matches_amount(name, reference_number, expected_amount):
            _resubmit_stranded_draft(name, reference_number)
            name = find_journal_entry_by_reference(reference_number)
    return name


def mollie_amount_or_none(mollie_object) -> Optional[float]:
    """The amount of a Mollie payment/refund/chargeback object, or None when it has none.

    For callers of :func:`resolve_journal_entry_by_reference`: an unreadable amount
    must reach it as None (draft left alone), not raise out of a webhook.
    """
    from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

    try:
        return get_payment_data_extractor().extract_amount(mollie_object)
    except ValueError:
        return None


def _draft_matches_amount(journal_entry_name: str, reference_number: str, expected_amount) -> bool:
    total_debit = flt(frappe.db.get_value("Journal Entry", journal_entry_name, "total_debit"), 2)
    if expected_amount and total_debit == flt(expected_amount, 2):
        return True
    _report_amount_mismatch(journal_entry_name, reference_number, total_debit, expected_amount)
    return False


def _report_amount_mismatch(journal_entry_name: str, reference_number: str, total_debit, expected_amount):
    """One Error Log row per draft (and edit) per 24h: discovery runs on every redelivery and sweep."""
    from verenigingen.verenigingen_payments.utils.webhook_ack import first_in_window

    modified = frappe.db.get_value("Journal Entry", journal_entry_name, "modified")
    if not first_in_window(f"je_draft_amount_mismatch:{journal_entry_name}:{modified}", 86400):
        return
    payment = flt(expected_amount, 2) if expected_amount else "unknown"
    frappe.log_error(
        title="Journal Entry Draft Amount Mismatch",
        message=f"Draft Journal Entry {journal_entry_name} (reference {reference_number}) totals "
        f"{total_debit} but the payment is {payment}, so it was NOT submitted. "
        "It still claims the reference; correct or delete it by hand.",
    )


def _resubmit_stranded_draft(journal_entry_name: str, reference_number: str) -> None:
    from verenigingen.utils.secure_operations import secure_document_operation

    je = frappe.get_doc("Journal Entry", journal_entry_name)
    result = secure_document_operation(
        operation="submit",
        doc=je,
        justification=f"Resubmit stranded draft Journal Entry {journal_entry_name} ({reference_number})",
        required_permissions=["Journal Entry:submit"],
        allow_system_user=True,
    )
    if result.success:
        return
    error_message = ", ".join(result.errors) if result.errors else "Unknown error"
    if result.partial_write:
        discard_unposted_journal_entry(
            journal_entry_name, subject=f"stranded draft for {reference_number}", error_message=error_message
        )
        return
    frappe.log_error(
        title="Journal Entry Draft Resubmit Error",
        message=f"Draft Journal Entry {journal_entry_name} (reference {reference_number}) could not be "
        f"submitted and is still a draft, so this booking is still not on the ledger: {error_message}",
    )


def discard_unposted_journal_entry(journal_entry_name: str, subject: str, error_message: str) -> None:
    """Undo a Journal Entry whose submit failed. Always returns None.

    The entry is **not** a draft. ``Document.save()`` runs ``db_update()`` before
    ``run_post_save_methods()``, and ``on_submit`` is what posts to the ledger, so
    a submit that throws leaves ``docstatus = 1`` already written and
    ``secure_document_operation`` catches the error without rolling back. ERPNext
    validates each GL row in ``GLEntry.on_update``, i.e. *after* inserting it, so
    the ledger can be left one-sided.

    That matters beyond a wrong status code: the reversal-key lookups count
    anything at ``docstatus != 2``, so left in place the unposted entry claims the
    key and every redelivery answers "already processed" -- the reversal reported
    done, permanently, having never reached the ledger.

    **Cancelled, not deleted.** Cancelling is what frees the key, and it leaves an
    auditable record of a posting that was attempted and failed. Deleting is worse
    in both directions: when ``cancel()`` itself raises -- which it does in the
    case this is most likely to see, a bad account, because ``on_cancel`` re-posts
    the reversal GL row into the same validation -- the delete never runs anyway;
    and when it does run, ``Accounts Settings.delete_linked_ledger_entries``
    defaults to 0, so the GL rows survive their voucher as orphans.

    Args:
        journal_entry_name: the entry to undo.
        subject: what the entry was about, for the operator reading the log.
        error_message: why the submit failed.
    """
    message = (
        f"Journal Entry {journal_entry_name} for {subject} could not be submitted and did not "
        f"post to the ledger: {error_message}"
    )
    frappe.logger().error(message)
    frappe.log_error(title="Mollie Journal Entry Not Posted", message=message)

    try:
        je = frappe.get_doc("Journal Entry", journal_entry_name)
        if je.docstatus == 1:
            je.cancel()
    except Exception as cleanup_error:  # failed-write-ok: reported-elsewhere
        frappe.logger().error(
            f"Could not cancel unposted Journal Entry {journal_entry_name}: {cleanup_error}"
        )

    # Report what is actually true, which is not always what was attempted:
    # ``cancel()`` can raise and STILL leave docstatus=2 behind, by the same
    # write-before-hooks ordering described above. Only a re-read can tell the
    # operator whether the key is free.
    docstatus = frappe.db.get_value("Journal Entry", journal_entry_name, "docstatus")
    if docstatus != 2:
        frappe.log_error(
            title="Mollie Journal Entry Still Claims Its Key",
            message=f"Unposted Journal Entry {journal_entry_name} is at docstatus={docstatus} and still "
            f"claims reference {frappe.db.get_value('Journal Entry', journal_entry_name, 'cheque_no')!r}. "
            f"Redeliveries will report it as already processed. Cancel it by hand.",
        )
    return None


def reconcile_bank_transaction_with_journal_entry(
    bank_transaction_name: str, journal_entry_name: str, amount: float
) -> None:
    """Link a bank line to the Journal Entry that booked it, and close it if covered.

    The "is it covered?" test is against whichever side the line actually carries.
    A deposit-only test read ``total_allocated >= flt(bt.deposit or 0)``, which on a
    withdrawal line is ``>= 0`` -- true before anything is allocated -- so the two
    copies of this helper had to disagree about which field to read. One rule
    covers both, and refuses to call a line with no amount on either side
    reconciled.
    """
    try:
        bt = frappe.get_doc("Bank Transaction", bank_transaction_name)

        already_linked = next(
            (row for row in bt.payment_entries if row.payment_entry == journal_entry_name), None
        )
        if already_linked:
            frappe.logger().info(
                f"Bank Transaction {bank_transaction_name} already linked to {journal_entry_name}"
            )
            return

        bt.append(
            "payment_entries",
            {
                "payment_document": "Journal Entry",
                "payment_entry": journal_entry_name,
                "allocated_amount": flt(amount),
            },
        )

        total_allocated = sum(flt(row.allocated_amount) for row in bt.payment_entries)
        line_amount = flt(bt.deposit or 0) or flt(bt.withdrawal or 0)
        bt.save()
        if line_amount and total_allocated >= line_amount:
            record_pool_outcome(bt, RECONCILED)
        frappe.db.commit()

        frappe.logger().info(
            f"Reconciled Bank Transaction {bank_transaction_name} with Journal Entry {journal_entry_name}"
        )
    except Exception as e:
        # Not raised: the money is already posted, and failing here would undo
        # nothing while reporting the booking as unbooked. Reported instead --
        # this used to be logged only through frappe.logger(), which CI never
        # surfaces (CLAUDE.md's logger trap).
        frappe.logger().error(f"Failed to reconcile Bank Transaction {bank_transaction_name}: {e}")
        frappe.log_error(
            title="Mollie Bank Transaction Reconciliation Failed",
            message=f"Journal Entry {journal_entry_name} posted but its Bank Transaction "
            f"{bank_transaction_name} could not be reconciled: {e}",
        )
