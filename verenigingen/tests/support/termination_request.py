"""One builder for the Membership Termination Request fixture two test modules need.

`test_history_lock_order` (#459) and `test_termination_non_resumable_errors` (#470) both
drive a real termination, so both need an inserted, committed request whose
`end_board_positions` is set -- the operations reload from the database, so an uncommitted
fixture is invisible to them.

They had a copy each, differing only in the member and the reason string. The duplicate
ratchet reported the pair rather than blocking it (the copies are not near-identical enough
to be a clone family), and its baseline is explicit that recording is the worse exit: the
file is "a to-do list, not a permission slip", and each line is a place where a later fix
lands in one copy and misses the other. Consolidating is the exit that shrinks it.
"""

from unittest.mock import patch

import frappe
from frappe.utils import today


def create_termination_request(case, member_name, reason):
    """Insert a committed, board-position-ending termination request and track it.

    ``case`` is the test case, used for ``track_doc`` -- the commit puts the row beyond the
    per-test rollback, so the tracked drain is what removes it.
    """
    request = frappe.get_doc(
        {
            "doctype": "Membership Termination Request",
            "member": member_name,
            "termination_type": "Voluntary",
            "termination_reason": reason,
            "member_request_date": today(),
            "termination_date": today(),
            "end_board_positions": 1,
        }
    )
    request.insert()
    case.track_doc("Membership Termination Request", request.name)
    frappe.db.commit()
    return request


def execute_real_termination(case, member_name, termination_date):
    """Drive a REAL termination through TerminationExecutionService (not a
    hand-set status -- #1530 was found precisely because an earlier fix
    trusted a status string instead of the real flow). Sets Membership
    Termination Request.status to whatever the service actually writes
    ("Executed") and moves Member.status away from "Active".

    ``case`` is the test case, used for ``track_doc``. Added for #1532
    (predictive_analytics.calculate_current_churn_rate and
    AnalyticsAlertRule.calculate_churn_rate both needed the identical
    fixture -- test_membership_goal.py's own
    ``_terminate_member_from_chapter`` additionally seats a Chapter Member
    row and is left as-is; this is the chapter-free version two more test
    modules needed, per this file's own "one builder" precedent).
    """
    from verenigingen.services.termination import TerminationExecutionService

    request = frappe.get_doc(
        {
            "doctype": "Membership Termination Request",
            "member": member_name,
            "termination_type": "Voluntary",
            "termination_reason": "Test termination",
            "termination_date": termination_date,
            "requested_by": frappe.session.user,
            "request_date": today(),
            "status": "Approved",
            "approved_by": frappe.session.user,
            "approval_date": frappe.utils.now(),
        }
    )
    request.insert()
    case.track_doc("Membership Termination Request", request.name)
    # Mocking frappe.db.begin/commit/rollback mirrors
    # test_termination_execution_service.py's own pattern: the service manages
    # its own savepoint/commit/rollback, which conflicts with
    # EnhancedTestCase's transaction if allowed to actually run mid-test.
    with patch("frappe.db.begin"), patch("frappe.db.commit"), patch("frappe.db.rollback"):
        result = TerminationExecutionService().execute(request)
    case.assertTrue(result, "Real termination execution must succeed")
    request.reload()
    return request


def create_draft_termination_request(case, member_name):
    """A Membership Termination Request left at status="Draft" (never
    executed) -- the control (#1532) that distinguishes filtering on
    status="Executed" from the plausible wrong fix of dropping the status
    filter entirely."""
    request = frappe.get_doc(
        {
            "doctype": "Membership Termination Request",
            "member": member_name,
            "termination_type": "Voluntary",
            "termination_reason": "Test draft termination (control, never executed)",
            "termination_date": today(),
            "requested_by": frappe.session.user,
            "request_date": today(),
        }
    )
    request.insert()
    case.track_doc("Membership Termination Request", request.name)
    case.assertEqual(request.status, "Draft", "precondition: request must NOT be Executed")
    return request
