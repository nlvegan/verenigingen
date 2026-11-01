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
NATIONAL_BOARD_MEMBER_PROFILE = "Verenigingen National Board Member"
NATIONAL_TREASURER_PROFILE = "Verenigingen Treasurer"
NATIONAL_PROFILES = frozenset({NATIONAL_BOARD_MEMBER_PROFILE, NATIONAL_TREASURER_PROFILE})

# erpnext's validate_employee_role (a User validate hook) strips these two from every
# user without an Employee record, so an editor without one can never hold them and
# requiring them refused every editor with no Employee record (#1649; typical seat
# holders have one, see below). Mapping a profile CAN create the record:
# user_role_profile_calculator._ensure_employee_for_profile runs from
# sync_user_role_profile (reached by board seating) for any enabled user with a linked
# Member when the target profile contains Employee. So an editor can indirectly hand
# Employee / Employee Self Service (own-record HR self-service, read on Company and
# Employee) to seat holders. Accepted: no administrative role, and the Volunteer
# profile already carries both. Every other role is still required.
_EMPLOYEE_RECORD_ROLES = frozenset({"Employee", "Employee Self Service"})

# Holders of these may map any profile; they could grant themselves anything anyway.
_UNRESTRICTED_ROLES = frozenset({Roles.SYSTEM_MANAGER, "Administrator"})


def validate_mapped_profiles(mappings, previous_mappings, *, national_allowed, system_mapping=False):
    """Refuse a mapping that would hand out more than it should.

    Only what is new in this save is checked, so a mapping already in place (set
    by an administrator, or before the national chapter changed) never blocks an
    unrelated save. "New" is per slot for the editor's-roles check: moving a
    profile an administrator mapped to one chapter role into the default slot
    hands it to the whole board, so that counts as new.

    Args:
        mappings: every (slot, Role Profile) pair the document maps after this
            save; slot is "default" or the chapter/team role.
        previous_mappings: the pairs it mapped before (empty on insert).
        national_allowed: True only for the chapter set as national_board_chapter.
        system_mapping: set by system code that maps a fixed profile of its own
            choosing (chapter provisioning, the default MijnRood teams), never one
            taken from user input. Skips the editor's-roles check only.
    """
    mappings = {(slot, p) for slot, p in mappings if p}
    previous_mappings = {(slot, p) for slot, p in previous_mappings if p}
    new_profiles = {p for _slot, p in mappings} - {p for _slot, p in previous_mappings}
    for profile in sorted(new_profiles):
        if profile in NATIONAL_PROFILES and not national_allowed:
            frappe.throw(
                _("Role Profile '{0}' can only be mapped on the national board chapter.").format(profile)
            )

    if not system_mapping:
        new_mappings = {p for _slot, p in mappings - previous_mappings}
        _validate_no_payroll_profile(new_mappings)
        _validate_editor_holds_roles(new_mappings)


def profile_grants_payroll_access(profile):
    return bool(_roles_granted_by(profile) & Roles.PAYROLL_ROLES)


def _validate_no_payroll_profile(new_profiles):
    """HR Manager / HR User are payroll access (#1606): never mapped by a mere holder of them."""
    if set(frappe.get_roles()) & (_UNRESTRICTED_ROLES | {Roles.VERENIGINGEN_ADMIN}):
        return
    for profile in sorted(new_profiles):
        if profile_grants_payroll_access(profile):
            frappe.throw(
                _(
                    "Role Profile '{0}' grants payroll access and can only be mapped by a System "
                    "Manager or a Verenigingen Administrator."
                ).format(profile)
            )


def validate_editor_holds_roles(mapped_roles, previous_roles):
    """Nobody maps a bare Role they do not hold themselves (#1633).

    Like validate_mapped_profiles, for (slot, Role) pairs: only a pair that is new
    in this save is checked.
    """
    new_roles = {r for _slot, r in {(s, r) for s, r in mapped_roles if r} - set(previous_roles)}
    own_roles = set(frappe.get_roles())
    if not own_roles & (_UNRESTRICTED_ROLES | {Roles.VERENIGINGEN_ADMIN}):
        for role in sorted(new_roles & Roles.PAYROLL_ROLES):
            # Holding HR Manager (the Treasurer does, #1606) is not enough to hand it out.
            frappe.throw(
                _(
                    "Role '{0}' grants payroll access and can only be mapped by a System Manager or a "
                    "Verenigingen Administrator."
                ).format(role)
            )
    if own_roles & _UNRESTRICTED_ROLES:
        return
    for role in sorted(new_roles - own_roles - {"All", "Guest"}):
        frappe.throw(_("You cannot map Role '{0}': you do not hold it yourself.").format(role))


def _validate_editor_holds_roles(new_profiles):
    """Nobody maps a profile granting roles they do not hold themselves."""
    own_roles = set(frappe.get_roles())
    if own_roles & _UNRESTRICTED_ROLES:
        return
    for profile in sorted(new_profiles):
        missing = _roles_granted_by(profile) - own_roles - {"All", "Guest"} - _EMPLOYEE_RECORD_ROLES
        if missing:
            frappe.throw(
                _("You cannot map Role Profile '{0}': it grants roles you do not hold ({1}).").format(
                    profile, ", ".join(sorted(missing))
                )
            )


def _roles_granted_by(profile):
    return set(
        frappe.get_all("Has Role", filters={"parenttype": "Role Profile", "parent": profile}, pluck="role")
    )


def require_may_remove_profile_for(doctype: str, entity: str, user: str) -> None:
    """Gate the whitelisted remove_*_role_profile endpoints (#1615 review).

    They were gated only by the security tier, so any Staff-profile caller could name any
    user. Now the caller needs System Manager / Verenigingen Administrator, or write
    permission on that Team/Chapter AND the target must have (or have had) a row there.
    An unknown entity, a forbidden one and an unrelated target are refused identically.
    """
    _require_may_manage_profiles_for(doctype, entity, lambda: _target_has_a_row(doctype, entity, user))


def require_may_bulk_assign_profiles_for(doctype: str, entity: str) -> None:
    """Gate the whitelisted team bulk assign endpoint (#1686): same authority as the remove
    endpoints (administrator, or write permission on that Team/Chapter, which for a Team means
    the Team Lead role AND team scope; a plain member has no Team write), without a target.
    The chapter board bulk endpoints are admin-only instead: see require_profile_admin."""
    _require_may_manage_profiles_for(doctype, entity, lambda: True)


def require_profile_admin() -> None:
    """Admin-only gate (#1686 ruling, 2026-10-31) for the chapter board bulk endpoints: System
    Manager / Verenigingen Administrator only, Treasurer, National Board Member and Staff
    refused. Same message as the other guards, so an unknown and a forbidden chapter answer alike."""
    if not is_profile_admin():
        frappe.throw(_("You do not have permission to change role profiles here."), frappe.PermissionError)


def is_profile_admin() -> bool:
    """The one definition of "may use the chapter board bulk endpoints". The Chapter form reads
    it through onload to decide whether to show the button, so the two cannot drift (#1831)."""
    return frappe.session.user == "Administrator" or bool(
        {Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_ADMIN} & set(frappe.get_roles())
    )


def _require_may_manage_profiles_for(doctype, entity, target_ok) -> None:
    if is_profile_admin():
        return
    if not (
        isinstance(entity, str)
        and frappe.db.exists(doctype, entity)
        and frappe.has_permission(doctype, "write", doc=entity)
        and target_ok()
    ):
        frappe.throw(_("You do not have permission to change role profiles here."), frappe.PermissionError)


def _target_has_a_row(doctype: str, entity: str, user: str) -> bool:
    member = frappe.db.get_value("Member", {"user": user}, "name")
    volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name") if member else None
    if doctype == "Team":
        if frappe.db.get_value("Team", entity, "team_lead") == user:
            return True
        row = "Team Member"
    else:
        row = "Chapter Board Member"
    return bool(volunteer and frappe.db.exists(row, {"parent": entity, "volunteer": volunteer}))
