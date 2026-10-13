"""Staff action: create the Employee record for a volunteer (#1606).

Staff hold no Employee permission on purpose (the doctype exposes salary, bank and health
fields at permlevel 0). When the automated account pipeline leaves a volunteer without an
Employee, Staff run this narrow action instead. It runs the pipeline's own insert
(AccountCreationManager._insert_employee_for_created_user), which is built for Staff callers.
"""

import frappe
from frappe import _

from verenigingen.services.member.account.account_creation_manager import AccountCreationManager
from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def create_employee_for_volunteer(volunteer: str) -> dict:
    """Create (or find) the Employee of a volunteer and link it; returns only its name."""
    # The role gate comes before any lookup so an unknown volunteer and a real one are
    # refused identically (message, exception, queries) for a caller who may not use this.
    if not set(frappe.get_roles()) & Roles.ADMIN_ROLES:
        frappe.throw(_("You are not permitted to create Employee records."), frappe.PermissionError)

    record = frappe.db.get_value("Volunteer", volunteer, ["name", "member", "employee_id"], as_dict=True)
    if not record:
        frappe.throw(_("Volunteer not found."), frappe.DoesNotExistError)

    member = frappe.get_doc("Member", record.member) if record.member else None
    linked = _linked_employee(record, member)
    if linked:
        return {"employee": linked, "created": False}

    if not member or not member.user:
        frappe.throw(_("The volunteer needs a linked member with a user account first."))
    _refuse_unsuitable_user(member)

    existing = frappe.db.get_value("Employee", {"user_id": member.user}, "name")
    if existing:
        _link_employee(record, existing)
        return {"employee": existing, "created": False}

    manager = AccountCreationManager(None)
    manager.created_user = member.user
    manager.source_doc = member
    manager.request = frappe._dict(
        full_name=member.full_name, email=member.email, request_type="Member", created_employee=None
    )
    manager._insert_employee_for_created_user()
    _link_employee(record, manager.created_employee)
    return {"employee": manager.created_employee, "created": True}


# Profiles whose holders an Employee may be created for. Staff can edit Member.user, so without
# this they could hand the Employee role, Employee/Company User Permissions and Member PII
# propagation to ANY user, a System Manager's included.
_MEMBER_TIER_PROFILES = (
    "Verenigingen Member",
    "Verenigingen Volunteer",
    "Verenigingen Team Leader",
    "Verenigingen Chapter Board Member",
)
_AUTOMATIC_ROLES = {"All", "Guest", "Desk User"}


def _refuse_unsuitable_user(member):
    allowed = _AUTOMATIC_ROLES | set(
        frappe.get_all(
            "Has Role",
            filters={"parenttype": "Role Profile", "parent": ["in", list(_MEMBER_TIER_PROFILES)]},
            pluck="role",
        )
    )
    if set(frappe.get_roles(member.user)) - allowed:
        frappe.throw(_("The user account holds roles above the member and volunteer level."))


def _linked_employee(record, member):
    """The Employee the volunteer already points at, if it is the member user's own."""
    if not (record.employee_id and frappe.db.exists("Employee", record.employee_id)):
        return None
    employee_user = frappe.db.get_value("Employee", record.employee_id, "user_id")
    if employee_user and employee_user != (member.user if member else None):
        # Never link, or name, somebody else's Employee
        frappe.throw(_("The Employee linked to this volunteer belongs to a different user."))
    return record.employee_id


def _link_employee(record, employee):
    # Same write as AccountCreationManager._link_records_phase
    if not record.employee_id:
        frappe.db.set_value("Volunteer", record.name, "employee_id", employee, update_modified=False)
