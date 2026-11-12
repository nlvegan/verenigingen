"""Give a user a team's role profile through the real sync path.

``BaseRoleProfileManager.assign_role_profile`` used to be the setup step for the
``remove_role_profile`` tests. It replaced ALL of a user's role profiles and had no
production caller (#1685), so it is gone. Production grants a team profile by sync:
the user's Member sits in a Team through a Volunteer's ``Team Member`` row and
``sync_user_role_profile`` derives the profile and records it as sync-granted. These
helpers reproduce exactly that.
"""

import frappe
from frappe.utils import today


def grant_team_profile_via_sync(user, volunteer, team):
    """Add ``volunteer`` to ``team`` as an Active member and run the real sync for ``user``.

    Returns the ``Team Member`` row name so a test can later end the membership.
    """
    from verenigingen.setup import create_default_team_roles

    create_default_team_roles()  # the "Team Member" Team Role must exist
    team_doc = frappe.get_doc("Team", team)
    row = team_doc.append(
        "team_members",
        {"volunteer": volunteer, "team_role": "Team Member", "from_date": today(), "status": "Active"},
    )
    team_doc.save()

    from verenigingen.utils.user_role_profile_calculator import sync_user_role_profile

    sync_user_role_profile(user)
    return row.name


def end_team_membership_without_sync(row_name):
    """Mark a ``Team Member`` row Inactive WITHOUT triggering a sync.

    Probe shortcut (direct ``set_value``, no doc hooks): it leaves the user still holding
    the profile with the membership gone, which is the state ``remove_role_profile`` is
    called in. Saving the Team would let the hook strip the profile first.
    """
    frappe.db.set_value("Team Member", row_name, "status", "Inactive", update_modified=False)
