# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Add a dedicated Critical Operation Rule for payment_success.py's refresh_payment_status (#1105).

refresh_payment_status shipped without a rule under any of the naming
conventions the framework probes, so it silently inherited
_generic_api_fallback's 100/hour per_user default. For a Guest caller
frappe.session.user is the literal string "Guest", so that scope collapses
into ONE shared bucket for every anonymous visitor: a live DoS vector, since
one abusive client exhausts the budget for every legitimate visitor watching
a pending payment. Same mechanism #1028 fixed for retry_payment, and this
patch follows that one exactly.

Unlike retry_payment's 5/60s, the rule this seeds is deliberately MORE
permissive than the fallback it replaces, not less: payment_success.html
polls this endpoint every 10s for up to five minutes while a payment is
pending (6 calls/minute), and per_ip means visitors behind one NAT address
share the budget. 60/60s leaves roughly 10x headroom for one poller. The
point here is the per_ip scope, not a smaller number.

Needed because setup_critical_operation_rules runs in after_install ONLY
(hooks/lifecycle.py), never in after_migrate -- so a rule added to the
fixture reaches fresh installs and nothing else. add_missing_critical_operation_rules
reads the fixture files and creates whatever is absent, so this is
idempotent and picks up any other rule that has drifted out too.
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
