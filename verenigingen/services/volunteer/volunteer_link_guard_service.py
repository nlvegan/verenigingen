"""
Guards on the links a Volunteer holds to a Member and an Employee (#2752).

Extracted from the Volunteer controller so the controller stays inside its size
budget; `Volunteer.validate` calls `guard_employee_and_member_links` and nothing else.
"""

import frappe
from frappe import _

from verenigingen.utils.constants import Roles


def guard_employee_and_member_links(volunteer):
    """Run both link guards; the member guard first, as the employee guard reads the member."""
    validate_member_repoint(volunteer)
    validate_employee_id_change(volunteer)


def validate_member_repoint(volunteer):
    """Refuse a non-staff writer repointing or clearing an already-set `member` (#2752).

    The Employee the writer may claim is derived from the PERSISTED member (see
    `_employee_belongs_to_member_user`), so `member` itself must not be movable in the
    same save. Filling an EMPTY member stays open: the application relink flows
    (`activate_volunteer_record`, run by whoever approves) adopt an orphan that way.
    """
    previous = volunteer.get_doc_before_save()
    old_member = previous.get("member") if previous else None
    if not old_member or (volunteer.member or None) == old_member:
        return
    if Roles.ADMIN_ROLES.intersection(frappe.get_roles()):
        return
    frappe.throw(
        _("Only staff can change or clear the Member linked to a volunteer."),
        frappe.PermissionError,
    )


def validate_employee_id_change(volunteer):
    """Refuse a Volunteer writer repointing `employee_id` at someone else's Employee (#2752).

    `read_only` is a form hint; a server save or REST PUT ignores it. Every expense read
    and write is keyed on this field, so repointing it hands over another person's
    claims. Staff (`Roles.ADMIN_ROLES`, #1101) may set, change or clear it. Anyone else
    may only fill an EMPTY field, with the Employee of the PERSISTED member's own user.
    The app's own writers (ACR pipeline, volunteer_employee_service) use
    `frappe.db.set_value`, which never runs validate, so they need no bypass.
    """
    previous = volunteer.get_doc_before_save()
    old_value = previous.get("employee_id") if previous else None
    if (volunteer.employee_id or None) == (old_value or None):
        return
    if Roles.ADMIN_ROLES.intersection(frappe.get_roles()):
        return
    if old_value or not volunteer.employee_id or not _employee_belongs_to_member_user(volunteer, previous):
        frappe.throw(
            _("Only staff can change or clear the Employee linked to a volunteer."),
            frappe.PermissionError,
        )


def _employee_belongs_to_member_user(volunteer, previous):
    # Local import: the service imports AccountCreationManager at module level
    from verenigingen.services.volunteer.volunteer_employee_service import _linked_employee

    # "Own" must come from something the writer cannot change in this same save: the
    # persisted member. On insert there is no persisted row, so the incoming member
    # counts, and the Employee must then also be the writer's own.
    own_member_name = previous.get("member") if previous else volunteer.member
    member = frappe.get_doc("Member", own_member_name) if own_member_name else None
    if not (member and member.user):
        return False
    if not previous and member.user != frappe.session.user:
        return False
    try:
        linked = _linked_employee(volunteer, member)
    except frappe.ValidationError:
        return False
    # _linked_employee also accepts an Employee with NO user; that is somebody's
    # Employee all the same, so require the member user's own.
    return bool(linked) and frappe.db.get_value("Employee", linked, "user_id") == member.user
