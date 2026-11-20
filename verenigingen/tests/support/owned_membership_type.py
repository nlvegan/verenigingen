"""A Membership Type a plain FrappeTestCase OWNS, instead of picking whichever row sorts first.

`frappe.get_all("Membership Type", limit=1)` and `get_value("Membership Type", {}, "name")` return the
newest-modified type, which on a shared shard may be one another module leaked with a different rate,
minimum or status (#2270 / #2271). Tests whose assertions depend on the type's fee data must create
their own and remove it again.
"""

import frappe


def make_owned_membership_type(test_case, **overrides):
    """Create an active Membership Type (plus its auto-created dues template) for `test_case`.

    Separate from `EnhancedTestCase.create_test_membership_type` on purpose: the callers are plain
    FrappeTestCase classes that cannot use that mixin method, and this one leaves the auto-created
    template at its default rate instead of aligning it to the type's minimum.

    Removal is registered with `addCleanup`, template first: the template links to the type, so the
    type's delete is refused while it exists. The delete is NOT swallowed.
    """
    role_profile = frappe.db.get_value("Role Profile", "Verenigingen Member", "name") or frappe.db.get_value(
        "Role Profile", {}, "name"
    )
    values = {
        "doctype": "Membership Type",
        "membership_type_name": f"Owned Type {frappe.generate_hash(length=8)}",
        "is_active": 1,
        "role_profile": role_profile,
    }
    values.update(overrides)
    membership_type = frappe.get_doc(values).insert()
    test_case.addCleanup(_remove_membership_type, membership_type.name)
    return membership_type


def _remove_membership_type(name):
    if not frappe.db.exists("Membership Type", name):
        return  # the class-level rollback already took it
    for template in frappe.get_all("Membership Dues Schedule", {"membership_type": name}, pluck="name"):
        frappe.delete_doc("Membership Dues Schedule", template, force=True)
    frappe.delete_doc("Membership Type", name, force=True)
