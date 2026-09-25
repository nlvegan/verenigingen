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
version of the same mechanism. #1401 (proposed in PR #1416, `_require_team_permission`
in `verenigingen/api/team_management.py`, still open) is the established fix
shape this file follows: catch the raise, fold it into the same refusal a
real forbidden record gets.

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
same substitution as any other doctype (measured on "Has Role", a child of
User: an existing-but-inaccessible row and `_forbidden_doc_permissions`'s
output for an unknown one match exactly).

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

## Second review round: two more leaks, both fixed here

**1. `_forbidden_doc_permissions`'s old hook-based shortcut was wrong.** It
assumed any doctype with a registered `has_permission` hook always denies,
returning a constant `{None: 0}`. That is false: a controller hook decides
PER DOCUMENT. `frappe/core/doctype/user/user.py:1281` denies only for
`STANDARD_USERS` (Administrator, Guest) and permits everyone else
unconditionally -- so for an existing NON-standard User, `get_doc_permissions`
falls through to the role-permission dict, which is very often non-zero (e.g.
a "Verenigingen Volunteer" caller got `select: 1, export: 1` in the
measurement below). An unknown email then looked exactly like Administrator
(`{None: 0}`) and UNLIKE every real user -- User is this fix's headline
target, so the oracle was still open there even though the three doctypes
the first test suite covered (User, ToDo, Member) all happened to have hooks
that deny unconditionally for the specific existing records those tests used
(Administrator, a foreign ToDo, a foreign Member), masking the bug.

**Fix:** stop reasoning about hooks in the abstract. `_forbidden_doc_permissions`
now builds a transient, UNSAVED `frappe.new_doc(doctype)`, sets `.name` to the
requested (nonexistent) docname and `.owner` to a value guaranteed not to be
the caller (`"Administrator"` -- this branch only ever runs for a
non-Administrator caller, checked above), and calls the REAL
`frappe.permissions.get_doc_permissions(doc, user=user)` against it. The
controller hook, the role-permission computation, and the User Permission /
ownership scoping all then run exactly as they would for a real record the
caller does not own -- because a `has_permission` hook can only inspect the
document's own fields and the caller's roles, neither of which differs
between a genuine foreign record and this fabricated stand-in (verified: no
registered hook function reads anything from the document that a fresh
`new_doc()` lacks -- see "Measured" below). `frappe.new_doc()` itself performs
no DB writes (traced `frappe.db.sql` across all 4 combinations below and
across all 31 app+core doctypes with a registered hook: zero non-SELECT
queries).

**Measured** on test_site_4, for a roleless user (roles: All, Guest only) and
separately for a "Verenigingen Volunteer" user, comparing this function's
output for an UNKNOWN docname against `frappe.permissions.get_doc_permissions`
called directly on a REAL existing-but-foreign record of the same doctype:

| doctype | caller    | existing-foreign (real)                                              | unknown (this function) |
|---------|-----------|-----------------------------------------------------------------------|--------------------------|
| User    | roleless  | `{..., 'select': 0, 'read': 0, ...}` (all zero)                        | identical |
| User    | volunteer | `{..., 'select': 1, 'read': 0, ...}` (role grants `select`)            | identical |
| ToDo    | either    | `{None: 0}` (hook denies an empty/unowned doc)                         | identical |
| Member  | either    | `{None: 0}` (hook denies: owner != caller)                             | identical |
| Role (no hook) | either | `{..., 'select': 0, 'read': 0, ...}` (all zero, role grants nothing) | identical |

Also swept all 31 doctypes app-wide (core + Verenigingen) that register a
`has_permission` hook, calling `get_doc_permissions` against a synthetic
unowned doc as the roleless user: zero raised exceptions. Still, a hook this
sweep didn't reach, or a future one, could read a field an empty document
lacks and raise -- the call is wrapped in a narrow `try/except Exception`
that falls back to `{}` (get_doc_permissions' own "fully denied" shape) if it
ever does, rather than letting that surface as a distinguishable error.

**Where no single shape can be claimed to match EVERY existing record of a
doctype, this function does not claim that -- it matches what an unowned
record of that doctype produces**, which is what `has_controller_permissions`
and `has_user_permission` decide from the caller's roles and an unmatched
ownership field, not from a real document's specific business data.  A
doctype whose PERMISSION outcome for a real, existing, non-owned record
depends on something a document ID cannot reveal in advance (business-data
scoping unrelated to ownership/hooks/roles) is not known to exist in this
app or in Frappe core as of this measurement; if one is found later, this
function's claim is scoped to "matches an unowned record," not "matches
every record."

**2. `has_permission`'s message-log leak was not fully closed -- residue on
the EXISTS path too, not just the unknown one.** The same mechanism PR #1416
found (commit 15b605f60): `frappe.permissions.has_permission`, when a `doc`
is given and the computed permission is falsy, builds an error MESSAGE by
calling `has_permission(doc.doctype)` (no `doc` this time, ptype-only) purely
to decide whether to append "- doc.name" to it. That nested call is wrapped
by `print_has_permission_check_logs` (`frappe/permissions.py:43`), whose
`print_logs` kwarg was not passed and so DEFAULTS to `True` regardless of the
OUTER call's own `print_logs=False` (`client.has_permission` always calls
with `throw=False`, hence `print_logs=False` -- see above). When the caller
lacks doctype-level read entirely, that nested call's own decorator does
`msgprint(...)` -- unconditionally, regardless of the outer call's intent --
queuing "User X does not have doctype access via role permission for
document Y" into `frappe.message_log`. This ONLY happens on the EXISTS path
(the nested call is inside the `if doc:` branch, reached only once
`frappe.get_lazy_doc` has already succeeded), so `clear_last_message()` in the
`except` branch could not touch it -- it lives on the OTHER branch entirely.
Measured (roleless caller, "Role" doctype -- no controller hook, so the
whole difference is this message-log side effect): an EXISTING role the
caller cannot read left this message in `frappe.message_log`; an UNKNOWN
role name left none (after this fix's substitution) -- a caller who reads
`message_log`/`_server_messages` alongside the return value could tell them
apart despite both replying `{"has_permission": false}`.

**Fix:** capture `len(frappe.message_log)` before calling
`frappe.has_permission(...)`, and delete everything queued past that point on
every exit path EXCEPT a re-raise (Administrator, or the doctype itself
unknown) -- preserving Administrator's and the DocType-existence case's
current message exactly, and leaving both the real-permission-computed
success path and the substituted unknown-docname path equally silent, which
is what `client.has_permission`'s own `print_logs=False` intent already
promised before this nested-call quirk defeated it.
"""

import frappe


@frappe.whitelist()
def has_permission(doctype: str, docname: str, perm_type: str = "read"):
    """Same contract as frappe.client.has_permission, without the existence oracle.

    :param doctype: DocType of the document to be checked
    :param docname: `name` of the document to be checked
    :param perm_type: one of `read`, `write`, `create`, `submit`, `cancel`, `report`. Default is `read`.
    """
    user = frappe.session.user
    log_len = len(frappe.message_log)
    try:
        allowed = frappe.has_permission(doctype, perm_type.lower(), docname)
    except frappe.DoesNotExistError:
        if user == "Administrator" or not frappe.db.exists("DocType", doctype):
            raise
        # Both the "not found" message the raise itself queued, and (on the
        # sibling success path below) the doctype-access message a nested
        # has_permission() call can queue regardless of print_logs -- see the
        # module docstring's "Second review round" section, item 2.
        del frappe.message_log[log_len:]
        return {"has_permission": False}
    del frappe.message_log[log_len:]
    return {"has_permission": allowed}


@frappe.whitelist()
def get_doc_permissions(doctype: str, docname: str):
    """Same contract as frappe.client.get_doc_permissions, without the existence oracle.

    :param doctype: DocType of the document to be evaluated
    :param docname: `name` of the document to be evaluated
    """
    user = frappe.session.user
    log_len = len(frappe.message_log)
    try:
        doc = frappe.get_lazy_doc(doctype, docname)
    except frappe.DoesNotExistError:
        if user == "Administrator" or not frappe.db.exists("DocType", doctype):
            raise
        del frappe.message_log[log_len:]
        return {"permissions": _forbidden_doc_permissions(doctype, docname, user)}
    result = {"permissions": frappe.permissions.get_doc_permissions(doc)}
    del frappe.message_log[log_len:]
    return result


def _forbidden_doc_permissions(doctype: str, docname: str, user: str) -> dict:
    """Reproduce get_doc_permissions' shape for an UNOWNED record of `doctype`,
    without a real document to evaluate (there isn't one -- `docname` doesn't
    exist). See the module docstring's "Second review round" section, item 1,
    for the measurement behind this approach and its scope.
    """
    doc = frappe.new_doc(doctype)
    doc.name = docname
    # Guaranteed not to be the caller: this function is only ever reached for
    # a non-Administrator caller (checked by both call sites above).
    doc.owner = "Administrator"
    try:
        return frappe.permissions.get_doc_permissions(doc, user=user)
    except Exception:
        # A hook (this app's own, or a future core one) reading a field an
        # empty document lacks is the only way this can raise -- none of the
        # 31 currently-registered has_permission hooks do (measured). Fail
        # closed rather than let an unanticipated raise become a new,
        # distinguishable outcome.
        return {}
