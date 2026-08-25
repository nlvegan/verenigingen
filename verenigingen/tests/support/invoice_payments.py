"""Receive a real payment against a Sales Invoice, so its amount columns DISAGREE.

Two of the #567 call sites read one of those two columns and the choice matters:
comparing an incoming payment against `grand_total` on a Partly Paid invoice
compares it to a number nobody still owes, and allocating `min(payment,
grand_total)` against one over-allocates -- ERPNext throws
"Allocated Amount cannot be greater than outstanding amount"
(`erpnext/accounts/doctype/payment_entry/payment_entry.py:498`, inside
`validate_allocated_amount_with_latest_data` -- the identically-worded check at :377 is
unreachable for a Customer, because `validate_allocated_amount` returns at :373).

A test cannot tell which column was read unless the two differ, so this lives in
one place rather than being re-derived per suite.
"""

import frappe
from frappe.utils import today


def receive_against_invoice(test_case, invoice_name, paid, mode_of_payment=None):
    """Receive `paid` against `invoice_name`.

    `paid` below the outstanding leaves the invoice Partly Paid; `paid` equal to it
    leaves the invoice Paid, which is what the reversal call site
    (`process_individual_return`) needs a candidate set of.

    `mode_of_payment` MATTERS for that caller: `reverse_failed_sepa_payment` only
    cancels a Payment Entry whose `mode_of_payment == "SEPA Direct Debit"`, so a
    fixture that omits it produces a payment the reversal cannot see -- and a test
    asserting "nothing was reversed" then passes for the wrong reason. Pass it.

    Returns `(invoice, payment_entry)`. The Payment Entry comes back because a
    caller whose code-under-test commits (the Mollie subscription path does) has
    that PE committed along with it and must force-clean it in tearDown; without
    the handle it leaks, and the drain then fails on it with "Could not find
    Party" once the Customer has been rolled back. Asserts through `test_case` that the
    fixture really did leave the two columns different -- a silently-failed
    part payment would make the caller's test pass for the wrong reason.

    PROVISIONS the company's default bank account rather than reading one, and FAILS --
    does not skip -- if that still leaves none. Reading was not enough: erpnext's
    `get_default_bank_cash_account` falls back to "the only non-group Bank account" and
    returns `{}` when the company has none or several, and on this bench there is exactly
    one, left behind by `test_bank_transaction_reconciliation`. So this fixture passed
    locally and failed in CI shard 11/12, which packs neither that module nor
    `test_sepa_reconciliation` (whose setUpClass provisions the same account) -- a
    fixture that picks a company and *then* looks for an account inside it is how a test
    comes to prove nothing (2026-08-24c handoff). Four tests depend on this one, and a
    skip is indistinguishable from a pass in a CI summary, so the answer is to guarantee
    the account and keep the failure loud if that is somehow impossible.
    """
    from verenigingen.tests.support.sepa_test_company import ensure_default_gl_bank_account

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    bank_account = ensure_default_gl_bank_account(invoice.company)
    if not bank_account:
        test_case.fail(
            f"{invoice.company} has no default bank account and one could not be "
            f"provisioned, so this fixture cannot receive a payment -- a skipped or "
            f"absent test proves exactly as much as one that never ran."
        )

    payment_entry = frappe.get_doc(
        {
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "company": invoice.company,
            "party_type": "Customer",
            "party": invoice.customer,
            "posting_date": today(),
            "paid_amount": paid,
            "received_amount": paid,
            "paid_from": invoice.debit_to,
            "paid_to": bank_account,
            "paid_from_account_currency": "EUR",
            "paid_to_account_currency": "EUR",
            "source_exchange_rate": 1,
            "target_exchange_rate": 1,
            "reference_no": f"PART-{frappe.generate_hash(length=8)}",
            "reference_date": today(),
            "mode_of_payment": mode_of_payment,
            "references": [
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": invoice.name,
                    "total_amount": invoice.grand_total,
                    "outstanding_amount": invoice.outstanding_amount,
                    "allocated_amount": paid,
                }
            ],
        }
    )
    payment_entry.insert()
    payment_entry.submit()

    invoice.reload()
    test_case.assertNotEqual(
        float(invoice.outstanding_amount),
        float(invoice.grand_total),
        "fixture must actually leave outstanding != grand_total",
    )
    return invoice, payment_entry


def member_with_customer(test_case, first_name):
    """A test Member guaranteed to have a linked Customer.

    `Member.after_insert` auto-creates and links one when the member has an email,
    so this normally just reads it back. Shared rather than copied per suite: two
    near-identical private copies of the same helper is what the duplicate-helper
    ratchet exists to block, and it is where a fix goes to die.
    """
    member = test_case.create_test_member(first_name=first_name)
    member.reload()
    if not member.customer:
        member.create_customer()
        member.reload()
    return member
