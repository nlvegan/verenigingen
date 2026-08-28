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
from frappe.utils import add_days, today


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

    READS the company's bank account; the caller's `setUpClass` must have provisioned
    it, via `get_eur_bank_account` as `ReconBase` and four other suites do. Reading is
    deliberate: provisioning from here would run `frappe.db.commit()` inside a test
    BODY, committing that test's in-flight fixtures -- a submitted Sales Invoice among
    them -- which is what `ReconBase.setUpClass` exists to avoid and says so in as many
    words (`test_sepa_reconciliation.py:97`).

    FAILS -- does not skip -- when that has not happened. This is not hypothetical: it
    is how shard 11/12 of #575 went red. erpnext's `get_default_bank_cash_account`
    resolves `Company.default_bank_account` FIRST and falls back to "the only non-group
    Bank account", so on a bench where an earlier module already stamped that field the
    read succeeds and locally nothing is wrong. In CI it depended on ORDER WITHIN THE
    SHARD -- of the five suites that provision it, only `test_bank_transaction_
    reconciliation` sorts ahead of this fixture's callers, and shard 11 did not pack it.
    A fixture that picks a company and *then* looks for an account inside it is how a
    test comes to prove nothing (2026-08-24c handoff); the answer is to make that loud,
    not to skip.
    """
    from erpnext.accounts.doctype.journal_entry.journal_entry import get_default_bank_cash_account

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    bank = get_default_bank_cash_account(invoice.company, "Bank")
    if not bank or not bank.get("account"):
        test_case.fail(
            f"{invoice.company} has no default bank account, so this fixture cannot "
            f"receive a payment. Provision it rather than skipping -- a skipped test "
            f"proves exactly as much as one that never ran."
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
            "paid_to": bank["account"],
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


def build_eur_membership_invoice(test_case, customer, rate=42.0, posting_date=None):
    """A submitted, v16-valid EUR membership Sales Invoice for `customer`.

    Every field below is mandatory on a v16 Sales Invoice or is there to keep the
    document currency aligned with the receivable account's -- a fresh site's
    selling price list otherwise defaults the invoice to USD and the payment that
    follows cannot allocate against it.

    One helper, three former copies: `_build_test_invoice` on
    `test_payment_entry_hook_defers` and `_build_secured_invoice` on
    `test_integrated_security_payment_system` and
    `test_payment_history_reconciliation`, the last two of which the
    duplicate-helper census already recorded as a 100%-near-identical clone
    family. Their bodies had not yet drifted; what they shared was the
    income-account bug fixed below, in three places at once.
    """
    from verenigingen.tests.support.sepa_test_company import get_eur_test_company

    company = get_eur_test_company()
    test_case._ensure_test_item("TEST-MEMBERSHIP")

    debit_to = frappe.db.get_value("Company", company, "default_receivable_account") or frappe.db.get_value(
        "Account", {"account_type": "Receivable", "company": company, "is_group": 0}, "name"
    )
    # ERPNext's standard chart leaves account_type EMPTY on income leaves; they
    # carry root_type = "Income". So the account_type filter resolves only when
    # some other fixture in the same shard has planted such a row -- hence the
    # fallback, which removes the None case. It does NOT make the choice
    # order-independent: among several income leaves get_value still returns the
    # most recently created one.
    income_account = frappe.db.get_value(
        "Account", {"account_type": "Income Account", "company": company, "is_group": 0}, "name"
    ) or frappe.db.get_value("Account", {"company": company, "root_type": "Income", "is_group": 0}, "name")
    cost_center = frappe.db.get_value("Company", company, "cost_center") or frappe.db.get_value(
        "Cost Center", {"company": company, "is_group": 0}, "name"
    )
    price_list = frappe.db.get_value("Price List", {"selling": 1}, "name") or "Standard Selling"

    invoice = frappe.new_doc("Sales Invoice")
    invoice.customer = customer
    invoice.company = company
    invoice.currency = "EUR"
    invoice.conversion_rate = 1.0
    invoice.debit_to = debit_to
    invoice.selling_price_list = price_list
    invoice.price_list_currency = "EUR"
    invoice.plc_conversion_rate = 1.0
    invoice.ignore_pricing_rule = 1
    invoice.posting_date = posting_date or today()
    invoice.set_posting_time = 1
    invoice.due_date = add_days(invoice.posting_date, 30)
    invoice.is_membership_invoice = 1
    invoice.append(
        "items",
        {
            "item_code": "TEST-MEMBERSHIP",
            "qty": 1,
            "rate": rate,
            "income_account": income_account,
            "cost_center": cost_center,
        },
    )
    invoice.save()
    invoice.submit()
    return invoice
