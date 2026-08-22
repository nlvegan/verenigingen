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
