# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Add a dedicated Critical Operation Rule for verenigingen_payments.hooks.api's
guest-reachable initiate_payment endpoint (#1048).

initiate_payment shipped with no rule of its own, so it silently inherited
_generic_api_fallback's 100/hour per_user default. For a Guest caller
frappe.session.user is the literal string "Guest", so that scope collapses
into ONE shared bucket for every anonymous visitor on the site -- a weak
brake on ownership-email guessing (see the check added alongside this patch)
and a live DoS vector shared by every legitimate caller of the endpoint. This
patch seeds a per_ip-scoped rule from the fixture file, matching the pattern
already used for donate.py's retry_payment (see
add_retry_payment_critical_operation_rule.py).
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
