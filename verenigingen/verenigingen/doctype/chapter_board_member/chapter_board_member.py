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
                frappe.log_error(f"Could not assign board member role to user {user}: Permission denied")

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
                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                delete_result = secure_document_operation(
                    operation="delete",
                    doc=frappe.get_doc("Has Role", role_assignment),
                    justification=f"Remove Chapter Board Member role from user {user} (no longer on any board)",
                    required_permissions=["Has Role:delete"],
                )

                if delete_result.success:
                    frappe.msgprint(f"Removed Chapter Board Member role from {user}")
                else:
                    frappe.log_error(
                        f"Could not remove board member role from user {user}: Permission denied"
                    )

    def validate(self):
        """Validate board member data and relationships"""
        self.validate_required_fields()
        self.validate_volunteer_exists()
        self.validate_role_exists()
        self.validate_date_range()
        self.validate_active_status()
        self.validate_email_format()
        self.validate_user_account()

    def validate_required_fields(self):
        """Validate required fields are present"""
        if not self.volunteer:
            frappe.throw("Volunteer is required for board member")
        if not self.chapter_role:
            frappe.throw("Chapter Role is required for board member")
        if not self.from_date:
            frappe.throw("Start Date (from_date) is required for board member")

    def validate_volunteer_exists(self):
        """Validate that the volunteer record exists"""
        if self.volunteer and not frappe.db.exists("Volunteer", self.volunteer):
            frappe.throw(f"Volunteer {self.volunteer} does not exist")

    def validate_role_exists(self):
        """Validate that the chapter role exists"""
        if self.chapter_role and not frappe.db.exists("Chapter Role", self.chapter_role):
            frappe.throw(f"Chapter Role {self.chapter_role} does not exist")

    def validate_date_range(self):
        """Validate start and end date logic"""
        if self.from_date and self.to_date:
            from_date = frappe.utils.getdate(self.from_date)
            to_date = frappe.utils.getdate(self.to_date)
            if to_date < from_date:
                frappe.throw(f"End Date ({to_date}) cannot be before Start Date ({from_date})")

    def validate_active_status(self):
        """Validate active status consistency with dates"""
        if self.is_active and self.to_date:
            to_date = frappe.utils.getdate(self.to_date)
            if to_date < frappe.utils.getdate(frappe.utils.today()):
                frappe.throw(f"Board member cannot be active with an end date ({to_date}) in the past")

    def validate_email_format(self):
        """Validate email format if provided"""
        if self.email:
            import re

            email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if not re.match(email_pattern, self.email):
                frappe.throw(f"Invalid email format: {self.email}")

    def validate_user_account(self):
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
