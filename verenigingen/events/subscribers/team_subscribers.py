"""
Team Event Subscribers

Background job handlers for team status and lifecycle change events.
These handle the actual business logic triggered by team status transitions.
"""

import time

import frappe
from frappe import _


def handle_assignment_history_updates(event_name, event_data):
    """
    Handle assignment history updates when team membership changes.

    Updates volunteer assignment history based on team membership changes.
    """
    try:
        team_name = event_data.get("team")
        volunteer = event_data.get("volunteer")
        action = event_data.get("action")  # added, removed, role_changed
        role = event_data.get("role")
        old_role = event_data.get("old_role")
        from_date = event_data.get("from_date")
        to_date = event_data.get("to_date")

        if not team_name or not volunteer:
            frappe.logger("events").warning("Missing team or volunteer in assignment history event")
            return

        team = frappe.get_doc("Team", team_name)

        # Handle different membership actions
        if action == "added":
            team.add_team_assignment_history(volunteer, role, from_date)
        elif action == "removed":
            end_date = to_date or frappe.utils.today()
            team.complete_team_assignment_history(volunteer, old_role, from_date, end_date)
        elif action == "role_changed":
            # Complete old role and start new one
            change_date = frappe.utils.today()
            team.complete_team_assignment_history(volunteer, old_role, from_date, change_date)
            team.add_team_assignment_history(volunteer, role, change_date)

        frappe.logger("events").info(f"Updated assignment history for {volunteer} in {team_name}")

    except Exception as e:
        frappe.log_error(f"Failed to update assignment history: {str(e)}", "Team Assignment History Error")


def handle_role_profile_assignments(event_name, event_data):
    """
    Handle role profile assignments when team membership changes.

    Assigns/removes appropriate role profiles based on team positions.
    """
    try:
        team_name = event_data.get("team")
        volunteer = event_data.get("volunteer")
        action = event_data.get("action")
        role = event_data.get("role")
        old_role = event_data.get("old_role")

        if not team_name or not volunteer:
            return

        # Get the volunteer's user for role assignment
        volunteer_doc = frappe.get_doc("Volunteer", volunteer)
        if not volunteer_doc.member:
            return

        member_doc = frappe.get_doc("Member", volunteer_doc.member)
        if not member_doc.user:
            return

        # Handle role profile assignments based on action
        if action == "added":
            _assign_team_role_profile(team_name, member_doc.user, role)
        elif action == "removed":
            _remove_team_role_profile(team_name, member_doc.user, old_role)
        elif action == "role_changed":
            _remove_team_role_profile(team_name, member_doc.user, old_role)
            _assign_team_role_profile(team_name, member_doc.user, role)

        frappe.logger("events").info(f"Updated role profiles for {volunteer} in {team_name}")

    except Exception as e:
        frappe.log_error(f"Failed to update role profiles: {str(e)}", "Team Role Profile Error")


def handle_membership_notifications(event_name, event_data):
    """
    Handle notification sending for team membership changes.

    Sends appropriate emails to team members and administrators.
    """
    try:
        team_name = event_data.get("team")
        volunteer = event_data.get("volunteer")
        action = event_data.get("action")
        role = event_data.get("role")

        if not team_name or not volunteer:
            return

        team = frappe.get_doc("Team", team_name)
        volunteer_doc = frappe.get_doc("Volunteer", volunteer)

        # Send notifications based on action
        if action == "added":
            _send_team_member_added_notification(team, volunteer_doc, role)
        elif action == "removed":
            _send_team_member_removed_notification(team, volunteer_doc, role)
        elif action == "role_changed":
            old_role = event_data.get("old_role")
            _send_team_role_changed_notification(team, volunteer_doc, old_role, role)

        frappe.logger("events").info(f"Sent team notifications for {volunteer} in {team_name}")

    except Exception as e:
        frappe.log_error(f"Failed to send team notifications: {str(e)}", "Team Notification Error")


def handle_volunteer_integration(event_name, event_data):
    """
    Handle integration with volunteer system when team membership changes.

    Updates volunteer records and related systems.
    """
    try:
        team_name = event_data.get("team")
        volunteer = event_data.get("volunteer")
        action = event_data.get("action")

        if not team_name or not volunteer:
            return

        # Update volunteer's team affiliations
        volunteer_doc = frappe.get_doc("Volunteer", volunteer)

        if action == "added":
            _update_volunteer_team_affiliation(volunteer_doc, team_name, "added")
        elif action == "removed":
            _update_volunteer_team_affiliation(volunteer_doc, team_name, "removed")

        frappe.logger("events").info(f"Updated volunteer integration for {volunteer} in {team_name}")

    except Exception as e:
        frappe.log_error(
            f"Failed to update volunteer integration: {str(e)}", "Team Volunteer Integration Error"
        )


def handle_settings_notifications(event_name, event_data):
    """
    Handle notifications for team settings changes.

    Notifies relevant parties about configuration updates.
    """
    try:
        team_name = event_data.get("team")
        changed_fields = event_data.get("changed_fields", [])

        if not team_name or not changed_fields:
            return

        team = frappe.get_doc("Team", team_name)

        # Notify team members about significant setting changes
        important_fields = ["enable_role_profiles", "default_role_profile", "is_active"]

        if any(field in changed_fields for field in important_fields):
            _send_team_settings_notification(team, changed_fields)

        frappe.logger("events").info(f"Sent settings notifications for {team_name}")

    except Exception as e:
        frappe.log_error(
            f"Failed to send settings notifications: {str(e)}", "Team Settings Notification Error"
        )


def handle_permissions_updates(event_name, event_data):
    """
    Handle permission updates when team settings change.

    Updates user permissions based on new configuration.
    """
    try:
        team_name = event_data.get("team")
        changed_fields = event_data.get("changed_fields", [])

        if not team_name:
            return

        # Update permissions if role-related settings changed
        role_fields = ["enable_role_profiles", "default_role_profile"]

        if any(field in changed_fields for field in role_fields):
            _update_team_permissions(team_name)

        frappe.logger("events").info(f"Updated permissions for team {team_name}")

    except Exception as e:
        frappe.log_error(f"Failed to update permissions: {str(e)}", "Team Permissions Update Error")


def handle_cache_invalidation(event_name, event_data):
    """
    Handle cache invalidation for team changes.

    Clears relevant caches when team data changes.
    """
    try:
        team_name = event_data.get("team")

        if not team_name:
            return

        # Clear team-specific caches
        frappe.cache().delete_keys(f"team_*_{team_name}")
        frappe.cache().delete_keys("team_list_*")
        frappe.cache().delete_keys("volunteer_teams_*")

        # Clear global team statistics cache
        frappe.cache().delete_key("team_statistics")

        frappe.logger("events").info(f"Cleared caches for team {team_name}")

    except Exception as e:
        frappe.log_error(f"Failed to clear caches: {str(e)}", "Team Cache Invalidation Error")


def handle_leadership_notifications(event_name, event_data):
    """
    Handle notifications for team leadership changes.

    Notifies relevant parties about team lead transitions.
    """
    try:
        team_name = event_data.get("team")
        old_lead = event_data.get("old_lead")
        new_lead = event_data.get("new_lead")

        if not team_name:
            return

        team = frappe.get_doc("Team", team_name)

        # Send leadership transition notifications
        _send_leadership_change_notification(team, old_lead, new_lead)

        frappe.logger("events").info(f"Sent leadership notifications for {team_name}")

    except Exception as e:
        frappe.log_error(
            f"Failed to send leadership notifications: {str(e)}", "Team Leadership Notification Error"
        )


def handle_leadership_role_updates(event_name, event_data):
    """
    Handle role updates for team leadership changes.

    Updates permissions and access levels for new/former team leads.
    """
    try:
        team_name = event_data.get("team")
        old_lead = event_data.get("old_lead")
        new_lead = event_data.get("new_lead")

        if not team_name:
            return

        # Update role assignments for leadership change
        if old_lead:
            _revoke_team_lead_permissions(team_name, old_lead)

        if new_lead:
            _grant_team_lead_permissions(team_name, new_lead)

        frappe.logger("events").info(f"Updated leadership roles for {team_name}")

    except Exception as e:
        frappe.log_error(f"Failed to update leadership roles: {str(e)}", "Team Leadership Role Error")


def handle_team_lead_permissions(event_name, event_data):
    """
    Handle team lead permission updates.

    Manages special permissions for team leads.
    """
    try:
        team_name = event_data.get("team")
        new_lead = event_data.get("new_lead")

        if not team_name or not new_lead:
            return

        # Grant team lead specific permissions
        _update_team_lead_access(team_name, new_lead)

        frappe.logger("events").info(f"Updated team lead permissions for {team_name}")

    except Exception as e:
        frappe.log_error(f"Failed to update team lead permissions: {str(e)}", "Team Lead Permission Error")


# Helper functions for specific operations


def _assign_team_role_profile(team_name, user, role):
    """Assign role profile to team member"""
    try:
        # Get team configuration
        team = frappe.get_doc("Team", team_name)

        if not team.enable_role_profiles:
            return

        # Determine role profile to assign
        role_profile = None

        # Check for role-specific profile
        if hasattr(team, "team_role_specific_profiles"):
            for profile_assignment in team.team_role_specific_profiles or []:
                if profile_assignment.team_role == role:
                    role_profile = profile_assignment.role_profile
                    break

        # Fall back to default profile
        if not role_profile and team.default_role_profile:
            role_profile = team.default_role_profile

        if role_profile:
            user_doc = frappe.get_doc("User", user)
            if not user_doc.role_profile_name or user_doc.role_profile_name != role_profile:
                user_doc.role_profile_name = role_profile
                user_doc.save()
                frappe.logger("events").info(f"Assigned role profile {role_profile} to {user}")

    except Exception as e:
        frappe.logger("events").warning(f"Failed to assign role profile for {user}: {str(e)}")


def _remove_team_role_profile(team_name, user, role):
    """Remove role profile from former team member"""
    try:
        # Only remove if user has no other active team memberships
        active_teams = frappe.db.sql(
            """
            SELECT DISTINCT t.name
            FROM `tabTeam` t
            JOIN `tabTeam Member` tm ON tm.parent = t.name
            JOIN `tabVolunteer` v ON tm.volunteer = v.name
            JOIN `tabMember` m ON v.member = m.name
            WHERE m.user = %s AND tm.is_active = 1 AND t.name != %s
        """,
            (user, team_name),
        )

        if not active_teams:
            # User has no other active team memberships, remove role profile
            user_doc = frappe.get_doc("User", user)
            if user_doc.role_profile_name:
                user_doc.role_profile_name = None
                user_doc.save()
                frappe.logger("events").info(f"Removed role profile from {user}")

    except Exception as e:
        frappe.logger("events").warning(f"Failed to remove role profile for {user}: {str(e)}")


def _send_team_member_added_notification(team, volunteer_doc, role):
    """Send notification when team member is added"""
    if volunteer_doc.member:
        member_doc = frappe.get_doc("Member", volunteer_doc.member)
        if member_doc.email:
            subject = f"Team Assignment - {team.name}"
            message = f"""
            Dear {member_doc.get_full_name()},

            You have been assigned to the team "{team.name}" as {role}.

            Welcome to the team!

            Best regards,
            The Verenigingen Team
            """

            frappe.sendmail(recipients=[member_doc.email], subject=subject, message=message)


def _send_team_member_removed_notification(team, volunteer_doc, role):
    """Send notification when team member is removed"""
    if volunteer_doc.member:
        member_doc = frappe.get_doc("Member", volunteer_doc.member)
        if member_doc.email:
            subject = f"Team Assignment Ended - {team.name}"
            message = f"""
            Dear {member_doc.get_full_name()},

            Your assignment to the team "{team.name}" as {role} has ended.

            Thank you for your contribution!

            Best regards,
            The Verenigingen Team
            """

            frappe.sendmail(recipients=[member_doc.email], subject=subject, message=message)


def _send_team_role_changed_notification(team, volunteer_doc, old_role, new_role):
    """Send notification when team member role changes"""
    if volunteer_doc.member:
        member_doc = frappe.get_doc("Member", volunteer_doc.member)
        if member_doc.email:
            subject = f"Team Role Update - {team.name}"
            message = f"""
            Dear {member_doc.get_full_name()},

            Your role in the team "{team.name}" has been updated from {old_role} to {new_role}.

            Best regards,
            The Verenigingen Team
            """

            frappe.sendmail(recipients=[member_doc.email], subject=subject, message=message)


def _update_volunteer_team_affiliation(volunteer_doc, team_name, action):
    """Update volunteer's team affiliations"""
    try:
        # Update volunteer's team association tracking
        if action == "added":
            # Check if volunteer has team affiliations field
            if hasattr(volunteer_doc, "current_teams"):
                current_teams = volunteer_doc.current_teams or []
                if team_name not in current_teams:
                    current_teams.append(team_name)
                    volunteer_doc.current_teams = current_teams
                    volunteer_doc.save()

        elif action == "removed":
            # Remove team from volunteer's affiliations
            if hasattr(volunteer_doc, "current_teams"):
                current_teams = volunteer_doc.current_teams or []
                if team_name in current_teams:
                    current_teams.remove(team_name)
                    volunteer_doc.current_teams = current_teams
                    volunteer_doc.save()

        frappe.logger("events").info(
            f"Updated volunteer {volunteer_doc.name} team affiliation for {team_name}"
        )

    except Exception as e:
        frappe.logger("events").warning(f"Failed to update volunteer team affiliation: {str(e)}")


def _send_team_settings_notification(team, changed_fields):
    """Send notification about team settings changes"""
    # Get team members for notification
    team_members = team.team_members or []

    for member in team_members:
        if member.is_active and member.volunteer:
            volunteer_doc = frappe.get_doc("Volunteer", member.volunteer)
            if volunteer_doc.member:
                member_doc = frappe.get_doc("Member", volunteer_doc.member)
                if member_doc.email:
                    subject = f"Team Settings Updated - {team.name}"
                    message = f"""
                    Dear Team Member,

                    The settings for your team "{team.name}" have been updated.

                    Changed settings: {', '.join(changed_fields)}

                    Best regards,
                    The Verenigingen System
                    """

                    frappe.sendmail(recipients=[member_doc.email], subject=subject, message=message)


def _update_team_permissions(team_name):
    """Update team permissions based on new settings"""
    try:
        team = frappe.get_doc("Team", team_name)

        # Update permissions for all team members based on new settings
        for member in team.team_members or []:
            if member.is_active and member.volunteer:
                volunteer_doc = frappe.get_doc("Volunteer", member.volunteer)
                if volunteer_doc.member:
                    member_doc = frappe.get_doc("Member", volunteer_doc.member)
                    if member_doc.user:
                        # Re-assign role profiles based on new settings
                        _assign_team_role_profile(team_name, member_doc.user, member.team_role)

        frappe.logger("events").info(f"Updated team permissions for {team_name}")

    except Exception as e:
        frappe.logger("events").warning(f"Failed to update team permissions: {str(e)}")


def _send_leadership_change_notification(team, old_lead, new_lead):
    """Send notification about team leadership change"""
    try:
        # Notify team members about leadership change
        team_members = team.team_members or []

        for member in team_members:
            if member.is_active and member.volunteer:
                volunteer_doc = frappe.get_doc("Volunteer", member.volunteer)
                if volunteer_doc.member:
                    member_doc = frappe.get_doc("Member", volunteer_doc.member)
                    if member_doc.email:
                        subject = f"Team Leadership Change - {team.name}"

                        old_lead_name = "Previous leader"
                        new_lead_name = "New leader"

                        if old_lead:
                            try:
                                old_lead_doc = frappe.get_doc("User", old_lead)
                                old_lead_name = old_lead_doc.full_name or old_lead
                            except:
                                pass

                        if new_lead:
                            try:
                                new_lead_doc = frappe.get_doc("User", new_lead)
                                new_lead_name = new_lead_doc.full_name or new_lead
                            except:
                                pass

                        message = f"""
                        Dear Team Member,

                        There has been a leadership change in your team "{team.name}".

                        Previous leader: {old_lead_name}
                        New leader: {new_lead_name}

                        Best regards,
                        The Verenigingen Team
                        """

                        frappe.sendmail(recipients=[member_doc.email], subject=subject, message=message)

        frappe.logger("events").info(f"Sent leadership change notifications for {team.name}")

    except Exception as e:
        frappe.logger("events").warning(f"Failed to send leadership notifications: {str(e)}")


def _revoke_team_lead_permissions(team_name, old_lead):
    """Revoke team lead permissions from former leader"""
    try:
        if not old_lead:
            return

        # Check if user still has other team lead positions
        other_lead_positions = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabTeam` t
            WHERE t.team_lead = %s AND t.name != %s AND t.is_active = 1
        """,
            (old_lead, team_name),
            as_dict=True,
        )

        if not other_lead_positions or other_lead_positions[0].count == 0:
            # User has no other team lead positions, revoke team lead role
            user_doc = frappe.get_doc("User", old_lead)

            # Remove team lead specific roles
            user_roles = [role.role for role in user_doc.roles]
            if "Team Lead" in user_roles:
                user_doc.roles = [role for role in user_doc.roles if role.role != "Team Lead"]
                user_doc.save()

        frappe.logger("events").info(f"Revoked team lead permissions for {old_lead}")

    except Exception as e:
        frappe.logger("events").warning(f"Failed to revoke team lead permissions: {str(e)}")


def _grant_team_lead_permissions(team_name, new_lead):
    """Grant team lead permissions to new leader"""
    try:
        if not new_lead:
            return

        user_doc = frappe.get_doc("User", new_lead)

        # Add team lead role if not already present
        user_roles = [role.role for role in user_doc.roles]
        if "Team Lead" not in user_roles:
            user_doc.append("roles", {"role": "Team Lead"})
            user_doc.save()

        frappe.logger("events").info(f"Granted team lead permissions to {new_lead}")

    except Exception as e:
        frappe.logger("events").warning(f"Failed to grant team lead permissions: {str(e)}")


def _update_team_lead_access(team_name, new_lead):
    """Update team lead specific access"""
    try:
        if not new_lead:
            return

        # Grant permissions to manage team
        from frappe.permissions import add_user_permission

        # Add user permission for the team
        if not frappe.db.exists(
            "User Permission", {"user": new_lead, "allow": "Team", "for_value": team_name}
        ):
            add_user_permission("Team", team_name, new_lead)

        frappe.logger("events").info(f"Updated team lead access for {new_lead}")

    except Exception as e:
        frappe.logger("events").warning(f"Failed to update team lead access: {str(e)}")
