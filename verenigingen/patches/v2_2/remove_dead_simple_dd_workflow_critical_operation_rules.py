# Copyright (c) 2026, Vegan Netwerk Nederland
# License: MIT

"""
Remove Critical Operation Rules for the dead Simple/DD-batch workflow setup
endpoints.

#753 deletes `verenigingen/setup/simple_dd_workflow_setup.py`: its Workflow bound
states (Draft, Pending, Approved, Rejected, Submitted, Completed) that were almost
entirely disjoint from `Direct Debit Batch.approval_status`'s real Select options
(Pending Approval, Pending Senior Approval, Approved, Rejected), so installing it
broke batch approval. The setup had no caller in hooks.py or patches.txt and no
live Workflow row existed on veg11 or test_site_1 -- it was dead code.

Because Critical Operation Rule is deliberately excluded from the `fixtures` hook
(see `verenigingen/hooks/fixtures.py`), `bench migrate` never re-imports or prunes
rows already inserted by `critical_operation_rules_setup.setup_critical_operation_rules`
during install. Removing an entry from the fixture file alone does not delete an
already-imported record -- this is the same gap the precedent patches for this
exact fixture (`remove_dead_dd_batch_critical_operation_rules`,
`remove_workflow_demo_critical_operation_rules`) exist to close.

`setup_production_dd_workflow` is included here too: it is the Critical Operation
Rule for `dd_batch_workflow_setup.py`, deleted in commit 53c41a791 together with
its fixture entry, but that commit did not add a prune patch, so the row survived
as an orphan (still `enabled=1` on veg11 as of this patch) -- the same class of
gap #753's own fixture edit would otherwise repeat.

Rule names equal the bare function name (autoname `field:operation_name`), and
neither name has any remaining definition anywhere in the app, so the deletion
cannot orphan a live endpoint's rate-limit configuration.
"""

import frappe

DEAD_RULES = [
    "setup_production_simple_workflow",
    "setup_production_dd_workflow",
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
        print(f"Removed {removed} dead Simple/DD-batch workflow Critical Operation Rule(s)")
