# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Customer Group Resolver
=======================

Single source of truth for resolving a non-group Customer Group when creating
a new Customer record. ERPNext's customer form filters the customer_group
link to leaves only (``is_group=0`` filter in ``customer.js``), and the
strict-validation branch of ``customer.py.validate`` likewise rejects a
group-node value at insert time with ``ValidationError: Cannot select a
Group type Customer Group``. (Note: the exact rejection mechanism varies
across ERPNext versions - some only filter client-side, others enforce
server-side. The fix is the same: never pass a group node through.)

The Selling Settings default is often a group node in fresh installs -
and explicitly so in ERPNext's ``set_defaults_for_tests`` hook, which
sets it to the root ``All Customer Groups``.

Every Customer-creation path in the codebase that consulted
``Selling Settings.customer_group`` had the same bug before this helper
existed: pass the Settings value through verbatim, fall back to a string
literal (often ``"Individual"`` or, in several Mollie + eBoekhouden sites,
the guaranteed-broken ``"All Customer Groups"``) when missing. Those bugs
caused 77 test failures in Account Creation CI until commit ``5a4632c2``
(PR #54) fixed the membership-approval path with this helper. This module
extracts and shares the helper so every caller resolves Customer Group the
same safe way.

Use ``resolve_non_group_customer_group()`` whenever you create a Customer
and need a default ``customer_group`` value. The helper:

1. Returns ``Selling Settings.customer_group`` if it points to a leaf
   (``is_group=0``) Customer Group that still exists.
2. Otherwise falls back to ``"Individual"`` if it exists as a leaf.
3. Otherwise returns any leaf Customer Group (deterministic by name).
4. Otherwise throws a clear, translatable error.

The helper performs no Customer write itself - it only resolves a name.
"""

import frappe
from frappe import _


def resolve_non_group_customer_group() -> str:
    """Return a non-group Customer Group name for a new Customer record.

    ERPNext rejects any Customer Group with ``is_group=1`` for a Customer
    (the form filters to leaves; the strict-validation branch of Customer
    server controller likewise throws ``Cannot select a Group type Customer
    Group``). The Selling Settings default is often a group node in fresh
    installs and in test environments - ERPNext's ``set_defaults_for_tests``
    sets it to the root explicitly - so this helper checks ``is_group``
    before passing the Settings value through and falls back to a leaf
    otherwise.

    The Settings default is accepted only when the group still exists:
    ``get_value`` returns ``None`` for a deleted name, and ``not None`` is
    truthy, so a stale name would otherwise pass any naive guard and the
    caller would crash downstream on a Link validation error.
    """
    selling_default = frappe.db.get_single_value("Selling Settings", "customer_group")
    if selling_default:
        is_group = frappe.db.get_value("Customer Group", selling_default, "is_group")
        if is_group == 0:
            return selling_default

    # Prefer "Individual" if it exists as a leaf; otherwise any leaf group.
    # order_by name keeps the choice deterministic across sites.
    leaf = frappe.db.get_value(
        "Customer Group", {"name": "Individual", "is_group": 0}, "name"
    ) or frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="name asc")
    if leaf:
        return leaf

    frappe.throw(
        _(
            "No non-group Customer Group is available. Create a leaf "
            "(is_group=0) Customer Group, or set Selling Settings.customer_group to one."
        )
    )
