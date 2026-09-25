# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove Critical Operation Rules for the dead verenigingen/fixes/ workspace.

#1395 deletes `verenigingen/fixes/`: an abandoned scratch workspace (~20 planning
.md files, three prototype e-Boekhouden importers) with zero references from
anywhere else in the app. Its whitelisted `test_new_invoice_creation()`
(`verenigingen/fixes/step1_fix_data_fetching.py`) NameErrors on every real
invocation -- it calls 14 names it neither defines nor imports -- so the module
never completed a real run, but `verenigingen/fixtures/critical_operation_rule.json`
still carried `enabled: 1` rows for it, for `compare_old_vs_new_import`, and for
`test_correct_import` (defined in the third deleted file,
`verenigingen/fixes/correct_implementation_example.py`, and gated the same way).

An AST sweep of every `def`/`async def` name across all three deleted files
(52 names total), cross-referenced against `operation_name` in all four fixture
files this validator's ``FIXTURE_FILES`` (and
`critical_operation_rules_setup.py`) load -- `critical_operation_rule.json`,
`critical_operation_rule_ponto_debug.json`,
`critical_operation_rule_balance_transactions.json`,
`critical_operation_rule_payment_recovery.json` -- found exactly these 3 matches,
all in `critical_operation_rule.json`; the other three fixture files have zero.

Because Critical Operation Rule is deliberately excluded from the `fixtures` hook
(see `verenigingen/hooks/fixtures.py`), `bench migrate` never re-imports or prunes
rows already inserted by `critical_operation_rules_setup.setup_critical_operation_rules`
during install. Removing the three entries from the fixture file alone does not
delete an already-imported record -- this is the same gap the precedent patches
for this exact fixture (`remove_dead_dd_batch_critical_operation_rules`,
`remove_dead_simple_dd_workflow_critical_operation_rules`, etc.) exist to close.

Rule names equal the bare function name (autoname `field:operation_name`), and
none of the three has any remaining definition anywhere in the app after this
deletion, so removing them cannot orphan a live endpoint's rate-limit
configuration.
"""

import frappe

DEAD_RULES = [
    "compare_old_vs_new_import",
    "test_correct_import",
    "test_new_invoice_creation",
]


def execute():
    if not frappe.db.exists("DocType", "Critical Operation Rule"):
        return

    removed = 0
    for name in DEAD_RULES:
        if frappe.db.exists("Critical Operation Rule", name):
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)
            removed += 1

    if removed:
        frappe.db.commit()
        print(f"Removed {removed} dead verenigingen/fixes/ Critical Operation Rule(s)")
