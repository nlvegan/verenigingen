# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Add Critical Operation Rules for ING Checkout feature-flag and Mollie Bulk Run listing endpoints.

These endpoints ship without rules so every page load of the Sales Invoice list
(is_ing_checkout_enabled) and every Mollie Bulk Run history poll
(list_recent_bulk_runs) emits "Critical Operation Rule ... not found" warnings.
The API security framework probes three naming variants per function; this patch
seeds sensible defaults for all six.
"""

import frappe


def execute():
    from verenigingen.setup.critical_operation_rules_setup import (
        add_missing_critical_operation_rules,
    )

    result = add_missing_critical_operation_rules()

    if result["created"] > 0:
        frappe.db.commit()
        print(f"Added {result['created']} missing Critical Operation Rules")
