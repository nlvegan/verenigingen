"""Supplier Group selection for Suppliers this app creates."""

import frappe


def resolve_non_group_supplier_group() -> str | None:
    """Return a non-group Supplier Group name for a new Supplier, or None.

    ERPNext version-16 rejects a Supplier whose Supplier Group has
    ``is_group=1`` ("Cannot select a Group type Supplier Group", erpnext
    96e0a3b011, the Supplier twin of the long-standing Customer rule), so the
    root "All Supplier Groups" may never be assigned. Unlike Customer Group,
    Supplier Group is optional, so when no leaf exists this returns None and
    the Supplier is created without one instead of failing.

    The Buying Settings default is accepted only when it still exists and is a
    leaf: ``get_value`` returns None for a deleted name, so a bare
    ``not is_group`` check would let a stale name through to a Link error.
    """
    configured = frappe.db.get_single_value("Buying Settings", "supplier_group")
    if configured and frappe.db.get_value("Supplier Group", configured, "is_group") == 0:
        return configured

    # order_by name keeps the choice deterministic across sites.
    return frappe.db.get_value("Supplier Group", {"is_group": 0}, "name", order_by="name asc")
