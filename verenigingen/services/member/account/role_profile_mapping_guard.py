"""
Which Role Profiles may be mapped onto a chapter board or a team (#1616).

A chapter's board members (and a team's lead) can edit the role profile mapping of
the board or team they sit on, and the next profile sync gives every seat holder
the mapped profile's roles. Unchecked, that let a board member map a profile
granting System Manager onto their own board.

A profile granting System Manager is not refused outright: the association-wide
"Landelijk Beheer" team is wired to "Verenigingen Administrator" on purpose
(MijnrodSyncSettings._ensure_default_teams). It is refused to anyone who does not
hold those roles already, like every other profile.
"""

import frappe
from frappe import _

from verenigingen.utils.constants import Roles

# Granted only by a seat on the national chapter's board.
NATIONAL_PROFILES = frozenset({"Verenigingen National Board Member", "Verenigingen Treasurer"})

# Holders of these may map any profile; they could grant themselves anything anyway.
_UNRESTRICTED_ROLES = frozenset({Roles.SYSTEM_MANAGER, "Administrator"})


def validate_mapped_profiles(profiles, previous_profiles, *, national_allowed):
    """Refuse a mapping that would hand out more than it should.

    Args:
        profiles: every Role Profile the document maps after this save.
        previous_profiles: the ones it mapped before (empty on insert). Only newly
            added profiles are checked against the editor's own roles, so a mapping
            an administrator set up does not block a board member's unrelated save.
        national_allowed: True only for the chapter set as national_board_chapter.
    """
    profiles = {p for p in profiles if p}
    for profile in sorted(profiles):
        if profile in NATIONAL_PROFILES and not national_allowed:
            frappe.throw(
                _("Role Profile '{0}' can only be mapped on the national board chapter.").format(profile)
            )

    _validate_editor_holds_roles(profiles - {p for p in previous_profiles if p})


def _validate_editor_holds_roles(new_profiles):
    """Nobody maps a profile granting roles they do not hold themselves."""
    own_roles = set(frappe.get_roles())
    if own_roles & _UNRESTRICTED_ROLES:
        return
    for profile in sorted(new_profiles):
        missing = _profile_roles(profile) - own_roles - {"All", "Guest"}
        if missing:
            frappe.throw(
                _("You cannot map Role Profile '{0}': it grants roles you do not hold ({1}).").format(
                    profile, ", ".join(sorted(missing))
                )
            )


def _profile_roles(profile):
    return set(
        frappe.get_all("Has Role", filters={"parenttype": "Role Profile", "parent": profile}, pluck="role")
    )
