"""Permission-aware replacement for `frappe.desk.notifications.get_open_count` (#2889).

Core's connections-tab RPC has two permission gaps, both measured on test_site_1:

1. When the caller passes `items=`, core only uses them as given; they are not limited to
   the doctypes the dashboard of `doctype` offers. `?items=["Donation"]` therefore reaches
   `get_external_links` for any doctype, so any reader of a doc can probe how many records
   of ANY doctype point at it.
2. `get_doc_count` counts with `frappe.get_all`, which ignores the viewer's permissions
   (doctype-level read AND User Permissions). A Staff user without Donation access, or a
   user whose User Permission excludes a donor, still got a real count.

This override (registered in `verenigingen/hooks/whitelisted_methods.py`, consulted at
dispatch only, so internal callers of the core function are untouched):

- keeps only `items` that the dashboard itself offers in `transactions`;
- drops every item the caller cannot read at doctype level;
- counts with `frappe.get_list`, so User Permissions and permission-query conditions apply.

Dropped items are simply absent from the response. An item the dashboard does not offer and
an item the viewer may not read are therefore indistinguishable from each other and from a
nonexistent doctype name: same response shape, no message_log entry, no Error Log row.

The main document is still loaded with `check_permission=True` exactly as in core, so the
unknown-name vs forbidden-name behaviour for `name` itself is core's (not changed here).
"""

import json

import frappe
from frappe.desk import notifications as core
from frappe.utils import unique


@frappe.whitelist()
@frappe.read_only()
def get_open_count(doctype: str, name: str | int, items: str | list[str] | None = None):
    """Same contract as `frappe.desk.notifications.get_open_count`, restricted to what the
    caller may see. See the module docstring."""
    if frappe.flags.in_migrate or frappe.flags.in_install:
        return {"count": []}

    # Same 1s statement ceiling core applies to every count query.
    try:
        with frappe.db.execution_timeout(1):
            return _linked_document_counts(doctype, name, items)
    except Exception as e:
        if frappe.db.is_statement_timeout(e):
            return {"count": []}
        raise


def _linked_document_counts(doctype, name, items):
    doc = frappe.get_lazy_doc(doctype, name, check_permission=True)
    links = doc.meta.get_dashboard_data()
    visible_items = _visible_items(links, items)

    found = {"external_links_found": [], "internal_links_found": []}
    for d in visible_items:
        _collect_item(found, doc, name, links, d)

    out = {"count": found}
    if not doc.meta.custom:
        module = frappe.get_meta_module(doctype)
        if hasattr(module, "get_timeline_data"):
            out["timeline_data"] = module.get_timeline_data(doctype, name)
    return out


def _visible_items(links, items):
    """The dashboard's own items, narrowed to the requested ones, that the caller may read."""
    offered = unique([item for group in links.transactions for item in group.get("items") or []])
    if items is None:
        requested = offered
    else:
        requested = json.loads(items) if not isinstance(items, list) else items
    # Non-strings are dropped first: an unhashable entry must not reach unique()/has_permission.
    requested = [d for d in requested if isinstance(d, str)]
    return [d for d in unique(requested) if d in offered and _can_read(d)]


def _can_read(doctype):
    return bool(frappe.has_permission(doctype, "read"))


def _collect_item(found, doc, name, links, d):
    internal_link = links.get("internal_links", {}).get(d) or links.get(
        "internal_and_external_links", {}
    ).get(d)
    if not internal_link:
        _collect_external(found, name, links, d)
        return
    internal = core.get_internal_links(doc, internal_link, d)
    if internal["count"]:
        found["internal_links_found"].append(internal)
    elif core.has_external_link_field(d, links):
        _collect_external(found, name, links, d)
    else:
        found["external_links_found"].append({"doctype": d, "open_count": 0, "count": 0})


def _collect_external(found, name, links, d):
    for fieldname in core.get_external_link_fieldnames(d, links):
        found["external_links_found"].append(_external_links(d, name, links, fieldname))


def _external_links(doctype, name, links, fieldname=None):
    fieldname = fieldname or core.get_external_link_fieldname(doctype, links)
    filters = core.get_dynamic_link_filters(doctype, links, fieldname) or {}

    child_doctypes = core.get_child_doctypes_with_field(doctype, fieldname)
    if len(child_doctypes) > 1:
        # Core's own helper already lists names with get_list (permission-aware); its
        # open_count is taken over those names only, so it cannot widen the result.
        return core.get_external_links_in_child_tables(doctype, name, fieldname, child_doctypes, filters)

    filters[fieldname] = name
    total_count = _permitted_count(doctype, filters)

    open_count = 0
    if open_count_filters := core.get_filters_for(doctype):
        filters.update(open_count_filters)
        open_count = _permitted_count(doctype, filters)

    return {"doctype": doctype, "fieldname": fieldname, "count": total_count, "open_count": open_count}


def _permitted_count(doctype, filters):
    try:
        return len(
            frappe.get_list(
                doctype, filters=filters, limit=100, distinct=True, ignore_ifnull=True, order_by=None
            )
        )
    except Exception as e:
        if frappe.db.is_statement_timeout(e):  # same as core: too slow to count exactly
            return "?"
        raise
