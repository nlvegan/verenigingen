# verenigingen/verenigingen/doctype/chapter_board_member/chapter_board_member.py
import frappe
import frappe.utils
from frappe.model.document import Document

from verenigingen.permissions import clear_permission_cache
from verenigingen.utils.secure_operations import secure_document_operation


class ChapterBoardMember(Document):
    def after_insert(self):
        """Assign Chapter Board Member role when someone joins a board"""
        self.assign_board_member_role()
        # Clear permission cache when board membership changes
        clear_permission_cache()
        # Send notification to the new board member
        self._send_board_added_notification()

    def on_trash(self):
        """Remove Chapter Board Member role if no longer on any board"""
        self.remove_board_member_role()
        # Clear permission cache when board membership changes
        clear_permission_cache()
        # Send notification to the removed board member
        self._send_board_removed_notification()

    def on_update(self):
        """Handle role changes when board member status changes"""
        # If marked inactive or past end date, check if role should be removed
        if not self.is_active or (self.to_date and frappe.utils.getdate(self.to_date) < frappe.utils.today()):
            self.remove_board_member_role()
        else:
            # If reactivated, ensure they have the role
            self.assign_board_member_role()

        # Clear permission cache when board member status changes
        clear_permission_cache()

    def assign_board_member_role(self):
        """Assign the Chapter Board Member role to the volunteer's user"""
        if not self.volunteer:
            return

        # Get the member and user associated with this volunteer
        volunteer_doc = frappe.get_doc("Volunteer", self.volunteer)
        if not volunteer_doc.member:
            return

        user = frappe.db.get_value("Member", volunteer_doc.member, "user")
        if not user:
            return

        # Check if user already has the role
        existing_role = frappe.db.exists(
            "Has Role", {"parent": user, "role": "Verenigingen Chapter Board Member"}
        )

        if not existing_role:
            # Create the role assignment via parent document
            user_doc = frappe.get_doc("User", user)
            user_doc.append(
                "roles",
                {
                    "role": "Verenigingen Chapter Board Member",
                },
            )
            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            save_result = secure_document_operation(
                operation="save",
                doc=user_doc,
                justification=f"Assign Chapter Board Member role to user {user} for board position",
                required_permissions=["User:write"],
            )

            if save_result.success:
                frappe.msgprint(f"Assigned Chapter Board Member role to {user}")
            else:
                # Report what actually failed. This branch used to hardcode "Permission
                # denied", which was wrong for every non-permission failure that
                # secure_document_operation turns into success=False -- and it is the only
                # record of the failure, since the exception itself is not re-raised.
                # (Transaction-fatal DB errors no longer reach here at all; those
                # propagate out of secure_document_operation.)
                frappe.log_error(
                    f"Could not assign board member role to user {user}: "
                    f"{'; '.join(save_result.errors) or 'no reason reported'}"
                )

    def remove_board_member_role(self):
        """Remove Chapter Board Member role if user is no longer on any board.

        ``exclude_row=self.name`` because this runs from the row's own controller
        hooks (``on_trash``/``on_update``), where the row is still in the database
        and would otherwise count as a seat that justifies keeping the role.
        """
        withdraw_board_member_role_if_unseated(self.volunteer, exclude_row=self.name)

    def validate(self):  # child-validate-ok: this row is loaded and saved DIRECTLY
        # (not via chapter_doc.append()+chapter_doc.save()) by
        # services/chapter/chapter_assignment_service.py's board-term-ending code
        # (frappe.get_doc("Chapter Board Member", name); ...; .save()). Frappe's
        # child-table skip ONLY applies to a row saved as part of its parent's
        # save -- a standalone Document.save() runs the full normal lifecycle on
        # self regardless of istable, so validate() DOES run here. #596 originally
        # deleted this method entirely on the (incomplete) belief that a child
        # DocType's validate() never runs anywhere; it does, on this path.
        #
        # required-field/Link-existence checks are NOT repeated here -- those are
        # covered by Frappe's own mandatory + Link-field validation regardless of
        # this method. Date range, active-status-vs-past-end-date and email format
        # have no other enforcement and are what this delegates to, via the same
        # validator ChapterValidator.validate_all() uses for the parent.append()+
        # save() path (verenigingen/verenigingen/doctype/chapter/validators/
        # board_member_validator.py) -- one rule, one implementation, two call sites.
        from verenigingen.verenigingen.doctype.chapter.validators.board_member_validator import (
            BoardMemberValidator,
        )

        result = BoardMemberValidator().validate_single_board_member(self.as_dict())
        for warning in result.warnings:
            frappe.msgprint(warning, indicator="orange", alert=True)
        if not result.is_valid:
            frappe.throw("; ".join(result.errors))

    def _send_board_added_notification(self):
        """Send notification when a volunteer is added to the board."""
        from verenigingen.utils.notification_helpers import send_volunteer_email

        chapter_name = self.parent

        send_volunteer_email(
            volunteer=self.volunteer,
            template_name="chapter_board_notification",
            notification_key="chapter_board_added",
            subject=f"Board Appointment - {chapter_name}",
            extra_context={
                "chapter_name": chapter_name,
                "board_position": self.chapter_role,
                "from_date": frappe.utils.formatdate(self.from_date),
            },
            reference_doctype="Chapter Board Member",
            reference_name=self.name,
        )

    def _send_board_removed_notification(self):
        """Send notification when a volunteer is removed from the board."""
        from verenigingen.utils.notification_helpers import send_volunteer_email

        chapter_name = self.parent

        send_volunteer_email(
            volunteer=self.volunteer,
            template_name="chapter_board_notification",
            notification_key="chapter_board_removed",
            subject=f"Board Position Ended - {chapter_name}",
            extra_context={
                "chapter_name": chapter_name,
                "board_position": self.chapter_role,
                "to_date": frappe.utils.formatdate(self.to_date) if self.to_date else frappe.utils.today(),
            },
            reference_doctype="Chapter Board Member",
            reference_name=self.name,
        )


def withdraw_board_member_role_if_unseated(volunteer: str, exclude_row: str = None) -> None:
    """Drop the Chapter Board Member role unless the volunteer still holds a live seat.

    Split out of ChapterBoardMember.remove_board_member_role() so BoardManager can run
    the same decision from Chapter.on_update, i.e. *after* the child rows are written.
    Run from validate() the decision reads a database that still shows the seat being
    withdrawn and — worse — the User.save() below is undone by Frappe itself: with a
    board role profile still attached, User.populate_role_profile_roles() resets
    ``roles`` to exactly the attached profiles' roles, putting the role straight back.
    See issue #211.

    Args:
        volunteer: Volunteer whose board access is being re-evaluated.
        exclude_row: Chapter Board Member row to ignore when counting live seats. Pass
            the row's own name from a row controller hook (the row is still in the
            database there); pass None once the parent save has persisted the change.
    """
    if not volunteer:
        return

    volunteer_doc = frappe.get_doc("Volunteer", volunteer)
    if not volunteer_doc.member:
        return

    user = frappe.db.get_value("Member", volunteer_doc.member, "user")
    if not user:
        return

    # Frappe's "is" filter operator accepts only "set" / "not set"; "null"
    # was rejected with `'is' operator only supports 'set' and 'not set'`.
    # The DocType is "Chapter Board Member" — "Verenigingen Chapter Board
    # Member" is the role name, not the DocType.
    open_ended = {"volunteer": volunteer, "is_active": 1, "to_date": ["is", "not set"]}
    future_dated = {"volunteer": volunteer, "is_active": 1, "to_date": [">=", frappe.utils.today()]}
    if exclude_row:
        open_ended["name"] = ["!=", exclude_row]
        future_dated["name"] = ["!=", exclude_row]

    total_active_positions = frappe.db.count("Chapter Board Member", open_ended) + frappe.db.count(
        "Chapter Board Member", future_dated
    )

    # Only remove the role if they are not on any other active board
    if total_active_positions:
        return

    # Has Role is a child table with no permissions defined — direct
    # delete fails for every user (including System Manager and the
    # background service user). Remove the role row from the parent
    # User document and save it instead, mirroring assign_board_member_role.
    if not frappe.db.exists("Has Role", {"parent": user, "role": "Verenigingen Chapter Board Member"}):
        return

    user_doc = frappe.get_doc("User", user)
    existing = {d.role: d for d in user_doc.roles}
    row_to_remove = existing.get("Verenigingen Chapter Board Member")
    if not row_to_remove:
        return
    user_doc.roles.remove(row_to_remove)

    save_result = secure_document_operation(
        operation="save",
        doc=user_doc,
        justification=f"Remove Chapter Board Member role from user {user} (no longer on any board)",
        required_permissions=["User:write"],
    )

    if save_result.success:
        frappe.msgprint(f"Removed Chapter Board Member role from {user}")
    else:
        # Report what actually failed rather than assuming a permission refusal:
        # secure_document_operation() flattens every non-fatal exception into
        # success=False, and this log is the only record of it.
        frappe.log_error(
            f"Could not remove board member role from user {user}: "
            f"{'; '.join(save_result.errors) or 'no reason reported'}"
        )
