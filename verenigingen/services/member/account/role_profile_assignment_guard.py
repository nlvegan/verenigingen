"""Who may deliberately assign a Role Profile to a user (#1654).

role_profile_mapping_guard (#1616) limits what a chapter board or team can MAP. This
module limits what a caller of an assignment endpoint can GIVE. The endpoints
(assign_role_profile_to_user, assign_chapter_board_role_profile,
assign_team_role_profile) are ADMIN-tier, and the Treasurer and National Board Member
profiles are themselves CRITICAL-tier, so without this check a holder of either could
hand out "Verenigingen Administrator" (System Manager), HR Manager (the stock "HR"
profile) or the national profiles to anybody.

A System Manager, the Administrator account or a Verenigingen Administrator may assign
any profile. Everybody else may not assign a national profile, and may only assign a
profile whose roles they all hold (the rule role_profile_mapping_guard applies to
mappings, reused here). The calculator that derives profiles from board seats and team
roles does not go through here: its mappings are guarded when they are saved.
"""

import frappe
from frappe import _

from verenigingen.services.member.account.role_profile_mapping_guard import (
    NATIONAL_PROFILES,
    _validate_editor_holds_roles,
)
from verenigingen.utils.constants import Roles

_ASSIGNER_ROLES = frozenset({Roles.SYSTEM_MANAGER, "Administrator", Roles.VERENIGINGEN_ADMIN})


def validate_may_assign_profile(profile):
    """Refuse unless the session user may assign `profile` directly."""
    if not profile or _ASSIGNER_ROLES & set(frappe.get_roles()):
        return
    if profile in NATIONAL_PROFILES:
        frappe.throw(
            _(
                "Role Profile '{0}' can only be assigned by a System Manager or a Verenigingen Administrator."
            ).format(profile),
            frappe.PermissionError,
        )
    _validate_editor_holds_roles({profile})
