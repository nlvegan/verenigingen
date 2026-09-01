# Copyright (c) 2025, Your Organization and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class TeamMember(Document):
    """Child table (istable: 1) of Team.team_members.

    NOTE: after_insert(), on_update(), on_trash() are NOT called for child tables
    managed via parent save. Team Lead role assignment and role profile sync are
    handled by Team.on_update hooks (team_role_profile_hooks.py).

    #596: this class used to define validate() (date range, required volunteer,
    unique-role-per-team, is_active/status sync) and a validate_unique_role()
    helper. Frappe never runs a child DocType's validate() -- there is no
    d.run_method("validate") for children anywhere in insert()/save(). Required
    volunteer/team_role are already covered by their own reqd/Link-field
    validation (which DOES run for children); unique-role-per-team is already
    covered by TeamService.validate_unique_roles(), called from
    Team._validate_unique_roles() in Team.validate() -- the only one of these
    rules that ever actually ran, since it lives on the parent. Date range and
    the is_active/status sync had no other enforcement and now run from
    TeamValidationService.validate_team_member_rows() (services/team_service.py),
    called from Team.validate(), iterating team_doc.team_members from the parent.

    REMOVED: _send_team_member_added_notification, _send_team_member_removed_notification.
    These were called from the dead after_insert/on_trash methods above. Team
    notifications are handled separately by the event subscriber system
    (events/subscribers/team_subscribers.py).
    """
