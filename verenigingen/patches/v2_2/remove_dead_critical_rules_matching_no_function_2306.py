# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove nine Critical Operation Rule rows that no function can ever match (#2306).

Critical Operation Rule is excluded from the `fixtures` hook, so dropping the rows from
`fixtures/critical_operation_rule.json` does not prune installed sites.

- `admin_tools_<x>` (six rows): named after the admin tools page that calls the endpoint,
  but the runtime names are the bare function name, `<defining module>_<name>` and
  `api_<name>`, so they only match a function `<x>` defined in module `admin_tools`, and
  there is none. The real endpoints (`apply_production_security`,
  `cleanup_orphaned_gl_entries`, `nuclear_cleanup_all_imported_data`,
  `nuclear_cleanup_all_members`, `nuclear_truncate_member_tables`,
  `nuclear_truncate_version_and_deleted_tables`) each already carry a bare-named critical
  rule with identical limits, which this patch does not touch.
- `add_role_to_user`, `create_payment_entries`, `sepa_batch_creation`: seeded in
  2dbea04eb ("fixes") for names that never had a decorated endpoint behind them
  (`sepa_batch_creation` is an audit-log operation string, `create_payment_entries` a
  Bank Transaction reconciler method).

No explicit commit: the patch runner commits after each patch.
Precedent: `remove_get_income_account_query_critical_operation_rule.py`.
"""

import frappe

DEAD_RULES = [
    "add_role_to_user",
    "admin_tools_apply_production_security",
    "admin_tools_cleanup_orphaned_gl_entries",
    "admin_tools_nuclear_cleanup_all_imported_data",
    "admin_tools_nuclear_cleanup_all_members",
    "admin_tools_nuclear_truncate_member_tables",
    "admin_tools_nuclear_truncate_version_and_deleted_tables",
    "create_payment_entries",
    "sepa_batch_creation",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
