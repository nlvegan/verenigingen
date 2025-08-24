# verenigingen/verenigingen/doctype/chapter_board_member/chapter_board_member.py
import frappe
import frappe.utils
from frappe.model.document import Document

from verenigingen.permissions import clear_permission_cache


class ChapterBoardMember(Document):
    def after_insert(self):
        """Assign Chapter Board Member role when someone joins a board"""
        self.assign_board_member_role()
        # Clear permission cache when board membership changes
        clear_permission_cache()

    def on_trash(self):
        """Remove Chapter Board Member role if no longer on any board"""
        self.remove_board_member_role()
        # Clear permission cache when board membership changes
        clear_permission_cache()

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
            user_doc.append("roles", {
                "role": "Verenigingen Chapter Board Member",
            })
            user_doc.save(ignore_permissions=True)

            frappe.msgprint(f"Assigned Chapter Board Member role to {user}")

    def remove_board_member_role(self):
        """Remove Chapter Board Member role if user is no longer on any board"""
        if not self.volunteer:
            return

        # Get the member and user associated with this volunteer
        volunteer_doc = frappe.get_doc("Volunteer", self.volunteer)
        if not volunteer_doc.member:
            return

        user = frappe.db.get_value("Member", volunteer_doc.member, "user")
        if not user:
            return

        # Check if this volunteer is on any other ACTIVE boards
        active_board_positions = frappe.db.count(
            "Verenigingen Chapter Board Member",
            {
                "volunteer": self.volunteer,
                "name": ["!=", self.name],
                "is_active": 1,
                "to_date": ["is", "null"],
            },
        )

        # Also check for positions with future end dates
        future_positions = frappe.db.count(
            "Verenigingen Chapter Board Member",
            {
                "volunteer": self.volunteer,
                "name": ["!=", self.name],
                "is_active": 1,
                "to_date": [">=", frappe.utils.today()],
            },
        )

        total_active_positions = active_board_positions + future_positions

        # Only remove role if they're not on any other active boards
        if total_active_positions == 0:
            # Remove the role assignment
            role_assignment = frappe.db.exists(
                "Has Role", {"parent": user, "role": "Verenigingen Chapter Board Member"}
            )

            if role_assignment:
                frappe.delete_doc("Has Role", role_assignment, ignore_permissions=True)
                frappe.msgprint(f"Removed Chapter Board Member role from {user}")

    def validate(self):
        """Ensure volunteer/member has a linked user account"""
        if self.volunteer:
            volunteer_doc = frappe.get_doc("Volunteer", self.volunteer)
            if volunteer_doc.member:
                user = frappe.db.get_value("Member", volunteer_doc.member, "user")
                if not user:
                    frappe.msgprint(
                        f"Warning: Volunteer {self.volunteer} does not have a linked user account. Board member role cannot be assigned.",
                        indicator="orange",
                    )
