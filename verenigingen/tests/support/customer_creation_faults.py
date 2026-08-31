"""Realistic ways ``Member.after_insert``'s Customer creation fails.

``Member.after_insert`` creates the member's ERPNext Customer, and what a caller
does when that fails is the subject of #254, #378 and #570 -- so more than one
test module needs to make it fail. The fault is injected by swapping a module
attribute rather than by mocking the unit under test: the Member insert, the
``after_insert`` hook and the real Customer/Contact creation all still run.
"""

import frappe

import verenigingen.services.member.approval.application_payments as approval_payments

BROKEN_CUSTOMER_GROUP = "No Such Customer Group ZZZ"


def break_customer_group(testcase):
    """Point ``Customer.customer_group`` at a group that does not exist.

    The real ``Customer.insert()`` runs and raises ``LinkValidationError`` -- a
    ``frappe.ValidationError`` subclass, which is what most real customer failures
    are (a missing link, a missing mandatory field, a ``frappe.throw`` for
    insufficient permissions). Restored via ``testcase.addCleanup``.
    """
    original = approval_payments.resolve_non_group_customer_group
    approval_payments.resolve_non_group_customer_group = lambda: BROKEN_CUSTOMER_GROUP
    testcase.addCleanup(setattr, approval_payments, "resolve_non_group_customer_group", original)


def break_customer_group_after_eating_the_savepoints(testcase):
    """The same fault, with every savepoint taken so far released first.

    Any commit nested under the insert clears the savepoint stack and takes the
    caller's savepoint with it -- ``transaction_errors.rollback_to_savepoint``
    exists because ``mt940_import`` really hit that. ``RELEASE SAVEPOINT``
    reproduces the half that matters (the savepoints are gone, the writes made
    under them are not) without a real commit, which would take the test's own
    fixtures with it. What it does NOT reproduce is durability: after a RELEASE the
    writes are still pending, so a test asserting the row is there is asserting it
    was written, not that it is committed.

    Single-row-shaped on purpose: ``taken`` never shrinks, so every recorded
    savepoint is re-released on each call. Harmless for one row; re-check it before
    reusing this for a multi-row batch.
    """
    taken = []
    real_savepoint = frappe.local.db.savepoint

    def _recording_savepoint(save_point):
        taken.append(save_point)
        return real_savepoint(save_point)

    frappe.local.db.savepoint = _recording_savepoint
    # Resolved at cleanup time, not here: `frappe.local.db` can be replaced
    # mid-test (a reconnect after a lost connection), and popping from the dead
    # object would leave the live one carrying this wrapper for the rest of the
    # shard.
    testcase.addCleanup(lambda: frappe.local.db.__dict__.pop("savepoint", None))

    original = approval_payments.resolve_non_group_customer_group

    def _eat_savepoints_and_break_the_group():
        for save_point in taken:
            try:
                frappe.db.sql(f"RELEASE SAVEPOINT {save_point}")
            except Exception:
                pass  # releasing an outer savepoint already took the inner ones
        return BROKEN_CUSTOMER_GROUP

    approval_payments.resolve_non_group_customer_group = _eat_savepoints_and_break_the_group
    testcase.addCleanup(setattr, approval_payments, "resolve_non_group_customer_group", original)
