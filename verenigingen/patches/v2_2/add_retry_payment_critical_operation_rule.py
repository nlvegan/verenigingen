# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Add a dedicated Critical Operation Rule for donate.py's retry_payment endpoint (#969).

retry_payment shipped without a rule, so it silently inherited
_generic_api_fallback's 100/hour per_user default. For a Guest caller
frappe.session.user is the literal string "Guest", so that scope collapses
into ONE shared bucket for every anonymous visitor on the site: a weak brake
on email-guessing (see the ownership check added in #969) and a live DoS
vector (one abusive client exhausts the budget for every legitimate donor
retrying a failed payment). This patch seeds per_ip-scoped rules for all
three naming variants the API security framework probes per function, from
the fixture file, matching the pattern already used for submit_donation's
own per_ip Critical Operation Rules.
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
