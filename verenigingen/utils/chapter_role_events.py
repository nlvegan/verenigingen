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

from verenigingen.permissions import assign_chapter_board_role, get_user_chapter_board_positions


def on_chapter_board_member_after_insert(doc, method):
    """
    Event handler for Chapter Board Member creation
    Automatically assigns Chapter Board Member system role
    """
    try:
        frappe.logger().info(f"Chapter Board Member created: {doc.name}")

        if doc.is_active and doc.volunteer:
            # Get the volunteer's member and user email
            volunteer_doc = frappe.get_doc("Volunteer", doc.volunteer)
            if volunteer_doc.member:
                member_doc = frappe.get_doc("Member", volunteer_doc.member)
                user_email = member_doc.user or member_doc.email

                if user_email:
                    success = assign_chapter_board_role(user_email)
                    if success:
                        frappe.logger().info(
                            f"Assigned Chapter Board Member role to {user_email} for board position {doc.name}"
                        )
                    else:
                        frappe.logger().warning(f"Failed to assign Chapter Board Member role to {user_email}")

    except Exception as e:
        frappe.log_error(f"Error in chapter board member after insert handler: {str(e)}")


def on_chapter_board_member_on_update(doc, method):
    """
    Event handler for Chapter Board Member updates
    Manages role assignment based on is_active status changes
    """
    try:
        frappe.logger().info(f"Chapter Board Member updated: {doc.name}")

        if doc.volunteer:
            # Get the volunteer's member and user email
            volunteer_doc = frappe.get_doc("Volunteer", doc.volunteer)
            if volunteer_doc.member:
                member_doc = frappe.get_doc("Member", volunteer_doc.member)
                user_email = member_doc.user or member_doc.email

                if user_email:
                    # Always re-evaluate role assignment based on current board positions
                    assign_chapter_board_role(user_email)

                    status = "activated" if doc.is_active else "deactivated"
                    frappe.logger().info(
                        f"Re-evaluated Chapter Board Member role for {user_email} after board position {status}"
                    )

    except Exception as e:
        frappe.log_error(f"Error in chapter board member update handler: {str(e)}")


def on_chapter_board_member_on_trash(doc, method):
    """
    Event handler for Chapter Board Member deletion
    Removes Chapter Board Member system role if no other active positions exist
    """
    try:
        frappe.logger().info(f"Chapter Board Member deleted: {doc.name}")

        if doc.volunteer:
            # Get the volunteer's member and user email
            volunteer_doc = frappe.get_doc("Volunteer", doc.volunteer)
            if volunteer_doc.member:
                member_doc = frappe.get_doc("Member", volunteer_doc.member)
                user_email = member_doc.user or member_doc.email

                if user_email:
                    # Re-evaluate role assignment (will remove role if no active positions)
                    assign_chapter_board_role(user_email)
                    frappe.logger().info(
                        f"Re-evaluated Chapter Board Member role for {user_email} after board position deletion"
                    )

    except Exception as e:
        frappe.log_error(f"Error in chapter board member trash handler: {str(e)}")


def on_volunteer_on_update(doc, method):
    """
    Event handler for Volunteer updates
    Re-evaluates board roles if member linkage changes
    """
    try:
        # Check if the member field changed
        if doc.has_value_changed("member"):
            old_member = doc._doc_before_save.get("member") if doc._doc_before_save else None
            new_member = doc.member

            # Handle old member - remove board role if they lost their volunteer record
            if old_member:
                old_member_doc = frappe.get_doc("Member", old_member)
                old_user_email = old_member_doc.user or old_member_doc.email

                if old_user_email:
                    assign_chapter_board_role(old_user_email)
                    frappe.logger().info(f"Re-evaluated board role for old member {old_user_email}")

            # Handle new member - assign board role if they have board positions
            if new_member:
                new_member_doc = frappe.get_doc("Member", new_member)
                new_user_email = new_member_doc.user or new_member_doc.email

                if new_user_email:
                    assign_chapter_board_role(new_user_email)
                    frappe.logger().info(f"Re-evaluated board role for new member {new_user_email}")

    except Exception as e:
        frappe.log_error(f"Error in volunteer update handler: {str(e)}")


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

    except Exception as e:
        frappe.log_error(f"Error in member update handler: {str(e)}")


@frappe.whitelist()
def validate_volunteer_expense_approval(expense_name, action):
    """
    Validate volunteer expense approval actions
    Only treasurers can approve/reject expenses
    """
    try:
        from verenigingen.permissions import can_approve_volunteer_expense

        expense_doc = frappe.get_doc("Volunteer Expense", expense_name)
        user = frappe.session.user

        if action in ["approve", "reject"] and not can_approve_volunteer_expense(expense_doc, user):
            frappe.throw("Only treasurers can approve or reject volunteer expenses.", frappe.PermissionError)

        return True

    except Exception as e:
        frappe.log_error(f"Error validating expense approval: {str(e)}")
        frappe.throw(f"Error validating approval permissions: {str(e)}")


def before_volunteer_expense_submit(doc, method):
    """
    Before submit handler for Volunteer Expense
    Validates approval permissions before status changes
    """
    try:
        # If status is being changed to Approved or Rejected, validate permissions
        if doc.status in ["Approved", "Rejected"]:
            from verenigingen.permissions import can_approve_volunteer_expense

            if not can_approve_volunteer_expense(doc):
                frappe.throw(
                    "Only treasurers can approve or reject volunteer expenses.", frappe.PermissionError
                )

            # Set approval metadata
            if not doc.approved_by:
                doc.approved_by = frappe.session.user
            if not doc.approved_on:
                doc.approved_on = frappe.utils.now()

    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.log_error(f"Error in volunteer expense before submit handler: {str(e)}")
        frappe.throw(f"Error validating expense approval: {str(e)}")


def on_chapter_role_on_update(doc, method):
    """
    Event handler for Chapter Role updates
    Re-evaluates board member roles if permissions_level changes
    """
    try:
        # Check if permissions_level changed - this affects treasurer status
        if doc.has_value_changed("permissions_level") or doc.has_value_changed("is_active"):
            # Get all board members with this chapter role
            board_members = frappe.get_all(
                "Verenigingen Chapter Board Member",
                filters={"chapter_role": doc.name, "is_active": 1},
                fields=["volunteer"],
            )

            for board_member in board_members:
                if board_member.volunteer:
                    volunteer_doc = frappe.get_doc("Volunteer", board_member.volunteer)
                    if volunteer_doc.member:
                        member_doc = frappe.get_doc("Member", volunteer_doc.member)
                        user_email = member_doc.user or member_doc.email

                        if user_email:
                            assign_chapter_board_role(user_email)
                            frappe.logger().info(
                                f"Re-evaluated board role for {user_email} due to chapter role changes"
                            )

    except Exception as e:
        frappe.log_error(f"Error in chapter role update handler: {str(e)}")


@frappe.whitelist()
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
def get_user_board_summary(user_email=None):
    """
    Get summary of user's board positions and permissions
    Useful for debugging and administration
    """
    try:
        if not user_email:
            user_email = frappe.session.user

        # Get user's member record
        user_member = frappe.db.get_value("Member", {"user": user_email}, "name")
        if not user_member:
            user_member = frappe.db.get_value("Member", {"email": user_email}, "name")

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
