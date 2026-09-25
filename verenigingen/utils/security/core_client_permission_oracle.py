"""Overrides for two Frappe CORE RPCs that expose a record-existence oracle.

`frappe.client.has_permission(doctype, docname, perm_type="read")` and
`frappe.client.get_doc_permissions(doctype, docname)` (both defined in
`frappe/client.py`, both bare `@frappe.whitelist()` with no additional gate of
their own) resolve the caller-supplied `docname` by loading it BEFORE any
permission decision is made:

- `has_permission` calls `frappe.has_permission(doctype, ptype, docname)`,
  whose implementation (`frappe.permissions.has_permission`) does
  `doc = frappe.get_lazy_doc(meta.name, doc)` whenever `doc` is a raw
  string/int rather than an already-loaded Document.
- `get_doc_permissions` calls `frappe.get_lazy_doc(doctype, docname)` directly,
  with no permission guard around the load at all.

`frappe.get_lazy_doc` raises `frappe.DoesNotExistError` for an unknown name,
while the identical call returns a value (not an exception) for a
real-but-forbidden one -- two different outcomes (a 404 vs. a 200 with a
value) for the identical "can I access this id" question, for ANY doctype and
ANY docname, reachable by any authenticated user regardless of role. See
issue #1411 (core-reachability finding) and #1401/#1394 for the app-level
version of the same mechanism. #1401 (fixed by PR #1416, `_require_team_permission`
in `verenigingen/api/team_management.py`) is the established fix shape this
file follows: catch the raise, fold it into the same refusal a real forbidden
record gets.

**Administrator is exempt from only half of this pair.**
`frappe.permissions.has_permission` short-circuits to `True` for the literal
"Administrator" user before ever loading the document, so `client.
has_permission` never raises for Administrator regardless of `docname` --
nothing to fix there, and the wrappers below never intervene for that user.
`frappe.get_lazy_doc` has no such short-circuit, so `client.get_doc_permissions`
DOES raise for Administrator on an unknown docname today; that is Administrator's
existing "not found" experience (there is no "forbidden" state for
Administrator to hide it behind), so the `get_doc_permissions` wrapper below
explicitly re-raises for that user rather than masking it.

**Only a record-existence oracle is in scope here, not a DocType-existence
one.** An invalid `doctype` argument (as opposed to a valid doctype with an
unknown `docname`) raises `frappe.DoesNotExistError` from `frappe.get_meta`
before either function reaches the record-existence question, and core's own
behaviour for that (visible to any authenticated user) is out of scope for
this fix -- doctype names are not a secrecy boundary the way record ids are.
Both wrappers below check `frappe.db.exists("DocType", doctype)` before
substituting a response, and re-raise unchanged when the doctype itself is
what does not exist.

Registered via `override_whitelisted_methods`
(`verenigingen/hooks/whitelisted_methods.py`), which `frappe.
override_whitelisted_method()` consults at dispatch (`frappe/handler.py`,
`frappe/api/v2.py`, `frappe/model/mapper.py`, `frappe/desk/treeview.py`) to
resolve the RPC name to these functions instead of the core ones. Everything
outside the unknown-docname branch calls straight through to the original core
implementation, so behaviour for Administrator, permitted callers, Single
doctypes (`docname` is ignored -- the single row is loaded by doctype name
regardless of what was passed), invalid doctype names, `perm_type` casing, and
int docnames is byte-identical to core. Child doctypes are also unaffected on
the `has_permission` side: `frappe.permissions.has_child_permission` resolves
the child row with a plain `frappe.db.get_value` (returns `None`, not a raise,
for an unknown row), so that path was never an oracle. `get_doc_permissions`
by contrast calls `frappe.get_lazy_doc` regardless of table-ness and DOES raise
for an unknown child row today; the wrapper below closes that too, using the
same substitution as any other doctype (measured: an existing-but-inaccessible
child row's real `get_doc_permissions` shape is the same "no controller hook"
zeroed-role-permission dict `_forbidden_doc_permissions` below reproduces).

No `frappe.PermissionError` branch is needed: `client.has_permission` calls
`frappe.has_permission(..., docname)` without `throw=True`, so
`frappe.permissions.has_permission`'s own `raise frappe.PermissionError` branch
(gated on `throw`) is unreachable from this call; and `client.
get_doc_permissions`'s `frappe.get_lazy_doc(doctype, docname)` call passes no
`check_permission`, so `get_doc_permission_check` never invokes
`doc.check_permission()` either. Measured on test_site_4 against a bare
"Verenigingen Member" role user across a zero-permission doctype (Role,
System Manager only), a Single doctype, a child doctype, and an unknown
doctype: none raised `frappe.PermissionError`, only `frappe.DoesNotExistError`
or a plain return value.
"""

import copy

import frappe
from frappe.utils import cint


@frappe.whitelist()
def has_permission(doctype: str, docname: str, perm_type: str = "read"):
    """Same contract as frappe.client.has_permission, without the existence oracle.

    :param doctype: DocType of the document to be checked
    :param docname: `name` of the document to be checked
    :param perm_type: one of `read`, `write`, `create`, `submit`, `cancel`, `report`. Default is `read`.
    """
    user = frappe.session.user
    try:
        allowed = frappe.has_permission(doctype, perm_type.lower(), docname)
    except frappe.DoesNotExistError:
        if user == "Administrator" or not frappe.db.exists("DocType", doctype):
            raise
        # frappe.get_lazy_doc's load_from_db appends "<doctype> <docname> not
        # found" to frappe.local.message_log via frappe.throw BEFORE raising
        # (frappe/model/document.py). Catching the exception leaves that
        # entry sitting in the log, which frappe.handler/frappe.api.v2 then
        # serialise into the response as _server_messages/messages -- so an
        # unknown docname's response body still carried the "not found" text
        # even though the status code and the has_permission value were
        # already fixed. Drop it before substituting, or the oracle survives
        # one layer up.
        frappe.clear_last_message()
        allowed = False
    return {"has_permission": allowed}


@frappe.whitelist()
def get_doc_permissions(doctype: str, docname: str):
    """Same contract as frappe.client.get_doc_permissions, without the existence oracle.

    :param doctype: DocType of the document to be evaluated
    :param docname: `name` of the document to be evaluated
    """
    user = frappe.session.user
    try:
        doc = frappe.get_lazy_doc(doctype, docname)
    except frappe.DoesNotExistError:
        if user == "Administrator" or not frappe.db.exists("DocType", doctype):
            raise
        # See the matching comment in has_permission() above: the "not found"
        # message is appended to frappe.local.message_log before the raise,
        # and survives in the response unless dropped here too.
        frappe.clear_last_message()
        return {"permissions": _forbidden_doc_permissions(doctype, user)}
    return {"permissions": frappe.permissions.get_doc_permissions(doc)}


def _forbidden_doc_permissions(doctype: str, user: str) -> dict:
    """Reproduce get_doc_permissions' shape for a forbidden record of `doctype`,
    without a real document to evaluate (there isn't one -- `docname` doesn't exist).

    frappe.permissions.get_doc_permissions(doc) checks, in order:

    1. `has_controller_permissions(doc, ptype, user)` -- a doctype's own
       `has_permission` hook. A hook can only ever DENY, never grant
       (`has_controller_permissions`' own docstring), and this check runs
       before anything doc-specific, so for ANY doctype with such a hook
       registered, `{ptype: 0}` is the correct denial shape regardless of what
       the hook would actually decide for a real document.
       `client.get_doc_permissions` always calls with `ptype=None`, so that
       shape is `{None: 0}`. Measured on test_site_4 for a bare "Verenigingen
       Member" role user against all three doctypes this fix's own tests
       cover -- User and ToDo both ship a core `has_permission` hook
       (`frappe.core.doctype.user.user.has_permission`,
       `frappe.desk.doctype.todo.todo.has_permission`); Member's is this app's
       own `verenigingen.permissions.has_member_permission` -- every
       existing-but-forbidden probe returned exactly `{None: 0}`.
    2. Role-permission computation (`get_role_permissions`), which needs only
       the DocType meta and the user's roles -- no document.
    3. User Permission / ownership scoping (`has_user_permission`,
       `is_user_owner`), which DOES need the document's own field values (e.g.
       which linked Company or Chapter it belongs to) and cannot be reproduced
       without one.

    So: when a controller hook is registered, match it exactly ({None: 0}).
    Otherwise, compute the role-permission dict (step 2), and if a real record
    of this doctype COULD be excluded from that by User Permission scoping on
    one of its link fields (step 3 is reachable for this user), fall back to
    `{}` -- get_doc_permissions' own shape for "not owner, no matching User
    Permission" -- rather than the role dict, which would look MORE permissive
    than any real forbidden record of this doctype can for this user (itself a
    distinguishing signal). When step 3 is not reachable for this user (no
    User Permission of theirs could ever apply to this doctype), the role dict
    IS what every real record of this doctype gives regardless of which one,
    so there is nothing left to distinguish "unknown" from "exists".
    """
    hooks = frappe.get_hooks("has_permission")
    if hooks.get(doctype) or hooks.get("*"):
        return {None: 0}

    meta = frappe.get_meta(doctype)
    permissions = copy.deepcopy(frappe.permissions.get_role_permissions(meta, user=user))
    if not cint(meta.is_submittable):
        permissions["submit"] = 0
    if not cint(meta.allow_import):
        permissions["import"] = 0

    if _doctype_may_be_user_permission_restricted(meta, doctype, user):
        return {}
    return permissions


def _doctype_may_be_user_permission_restricted(meta, doctype: str, user: str) -> bool:
    """Mirror frappe.permissions.has_user_permission's two existence checks
    (self-scoping and link-field scoping) closely enough to tell whether SOME
    real record of `doctype` could be excluded for `user` by a User Permission
    -- without needing an actual record to test it against."""
    from frappe.core.doctype.user_permission.user_permission import get_user_permissions

    user_permissions = get_user_permissions(user)
    if not user_permissions:
        return False

    if doctype in user_permissions:
        return True

    for field in meta.get_link_fields():
        if field.ignore_user_permissions:
            continue
        if field.options in user_permissions and frappe.permissions.get_allowed_docs_for_doctype(
            user_permissions.get(field.options, []), doctype
        ):
            return True

    return False
