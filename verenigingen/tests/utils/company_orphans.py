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

**That measurement holds only for a company with NO GL Entry, and the difference
is large.** erpnext gates its whole Account / Cost Center / Budget / Party Account
cleanup on `rec = SELECT name FROM tabGL Entry WHERE company = %s; if not rec:`
(`erpnext/setup/doctype/company/company.py:763`). Measured: the same probe company
with one `tabGL Entry` row present survives its own delete carrying
`{'Cost Center': 2, 'GL Entry': 1}`; without the row, `{}`. On a chart-bearing
company that branch also strands its ~97 Accounts.

Those are deliberately OUT of scope here, and the reason is not squeamishness: a
stranded Account or Cost Center is a standalone document that nothing re-saves, so
it does not reproduce the failure this sweep exists to prevent. `Expense Claim
Account` is different precisely because its rows live inside `Expense Claim Type`
-- a SHARED parent that hrms re-saves on the next Company insert, which is what
turns a dangling link into a `LinkValidationError` in someone else's setUpClass.
Sweeping accounting rows out from under a company that still has ledger entries
would also be a much larger and riskier behaviour change than this fix.
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

    Normally called once that company's own row is gone -- same contract as
    `purge_ledger_rows`, and for the same reason: there is no live parent left for
    these to belong to.

    The e_boekhouden probe teardown deliberately breaks that rule, calling this
    whether or not its delete raised, because a part-completed delete strands the
    same rows as a successful one. That is safe for the narrow reason that these
    rows are re-created by hrms on the company's next `on_update`: sweeping them
    from a company that survives costs a default, not data.

    Deleting child rows directly is what hrms's own `delete_docs_with_company_field`
    does for the doctypes it covers; this is the same move for the one it missed.

    Returns the number of rows removed, so a caller can report what it swept.
    """
    removed = 0
    for doctype, rows in company_orphans(company_name).items():
        frappe.db.delete(doctype, {"name": ("in", rows)})
        removed += len(rows)
    return removed
