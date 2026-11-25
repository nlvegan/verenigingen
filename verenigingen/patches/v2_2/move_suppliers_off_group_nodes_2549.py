"""Move Suppliers off Supplier Group nodes into the leaf "Unsorted" (#2549, ruling on #2550).

erpnext version-16 refuses to save a Supplier whose Supplier Group is a group node, so every
Supplier the eBoekhouden paths filed under the root "All Supplier Groups" became un-editable
(725 on veg11). The target is the leaf "Unsorted", created here when absent. Suppliers with no
group, or in a leaf, are not touched. Idempotent. A plain UPDATE, not a save: the save is exactly
what v16 refuses, and ``modified`` is left alone so the move is not shown as a user edit.
"""

import frappe

from verenigingen.services.supplier_group_resolver import ensure_unsorted_supplier_group


def execute():
    unsorted = ensure_unsorted_supplier_group()
    frappe.db.sql(
        """
        UPDATE `tabSupplier`
        SET supplier_group = %s
        WHERE supplier_group IN (SELECT name FROM `tabSupplier Group` WHERE is_group = 1)
        """,
        unsorted,
    )
