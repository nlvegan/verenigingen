# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Raise the mollie_subscription_webhook rate limit from global 30/h to the
sibling Mollie webhook ceiling (#1763).

The rule was `global` 30 calls/3600 s: one counter for every sender, so the
31st subscription notification in an hour was refused (403) before it was
verified. setup_critical_operation_rules runs in after_install only and never
overwrites an existing row, so editing the fixture reaches fresh installs and
nothing else; this patch carries the value to existing sites.

Only a row that still holds the OLD shipped values is changed. A row an
operator has tuned (different calls, period or scope) is left alone.
"""

import json
from pathlib import Path

import frappe

RULE = "mollie_subscription_webhook"
OLD = {"rate_limit_scope": "global", "rate_limit_calls": 30, "rate_limit_period_seconds": 3600}


def execute():
    if not frappe.db.exists("Critical Operation Rule", RULE):
        return
    current = frappe.db.get_value("Critical Operation Rule", RULE, list(OLD), as_dict=True)
    if any(current[f] != v for f, v in OLD.items()):
        return

    fixture = Path(__file__).parents[2] / "fixtures" / "critical_operation_rule.json"
    new = next(r for r in json.loads(fixture.read_text()) if r["name"] == RULE)
    frappe.db.set_value("Critical Operation Rule", RULE, {f: new[f] for f in OLD})
