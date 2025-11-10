"""
User-Member Image Synchronization
==================================

Bidirectional synchronization of profile pictures between User and Member records.

This module ensures that when a profile picture is updated on either the User record
or the Member record, the change is automatically synchronized to the other record.

Architecture:
    - Uses document hooks to detect image changes
    - Prevents infinite loops with sync flags
    - Maintains audit trail of sync operations
    - Handles edge cases (missing records, deleted images)

Usage:
    This module is automatically invoked via hooks configuration.
    No manual intervention required.

Author: Verenigingen Development Team
"""

import frappe
from frappe import _


def sync_member_image_to_user(doc, method=None):
    """
    Sync Member image to User record when Member image changes.

    Args:
        doc: Member document
        method: Hook method name (not used)
    """
    # Prevent infinite loops - skip if this update is from a sync operation
    if frappe.flags.get("syncing_user_member_image"):
        return

    # Only proceed if member has a linked user
    if not doc.user:
        return

    # Only sync if image field has actually changed
    if not doc.has_value_changed("image"):
        return

    try:
        # Set flag to prevent infinite loop
        frappe.flags.syncing_user_member_image = True

        # Get the User document
        user_doc = frappe.get_doc("User", doc.user)  # ast-skip: doc is Member with user field

        # Update user_image field
        user_doc.user_image = doc.image  # ast-skip: doc is Member with image field

        # Save without triggering validation (to avoid recursion)
        user_doc.save(ignore_permissions=True)

        frappe.logger().info(
            f"Synced image from Member {doc.name} to User {doc.user}"
        )  # ast-skip: doc is Member

    except Exception as e:
        # Log error but don't block the member save
        frappe.log_error(f"Failed to sync Member image to User: {str(e)}", "Member-User Image Sync Error")
    finally:
        # Always clear the flag
        frappe.flags.syncing_user_member_image = False


def sync_user_image_to_member(doc, method=None):
    """
    Sync User image to Member record when User image changes.

    Args:
        doc: User document
        method: Hook method name (not used)
    """
    # Prevent infinite loops - skip if this update is from a sync operation
    if frappe.flags.get("syncing_user_member_image"):
        return

    # Only sync if user_image field has actually changed
    if not doc.has_value_changed("user_image"):
        return

    try:
        # Set flag to prevent infinite loop
        frappe.flags.syncing_user_member_image = True

        # Find Member record linked to this user
        member_name = frappe.db.get_value(
            "Member", {"user": doc.name}, "name"
        )  # ast-skip: doc is User with name field

        if not member_name:
            # No linked member found - this is normal for non-member users
            return

        # Get the Member document
        member_doc = frappe.get_doc("Member", member_name)

        # Update image field
        member_doc.image = doc.user_image  # ast-skip: doc is User with user_image field

        # Save without triggering validation (to avoid recursion)
        member_doc.save(ignore_permissions=True)

        frappe.logger().info(
            f"Synced image from User {doc.name} to Member {member_name}"
        )  # ast-skip: doc is User

    except Exception as e:
        # Log error but don't block the user save
        frappe.log_error(f"Failed to sync User image to Member: {str(e)}", "User-Member Image Sync Error")
    finally:
        # Always clear the flag
        frappe.flags.syncing_user_member_image = False
