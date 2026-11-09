# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Rate-limit rules for the application review endpoints (#1928, #1765).

The member-keyed approve/reject endpoints had Critical Operation Rules (approve 500/h with an alert,
reject 20/h, quick approve 80/min). The engine looks a rule up by function name, so the replacements
(`approve_application`, `reject_application`, `request_more_info`, `quick_approve_application`,
`quick_approve_join_request`) ran on `_generic_api_fallback`. The fixture now carries a row for each;
setup_critical_operation_rules runs in after_install only and never overwrites a row, so this patch
creates the missing rows on existing sites.

`reject_application` already existed as a stale row left by the removed `Member.reject_application`
(low security, 180/h, minimal audit). Only a row that still holds those shipped values is brought to the
fixture's; a row an operator tuned is left alone.
"""

import json
from pathlib import Path

import frappe

RULE = "reject_application"
STALE = {"security_level": "low", "rate_limit_calls": 180, "audit_level": "minimal"}
BROUGHT_TO_FIXTURE = (
    "description",
    "security_level",
    "business_context",
    "required_roles",
    "rate_limit_calls",
    "audit_level",
    "alert_on_execution",
    "notification_recipients",
    "batch_rate_limit_calls",
    "batch_rate_limit_period_seconds",
    "apply_batch_limits_to",
)


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return
    _bring_stale_reject_row_to_the_fixture()
    from verenigingen.setup.critical_operation_rules_setup import add_missing_critical_operation_rules

    add_missing_critical_operation_rules()


def _bring_stale_reject_row_to_the_fixture():
    if not frappe.db.exists("Critical Operation Rule", RULE):
        return
    current = frappe.db.get_value("Critical Operation Rule", RULE, list(STALE), as_dict=True)
    if any(current[field] != value for field, value in STALE.items()):
        return
    fixture = Path(__file__).parents[2] / "fixtures" / "critical_operation_rule.json"
    new = next(rule for rule in json.loads(fixture.read_text()) if rule["name"] == RULE)
    frappe.db.set_value("Critical Operation Rule", RULE, {field: new.get(field) for field in BROUGHT_TO_FIXTURE})
