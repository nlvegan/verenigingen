# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Add Critical Operation Rules for the Mollie member-portal self-service endpoints.

get_subscription_details, update_mollie_bank_account and cancel_specific_subscription
ship without rules, so using them on the payment dashboard surfaces
"Critical Operation Rule ... not found" messages to the member (the API security
framework probes three naming variants per function and frappe.get_doc leaks the
not-found message into the response). This patch seeds sensible defaults for all
nine variants from the fixture file.
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
