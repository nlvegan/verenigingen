"""
Chapter Event Subscribers

Background job handlers for chapter status and lifecycle change events.
These handle the actual business logic triggered by chapter status transitions.
"""

import time

import frappe
from frappe import _


def handle_board_role_assignments(event_name, event_data):
    """
    Handle role profile assignments when board membership changes.

    Assigns/removes appropriate role profiles based on board positions.
    """
    try:
        chapter_name = event_data.get("chapter")
        volunteer = event_data.get("volunteer")
        action = event_data.get("action")  # added, removed, role_changed
        role = event_data.get("role")
        old_role = event_data.get("old_role")

        if not chapter_name or not volunteer:
            frappe.logger("events").warning("Missing chapter or volunteer in board role assignment event")
            return

        chapter = frappe.get_doc("Chapter", chapter_name)

        # Handle different board change actions
        if action == "added":
            _assign_board_role_profile(chapter, volunteer, role)
        elif action == "removed":
            _remove_board_role_profile(chapter, volunteer, old_role)
        elif action == "role_changed":
            _update_board_role_profile(chapter, volunteer, old_role, role)

        frappe.logger("events").info(f"Processed board role assignment for {volunteer} in {chapter_name}")

    except Exception as e:
        frappe.log_error(
            f"Failed to handle board role assignment: {str(e)}", "Chapter Board Role Assignment Error"
        )


def handle_board_notifications(event_name, event_data):
    """
    Handle notification sending for board changes.

    Sends appropriate emails to board members, chapter members, and administrators.
    """
    try:
        chapter_name = event_data.get("chapter")
        volunteer = event_data.get("volunteer")
        action = event_data.get("action")
        role = event_data.get("role")

        if not chapter_name or not volunteer:
            return

        chapter = frappe.get_doc("Chapter", chapter_name)

        # Send notifications based on action
        if action == "added":
            _send_board_member_added_notification(chapter, volunteer, role)
        elif action == "removed":
            _send_board_member_removed_notification(chapter, volunteer, role)
        elif action == "role_changed":
            old_role = event_data.get("old_role")
            _send_board_role_changed_notification(chapter, volunteer, old_role, role)

        frappe.logger("events").info(f"Sent board notifications for {volunteer} in {chapter_name}")

    except Exception as e:
        frappe.log_error(f"Failed to send board notifications: {str(e)}", "Chapter Board Notification Error")


def handle_volunteer_sync(event_name, event_data):
    """
    Handle synchronization with volunteer system when board changes.

    Updates volunteer records and assignment history.
    """
    try:
        chapter_name = event_data.get("chapter")
        volunteer = event_data.get("volunteer")
        action = event_data.get("action")

        if not chapter_name or not volunteer:
            return

        chapter = frappe.get_doc("Chapter", chapter_name)

        # Use the chapter's volunteer integration manager
        if action in ["added", "removed", "role_changed"]:
            chapter.volunteer_integration_manager.sync_board_members_with_volunteer_system()

        frappe.logger("events").info(f"Synced volunteer system for {volunteer} in {chapter_name}")

    except Exception as e:
        frappe.log_error(f"Failed to sync volunteer system: {str(e)}", "Chapter Volunteer Sync Error")


def handle_membership_notifications(event_name, event_data):
    """
    Handle notifications for chapter membership changes.

    Sends welcome/farewell messages to members and chapter administrators.
    """
    try:
        chapter_name = event_data.get("chapter")
        member = event_data.get("member")
        action = event_data.get("action")  # joined, left
        reason = event_data.get("reason")

        if not chapter_name or not member:
            return

        chapter = frappe.get_doc("Chapter", chapter_name)
        member_doc = frappe.get_doc("Member", member)

        # Send notifications based on action
        if action == "joined":
            _send_member_welcome_notification(chapter, member_doc)
        elif action == "left":
            _send_member_farewell_notification(chapter, member_doc, reason)

        frappe.logger("events").info(f"Sent membership notifications for {member} in {chapter_name}")

    except Exception as e:
        frappe.log_error(
            f"Failed to send membership notifications: {str(e)}", "Chapter Membership Notification Error"
        )


def handle_member_role_updates(event_name, event_data):
    """
    Handle member role updates when chapter membership changes.

    Updates member permissions and access levels.
    """
    try:
        chapter_name = event_data.get("chapter")
        member = event_data.get("member")
        action = event_data.get("action")

        if not chapter_name or not member:
            return

        member_doc = frappe.get_doc("Member", member)

        # Update member's chapter-related permissions
        if action == "joined":
            _grant_chapter_member_permissions(chapter_name, member_doc)
        elif action == "left":
            _revoke_chapter_member_permissions(chapter_name, member_doc)

        frappe.logger("events").info(f"Updated member roles for {member} in {chapter_name}")

    except Exception as e:
        frappe.log_error(f"Failed to update member roles: {str(e)}", "Chapter Member Role Update Error")


def handle_cache_invalidation(event_name, event_data):
    """
    Handle cache invalidation for chapter changes.

    Clears relevant caches when chapter data changes.
    """
    try:
        chapter_name = event_data.get("chapter")

        if not chapter_name:
            return

        # Clear chapter-specific caches
        frappe.cache().delete_keys(f"chapter_*_{chapter_name}")
        frappe.cache().delete_keys("chapter_list_*")
        frappe.cache().delete_keys("member_chapters_*")

        # Clear global chapter statistics cache
        frappe.cache().delete_key("chapter_statistics")

        frappe.logger("events").info(f"Cleared caches for chapter {chapter_name}")

    except Exception as e:
        frappe.log_error(f"Failed to clear caches: {str(e)}", "Chapter Cache Invalidation Error")


def handle_settings_notifications(event_name, event_data):
    """
    Handle notifications for chapter settings changes.

    Notifies relevant parties about configuration updates.
    """
    try:
        chapter_name = event_data.get("chapter")
        changed_fields = event_data.get("changed_fields", [])

        if not chapter_name or not changed_fields:
            return

        chapter = frappe.get_doc("Chapter", chapter_name)

        # Notify board members about significant setting changes
        important_fields = ["published", "enable_board_role_specific_profiles", "default_board_role_profile"]

        if any(field in changed_fields for field in important_fields):
            _send_settings_change_notification(chapter, changed_fields)

        frappe.logger("events").info(f"Sent settings notifications for {chapter_name}")

    except Exception as e:
        frappe.log_error(
            f"Failed to send settings notifications: {str(e)}", "Chapter Settings Notification Error"
        )


def handle_permissions_updates(event_name, event_data):
    """
    Handle permission updates when chapter settings change.

    Updates user permissions based on new configuration.
    """
    try:
        chapter_name = event_data.get("chapter")
        changed_fields = event_data.get("changed_fields", [])

        if not chapter_name:
            return

        # Update permissions if role-related settings changed
        role_fields = [
            "enable_board_role_specific_profiles",
            "default_board_role_profile",
            "board_role_specific_profiles",
        ]

        if any(field in changed_fields for field in role_fields):
            _update_chapter_permissions(chapter_name)

        frappe.logger("events").info(f"Updated permissions for chapter {chapter_name}")

    except Exception as e:
        frappe.log_error(f"Failed to update permissions: {str(e)}", "Chapter Permissions Update Error")


def handle_website_updates(event_name, event_data):
    """
    Handle website updates when chapter settings change.

    Updates public website content and visibility.
    """
    try:
        chapter_name = event_data.get("chapter")
        changed_fields = event_data.get("changed_fields", [])

        if not chapter_name:
            return

        # Update website if public-facing fields changed
        website_fields = ["published", "introduction", "image", "route"]

        if any(field in changed_fields for field in website_fields):
            _update_chapter_website(chapter_name)

        frappe.logger("events").info(f"Updated website for chapter {chapter_name}")

    except Exception as e:
        frappe.log_error(f"Failed to update website: {str(e)}", "Chapter Website Update Error")


# Helper functions for specific operations


def _assign_board_role_profile(chapter, volunteer, role):
    """Assign role profile to new board member"""
    from verenigingen.utils.chapter_role_profile_manager import assign_role_profile_to_board_member

    volunteer_doc = frappe.get_doc("Volunteer", volunteer)
    if volunteer_doc.member:
        member_doc = frappe.get_doc("Member", volunteer_doc.member)
        if member_doc.user:
            assign_role_profile_to_board_member(chapter.name, volunteer, role)


def _remove_board_role_profile(chapter, volunteer, old_role):
    """Remove role profile from former board member"""
    from verenigingen.utils.chapter_role_profile_manager import remove_role_profile_from_board_member

    volunteer_doc = frappe.get_doc("Volunteer", volunteer)
    if volunteer_doc.member:
        member_doc = frappe.get_doc("Member", volunteer_doc.member)
        if member_doc.user:
            remove_role_profile_from_board_member(chapter.name, volunteer, old_role)


def _update_board_role_profile(chapter, volunteer, old_role, new_role):
    """Update role profile for board member with changed role"""
    _remove_board_role_profile(chapter, volunteer, old_role)
    _assign_board_role_profile(chapter, volunteer, new_role)


def _send_board_member_added_notification(chapter, volunteer, role):
    """Send notification when board member is added"""
    volunteer_doc = frappe.get_doc("Volunteer", volunteer)
    if volunteer_doc.member:
        member_doc = frappe.get_doc("Member", volunteer_doc.member)

        if member_doc.email:
            subject = f"Board Appointment - {chapter.name}"
            message = f"""
            Dear {member_doc.get_full_name()},

            Congratulations! You have been appointed to the board of {chapter.name} as {role}.

            Welcome to the team!

            Best regards,
            The Verenigingen Team
            """

            frappe.sendmail(recipients=[member_doc.email], subject=subject, message=message)


def _send_board_member_removed_notification(chapter, volunteer, role):
    """Send notification when board member is removed"""
    volunteer_doc = frappe.get_doc("Volunteer", volunteer)
    if volunteer_doc.member:
        member_doc = frappe.get_doc("Member", volunteer_doc.member)

        if member_doc.email:
            subject = f"Board Tenure Ended - {chapter.name}"
            message = f"""
            Dear {member_doc.get_full_name()},

            Your tenure as {role} on the board of {chapter.name} has ended.

            Thank you for your service!

            Best regards,
            The Verenigingen Team
            """

            frappe.sendmail(recipients=[member_doc.email], subject=subject, message=message)


def _send_board_role_changed_notification(chapter, volunteer, old_role, new_role):
    """Send notification when board member role changes"""
    volunteer_doc = frappe.get_doc("Volunteer", volunteer)
    if volunteer_doc.member:
        member_doc = frappe.get_doc("Member", volunteer_doc.member)

        if member_doc.email:
            subject = f"Board Role Update - {chapter.name}"
            message = f"""
            Dear {member_doc.get_full_name()},

            Your role on the board of {chapter.name} has been updated from {old_role} to {new_role}.

            Best regards,
            The Verenigingen Team
            """

            frappe.sendmail(recipients=[member_doc.email], subject=subject, message=message)


def _send_member_welcome_notification(chapter, member_doc):
    """Send welcome notification to new chapter member"""
    if member_doc.email:
        subject = f"Welcome to {chapter.name}"
        message = f"""
        Dear {member_doc.get_full_name()},

        Welcome to {chapter.name}! We're excited to have you as part of our chapter.

        {chapter.introduction or ""}

        Best regards,
        The {chapter.name} Team
        """

        frappe.sendmail(recipients=[member_doc.email], subject=subject, message=message)


def _send_member_farewell_notification(chapter, member_doc, reason):
    """Send farewell notification to departing chapter member"""
    if member_doc.email:
        subject = f"Farewell from {chapter.name}"
        message = f"""
        Dear {member_doc.get_full_name()},

        We're sorry to see you leave {chapter.name}. Thank you for being part of our community.

        {f"Reason: {reason}" if reason else ""}

        You're always welcome back!

        Best regards,
        The {chapter.name} Team
        """

        frappe.sendmail(recipients=[member_doc.email], subject=subject, message=message)


def _grant_chapter_member_permissions(chapter_name, member_doc):
    """Grant chapter-specific permissions to new member"""
    try:
        if not member_doc.user:
            return

        # Grant chapter member permissions
        from frappe.permissions import add_user_permission

        # Add user permission for the chapter
        if not frappe.db.exists(
            "User Permission", {"user": member_doc.user, "allow": "Chapter", "for_value": chapter_name}
        ):
            add_user_permission("Chapter", chapter_name, member_doc.user)

        # Add basic chapter member role if not present
        user_doc = frappe.get_doc("User", member_doc.user)
        user_roles = [role.role for role in user_doc.roles]
        if "Chapter Member" not in user_roles:
            user_doc.append("roles", {"role": "Chapter Member"})
            user_doc.save()

        frappe.logger("events").info(f"Granted chapter permissions to {member_doc.user} for {chapter_name}")

    except Exception as e:
        frappe.logger("events").warning(f"Failed to grant chapter permissions: {str(e)}")


def _revoke_chapter_member_permissions(chapter_name, member_doc):
    """Revoke chapter-specific permissions from former member"""
    try:
        if not member_doc.user:
            return

        # Remove chapter-specific user permission
        existing_permission = frappe.db.exists(
            "User Permission", {"user": member_doc.user, "allow": "Chapter", "for_value": chapter_name}
        )

        if existing_permission:
            frappe.delete_doc("User Permission", existing_permission)

        # Check if user has other chapter memberships
        other_chapters = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabChapter Member` cm
            WHERE cm.member = %s AND cm.enabled = 1 AND cm.parent != %s
        """,
            (member_doc.name, chapter_name),
            as_dict=True,
        )

        # If no other chapter memberships, remove Chapter Member role
        if not other_chapters or other_chapters[0].count == 0:
            user_doc = frappe.get_doc("User", member_doc.user)
            user_doc.roles = [role for role in user_doc.roles if role.role != "Chapter Member"]
            user_doc.save()

        frappe.logger("events").info(f"Revoked chapter permissions for {member_doc.user} from {chapter_name}")

    except Exception as e:
        frappe.logger("events").warning(f"Failed to revoke chapter permissions: {str(e)}")


def _send_settings_change_notification(chapter, changed_fields):
    """Send notification about chapter settings changes to board members"""
    board_members = chapter.get_board_members()

    for board_member in board_members:
        if board_member.get("email"):
            subject = f"Chapter Settings Updated - {chapter.name}"
            message = f"""
            Dear Board Member,

            The settings for {chapter.name} have been updated.

            Changed settings: {', '.join(changed_fields)}

            Please review the changes in the chapter administration panel.

            Best regards,
            The Verenigingen System
            """

            frappe.sendmail(recipients=[board_member.get("email")], subject=subject, message=message)


def _update_chapter_permissions(chapter_name):
    """Update chapter permissions based on new settings"""
    try:
        chapter = frappe.get_doc("Chapter", chapter_name)

        # Update board member role profiles based on new settings
        for board_member in chapter.board_members or []:
            if board_member.is_active and board_member.volunteer:
                volunteer_doc = frappe.get_doc("Volunteer", board_member.volunteer)
                if volunteer_doc.member:
                    member_doc = frappe.get_doc("Member", volunteer_doc.member)
                    if member_doc.user:
                        # Re-assign role profiles based on new chapter configuration
                        _assign_board_role_profile(chapter, board_member.volunteer, board_member.chapter_role)

        frappe.logger("events").info(f"Updated chapter permissions for {chapter_name}")

    except Exception as e:
        frappe.logger("events").warning(f"Failed to update chapter permissions: {str(e)}")


def _update_chapter_website(chapter_name):
    """Update chapter website content"""
    try:
        # Clear website cache for this chapter
        frappe.cache().delete_keys(f"website_*{chapter_name}*")
        frappe.cache().delete_keys("chapters_*")

        # Trigger website rebuild if needed
        chapter = frappe.get_doc("Chapter", chapter_name)
        if chapter.published:
            chapter.clear_cache()

            # Update website route if needed
            if hasattr(chapter, "route") and chapter.route:
                from frappe.website.render import clear_cache

                clear_cache(chapter.route)

        frappe.logger("events").info(f"Updated website for chapter {chapter_name}")

    except Exception as e:
        frappe.logger("events").warning(f"Failed to update website for {chapter_name}: {str(e)}")
