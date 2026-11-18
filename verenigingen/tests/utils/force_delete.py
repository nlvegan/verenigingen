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


def release_single_links_to_chapter(chapter_name: str) -> None:
    """Clear every Single's Link field that names ``chapter_name`` (#2745).

    A Chapter delete is refused while anything links to it, even under force=1, and a
    Single's value (``Verenigingen Settings.national_board_chapter``) is a link like any
    other. A test that points a Single at its throwaway Chapter restores the old value in
    an ``addCleanup``, which runs AFTER teardown's deletes, so without this the Chapter
    leaks. Only a value that names THIS Chapter is cleared.
    """
    fields = frappe.get_all(
        "DocField", filters={"fieldtype": "Link", "options": "Chapter"}, fields=["parent", "fieldname"]
    ) + frappe.get_all(
        "Custom Field",
        filters={"fieldtype": "Link", "options": "Chapter"},
        fields=["dt as parent", "fieldname"],
    )
    for field in fields:
        if not frappe.db.exists("DocType", field.parent) or not frappe.get_meta(field.parent).issingle:
            continue
        if frappe.db.get_single_value(field.parent, field.fieldname) == chapter_name:
            frappe.db.set_single_value(field.parent, field.fieldname, None, update_modified=False)


def vacate_board_seats_of_chapters(chapter_names) -> None:
    """Delete the board seats of Chapters about to be drained, while their people still exist.

    The Member drain runs before the Chapter's, and a Chapter delete is refused while a
    Volunteer still links to it (#2745), so the Chapter is retried by the captured-insert
    drain, in reverse creation order. That reaches the standalone Chapter Board Member row
    BEFORE its Volunteer, and the row's ``after_delete`` then re-saves a Volunteer whose
    Member is already gone (``LinkValidationError``, a leak). Removing the rows first,
    through the normal delete, lets their hooks run against living records. A seat that
    cannot be removed here is rolled back to its savepoint and left for the drains, which
    record it as a leak with its reason.
    """
    from frappe.database import savepoint

    for chapter_name in chapter_names:
        for seat in frappe.get_all("Chapter Board Member", filters={"parent": chapter_name}, pluck="name"):
            with savepoint(catch=Exception):
                frappe.delete_doc("Chapter Board Member", seat, force=True, ignore_permissions=True)


def chapters_last(doc_infos) -> list:
    """``doc_infos`` in the same order, except every Chapter goes after everything else (#2745).

    A tracked Chapter is usually created AFTER the Member and Volunteer that end up linked
    to it, so draining in reverse creation order reaches the Chapter first, and the Chapter
    delete is now refused while they exist. Stable, so the order among the rest, and among
    the Chapters, is untouched.
    """
    doc_infos = list(doc_infos)
    return [d for d in doc_infos if d["doctype"] != "Chapter"] + [
        d for d in doc_infos if d["doctype"] == "Chapter"
    ]
