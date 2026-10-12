"""Who may deliberately assign a privileged Role Profile to a user (#1654).

role_profile_mapping_guard (#1616) limits what a chapter board or team can MAP. This
module limits what a caller of an assignment endpoint can GIVE. The endpoints
(assign_role_profile_to_user, assign_chapter_board_role_profile,
assign_team_role_profile) are ADMIN-tier, and the Treasurer and National Board Member
profiles are themselves CRITICAL-tier, so without this check a holder of either could
hand out "Verenigingen Administrator" (System Manager), or the national profiles, to
anybody.

Privileged = a national profile, or any profile granting System Manager / Administrator.
Only a System Manager, the Administrator account or a Verenigingen Administrator may
assign one directly. The calculator that derives profiles from board seats and team
roles does not go through here: its mappings are guarded when they are saved.
"""

import frappe
from frappe import _

from verenigingen.services.member.account.role_profile_mapping_guard import NATIONAL_PROFILES
from verenigingen.utils.constants import Roles

_ASSIGNER_ROLES = frozenset({Roles.SYSTEM_MANAGER, "Administrator", Roles.VERENIGINGEN_ADMIN})
_ESCALATING_ROLES = frozenset({Roles.SYSTEM_MANAGER, "Administrator"})


def is_privileged_profile(profile):
    if not profile:
        return False
    if profile in NATIONAL_PROFILES:
        return True
    granted = frappe.get_all(
        "Has Role", filters={"parenttype": "Role Profile", "parent": profile}, pluck="role"
    )
    return bool(_ESCALATING_ROLES & set(granted))


def validate_may_assign_profile(profile):
    """Refuse (PermissionError) unless the session user may assign `profile` directly."""
    if not is_privileged_profile(profile):
        return
    if _ASSIGNER_ROLES & set(frappe.get_roles()):
        return
    frappe.throw(
        _(
            "Role Profile '{0}' can only be assigned by a System Manager or a Verenigingen Administrator."
        ).format(profile),
        frappe.PermissionError,
    )
