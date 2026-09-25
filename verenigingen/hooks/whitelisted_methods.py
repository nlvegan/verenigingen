# verenigingen/hooks/whitelisted_methods.py
"""Overrides for whitelisted RPCs, keyed by the ORIGINAL dotted method path.

frappe.override_whitelisted_method() consults this at dispatch time
(frappe/handler.py, frappe/api/v2.py, frappe/model/mapper.py,
frappe/desk/treeview.py) and resolves the last entry in each list instead of
the original method -- see frappe/hooks.py's own override_whitelisted_methods
for the pattern this follows.
"""

override_whitelisted_methods = {
    # #1411: both frappe.client.has_permission and frappe.client.
    # get_doc_permissions load the caller-supplied docname before deciding
    # permission, raising frappe.DoesNotExistError for an unknown one while
    # returning a value for a real-but-forbidden one -- an existence oracle
    # over any doctype/docname pair. See
    # verenigingen/utils/security/core_client_permission_oracle.py for the fix.
    "frappe.client.has_permission": [
        "verenigingen.utils.security.core_client_permission_oracle.has_permission"
    ],
    "frappe.client.get_doc_permissions": [
        "verenigingen.utils.security.core_client_permission_oracle.get_doc_permissions"
    ],
}
