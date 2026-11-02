"""Best-effort deletion of one record during test teardown.

Three test modules had grown a byte-identical private `_force_delete`, which the
duplicate-helper ratchet blocks for the usual reason: the next person fixes one copy
and the others keep the bug. This is that helper, once.

Swallowing every exception is the point, not laziness. A teardown that raises replaces
the test's real verdict with a cleanup error, and a record that resists deletion is
already reported -- with its identity and the reason -- by `leak_guard`, which is what
the leak ratchet reads. So there is nothing here worth failing a test over that is not
said better elsewhere.

`force=True` does NOT bypass Frappe's submitted check: `delete_doc` runs
`check_permission_and_not_submitted(doc)` before its `if not force:` guard, so a
submitted document has to be cancelled first. Callers that create submittable
documents must do that themselves; this helper deliberately does not, because
cancelling writes MORE rows (reversal ledger entries) and that is a decision the
caller has to make knowingly.
"""

import frappe


def force_delete(doctype: str, name: str) -> None:
    """Delete `name`, ignoring permissions and links; never raise."""
    try:
        frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
    except Exception:
        pass


def delete_role_and_grants(role_name: str) -> None:
    """Delete a Role and every `Has Role` row that points at it (#1665).

    Frappe's Role has `remove_roles()` but no `on_trash` that calls it, so a bare
    `delete_doc("Role", ..., force=True)` leaves the rows on every user that held the role
    (Administrator included). The next `User.save()` of such a user dies with "Could not find
    Row #N: Role: ...", and `before_tests` re-saves Administrator, so on a shard every later
    module fails. Unlike `force_delete` this raises: callers decide whether a failed role
    teardown matters.
    """
    frappe.db.delete("Has Role", {"role": role_name})
    frappe.delete_doc("Role", role_name, force=True, ignore_permissions=True)
