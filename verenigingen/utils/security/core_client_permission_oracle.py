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
for an unknown child row today; the wrapper below closes that too, the same
way as any other doctype -- `frappe.get_lazy_doc` raising is exactly the
case its `except frappe.DoesNotExistError` handles, regardless of table-ness.

`has_permission` never needs its own `frappe.PermissionError` branch:
`client.has_permission` calls `frappe.has_permission(..., docname)` without
`throw=True`, so `frappe.permissions.has_permission`'s own `raise
frappe.PermissionError` branch (gated on `throw`) is unreachable from this
call. Measured on test_site_4 against a bare "Verenigingen Member" role
user across a zero-permission doctype (Role, System Manager only), a Single
doctype, a child doctype, and an unknown doctype: none raised
`frappe.PermissionError` from that call, only `frappe.DoesNotExistError` or
a plain return value. `get_doc_permissions` is different as of the "Third
review round" below: it raises `frappe.PermissionError` itself, DELIBERATELY,
whenever `frappe.has_permission(doctype, "read", doc)` returns falsy for an
existing document -- see that section for the behaviour-change this implies.

## Second review round: two more leaks (fixed in 84fffff15, since revised again)

`84fffff15` fixed a message-log leak in `has_permission` (below) and
replaced `get_doc_permissions`'s substitution with a synthetic
`frappe.new_doc(doctype)` shaped to look like an unowned record. An
independent review of THAT approach found it reopened the exact oracle
class this file exists to close -- see "Third review round" below for why
it was replaced rather than patched.

**`has_permission`'s message-log leak.** `frappe.permissions.has_permission`,
when a `doc` is given and the computed permission is falsy, builds an error
MESSAGE by calling `has_permission(doc.doctype)` (no `doc` this time,
ptype-only) purely to decide whether to append "- doc.name" to it. On
Frappe 16.30 that nested call did not pass `print_logs`, so it defaulted to
`True` regardless of the OUTER call's own `print_logs=False`
(`client.has_permission` always calls with `throw=False`, hence
`print_logs=False`), and its `print_has_permission_check_logs` decorator
(`frappe/permissions.py:43`) would `msgprint(...)` "User X does not have
doctype access via role permission for document Y" into
`frappe.message_log` whenever the caller lacked doctype-level read entirely
-- but ONLY on the EXISTS path (that nested call only runs once
`frappe.get_lazy_doc` has already succeeded), so a fix that only cleared
the message on the unknown/except branch left this untouched. **On Frappe
16.35 this nested call now passes `print_logs=False` explicitly
(`frappe/permissions.py:151`), and the outer call passes `print_logs=throw`
(`frappe/__init__.py`), so this specific leak no longer reproduces on stock
16.35** -- confirmed by reading both call sites. The length-trim below is
kept anyway: harmless, and it costs nothing to stay correct if a future
Frappe version reintroduces an unguarded nested call, or if some other path
through `get_doc_permissions`/`has_permission` ever queues something.

**Fix, unchanged from the second review round:** capture
`len(frappe.message_log)` before calling `frappe.has_permission(...)`, and
delete everything queued past that point on every exit path EXCEPT a
re-raise (Administrator, or the doctype itself unknown) -- preserving
Administrator's and the DocType-existence case's current message exactly.

## Third review round: get_doc_permissions redesigned -- no more synthetic document

**CRITICAL, confirmed:** the synthetic `frappe.new_doc(doctype)` approach
(84fffff15) reopened the SAME oracle class it exists to close, on every
User-Permission-scoped doctype. `frappe.new_doc()` -> `get_new_doc` ->
`make_new_doc` -> `set_user_and_static_default_values`
(`frappe/model/create_new.py`) autofills Link field defaults from the
**calling user's own** `is_default=1` User Permissions. So the synthetic
"unknown" document did not look like an arbitrary foreign record -- it
looked like a record sitting INSIDE the caller's own User-Permission scope.
Measured (test_site_4, 16.35, role "Accounts User" -- real DocPerm `read=1`
on Cost Center -- plus a User Permission `{allow: "Company", for_value:
"_Test Company", is_default: 1}`):

| record                                    | `get_doc_permissions` shape          |
|-------------------------------------------|---------------------------------------|
| real, in-scope (Company = "_Test Company") | `{..., read: 1, print: 1, email: 1, report: 1, ...}` |
| real, OUT-of-scope (Company = "_Test Company 1") | `{}` (fully denied) |
| **unknown docname** (via the synthetic doc) | `{..., read: 1, print: 1, email: 1, report: 1, ...}` -- **matches the IN-scope record, not the out-of-scope one** |

An unknown docname was indistinguishable from a record the caller CAN read,
and clearly distinguishable from one the caller cannot -- the exact
inversion of this file's purpose, on any doctype with a User-Permission-
scoped Link field (Company/Cost Center/Warehouse/Territory and similar are
common in ERPNext). The old (pre-84fffff15) version had a guard for exactly
this (`_doctype_may_be_user_permission_restricted`, falling back to `{}`);
it was removed along with the rest of the old function body and not
replaced, which is what reopened this.

**Also found: `_forbidden_doc_permissions`'s bare `except Exception: return
{}` silently swallowed `verenigingen.utils.transaction_errors.
NON_RESUMABLE_DB_ERRORS` (`QueryDeadlockError`, `QueryTimeoutError`) with no
logging at all** -- exactly the "silent swallow, worse than log-and-return"
class that module's own docstring warns against, since a 1213/1205 rolls
back the whole transaction and the caller would continue against state the
DB has already discarded, believing it got an ordinary "forbidden" answer.

**Fix (this round): stop synthesising a shape entirely.** `get_doc_permissions`
now answers only for documents the caller can actually READ, and refuses
identically (a `frappe.PermissionError`, no message-log residue) for
everything else -- an existing-but-unreadable document included:

```python
log_len = len(frappe.message_log)
try:
    doc = frappe.get_lazy_doc(doctype, docname)
    readable = frappe.has_permission(doctype, "read", doc)
except frappe.DoesNotExistError:
    if user == "Administrator" or not frappe.db.exists("DocType", doctype):
        raise
    del frappe.message_log[log_len:]
    readable = False
else:
    del frappe.message_log[log_len:]

if not readable:
    raise frappe.PermissionError(_("Not permitted"))
return {"permissions": frappe.permissions.get_doc_permissions(doc)}
```

Note the trim is NOT a blanket `finally`: a `finally` runs even while an
exception is propagating out of the `except` block's own `raise`, which
would have deleted the "not found" message Administrator (or an
unknown-doctype caller) is about to see -- exactly the message this fix
must NOT touch for those two re-raise paths. The `del` only happens on the
`else` branch (real success) and after the `if ...: raise` check inside
`except` (only when NOT re-raising).

This has no synthetic document to leak the caller's own scope: `doc` is
either a REAL document (the `if not readable:` check runs `frappe.
has_permission` against it exactly as core's own permission-scoped views
already do) or the function never reaches that line at all (`get_lazy_doc`
raised, `readable` was set to `False` directly, no document was ever
loaded or looked at). `NON_RESUMABLE_DB_ERRORS` are not caught by anything
here -- only `frappe.DoesNotExistError` is, so a deadlock/timeout raised
from `frappe.get_lazy_doc` or `frappe.has_permission` propagates unchanged,
exactly as it would from unmodified core.

**Deliberate behaviour change:** an existing-but-unreadable document now
gets a 403 `PermissionError` instead of `{"permissions": {...mostly
zero...}}` (still 200). Checked the in-repo callers of `frappe.client.
get_doc_permissions`: `frappe/public/js/frappe/views/kanban/kanban_view.js`
(a Kanban Board the view is already displaying -- reachable only via a
board the caller already listed/opened) and hrms's `FormView.vue` /
`RequestActionSheet.vue` (a document already open in the form / an action
sheet for a request already in hand). All three ask about a document the
caller has, by construction, already been shown -- none probes an
arbitrary or foreign id -- so none is expected to hit the new refusal in
normal operation; if one somehow does (the record became unreadable
between load and this call), it now gets an error response instead of a
silently near-empty permissions dict, which is the intended tightening.

Measured on test_site_4 (16.35), roleless caller, across User (a standard
name, an ordinary existing user, and the caller's own record), ToDo
(foreign vs. assigned-to-self), and Role, each paired with an unknown name:
forbidden and unknown are IDENTICAL (`frappe.PermissionError("Not
permitted")`, empty message log, same HTTP shape over a real WSGI round
trip), and a readable/own record still returns the real permission dict.
See this file's tests for the full matrix, including the User-Permission
case from Finding A above (an is_default-scoped user, Cost Center)."""

import frappe
from frappe import _


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
    """Answers only for documents the caller can READ; refuses identically
    (frappe.PermissionError, no distinguishing message-log residue) for an
    unknown docname and for an existing-but-unreadable one alike. See the
    module docstring's "Third review round" section for why this doesn't
    synthesise a permissions shape the way the previous version did, and
    for the deliberate behaviour-change this implies for a caller asking
    about a document it cannot read (a 403 now, not a mostly-empty dict).

    :param doctype: DocType of the document to be evaluated
    :param docname: `name` of the document to be evaluated
    """
    user = frappe.session.user
    log_len = len(frappe.message_log)
    try:
        doc = frappe.get_lazy_doc(doctype, docname)
        readable = frappe.has_permission(doctype, "read", doc)
    except frappe.DoesNotExistError:
        if user == "Administrator" or not frappe.db.exists("DocType", doctype):
            # NOT a blanket `finally`: this raise must carry the "not found"
            # message frappe.get_lazy_doc already queued, unmodified, for
            # Administrator and for an unknown doctype -- trimming here
            # would delete the very message this path exists to preserve.
            raise
        del frappe.message_log[log_len:]
        readable = False
    else:
        del frappe.message_log[log_len:]

    if not readable:
        raise frappe.PermissionError(_("Not permitted"))
    return {"permissions": frappe.permissions.get_doc_permissions(doc)}
