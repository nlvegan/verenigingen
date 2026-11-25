"""Supplier Group selection for Suppliers this app creates."""

import frappe
from frappe import _

UNSORTED_SUPPLIER_GROUP = "Unsorted"
ROOT_SUPPLIER_GROUP = "All Supplier Groups"


def resolve_non_group_supplier_group() -> str:
    """Return a non-group Supplier Group name for a new Supplier.

    ERPNext version-16 rejects a Supplier whose Supplier Group has
    ``is_group=1`` ("Cannot select a Group type Supplier Group", erpnext
    96e0a3b011, the Supplier twin of the long-standing Customer rule), so the
    root "All Supplier Groups" may never be assigned.

    The Buying Settings default is accepted only when it still exists and is a
    leaf: ``get_value`` returns None for a deleted name, so a bare
    ``not is_group`` check would let a stale name through to a Link error.
    Otherwise the Supplier goes to the dedicated leaf "Unsorted" (maintainer
    ruling on #2550). The old fallback, the first leaf by name, put imported
    Suppliers in an arbitrary group, and ERPNext reads payable account and
    payment terms from that group.
    """
    configured = frappe.db.get_single_value("Buying Settings", "supplier_group")
    if configured and frappe.db.get_value("Supplier Group", configured, "is_group") == 0:
        return configured

    return ensure_unsorted_supplier_group()


def ensure_unsorted_supplier_group() -> str:
    """Return the name of the leaf Supplier Group "Unsorted", creating it if absent.

    Idempotent. Does not commit: it runs inside a caller's transaction (a patch,
    or the request that creates a Supplier). Refuses, rather than assigns, an
    "Unsorted" that someone turned into a group node.
    """
    is_group = frappe.db.get_value("Supplier Group", UNSORTED_SUPPLIER_GROUP, "is_group")
    if is_group is None:
        _create_unsorted_supplier_group()
    elif is_group:
        frappe.throw(
            _("Supplier Group {0} is a group node; it must be a leaf to hold Suppliers.").format(
                UNSORTED_SUPPLIER_GROUP
            )
        )
    return UNSORTED_SUPPLIER_GROUP


def _create_unsorted_supplier_group() -> None:
    # Security: system-owned fallback tree nodes; the calling user may lack Supplier Group create.
    if not frappe.db.exists("Supplier Group", ROOT_SUPPLIER_GROUP):
        root = frappe.get_doc(
            {"doctype": "Supplier Group", "supplier_group_name": ROOT_SUPPLIER_GROUP, "is_group": 1}
        )
        root.insert(ignore_permissions=True)  # Security: system-owned root node
    unsorted = frappe.get_doc(
        {
            "doctype": "Supplier Group",
            "supplier_group_name": UNSORTED_SUPPLIER_GROUP,
            "parent_supplier_group": ROOT_SUPPLIER_GROUP,
            "is_group": 0,
        }
    )
    try:
        unsorted.insert(ignore_permissions=True)  # Security: system-owned fallback leaf
    except frappe.DuplicateEntryError:
        # A concurrent request created it first; the next read decides if it is usable.
        pass
