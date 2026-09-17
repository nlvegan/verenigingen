"""The rows a deleted Company leaves behind, and what to do about them.

hrms `version-16` hooks `Company.on_update` to `set_expense_claim_type_accounts`,
which appends an `Expense Claim Account` child row -- carrying `company` and
`default_account` -- to EVERY `Expense Claim Type`. Nothing removes it when the
Company goes: erpnext's `Company.on_trash` never mentions Expense Claim, and
hrms's own `handle_linked_docs` deletes only the nine doctypes listed in its
`company_data_to_be_ignored` hook, which does not include this one.

So a `force=True` delete -- which is what both drains do -- leaves rows whose
`company` and `default_account` both dangle. They are not inert: the next Company
insert in the same process runs the same hrms hook, which saves the Expense Claim
Type, and `_validate_links` then walks the stranded rows and raises

    LinkValidationError: Could not find Row #29: Company: <dead company>,
                         Row #29: Default Account: Expense Claims - <dead abbr>

erroring `setUpClass` for classes that never touched the module responsible. That
is #1150 (one instance, fixed in its own teardown) and #1154 (the class).

Sibling of `ledger_rows`, and deliberately NOT built the same way. That one is
data-driven because the set of doctypes posting to the ledger grows with every
erpnext release and a stale allowlist would fail open. Here the set was MEASURED:
all 190 doctypes carrying a `company` Link field were counted across a real
force-delete of a chart-bearing Company --

    before: Account 97, Cost Center 2, Department 13, Expense Claim Account 5,
            Item Tax Template 2, Mode of Payment Account 1,
            Purchase Taxes and Charges Template 2,
            Sales Taxes and Charges Template 2, Warehouse 5
    after:  {'Expense Claim Account': 5}

-- exactly one survivor. Scanning all 190 on every drained Company would cost 190
queries per company to rediscover that. The drift risk is real, so the scan lives
in the TEST (`test_no_doctype_retains_rows_for_a_drained_company`), where it runs
once instead of once per teardown and fails loudly if a release adds another.
"""

import frappe

COMPANY_ORPHAN_DOCTYPES = ("Expense Claim Account",)


def company_orphans(company_name):
    """The surviving rows that reference a company, keyed by doctype."""
    found = {}
    for doctype in COMPANY_ORPHAN_DOCTYPES:
        rows = frappe.get_all(doctype, filters={"company": company_name}, pluck="name")
        if rows:
            found[doctype] = rows
    return found


def purge_company_orphans(company_name):
    """Remove the rows a Company delete left behind.

    Call ONLY once that company's own row is gone -- same contract as
    `purge_ledger_rows`, and for the same reason: there is no live parent left for
    these to belong to.

    Deleting child rows directly is what hrms's own `delete_docs_with_company_field`
    does for the doctypes it covers; this is the same move for the one it missed.

    Returns the number of rows removed, so a caller can report what it swept.
    """
    removed = 0
    for doctype, rows in company_orphans(company_name).items():
        frappe.db.delete(doctype, {"name": ("in", rows)})
        removed += len(rows)
    return removed
