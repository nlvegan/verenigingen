"""Shared Account / Journal Entry builders for tests (#788, #789).

`_make_account` already exists in 14 files and the duplicate-helper ratchet marks it a
clone family at 27% near-identical pairs. The two copies the #788/#789 fix originally
added were rejected by the CI gate:

    Clone-family copies grew from 553 to 554 without a validator change.
    A near-identical helper was recorded into the baseline instead of consolidated.

The gate is right, so these live here instead. This does NOT converge the 12 pre-existing
copies -- that is #401's consolidation work and would bury a 3-line production fix in a
tree-wide refactor. It only stops this change adding to the pile.

The signature is the union of the two copies it replaces: get-or-create by full name
(from the e_boekhouden copy) and an unconditional leaf under a matching-root group parent
(from the period-closing copy). Neither tracked its documents identically, so tracking is
left to the caller -- `track_doc` belongs to the TestCase, not to a free function.
"""

import frappe
from frappe.utils import today


def make_leaf_account(company, abbr, account_name, *, account_type="", root_type="Asset", is_group=0):
    """Get-or-create an Account under the group parent matching `root_type`.

    Returns the Account name. `account_type` is applied only when truthy: "" is a real,
    valid state for an Account (it means "no specific type"), and assigning it explicitly
    is not the same as leaving it unset -- which is the distinction #788 turned on.
    """
    full_name = f"{account_name} - {abbr}"
    if frappe.db.exists("Account", full_name):
        return full_name

    parent = frappe.db.get_value(
        "Account", {"company": company, "root_type": root_type, "is_group": 1}, "name"
    )
    if not parent:
        # Loud, because the usual cause is the shared test company having been drained by
        # an earlier class in the same shard -- a failure that is otherwise reported as an
        # unrelated mandatory-field error on insert.
        raise RuntimeError(
            f"no is_group root_type={root_type!r} Account on company {company!r} "
            f"to parent {account_name!r} under"
        )

    doc = frappe.new_doc("Account")
    doc.account_name = account_name
    doc.company = company
    doc.parent_account = parent
    doc.root_type = root_type
    if account_type:
        doc.account_type = account_type
    doc.is_group = is_group
    doc.insert(ignore_permissions=True)
    return doc.name


def make_submitted_journal_entry(company, debit_account, credit_account, amount, posting_date=None):
    """Submit a balanced two-line Journal Entry. Returns the document.

    Submitted, not draft: a draft Journal Entry writes no GL Entry, so any test asserting
    on a ledger scan would pass against an empty result for the wrong reason.
    """
    entry = frappe.new_doc("Journal Entry")
    entry.company = company
    entry.posting_date = posting_date or today()
    entry.append(
        "accounts",
        {"account": debit_account, "debit_in_account_currency": amount, "credit_in_account_currency": 0},
    )
    entry.append(
        "accounts",
        {"account": credit_account, "debit_in_account_currency": 0, "credit_in_account_currency": amount},
    )
    entry.insert(ignore_permissions=True)
    entry.submit()
    return entry
