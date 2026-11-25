# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Lower the retry_failed_payment rate limit from 5000 to 5 calls/hour (#2596).

A manual retry mails staff and writes SEPA Payment Retry records, and a member can
now trigger it for their own invoice. setup_critical_operation_rules runs in
after_install only and never overwrites an existing row, so editing the fixture
reaches fresh installs and nothing else; this patch carries the value to existing
sites (the rule engine reads the DB row).

Only a row that still holds the OLD shipped value is changed. A row an operator
has tuned is left alone.
"""

import frappe

RULE = "retry_failed_payment"
OLD_CALLS = 5000
NEW_CALLS = 5


def execute():
    if not frappe.db.exists("Critical Operation Rule", RULE):
        return
    if frappe.db.get_value("Critical Operation Rule", RULE, "rate_limit_calls") != OLD_CALLS:
        return
    frappe.db.set_value("Critical Operation Rule", RULE, "rate_limit_calls", NEW_CALLS)
