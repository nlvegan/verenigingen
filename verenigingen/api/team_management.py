"""
Team Management API

This module provides API endpoints for team management operations,
extracted from the Team DocType controller to maintain proper separation of concerns.
"""

import frappe
from frappe import _

from verenigingen.utils.error_handling import handle_api_error
from verenigingen.utils.security.api_security_framework import standard_api
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS


def _require_team_permission(team_name, ptype, message):
    """Refuse access to a caller-supplied Team id without an existence oracle.

    frappe.has_permission("Team", ptype, name) loads the document internally
    (frappe.get_lazy_doc) before consulting the permission tables, and that load
    raises DoesNotExistError for an unknown name while the same call returns plain
    False for a real-but-forbidden one (#1401) -- two different exceptions (and
    messages, once @handle_api_error renders them) for the identical "can I access
    this id" question. Catching the raise and folding it into the same refusal as
    "False" closes that without an extra existence lookup on the success path, and
    without changing behaviour for the literal "Administrator" user: its
    frappe.has_permission call returns True before touching the document at all
    (frappe/permissions.py), so it never raises here regardless of team_name, and
    a subsequent frappe.get_doc still surfaces the ordinary "not found" for a truly
    unknown id -- exactly as before this fix.

    The raise-vs-False difference is not only in the return value: frappe.throw()
    (raised by the internal document load for an unknown name) APPENDS a "Team
    <name> not found" entry to frappe.message_log before raising, and that queued
    message survives catching the exception -- it would otherwise ride along in
    _server_messages on an unknown id and not on a foreign one, reopening the
    oracle in the response body even once the exception itself is masked (found
    in review, sibling to #1430's frappe.client.has_permission finding).

    A single frappe.clear_last_message() is not enough to equalise the two paths
    either: for a real-but-forbidden team, frappe.has_permission's OWN internal
    message composition (frappe/permissions.py's has_permission recomputes
    has_permission(doctype) with no `doc`, to decide whether to name the
    document in ITS diagnostic) makes an unrelated, unsuppressable recursive call
    that defaults to print_logs=True regardless of what this call passed, so it
    queues its OWN message ("User X does not have doctype access via role
    permission...") on the False path whenever the caller's role holds no
    blanket doctype-level grant -- measured for both a "Verenigingen Volunteer"
    (read) and a "Team Lead" (write) caller. So instead of guessing which
    messages to pop, both branches are trimmed back to the message_log length
    captured before the call, discarding whatever frappe.has_permission queued
    on EITHER path, before this function raises its own single message.
    """
    log_len = len(frappe.message_log)
    try:
        allowed = frappe.has_permission("Team", ptype, team_name)
    except frappe.DoesNotExistError:
        allowed = False
    finally:
        del frappe.message_log[log_len:]

    if not allowed:
        frappe.throw(message)


@frappe.whitelist()
@standard_api
@handle_api_error
def get_team_members(team):
    """Get team members with volunteer info"""
    if not team:
        frappe.throw(_("Team is required"))

    _require_team_permission(team, "read", _("Insufficient permissions to access team data"))

    team_doc = frappe.get_doc("Team", team)
    members = []

    for member in team_doc.team_members:
        member_data = {
            "volunteer": member.volunteer,
            "volunteer_name": member.volunteer_name,
            "role": member.role,
            "team_role": member.team_role,
            "is_active": member.is_active,
            "from_date": member.from_date,
            "to_date": member.to_date,
        }

        if member.volunteer:
            try:
                volunteer_doc = frappe.get_doc("Volunteer", member.volunteer)
                member_data.update(
                    {
                        "email": volunteer_doc.email,
                        "phone": None,  # Phone field not available in Volunteer DocType
                        # Note: skills_and_qualifications is a text field, not a child table
                        "skills": volunteer_doc.skills_and_qualifications or "",
                    }
                )
            except frappe.DoesNotExistError:
                pass

        members.append(member_data)

    return members


@frappe.whitelist()
@standard_api
@handle_api_error
def sync_team_with_volunteers(team_name: str | None = None):
    """Sync team members with volunteer system"""

    # Permission check
    if not frappe.has_permission("Team", "write"):
        frappe.throw(_("Insufficient permissions to sync teams"))

    teams_to_sync = []
    if team_name:
        _require_team_permission(
            team_name, "write", _("Insufficient permissions to sync team {0}").format(team_name)
        )
        teams_to_sync = [{"name": team_name}]
    else:
        # get_list, NOT get_all. `get_all` bypasses permissions by design, so this branch
        # fanned out over EVERY team in the system while being gated only by the
        # doctype-level check above -- and that check passes a doc of None, so it consults
        # only the role layer (frappe/permissions.py), never the has_permission hook.
        # team.json grants `Team Lead` write on Team with no if_owner, so any Team Lead
        # holder could sync teams they have no relationship to. See #266.
        #
        # get_list applies get_team_permission_query_conditions, which scopes Team to
        # admin -> all, owner -> own, active Team Member -> those teams. That is the right
        # scope here only because has_team_permission deliberately ignores `ptype` and is
        # kept in lockstep with the query, so "visible" and "writable" are the same set for
        # Team. If a write-specific rule is ever added to has_team_permission, this branch
        # needs a per-team frappe.has_permission("Team", "write", name) filter as well.
        #
        # limit=0 is explicit because frappe.get_list's docstring claims a default page
        # length of 20. MEASURED on this bench it does not truncate either way, but a silent
        # cap here would quietly stop syncing teams rather than fail, so the intent is
        # stated rather than inherited. `limit`, not the older `limit_page_length`, which
        # frappe deprecates for removal in v17.
        teams_to_sync = frappe.get_list("Team", fields=["name"], limit=0)

    updated_count = 0

    for team in teams_to_sync:
        try:
            team_doc = frappe.get_doc("Team", team["name"])
            # Import here to avoid circular imports
            from verenigingen.services.team_service import TeamService

            TeamService().sync_with_volunteers(team_doc)
            updated_count += 1
        # #505: without this a 1205/1213 syncing one team is logged and the loop
        # keeps syncing further teams against a transaction the server has already
        # discarded (the #470 shape, one frame below @handle_api_error). Re-raise
        # unconditionally.
        except NON_RESUMABLE_DB_ERRORS:
            raise
        except Exception as e:
            frappe.log_error(f"Failed to sync team {team['name']}: {str(e)}", "Team Sync Error")

    return {"updated_count": updated_count}


@frappe.whitelist()
@standard_api
@handle_api_error
def get_role_profile_preview(team_name: str):
    """Get preview of which role profiles would be assigned to team members"""

    _require_team_permission(team_name, "read", _("Insufficient permissions to access team data"))

    team_doc = frappe.get_doc("Team", team_name)
    preview = []

    for member in team_doc.team_members:
        if member.is_active and member.volunteer:
            role_profile = None

            # Get role profile from team role configuration
            if member.team_role and team_doc.role_specific_profiles:
                for mapping in team_doc.role_specific_profiles:
                    if mapping.team_role == member.team_role:
                        role_profile = mapping.role_profile
                        break

            preview.append(
                {
                    "volunteer": member.volunteer,
                    "volunteer_name": member.volunteer_name,
                    "team_role": member.team_role,
                    "current_role_profile": role_profile,
                    "would_be_assigned": role_profile is not None,
                }
            )

    return preview


@frappe.whitelist()
@standard_api
@handle_api_error
def bulk_apply_team_role_profiles(team_name: str):
    """Recalculate role profiles for all active members of a team.

    Uses auto_sync_on_role_change() which derives the correct profile from
    ground truth (actual DB state) rather than trying to assign a specific profile.
    """
    from verenigingen.utils.user_role_profile_calculator import auto_sync_on_role_change

    _require_team_permission(team_name, "write", _("Insufficient permissions to modify team"))

    if not frappe.db.exists("Team", team_name):
        return {"success": False, "applied_count": 0, "message": f"Team '{team_name}' does not exist"}

    # Get active team members: TM.volunteer → Volunteer.member → Member.user
    team_members = frappe.db.sql(
        """
        SELECT DISTINCT m.user
        FROM `tabTeam Member` tm
        JOIN `tabVolunteer` v ON tm.volunteer = v.name
        JOIN `tabMember` m ON v.member = m.name
        WHERE tm.parent = %s
          AND tm.is_active = 1
          AND m.user IS NOT NULL
          AND m.user != ''
        """,
        (team_name,),
        as_dict=True,
    )

    updated = 0
    for row in team_members:
        user = row["user"] if isinstance(row, dict) else row.user
        try:
            auto_sync_on_role_change(user)
            updated += 1
        # #505: same shape as sync_team_with_volunteers above -- re-raise
        # unconditionally so @handle_api_error's own guard (#504) sees the class.
        except NON_RESUMABLE_DB_ERRORS:
            raise
        except Exception as e:
            frappe.log_error(
                f"Role profile sync failed for {user}: {e}",
                "Bulk Team Role Profile Sync",
            )

    return {
        "success": updated > 0 or len(team_members) == 0,
        "applied_count": updated,
        "message": f"Synced role profiles for {updated} team members",
    }
