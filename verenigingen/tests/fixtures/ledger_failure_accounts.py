"""An account that makes a Journal Entry fail AFTER its docstatus is written.

`Document.save()` writes `db_update()` (docstatus=1) before `on_submit` posts
the GL Entries, and each GL Entry is `db_insert`ed before its own `on_update`
validation runs. A rule that only GL Entry's `on_update` enforces therefore
fails a submit after the Journal Entry and that GL row have both landed: the
partial-write shape #385 is about.

A Group Account used to be that trigger. Since ERPNext #59687 (v16.50) the
Journal Entry rejects a group account in `validate`, before anything is
written, so it no longer reaches `on_submit`. `balance_must_be` is still
checked only in `GLEntry.on_update` (`validate_balance_type`), never by the
Journal Entry itself.
"""

import frappe


def make_balance_restricted_account(company, root_type, balance_must_be):
    """Create a fresh ledger account under `company`'s `root_type` root.

    Fresh, so it has no prior balance: the first posting against the wrong
    side (a credit when `balance_must_be="Debit"`) fails `validate_balance_type`.
    """
    parent = frappe.db.get_value(
        "Account",
        {"company": company, "root_type": root_type, "is_group": 1},
        "name",
        order_by="lft",
    )
    account = frappe.get_doc(
        {
            "doctype": "Account",
            "account_name": f"TEST Balance Must Be {balance_must_be} {frappe.generate_hash(length=6)}",
            "parent_account": parent,
            "company": company,
            "is_group": 0,
            "balance_must_be": balance_must_be,
        }
    ).insert(ignore_permissions=True)
    return account.name
