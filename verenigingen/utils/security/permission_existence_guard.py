"""Shared no-oracle wrapper for ``frappe.has_permission(doctype, ptype, name)``.

``frappe.has_permission(doctype, ptype, name)`` loads the named document
internally (``frappe.get_lazy_doc``) before consulting the permission tables,
whenever ``name`` is a raw string/int rather than an already-loaded Document
object. That load raises ``frappe.DoesNotExistError`` for an unknown name,
while the identical call returns plain ``False`` for a real-but-forbidden one
-- two different outcomes for the identical "can I access this id" question
(#1401, #1411).

``frappe.throw()`` (raised by the internal document load) also appends a
``"<DocType> <name> not found"`` entry to ``frappe.message_log`` BEFORE
raising, so catching the exception alone is not enough: that entry would
still ride along in ``_server_messages`` on an unknown id and not on a
foreign one, reopening the oracle in the response body even though the
exception itself is masked. A single ``frappe.clear_last_message()`` is not
sufficient either: ``frappe.has_permission``'s own internal message
composition (recomputing ``has_permission(doctype)`` with no ``doc``, to
decide whether to name the document in its own diagnostic) makes an
unrelated, unsuppressable recursive call that can queue its OWN message on
the SUCCESS/False path too, whenever the caller's role holds no blanket
doctype-level grant. So both branches are trimmed back to the
``message_log`` length captured before the call, discarding whatever
``frappe.has_permission`` queued on EITHER path.

This is the same pattern ``verenigingen.api.team_management.
_require_team_permission`` introduced for #1401 (PR #1416) and
``verenigingen.utils.security.core_client_permission_oracle`` applies (with
extra Administrator / DocType-existence re-raise handling of its own, needed
there because that module reproduces Frappe core's exact RPC contract) for
the equivalent core RPCs (#1430/#1436). Extracted here so every other
caller-supplied-name site in the app (#1411's census) shares one
implementation instead of a fourth copy of the same few lines.

Does NOT change behaviour for the literal "Administrator" user:
``frappe.permissions.has_permission`` short-circuits to ``True`` for
Administrator before ever touching the document, so it never raises here
regardless of ``name`` -- a subsequent ``frappe.get_doc`` still surfaces the
ordinary "not found" for a truly unknown id if the caller goes on to load it.
"""

import frappe


def permission_allowed_without_oracle(doctype: str, ptype: str, name) -> bool:
    """True/False, refusing IDENTICALLY for an unknown ``name`` and a
    real-but-forbidden one -- never raises ``frappe.DoesNotExistError``.

    Any OTHER exception (a deadlock/timeout, a hook error, ...) still
    propagates unchanged; only ``frappe.DoesNotExistError`` is folded into
    ``False``. Callers that need a distinguishable message for a refusal
    should build it themselves from ``doctype``/``ptype``/``name`` -- this
    helper only answers the yes/no question without leaking which branch
    produced it.
    """
    log_len = len(frappe.message_log)
    try:
        allowed = frappe.has_permission(doctype, ptype, name)
    except frappe.DoesNotExistError:
        allowed = False
    finally:
        del frappe.message_log[log_len:]
    return allowed
