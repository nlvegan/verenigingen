"""End board seats and withdraw board access when the person behind them goes away (#2471).

Maintainer ruling (2026-11-25): when a seated Volunteer is deleted, a Member is deleted, or the
User is disabled, the board role is withdrawn AND the seat ends.

No role removal is hand-rolled here. The seats are ended through their parent Chapter save, the
route termination's ``end_board_positions_safe`` already uses: the save defers and flushes the
role-profile sync, withdraws ``Verenigingen Chapter Board Member`` from a user with no live seat
left (a user who holds another active seat keeps it) and asserts the withdrawal happened.

A delete trigger fails CLOSED (raises): a seat that survives the delete would leave an orphan row
and a role nobody can trace. A User disable fails SOFT: refusing to disable an account is the worse
outcome, and the disabled account's role is inert, so the failure is logged for staff instead.
"""

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.services.termination.termination_integration import end_board_positions_safe
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS

REASON_VOLUNTEER_DELETED = "Volunteer deleted"
REASON_MEMBER_DELETED = "Member deleted"
REASON_USER_DISABLED = "User disabled"


def end_seats_for_deleted_volunteer(volunteer_name: str) -> None:
    """Volunteer.on_trash: end the volunteer's live seats and withdraw their board access."""
    failures = []
    end_board_positions_safe(
        None,
        today(),
        REASON_VOLUNTEER_DELETED,
        failures,
        volunteer_names=[volunteer_name],
        ignore_permissions=True,  # Security: the delete/disable mandates the seat-end, whatever Chapter rights the caller has (#2471)
    )
    _refuse_if_any(failures, volunteer_name)


def end_seats_for_deleted_member(member_name: str) -> None:
    """Member deletion (also reached by the #1306 anonymise-instead-of-delete branch)."""
    failures = []
    # Security: the delete mandates the seat-end, whatever Chapter rights the caller has (#2471)
    end_board_positions_safe(member_name, today(), REASON_MEMBER_DELETED, failures, ignore_permissions=True)
    _refuse_if_any(failures, member_name)


def end_seats_for_disabled_user(doc, method=None) -> None:
    """User.on_update: when the account has just been disabled, end its member's live seats."""
    if doc.enabled or not doc.has_value_changed("enabled"):
        return
    member_name = frappe.db.get_value("Member", {"user": doc.name}, "name")
    if not member_name:
        return
    failures = []
    # Security: the disable mandates the seat-end, whatever Chapter rights the caller has (#2471)
    ended = end_board_positions_safe(
        member_name, today(), REASON_USER_DISABLED, failures, ignore_permissions=True
    )
    if ended or _holds_board_role(doc.name):
        _withdraw_role_of_disabled_user(doc.name, member_name, failures)
    if failures:
        frappe.log_error(
            title="Board seats not ended for disabled user",
            message=f"User {doc.name} (Member {member_name}): " + "; ".join(failures),
        )


def _holds_board_role(user):
    return bool(frappe.db.exists("Has Role", {"parent": user, "role": "Verenigingen Chapter Board Member"}))


def _withdraw_role_of_disabled_user(user, member_name, failures):
    """The Chapter save's own role-profile sync skips a disabled user, so the role would stay.

    Same as termination: re-run the sync with ``allow_disabled=True`` (it only withdraws), then
    the existing unseated-role withdrawal for each of the member's volunteers.
    """
    from verenigingen.services.member.account.user_role_profile_calculator import sync_user_role_profile
    from verenigingen.verenigingen.doctype.chapter_board_member.chapter_board_member import (
        withdraw_board_member_role_if_unseated,
    )

    try:
        sync_user_role_profile(user, allow_disabled=True)
        for volunteer in frappe.get_all("Volunteer", filters={"member": member_name}, pluck="name"):
            withdraw_board_member_role_if_unseated(volunteer)
    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        failures.append(f"board role not withdrawn from {user}: {e}")


def _refuse_if_any(failures, subject):
    if failures:
        frappe.throw(
            _("Board seats of {0} could not be ended, so it cannot be deleted: {1}").format(
                subject, "; ".join(failures)
            )
        )
