"""
Chapter Role Event Handlers
===========================

This module provides event handlers for Chapter Board Member and Chapter Role changes
to automatically manage Chapter Board Member system role assignments and permissions.

Event Triggers:
- Chapter Board Member creation/update/deletion
- Chapter Role changes that affect board membership
- Member/Volunteer record changes that affect board positions

Security Features:
- Automatic role assignment based on active board positions
- Role removal when board positions end
- Permission validation and audit logging
- Prevention of orphaned system roles
"""

import frappe
from frappe.utils import escape_html

from verenigingen.permissions import assign_chapter_board_role, get_user_chapter_board_positions
from verenigingen.utils.notification_helpers import notify_administrators
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api
from verenigingen.utils.security_decorators import development_only
from verenigingen.utils.transaction_errors import (
    NON_RESUMABLE_DB_ERRORS,
    release_savepoint_if_present,
    rollback_to_savepoint,
)
from verenigingen.verenigingen.doctype.chapter.managers import BoardAccessWithdrawalError

NOTIFICATION_KEY = "chapter_role_holder_withdrawal_failed"

# REMOVED: on_chapter_board_member_after_insert, on_chapter_board_member_on_update,
# on_chapter_board_member_on_trash. These child table doc_events never fire when
# rows are managed via parent save. Role assignment and role profile sync are now
# handled by BoardManager.handle_board_member_additions/changes/deletions.
#
# REMOVED: on_volunteer_on_update (#688). It re-ran assign_chapter_board_role()
# when Volunteer.member changed. It was registered under "Verenigingen Volunteer"
# -- a Role name, not a DocType -- so it never fired, and BoardManager was built
# in its absence to own the same decision. Restoring it would make a second writer
# of the board role, and (before #702) a broken one: assign_chapter_board_role()'s
# else-branch raw-deleted the Has Role row WITHOUT the role-profile sync that must precede it
# (User.populate_role_profile_roles resets User.roles from the assigned profile on
# every save), so the removal would be undone by the next User save. See
# BoardManager.flush_pending_board_profile_syncs for the ordering that is correct.
#
# That defect was live in on_member_on_update and on_chapter_role_on_update (real
# DocTypes, same function) until #702: assign_chapter_board_role now withdraws the
# role profile with the role and raises BoardAccessWithdrawalError when it cannot, and
# both handlers let that abort the save.
#
# #702 also names the case BoardManager structurally cannot see: Volunteer.member
# is editable (unique, but not set_only_once), and BoardManager runs only from
# Chapter.on_update, so a Volunteer.member re-link leaves board access on the old
# member's user. The re-link half is fixed by on_volunteer_member_relinked below, called
# from Volunteer.on_update (#2615); the delete half (Volunteer.on_trash) is tracked in #2471.


def on_volunteer_member_relinked(volunteer):
    """Move board access with a seated Volunteer when its `member` is re-linked (#2615).

    Called from Volunteer.on_update, not registered as a doc_event (see the #688 note
    above for why a second hook-time writer of the role is the wrong shape). Board access
    follows Volunteer -> Member -> Member.user, so after a re-link the OLD member's user
    holds access no seat justifies and the NEW member's user holds none for a seat they now
    have.

    Old user: the same withdrawal on_member_on_update runs for a Member.user re-link
    (profile sync first, then the role, raising BoardAccessWithdrawalError when it cannot),
    so a manually granted profile is treated exactly as #702 treats it (#2759 is open on that).
    New user: the role-profile sync, which is what a seat add does (BoardManager applies no
    direct role grant, #1672); the profile brings the role. Only for a seated volunteer. A failed
    grant is logged, as there. Insert and empty-to-filled `member` are not re-links: nothing runs.
    """
    previous = volunteer.get_doc_before_save()
    old_member = previous.get("member") if previous else None
    # Only a TRUE re-link. On insert has_value_changed("member") is True and is_new() is
    # already False inside on_update; filling an EMPTY member adopts an orphan and is not
    # what #2615 asks for (the sync would provision the user's roles and Employee).
    if not old_member or not volunteer.has_value_changed("member"):
        return
    old_user = frappe.db.get_value("Member", old_member, "user")
    new_user = frappe.db.get_value("Member", volunteer.member, "user") if volunteer.member else None
    if old_user and old_user != new_user:
        assign_chapter_board_role(old_user)
    # Only a seated volunteer confers board access; syncing an unseated one would only
    # provision the user's ordinary roles and Employee, an unrequested side effect.
    if new_user and new_user != old_user and _holds_active_seat(volunteer.name):
        _grant_board_profile_to(new_user)


def _holds_active_seat(volunteer_name):
    return bool(frappe.db.count("Chapter Board Member", {"volunteer": volunteer_name, "is_active": 1}))


def _grant_board_profile_to(user):
    from verenigingen.services.member.account.user_role_profile_calculator import sync_user_role_profile

    result = sync_user_role_profile(user)
    if not result.get("success"):
        frappe.log_error(
            title="Board profile grant after Volunteer re-link failed",
            message=f"Could not sync the role profile of {user}: {result.get('error')}",
        )


def on_member_on_update(doc, method):
    """
    Event handler for Member updates
    Re-evaluates board roles if user field changes
    """
    try:
        # Check if the user field changed
        if doc.has_value_changed("user"):
            old_user = doc._doc_before_save.get("user") if doc._doc_before_save else None
            new_user = doc.user

            # Handle old user - remove board role
            if old_user:
                assign_chapter_board_role(old_user)
                frappe.logger().info(f"Re-evaluated board role for old user {old_user}")

            # Handle new user - assign board role if they have board positions
            if new_user:
                assign_chapter_board_role(new_user)
                frappe.logger().info(f"Re-evaluated board role for new user {new_user}")

    except (BoardAccessWithdrawalError, *NON_RESUMABLE_DB_ERRORS):
        raise  # #702/#1953: a failed withdrawal aborts the save instead of leaving live board access
    except Exception as e:
        frappe.log_error(f"Error in member update handler: {str(e)}")


def on_chapter_role_on_update(doc, method):
    """
    Event handler for Chapter Role updates
    Re-evaluates board member roles if permissions_level changes

    Each holder is processed under its own savepoint (#2857): one User whose board access cannot
    be withdrawn must not roll back the edit for everyone else. The save succeeds; each failure
    is logged and ONE staff alert lists the failed users, so it stays loud (#702, #1953).
    """
    try:
        # Check if permissions_level changed - this affects treasurer status
        if doc.has_value_changed("permissions_level") or doc.has_value_changed("is_active"):
            # Get all board members with this chapter role
            board_members = frappe.get_all(
                "Chapter Board Member",
                filters={"chapter_role": doc.name, "is_active": 1},
                fields=["volunteer"],
            )

            failed = []
            for board_member in board_members:
                if board_member.volunteer:
                    _reevaluate_holder(board_member.volunteer, failed)
            _alert_failed_holders(doc.name, failed)

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.log_error(f"Error in chapter role update handler: {str(e)}")

    _refresh_expense_approvers_for_role(doc)


def _reevaluate_holder(volunteer, failed):
    """Re-evaluate one holder's board role under a savepoint; a failure is collected in ``failed``.

    The savepoint undoes the failing user's half-done writes (the strip may already have removed
    the role when its post-condition refuses). A deadlock/lock-wait has destroyed the savepoint
    and propagates, as it must.
    """
    savepoint = f"chapter_role_holder_{frappe.generate_hash(length=10)}"
    frappe.db.savepoint(savepoint)
    user_email = None
    try:
        volunteer_doc = frappe.get_doc("Volunteer", volunteer)
        if volunteer_doc.member:
            member_doc = frappe.get_doc("Member", volunteer_doc.member)
            user_email = member_doc.user or member_doc.email

            if user_email:
                assign_chapter_board_role(user_email)
                frappe.logger().info(f"Re-evaluated board role for {user_email} due to chapter role changes")
        release_savepoint_if_present(savepoint)
    except NON_RESUMABLE_DB_ERRORS:
        raise
    # Deliberately NOT only BoardAccessWithdrawalError: any failure in one holder's turn (a missing
    # Volunteer/Member, a failed insert) must not skip the remaining holders or the alert (#2857).
    except Exception as e:
        who = user_email or f"Volunteer {volunteer}"
        if not rollback_to_savepoint(savepoint):
            # A nested commit consumed the savepoint: the holder's partial writes now persist.
            frappe.log_error(
                title=f"Chapter Role holder partial changes not rolled back: {who}"[:140],
                message=f"The savepoint of {who} was already gone, so the changes made before the failure "
                "could not be rolled back and may be half-applied. Check this user's roles and role profile.",
            )
        frappe.log_error(
            title=f"Chapter Role holder withdrawal failed: {who}"[:140],
            message=f"Re-evaluating the board role of {who} after a Chapter Role change failed: "
            f"{e.__class__.__name__}: {e}\n\n{frappe.get_traceback()}",
        )
        failed.append((who, f"{e.__class__.__name__}: {e}"))


def _alert_failed_holders(role_name, failed):
    """ONE staff alert listing the holders whose re-evaluation failed (none: no alert).

    Alert trouble must never undo the Chapter Role save, which has already succeeded.
    """
    if not failed:
        return
    try:
        lines = "".join(
            f"<li><b>{escape_html(who)}</b>: {escape_html(reason)}</li>" for who, reason in failed
        )
        notify_administrators(
            subject=f"Board access was not withdrawn for {len(failed)} user(s) after a Chapter Role change",
            message=(
                f"<p>Chapter Role <b>{escape_html(role_name)}</b> was saved, but the board access of these "
                "holders could not be re-evaluated. Fix the cause on each User, then save the role again.</p>"
                f"<ul>{lines}</ul>"
            ),
            notification_key=NOTIFICATION_KEY,  # literal in the registry: key discovery greps for it
            event_reference=NOTIFICATION_KEY,
            # staff alerts never go to Administrator (the delivery layer also excludes it)
            exclude_users=["Administrator"],
            staff_alert=True,
        )
    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception:
        frappe.log_error(title="Chapter Role holder alert failed", message=frappe.get_traceback())


def _refresh_expense_approvers_for_role(doc):
    """A role gaining or losing Financial (or being deactivated) re-points its chapters' approvers (#1682).

    Queued, not run here: a role can be held in many chapters, and the national chapter's
    seats feed every volunteer. Only a role that WAS an active Financial role and no longer
    is can make an approver stale; any other change just recomputes.
    """
    if not (doc.has_value_changed("permissions_level") or doc.has_value_changed("is_active")):
        return

    try:
        from verenigingen.services.volunteer.native_expense_helpers import (
            enqueue_expense_approver_refresh_for_role,
        )

        was_financial = _is_active_financial_role(doc.get_doc_before_save())
        is_financial = _is_active_financial_role(doc)
        enqueue_expense_approver_refresh_for_role(doc.name, left_financial=was_financial and not is_financial)
    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.log_error(
            title="Chapter Role approver refresh",
            message=f"Expense approver refresh after Chapter Role {doc.name} change failed: {e}",
        )


def _is_active_financial_role(role_doc):
    return bool(role_doc and role_doc.get("permissions_level") == "Financial" and role_doc.get("is_active"))


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def sync_all_chapter_board_roles():
    """
    Maintenance function to sync all Chapter Board Member system roles
    Can be called manually or scheduled
    """
    try:
        from verenigingen.permissions import update_all_chapter_board_roles

        result = update_all_chapter_board_roles()

        return {
            "success": True,
            "updated_count": result,
            "message": f"Successfully synced Chapter Board Member roles for {result} users",
        }

    except Exception as e:
        frappe.log_error(f"Error syncing chapter board roles: {str(e)}")
        return {"success": False, "error": str(e), "message": "Failed to sync Chapter Board Member roles"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_user_board_summary(user_email: str | None = None):
    """
    Get summary of user's board positions and permissions
    Useful for debugging and administration
    """
    try:
        if not user_email:
            user_email = frappe.session.user

        # Board identity is Member.user only (#1546, #1936): no Member.email fallback
        from verenigingen.utils.member_utils import get_member_name_for_board_access

        user_member = get_member_name_for_board_access(user_email)

        if not user_member:
            return {"success": False, "message": "No member record found for user"}

        # Get board positions
        board_positions = get_user_chapter_board_positions(user_member)

        # Check system role status
        has_board_role = frappe.db.exists(
            "Has Role", {"parent": user_email, "role": "Verenigingen Chapter Board Member"}
        )

        # Check treasurer status
        treasurer_chapters = []
        for position in board_positions:
            if position.get("permissions_level") == "Financial":
                treasurer_chapters.append(position.get("chapter_name"))

        return {
            "success": True,
            "user_email": user_email,
            "member_name": user_member,
            "board_positions": board_positions,
            "has_chapter_board_role": bool(has_board_role),
            "treasurer_chapters": treasurer_chapters,
            "can_approve_expenses": len(treasurer_chapters) > 0,
        }

    except Exception as e:
        frappe.log_error(f"Error getting user board summary: {str(e)}")
        return {"success": False, "error": str(e), "message": "Failed to get user board summary"}
