# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Split the retry_failed_payment rate limit (#2596).

A manual retry mails staff and writes SEPA Payment Retry records, and a member can now
trigger it for their own invoice. Maintainer ruling (2026-11-25): a member's own retry is
limited to 5/hour, staff acting for another member get a SEPARATE 30/hour.

* ``retry_failed_payment`` (the decorator's bucket, so the staff cross-member limit and a
  ceiling for everyone): 5000 -> 30.
* ``retry_failed_payment_self`` (checked in the endpoint for a member's own invoice): created at 5.

setup_critical_operation_rules runs in after_install only and never overwrites an existing
row, so editing the fixture reaches fresh installs and nothing else; this patch carries the
values to existing sites (the rule engine reads the DB row). Rows are found by
``operation_name``, the column the engine filters on, not by ``name``.

Only a row that still holds a value this change shipped or replaced is changed. A row an
operator has tuned is left alone, and an existing self row is never overwritten.
"""

import frappe

STAFF_OPERATION = "retry_failed_payment"
SELF_OPERATION = "retry_failed_payment_self"
STAFF_CALLS = 30
SELF_CALLS = 5
# 5000 was shipped; 5 was this branch's first cut, before the staff/self split.
REPLACED_STAFF_VALUES = (5000, 5)


def execute():
    _set_staff_limit()
    _create_self_rule()


def _set_staff_limit():
    row = frappe.db.get_value(
        "Critical Operation Rule", {"operation_name": STAFF_OPERATION}, ["name", "rate_limit_calls"], as_dict=True
    )
    if row and row.rate_limit_calls in REPLACED_STAFF_VALUES:
        frappe.db.set_value("Critical Operation Rule", row.name, "rate_limit_calls", STAFF_CALLS)


def _create_self_rule():
    if frappe.db.exists("Critical Operation Rule", {"operation_name": SELF_OPERATION}):
        return
    staff = frappe.db.get_value(
        "Critical Operation Rule",
        {"operation_name": STAFF_OPERATION},
        ["rate_limit_period_seconds", "rate_limit_scope", "required_roles"],
        as_dict=True,
    )
    if not staff:
        return  # the rule set has not been seeded on this site; setup seeds both from the fixture
    frappe.get_doc(
        {
            "doctype": "Critical Operation Rule",
            "name": SELF_OPERATION,
            "operation_name": SELF_OPERATION,
            "operation_type": "reporting",
            "description": "A member retrying their own failed payment",
            "enabled": 1,
            "security_level": "medium",
            "business_context": "Payment recovery: strict budget for a member retrying their own invoice",
            "required_roles": staff.required_roles,
            "rate_limit_calls": SELF_CALLS,
            "rate_limit_period_seconds": staff.rate_limit_period_seconds,
            "rate_limit_scope": staff.rate_limit_scope,
            "audit_level": "standard",
            "alert_on_execution": 0,
        }
    ).insert(ignore_permissions=True)
