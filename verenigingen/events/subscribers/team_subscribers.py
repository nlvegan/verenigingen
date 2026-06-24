"""
Team Event Subscribers

Background job handlers for team lifecycle events: assignment history,
notifications, cache invalidation, and permissions.

NOTE: Role profile sync and Team Lead Has Role assignment are handled
synchronously by doc_event hooks in team_role_profile_hooks.py — NOT here.
"""

import frappe

from verenigingen.events.subscribers.subscriber_utils import get_doc_if_exists
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config


def handle_assignment_history_updates(event_name, event_data, **kwargs):
    """
    Handle assignment history updates when team membership changes.

    Updates volunteer assignment history based on team membership changes.

    Args:
        event_name: Name of the event that triggered this handler
        event_data: Dict containing event-specific data
        **kwargs: Additional keyword arguments from background job system (dedupe, delay, etc.)
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

        # A deleted/not-yet-committed Team is a benign race for a background job
        # (e.g. the team was removed, or its insert hasn't committed yet). Guard
        # like the member/chapter subscribers do, so the moot update is a clean
        # no-op instead of an Error Log row. See subscriber_utils.get_doc_if_exists.
        team = get_doc_if_exists("Team", team_name, "assignment history update")
        if not team:
            return

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


def handle_membership_notifications(event_name, event_data, **kwargs):
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

        team = get_doc_if_exists("Team", team_name, "team membership notification")
        volunteer_doc = get_doc_if_exists("Volunteer", volunteer, "team membership notification")
        if not team or not volunteer_doc:
            return

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


def handle_settings_notifications(event_name, event_data, **kwargs):
    """
    Handle notifications for team settings changes.

    Notifies relevant parties about configuration updates.

    Args:
        event_name: Name of the event that triggered this handler
        event_data: Dict containing event-specific data
        **kwargs: Additional keyword arguments from background job system (dedupe, delay, etc.)
    """
    try:
        team_name = event_data.get("team")
        changed_fields = event_data.get("changed_fields", [])

        if not team_name or not changed_fields:
            return

        team = get_doc_if_exists("Team", team_name, "team settings notification")
        if not team:
            return

        # Notify team members about significant setting changes
        important_fields = ["enable_role_profiles", "default_role_profile", "is_active"]

        if any(field in changed_fields for field in important_fields):
            _send_team_settings_notification(team, changed_fields)

        frappe.logger("events").info(f"Sent settings notifications for {team_name}")

    except Exception as e:
        frappe.log_error(
            f"Failed to send settings notifications: {str(e)}", "Team Settings Notification Error"
        )


def handle_permissions_updates(event_name, event_data, **kwargs):
    """
    Handle permission updates when team settings change.

    Updates user permissions based on new configuration.

    Args:
        event_name: Name of the event that triggered this handler
        event_data: Dict containing event-specific data
        **kwargs: Additional keyword arguments from background job system (dedupe, delay, etc.)
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


def handle_cache_invalidation(event_name, event_data, **kwargs):
    """
    Handle cache invalidation for team changes.

    Clears relevant caches when team data changes.

    Args:
        event_name: Name of the event that triggered this handler
        event_data: Dict containing event-specific data
        **kwargs: Additional keyword arguments from background job system (dedupe, delay, etc.)
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


def handle_leadership_notifications(event_name, event_data, **kwargs):
    """
    Handle notifications for team leadership changes.

    Notifies relevant parties about team lead transitions.

    Args:
        event_name: Name of the event that triggered this handler
        event_data: Dict containing event-specific data
        **kwargs: Additional keyword arguments from background job system (dedupe, delay, etc.)
    """
    try:
        team_name = event_data.get("team")
        old_lead = event_data.get("old_lead")
        new_lead = event_data.get("new_lead")

        if not team_name:
            return

        team = get_doc_if_exists("Team", team_name, "team leadership notification")
        if not team:
            return

        # Send leadership transition notifications
        _send_leadership_change_notification(team, old_lead, new_lead)

        frappe.logger("events").info(f"Sent leadership notifications for {team_name}")

    except Exception as e:
        frappe.log_error(
            f"Failed to send leadership notifications: {str(e)}", "Team Leadership Notification Error"
        )


def handle_team_lead_permissions(event_name, event_data, **kwargs):
    """
    Handle team lead permission updates.

    Manages special permissions for team leads.

    Args:
        event_name: Name of the event that triggered this handler
        event_data: Dict containing event-specific data
        **kwargs: Additional keyword arguments from background job system (dedupe, delay, etc.)
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


def _send_team_member_added_notification(team, volunteer_doc, role):
    """Send notification when team member is added"""
    if volunteer_doc.member:
        member_doc = frappe.get_doc("Member", volunteer_doc.member)
        if member_doc.email:
            # MIGRATED: Use unified EmailService with professional template
            from verenigingen.services.communication.email_service import get_email_service

            email_service = get_email_service()
            context = {
                "member_name": member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}",
                "team_name": team.name,
                "change_type": "Team Assignment",
                "new_role": role,
                "effective_date": frappe.utils.today(),
                "additional_message": "Welcome to the team!",
                "company": get_mollie_config().get_default_company(),
            }

            email_service.send_templated_email(
                template_name="team_role_notification",
                recipients=[member_doc.email],
                context=context,
                subject_override=f"Team Assignment - {team.name}",
                reference_doctype="Team",
                reference_name=team.name,
                notification_key="team_member_added",
            )


def _send_team_member_removed_notification(team, volunteer_doc, role):
    """Send notification when team member is removed"""
    if volunteer_doc.member:
        member_doc = frappe.get_doc("Member", volunteer_doc.member)
        if member_doc.email:
            # MIGRATED: Use unified EmailService with professional template
            from verenigingen.services.communication.email_service import get_email_service

            email_service = get_email_service()
            context = {
                "member_name": member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}",
                "team_name": team.name,
                "change_type": "Team Assignment Ended",
                "new_role": role,
                "effective_date": frappe.utils.today(),
                "additional_message": "Thank you for your contribution!",
                "company": get_mollie_config().get_default_company(),
            }

            email_service.send_templated_email(
                template_name="team_role_notification",
                recipients=[member_doc.email],
                context=context,
                subject_override=f"Team Assignment Ended - {team.name}",
                reference_doctype="Team",
                reference_name=team.name,
                notification_key="team_member_removed",
            )


def _send_team_role_changed_notification(team, volunteer_doc, old_role, new_role):
    """Send notification when team member role changes"""
    if volunteer_doc.member:
        member_doc = frappe.get_doc("Member", volunteer_doc.member)
        if member_doc.email:
            # MIGRATED: Use unified EmailService with professional template
            from verenigingen.services.communication.email_service import get_email_service

            email_service = get_email_service()
            context = {
                "member_name": member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}",
                "team_name": team.name,
                "change_type": "Role Update",
                "new_role": new_role,
                "effective_date": frappe.utils.today(),
                "additional_message": f"Your role has been updated from {old_role} to {new_role}.",
                "company": get_mollie_config().get_default_company(),
            }

            email_service.send_templated_email(
                template_name="team_role_notification",
                recipients=[member_doc.email],
                context=context,
                subject_override=f"Team Role Update - {team.name}",
                reference_doctype="Team",
                reference_name=team.name,
                notification_key="team_role_changed",
            )


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
                    # MIGRATED: Use unified EmailService with professional template
                    from verenigingen.services.communication.email_service import get_email_service

                    email_service = get_email_service()
                    context = {
                        "member_name": member_doc.full_name
                        or f"{member_doc.first_name} {member_doc.last_name}",
                        "team_name": team.name,
                        "change_type": "Team Settings Update",
                        "effective_date": frappe.utils.today(),
                        "additional_message": f"Changed settings: {', '.join(changed_fields)}",
                        "company": get_mollie_config().get_default_company(),
                    }

                    email_service.send_templated_email(
                        template_name="team_role_notification",
                        recipients=[member_doc.email],
                        context=context,
                        subject_override=f"Team Settings Updated - {team.name}",
                        reference_doctype="Team",
                        reference_name=team.name,
                        notification_key="team_settings_changed",
                    )


def _update_team_permissions(team_name):
    """Update team permissions based on new settings.

    Uses auto_sync_on_role_change to recalculate role profiles
    for all active team members.
    """
    from verenigingen.utils.user_role_profile_calculator import auto_sync_on_role_change

    try:
        team = frappe.get_doc("Team", team_name)

        for member in team.team_members or []:
            if member.is_active and member.volunteer:
                volunteer_doc = frappe.get_doc("Volunteer", member.volunteer)
                if volunteer_doc.member:
                    member_doc = frappe.get_doc("Member", volunteer_doc.member)
                    if member_doc.user:
                        auto_sync_on_role_change(member_doc.user)

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

                        # MIGRATED: Use unified EmailService with professional template
                        from verenigingen.services.communication.email_service import get_email_service

                        email_service = get_email_service()
                        context = {
                            "member_name": member_doc.full_name
                            or f"{member_doc.first_name} {member_doc.last_name}",
                            "team_name": team.name,
                            "change_type": "Leadership Change",
                            "effective_date": frappe.utils.today(),
                            "additional_message": f"Previous leader: {old_lead_name}\nNew leader: {new_lead_name}",
                            "company": get_mollie_config().get_default_company(),
                        }

                        email_service.send_templated_email(
                            template_name="team_role_notification",
                            recipients=[member_doc.email],
                            context=context,
                            subject_override=subject,
                            reference_doctype="Team",
                            reference_name=team.name,
                            notification_key="team_leadership_changed",
                        )

        frappe.logger("events").info(f"Sent leadership change notifications for {team.name}")

    except Exception as e:
        frappe.logger("events").warning(f"Failed to send leadership notifications: {str(e)}")


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
