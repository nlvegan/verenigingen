"""
Payment Entry Creation Service

Unified payment entry creation service that consolidates duplicate logic from:
- batch_processing_service._create_payment_entry_for_invoice()
- direct_debit_batch.create_payment_entry_for_invoice()
- sepa_reconciliation.create_payment_entry_from_transaction()

This service provides standardized payment entry creation with:
- Explicit permission checking before database operations
- Proper exception handling (fail-fast for financial operations)
- Input validation (amount, invoice existence)
- Optional graceful degradation to draft entries

Gateway payments (Mollie, Ponto, ING) are supported via `bank_account` and `remarks`;
the four hand-rolled gateway wrappers are being migrated onto this service so a fix
lands in one place rather than four.

Callers must already hold Payment Entry create/submit and Sales Invoice read; this
service does NOT bypass those checks for anyone. The Mollie webhook meets that by
running as the configured service user (webhook_security.py sets it after signature
verification). Ponto does NOT - its executed-payment branch runs inline under an
allow_guest request - so that path must arrange a permitted identity itself rather than
assume one. Note also that get_service_user() falls back to Administrator when
`Verenigingen Payments Settings.webhook_user` does not resolve -- including when it
names a user that has been DELETED, since the enabled-flag lookup returns None for a
missing user exactly as for a disabled one, so the setting can read as configured
while every gateway silently runs as Administrator. setup_webhook_user now runs on
after_migrate and converges, so a site should not sit in that state; verify with
get_service_user() rather than by eyeballing the setting.

Does NOT handle:
- Unallocated payment entries (this service is invoice-driven by construction)
- Payment plan entries (different pattern - builds from scratch)
- Fee entries (Journal Entry doctype)
- Membership status updates (caller responsibility)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe
from frappe import _

if TYPE_CHECKING:
    from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry


def _suppress_early_payment_discount(payment_entry, allocated_float: float) -> None:
    """Undo any early-payment discount ERPNext applied inside get_payment_entry().

    MUST be handed the ALLOCATION (the ``party_amount`` passed to get_payment_entry),
    never the total cash received. The detection below is an equality test against
    that figure, and pre-discount ``paid_amount`` equals ``party_amount`` and nothing
    else. Hand it the cash on an overpayment and ``paid_amount != cash`` holds with no
    discount anywhere, so it concludes a discount was applied: on the same-currency
    path it then arrives at the right number by accident, and on a currency boundary it
    throws a message about a discount the invoice does not have, refusing cash that has
    already been taken.

    WHY the discount must not apply here. ``amount`` is cash a payment gateway actually
    moved. An early-payment discount is something a customer ELECTS when settling an
    invoice; a webhook saying "X euros arrived" carries no such election. ERPNext,
    however, applies the discount whenever the invoice has a live discounted payment
    term, and computes it from the WHOLE invoice - ``doc.base_grand_total`` in
    ``apply_early_payment_discount`` (payment_entry.py) - not from the amount being paid.
    Every caller here passes a partial figure (``min(amount, outstanding)``), so leaving
    it alone debits the bank or clearing account by ``amount - full_invoice_discount``:
    short of the cash that really arrived, in precisely the account that must reconcile
    against the gateway settlement.

    Two harder failures also become reachable when the discount is left in place:
    ``paid_amount`` can reach 0 or below and trip "Paid Amount is mandatory"
    (``PaymentEntry.validate_mandatory``), and when no ``bank_account`` is passed and the
    company has no default bank/cash account, ``get_payment_entry`` skips the deductions
    row while still reducing ``paid_amount``, so ``on_submit`` throws "Difference Amount
    must be zero".

    Suppressing it means the entry records exactly the cash received against the invoice
    and leaves the remainder outstanding. If the payer is genuinely entitled to a
    discount, that is a credit note, not something to infer from a settlement webhook.

    Detection: pre-discount, ``set_paid_amount_and_received_amount`` returns
    ``abs(outstanding_amount)`` for ``paid_amount`` in BOTH the equal- and
    differing-currency branches, and ``set_grand_total_and_outstanding_amount`` makes
    ``outstanding_amount`` exactly ``party_amount`` (both in payment_entry.py). So
    ``paid_amount`` differing from the requested amount means, and only means, that a
    discount was applied.
    """
    from frappe.utils import flt

    precision = payment_entry.precision("paid_amount") or 2
    if flt(payment_entry.paid_amount, precision) == flt(allocated_float, precision):
        return

    # A discount plus a currency difference cannot be undone by simple arithmetic: the
    # two sides were reduced by different figures (`discount_amount` versus
    # `discount_amount * conversion_rate` in `apply_early_payment_discount`), and the
    # deductions table may also hold exchange gain/loss rows that must survive. Refuse
    # loudly rather than post a plausible-looking wrong number.
    if payment_entry.paid_from_account_currency != payment_entry.paid_to_account_currency:
        frappe.throw(
            _(
                "Invoice {0} carries an early-payment discount and the payment crosses a "
                "currency boundary. Record this payment manually - the service will not "
                "guess the split."
            ).format(payment_entry.references[0].reference_name if payment_entry.references else "")
        )

    # Same currency: paid_amount == received_amount, and every deductions row present at
    # this point was added by the discount (the only other producer,
    # set_exchange_gain_loss, requires the currency difference excluded above).
    payment_entry.set("deductions", [])
    payment_entry.paid_amount = allocated_float
    payment_entry.received_amount = allocated_float


class PaymentEntryCreationService:
    """
    Service for creating payment entries from invoices.

    Provides standardized payment entry creation with permission-aware
    operations, proper error handling, and input validation.
    """

    @staticmethod
    def create_payment_entry_from_invoice(
        invoice_name: str,
        amount: Decimal,
        posting_date: date,
        reference_no: str,
        reference_date: date,
        mode_of_payment: str,
        payment_type: str = "Receive",
        bank_transaction_name: Optional[str] = None,
        allow_draft_on_permission_failure: bool = False,
        custom_fields: Optional[Dict[str, Any]] = None,
        bank_account: Optional[str] = None,
        remarks: Optional[str] = None,
        cash_received: Optional[Decimal] = None,
    ) -> "PaymentEntry":
        """
        Create and submit payment entry from invoice.

        Args:
            invoice_name: Sales Invoice name
            amount: Amount to ALLOCATE to this invoice (must be positive). Callers cap
                    this at the invoice's outstanding themselves; ERPNext rejects a
                    reference row above outstanding, so passing more throws - which is
                    the intended, loud outcome for callers whose amount is not known to
                    belong to this invoice (bank reconciliation matches an invoice
                    number found in a description, with no amount check at all).
            posting_date: Posting date for payment entry
            reference_no: Payment reference number
            reference_date: Reference date for payment
            mode_of_payment: Payment method (SEPA Direct Debit, Bank Transfer, etc.)
            payment_type: Payment type (Receive/Pay), default "Receive"
            bank_transaction_name: Optional link to Bank Transaction for reconciliation
            allow_draft_on_permission_failure: If True, return draft entry if user lacks
                                               submit permission (for reconciliation workflows)
            custom_fields: Optional dict of custom field names to values to set on payment entry
                          (e.g., {"custom_sepa_batch": "BATCH-001"}). Unknown field names
                          THROW - see the loop below for why - so every name here must be
                          a real Payment Entry field.
            bank_account: Optional GL account the money lands in (a gateway clearing
                          account such as Mollie clearing, Ponto bank or ING). Passed
                          through to ERPNext, which derives paid_to/paid_from and the
                          matching account currency from it. Defaults to the company's
                          bank/cash account when omitted.
            remarks: Optional remarks text. Sets custom_remarks so Payment Entry.validate()
                     does not regenerate it. Omit to keep ERPNext's generated text.
            cash_received: Total cash the gateway actually moved, when it EXCEEDS
                     `amount`. Opt-in, and defaults to `amount` (behaviour unchanged).
                     Supplied, the entry records the full cash: `amount` still settles
                     the invoice and the excess lands in `unallocated_amount` as a
                     credit on the customer, applicable to another invoice via
                     Payment Reconciliation.

                     WHY THIS IS OPT-IN rather than simply reinterpreting `amount`.
                     Most callers pass a figure they know belongs to this invoice, and
                     for them "more than outstanding" is a bug that must keep throwing.
                     bank_transaction_reconciliation.create_payment_entry_from_transaction
                     passes a whole bank deposit against a single invoice matched by an
                     invoice number appearing in the description, with no amount check.
                     Under a blanket reinterpretation it would silently post the excess
                     as a credit and stamp the Bank Transaction "Reconciled", replacing
                     an error an operator sees with a number nobody does. Only callers
                     whose cash figure is authoritative - a gateway settling into a
                     clearing account that must reconcile against a settlement file -
                     should opt in.

        Returns:
            PaymentEntry: Created and submitted Payment Entry document
                         (or draft if allow_draft_on_permission_failure=True and lacking permission)

        Raises:
            frappe.DoesNotExistError: If invoice doesn't exist
            frappe.ValidationError: If amount is invalid (negative, zero)
            frappe.PermissionError: If user lacks create permission, or lacks submit permission
                                   in strict mode (allow_draft_on_permission_failure=False)

        Examples:
            # Standard batch processing (strict mode - must submit)
            from verenigingen.verenigingen_payments.services.payment import payment_entry_service

            payment_entry = payment_entry_service.create_payment_entry_from_invoice(
                invoice_name="SI-2024-001",
                amount=Decimal("50.00"),
                posting_date=date.today(),
                reference_no="BATCH-001",
                reference_date=date.today(),
                mode_of_payment="SEPA Direct Debit"
            )
            # Returns: submitted Payment Entry or raises exception

            # Bank reconciliation (graceful degradation)
            payment_entry = payment_entry_service.create_payment_entry_from_invoice(
                invoice_name="SI-2024-001",
                amount=Decimal("50.00"),
                posting_date=transaction_date,
                reference_no=bank_trans.reference_number,
                reference_date=transaction_date,
                mode_of_payment="SEPA Direct Debit",
                bank_transaction_name=bank_trans.name,
                allow_draft_on_permission_failure=True  # Can return draft
            )
            # Returns: submitted Payment Entry, or draft if lacking submit permission, or raises

            # SEPA reconciliation with custom fields
            payment_entry = payment_entry_service.create_payment_entry_from_invoice(
                invoice_name="SI-2024-001",
                amount=Decimal("50.00"),
                posting_date=transaction_date,
                reference_no=bank_trans.reference_number,
                reference_date=transaction_date,
                mode_of_payment="SEPA Direct Debit",
                custom_fields={
                    "custom_bank_transaction": bank_trans.name,
                    "custom_sepa_batch": batch.name,
                }
            )
        """
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        # Validate amount
        if amount <= Decimal("0"):
            frappe.throw(_("Payment amount must be greater than zero. Got: {0}").format(amount))

        # cash_received below the allocation would settle the invoice with money that
        # never arrived. ERPNext DOES catch it - set_difference_amount() computes
        # base_total_allocated + base_unallocated - base_received, and on_submit refuses a
        # non-zero difference, so a 20 payment allocated 50 dies on "Difference Amount
        # must be zero". This guard exists to fail at input validation with a message
        # naming the two figures and the invoice, rather than after the document has been
        # built and submitted, where the operator is left to work backwards from an
        # arithmetic complaint to a caller that passed the wrong pair.
        if cash_received is not None and cash_received < amount:
            frappe.throw(
                _(
                    "Cash received ({0}) cannot be less than the amount allocated to invoice {1} ({2})."
                ).format(cash_received, invoice_name, amount)
            )

        # Validate invoice exists
        if not frappe.db.exists("Sales Invoice", invoice_name):
            frappe.throw(_("Sales Invoice {0} does not exist").format(invoice_name))

        # Check permissions BEFORE starting any database operations
        if not frappe.has_permission("Payment Entry", "create"):
            frappe.throw(
                _("Insufficient permissions to create payment entry"),
                frappe.PermissionError,
            )

        # Check submit permission for strict mode
        if not allow_draft_on_permission_failure:
            # In strict mode, we need submit permission upfront
            # Check on doctype level first (more efficient)
            if not frappe.has_permission("Payment Entry", "submit"):
                frappe.throw(
                    _("Insufficient permissions to submit payment entry"),
                    frappe.PermissionError,
                )

        try:
            # Get the invoice
            invoice = frappe.get_doc("Sales Invoice", invoice_name)

            # Convert Decimal to float for ERPNext API compatibility
            amount_float = float(amount)

            # Create payment entry using ERPNext's standard function
            # This auto-populates accounts, party information, and references.
            # bank_account is passed THROUGH rather than assigned afterwards: ERPNext
            # derives paid_to/paid_from *and* the matching account currency together from
            # the account get_payment_entry() resolves here, so a post-hoc assignment
            # would move the account and leave the currency behind.
            # payment_type and reference_date are passed IN rather than assigned after.
            # get_payment_entry() derives paid_from/paid_to from payment_type and only
            # falls back to set_payment_type() when
            # the argument is None, so assigning it afterwards left the accounts derived
            # from ERPNext's guess: for an invoice with outstanding <= 0 that guess is
            # "Pay", which puts the bank account on paid_from, and forcing "Receive" over
            # it inverted the posting. reference_date decides early-payment discount
            # eligibility (`reference_date <= term.discount_date`), which was previously
            # evaluated against getdate(None) - today - rather than the caller's date,
            # so a replayed historical payment was judged against the wrong day.
            payment_entry = get_payment_entry(
                dt="Sales Invoice",
                dn=invoice.name,
                party_amount=amount_float,
                bank_account=bank_account,
                payment_type=payment_type,
                reference_date=reference_date,
            )

            # Handed the ALLOCATION, never cash_received - see the helper's docstring.
            _suppress_early_payment_discount(payment_entry, amount_float)

            # Record the full cash when the caller opted in and it exceeds what this
            # invoice can absorb. ERPNext derives the rest: set_unallocated_amount()
            # gives `paid - allocated`, and set_difference_amount() then nets
            # `(allocated + unallocated) - received` to zero, so the entry submits and
            # posts TWO debtors credits - the allocation against the invoice, and the
            # remainder with no against_voucher, which is the canonical unreconciled
            # advance. They cannot merge: get_merge_properties() keys on
            # against_voucher (general_ledger.py), so the invoice is never silently
            # cleared for the full cash.
            if cash_received is not None and cash_received > amount:
                # Same refusal as the discount path above, for the same reason: across a
                # currency boundary set_received_amount() does NOT normalise the two
                # sides, so assigning the gateway's single figure to both makes
                # set_exchange_gain_loss() book the mismatch as a deductions row.
                # difference_amount still nets to zero and the entry SUBMITS, debiting
                # the clearing account a converted figure for unconverted cash. A
                # settlement webhook reports one number and nothing says which side of
                # the boundary it belongs to, so guessing is not available.
                if payment_entry.paid_from_account_currency != payment_entry.paid_to_account_currency:
                    frappe.throw(
                        _(
                            "Payment for invoice {0} exceeds the outstanding amount and crosses a "
                            "currency boundary. Record this payment manually - the service will not "
                            "guess the split."
                        ).format(invoice_name)
                    )

                payment_entry.paid_amount = float(cash_received)
                payment_entry.received_amount = float(cash_received)

            # Set payment details
            payment_entry.payment_type = payment_type
            payment_entry.mode_of_payment = mode_of_payment
            payment_entry.reference_no = reference_no
            payment_entry.reference_date = reference_date
            payment_entry.posting_date = posting_date

            # Gateway callers supply their own remarks (payment id, orphan banner,
            # payment-link name); otherwise keep the text ERPNext generated.
            # custom_remarks MUST be set alongside: Payment Entry.validate() calls
            # set_remarks(), which regenerates the field from the amount/party and
            # returns early only when custom_remarks is truthy. Assigning remarks alone
            # is silently discarded on save.
            if remarks:
                payment_entry.remarks = remarks
                payment_entry.custom_remarks = 1

            # paid_amount/received_amount are re-assigned above ONLY on the opt-in
            # cash_received path, and are otherwise deliberately left alone.
            #
            # get_payment_entry() already derives both from party_amount:
            # set_grand_total_and_outstanding_amount() sets outstanding_amount =
            # party_amount and set_paid_amount_and_received_amount() returns
            # abs(outstanding_amount) for both, so on the ordinary path an assignment
            # here is a no-op.
            #
            # Where it is NOT a no-op it corrupted the posting. ERPNext lowers both amounts
            # for an early-payment discount and books the difference as a `deductions` row;
            # re-asserting the gross amount afterwards does not throw, as one might expect.
            # set_unallocated_amount() tests
            # `base_total_allocated < base_paid_amount + deductions_to_consider`
            # -> `A < A + D` -> true, so it silently absorbed the
            # discount into unallocated_amount and difference_amount still netted to zero.
            # The entry submitted and posted a debtors credit of A + D - a credit the
            # customer never paid for.
            #
            # Any early-payment discount ERPNext would apply is suppressed instead - see
            # _suppress_early_payment_discount, called above.
            # Regression tests: test_early_payment_discount_is_not_overwritten and
            # test_partial_payment_against_discounted_invoice_records_full_cash.

            # Link to bank transaction if provided (for reconciliation path).
            # The field is custom_bank_transaction (added by this app); ERPNext's Payment
            # Entry has no `bank_transaction` field, so the previous assignment was dropped
            # by get_valid_dict() on insert and the link was never stored.
            #
            # Note this does NOT affect api/sepa_duplicate_prevention.py: its query filters
            # on `custom_sepa_batch`, which no caller of this service sets, so no
            # service-created entry has ever been in scope for that guard. It DOES mean a
            # submitted Payment Entry now back-links the Bank Transaction through a Link
            # field, so cancelling a reconciled Bank Transaction raises LinkExistsError
            # (BankTransaction.on_cancel only exempts GL Entry). Deletion is unaffected
            # where force=True, which covers every delete site in this app.
            if bank_transaction_name:
                payment_entry.custom_bank_transaction = bank_transaction_name

            # Apply custom fields if provided (for SEPA batch tracking, etc.)
            if custom_fields:
                for field_name, field_value in custom_fields.items():
                    # Throw rather than warn. This is a money path, and the caller asked
                    # for a field to be recorded on the entry: a typo or a renamed custom
                    # field previously vanished into frappe.logger(), leaving a submitted
                    # Payment Entry silently missing the link (custom_member, the SEPA
                    # batch reference) that a later reconciliation or dedup query relies
                    # on to find it. Failing here is recoverable; a payment nobody can
                    # trace back is not.
                    if not hasattr(payment_entry, field_name):
                        frappe.throw(
                            _("Custom field '{0}' does not exist on Payment Entry.").format(field_name)
                        )
                    setattr(payment_entry, field_name, field_value)

            # insert() and submit() are one unit. The permission checks above answer
            # "may this user submit this DOCTYPE?", which is all that can be asked before
            # the document exists; they cannot see the document-level reasons a submit
            # throws (frozen account, closed period, a validation that only runs on
            # submit). Those fail BETWEEN the two calls, and Frappe takes no savepoint of
            # its own - Document._save() writes docstatus=1 via db_update() before
            # run_post_save_methods() - so the row survives as docstatus=1 with no GL
            # entries. Three of the four gateways swallow the exception, so that row then
            # persists and satisfies the very dedup guards meant to force a retry.
            from verenigingen.utils.transaction_errors import (
                insert_and_submit_atomically,
                submit_atomically,
            )

            # Try to submit
            # In strict mode, we already checked permission above
            # In graceful mode, we check instance-level permission here
            if allow_draft_on_permission_failure:
                # Insert first: the instance-level check below is about THIS document.
                # A draft left behind here is a legitimate outcome, so only the submit
                # needs to be undoable.
                payment_entry.insert()
                if frappe.has_permission("Payment Entry", "submit", payment_entry):
                    submit_atomically(payment_entry)
                    frappe.logger().info(
                        f"Created and submitted payment entry {payment_entry.name} for invoice {invoice_name}"
                    )
                else:
                    # Graceful degradation - return draft for manual review
                    frappe.logger().warning(
                        f"User {frappe.session.user} created draft payment entry {payment_entry.name} "
                        f"for invoice {invoice_name} - lacks submit permission. Manual review required."
                    )
            else:
                # Strict mode - permission already validated, so insert and submit
                # together and leave nothing behind if the submit throws.
                insert_and_submit_atomically(payment_entry)
                frappe.logger().info(
                    f"Created and submitted payment entry {payment_entry.name} for invoice {invoice_name}"
                )

            return payment_entry

        except frappe.PermissionError:
            # Re-raise permission errors as-is (security boundary)
            raise

        except frappe.ValidationError as e:
            # ERPNext raises ValidationError for both:
            # 1. Business rule violations (currency mismatch, account config)
            # 2. Data validation (party doesn't exist, etc.)
            #
            # Distinguish by checking error message for setup/config keywords
            error_msg = str(e).lower()

            # Setup/configuration errors - likely need admin intervention
            setup_keywords = [
                "account",
                "currency",
                "does not exist",
                "not permitted",
                "is mandatory",
                "must be",
            ]

            if any(keyword in error_msg for keyword in setup_keywords):
                # Log as configuration error for admin visibility
                frappe.log_error(
                    f"Payment entry configuration error for invoice {invoice_name}: {str(e)}\n"
                    f"This may indicate missing account setup, currency mismatch, or party configuration issues.",
                    "Payment Entry Configuration Error",
                )
                # Re-raise with additional context for admins
                frappe.throw(
                    _(
                        "Payment entry creation failed due to system configuration: {0}\n\n"
                        "Please check account setup, currency configuration, and party settings."
                    ).format(str(e)),
                    frappe.ValidationError,
                )
            else:
                # Business rule violation or data issue - re-raise as-is
                # These are typically user-correctable (e.g., duplicate entry, invalid state)
                raise

        except Exception as e:
            # Unexpected errors (framework issues, database errors, etc.)
            # These are rare and indicate serious problems
            # Keyword args, and the traceback explicitly. Passed positionally, the
            # message lands in `title` and gets truncated, and frappe's auto-swap
            # heuristic does not rescue it: error.py only swaps the two when the title
            # contains a newline, and this message has none. The traceback must be
            # added by hand for the same reason - log_error only captures one when it
            # is given no message at all.
            frappe.log_error(
                title="Payment Entry Unexpected Error",
                message=(
                    f"Unexpected error creating payment entry for invoice {invoice_name}: "
                    f"{str(e)}\n\n{frappe.get_traceback(with_context=True)}"
                ),
            )
            frappe.throw(
                _(
                    "An unexpected error occurred while creating payment entry for invoice {0}. "
                    "Please contact system administrator."
                ).format(invoice_name),
                exc=e,
            )


# Singleton instance for convenience
payment_entry_service = PaymentEntryCreationService()
