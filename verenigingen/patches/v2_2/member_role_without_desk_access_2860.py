"""Members are Website Users, not desk System Users (#2860).

`Verenigingen Member` shipped with desk_access=1, so Frappe's `User.set_system_user` made every
member-only account a System User. The role fixture now ships desk_access=0, but `user_type` is
recomputed from the roles only when a User is saved, so existing accounts keep "System User"
until this patch converts them.

Runs in post_model_sync, which is BEFORE the fixture sync: the Role row is therefore set here as
well (the fixture would write the same value afterwards).

The "Verenigingen Member" Role Profile also listed "All", and a stored Has Role row for "All"
carries desk_access=1 on its own, so profile-created members were System Users for that reason too
(and would flip straight back on their next save). "All" is an automatic role every user has, so
it is removed from that profile and from the converted users.

Only users whose desk access came solely from the member role (and "All") are converted. A member who also
holds any other desk_access=1 role (staff, volunteer, board, System Manager, ...) stays a System
User; Administrator and Guest are never touched. Sessions already open keep the user_type they
booted with until the next login. Idempotent: a second run finds nothing to convert.
"""

import frappe

ROLE = "Verenigingen Member"
AUTOMATIC_ROLE = "All"
FIXED_USERS = ("Administrator", "Guest")


def execute():
    if not frappe.db.exists("Role", ROLE):
        return

    frappe.db.set_value("Role", ROLE, "desk_access", 0, update_modified=False)
    frappe.clear_document_cache("Role", ROLE)
    frappe.db.delete(
        "Has Role", {"parenttype": "Role Profile", "parent": ROLE, "role": AUTOMATIC_ROLE}
    )
    frappe.clear_document_cache("Role Profile", ROLE)
    convert_member_only_users()


def convert_member_only_users():
    """Make member-only System Users Website Users; return the converted user names."""
    candidates = _system_users_holding_the_member_role()
    if not candidates:
        return []

    keep = set(_users_holding_another_desk_role(candidates))
    converted = [name for name in candidates if name not in keep]
    for name in converted:
        frappe.db.delete("Has Role", {"parenttype": "User", "parent": name, "role": AUTOMATIC_ROLE})
        # A direct write: a User save would also re-run its hooks and rewrite `modified`.
        frappe.db.set_value("User", name, "user_type", "Website User", update_modified=False)
        frappe.clear_document_cache("User", name)
    return converted


def _system_users_holding_the_member_role():
    holders = frappe.get_all(
        "Has Role", filters={"role": ROLE, "parenttype": "User"}, pluck="parent", distinct=True
    )
    if not holders:
        return []
    system_users = frappe.get_all(
        "User", filters={"name": ["in", holders], "user_type": "System User"}, pluck="name"
    )
    return [name for name in system_users if name not in FIXED_USERS]


def _users_holding_another_desk_role(users):
    desk_roles = frappe.get_all(
        "Role", filters={"desk_access": 1, "name": ["not in", [ROLE, AUTOMATIC_ROLE]]}, pluck="name"
    )
    return frappe.get_all(
        "Has Role",
        filters={"parenttype": "User", "parent": ["in", users], "role": ["in", desk_roles]},
        pluck="parent",
        distinct=True,
    )
