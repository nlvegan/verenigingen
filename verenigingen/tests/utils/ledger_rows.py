"""The ledger rows a voucher leaves behind, and what to do about them.

`GL Entry` and `Payment Ledger Entry` key to their parent by
`(voucher_type, voucher_no)` and are NOT removed when that parent is deleted. Both test
bases have to know that, and neither can inherit the other's teardown -- they are
siblings, both deriving from the compat `FrappeTestCase`. So the knowledge lives here
rather than being stated twice and diverging, which is what #482 was.

Deliberately data-driven rather than a list of voucher doctypes: the set of things that
post to the ledger grows with every erpnext release, and a stale allowlist fails open --
silently stranding rows again.
"""

import frappe

LEDGER_DOCTYPES = ("GL Entry", "Payment Ledger Entry")


def has_ledger_rows(doctype, name):
    """True when deleting this document would strand ledger rows behind it."""
    return any(
        frappe.db.exists(ledger, {"voucher_type": doctype, "voucher_no": name})
        for ledger in LEDGER_DOCTYPES
    )


def purge_ledger_rows(doctype, name):
    """Remove the ledger rows `delete_doc` left behind for a deleted voucher.

    Call ONLY once that voucher's own row is gone, so there is no live parent left for
    these to belong to. Leaving them is not neutral: `delete_doc` calls
    `revert_series_if_last()`, so the naming series rewinds and hands the name to the
    next voucher, which is then born owning rows it never posted. Measured on
    test_site_3 -- two identical runs of one probe, and the second invoice took the
    first one's docname and read 4 GL / 2 PLE at the moment it posted.

    Returns the number of rows removed, so a caller can report what it swept.
    """
    removed = 0
    for ledger in LEDGER_DOCTYPES:
        rows = frappe.get_all(
            ledger, filters={"voucher_type": doctype, "voucher_no": name}, pluck="name"
        )
        for row in rows:
            frappe.db.delete(ledger, {"name": row})
            removed += 1
    return removed
