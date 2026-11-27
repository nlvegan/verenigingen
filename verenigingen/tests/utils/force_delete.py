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


def _chapter_side_row_company():
    """The company Chapter.after_insert creates its Cost Center/Department in (same order as
    DepartmentSyncService and ChapterFinanceService: Verenigingen Settings, then Global Defaults)."""
    for doctype, field in (("Verenigingen Settings", "company"), ("Global Defaults", "default_company")):
        company = frappe.db.get_single_value(doctype, field)
        if company and frappe.db.exists("Company", company):
            return company
    return None


def side_rows_of(doctype: str, name: str) -> list:
    """``(doctype, name)`` of the rows production hooks built BESIDE ``name``, which its delete leaves (#2209).

    Read BEFORE the parent is deleted: the Chapter's links to them go with it. Chapter's
    ``after_insert`` creates a Cost Center and a Department and ``chapter.py`` has no ``on_trash``;
    a Volunteer's creation queues an Account Creation Request and gives its User a Contact. A
    tracked-only drain never saw them, so a test whose body commits left them on the site. Whether
    a PRODUCTION Chapter delete should remove its Cost Center is an open product question; this
    only tidies what a test built.

    A Contact is claimed only if it is NOT older than the Volunteer, so one that predates the test
    (a shared user's) is never taken.
    """
    if doctype == "Chapter":
        # Found by the LINK, and by the NAME the sync services give them. The link alone missed a
        # Department: a later save of a stale in-memory Chapter wrote `department` back as empty
        # (MemberManager's request_to_join test), leaving it with no pointer to it. A name hit is
        # trusted only in the company the services create in, and only if it is not older than the
        # Chapter: a same-named row elsewhere, or a fixture (`Sales - _TC`), is not the Chapter's.
        cost_center, department, created = frappe.db.get_value(
            "Chapter", name, ["cost_center", "department", "creation"]
        ) or (None, None, None)
        cost_centers, departments = {cost_center}, {department}
        company = _chapter_side_row_company()
        if company:
            cost_centers |= set(
                frappe.get_all(
                    "Cost Center",
                    filters={"cost_center_name": f"{name} - Chapter", "company": company},
                    pluck="name",
                )
            )
            departments |= set(
                frappe.get_all(
                    "Department", filters={"department_name": name, "company": company}, pluck="name"
                )
            )
        # A row older than the Chapter was not made by it, even when it is the one the Chapter links
        # (the services link an existing same-named row instead of creating one).
        return [
            (dt, n)
            for dt, names in (("Cost Center", cost_centers), ("Department", departments))
            for n in names
            if n and created and frappe.db.exists(dt, n) and frappe.db.get_value(dt, n, "creation") >= created
        ]
    if doctype == "Volunteer":
        created, user = frappe.db.get_value("Volunteer", name, ["creation", "user"]) or (None, None)
        requests = frappe.get_all(
            "Account Creation Request",
            filters={"request_type": ["in", ["Volunteer", "Both"]], "source_record": name},
            fields=["name", "created_user"],
        )
        # The Volunteer's own `user` link is often empty: the pipeline that makes the User (and
        # through it the Contact) records it on the request instead.
        users = {u for u in [user] + [r.created_user for r in requests] if u}
        contacts = (
            frappe.get_all("Contact", filters={"user": ["in", list(users)], "creation": [">=", created]}, pluck="name")
            if users and created
            else []
        )
        return [("Account Creation Request", r.name) for r in requests] + [("Contact", n) for n in contacts]
    return []


def delete_side_rows(rows, attempts: int = 3, pause: float = 0.5) -> None:
    """Delete what ``side_rows_of`` returned, once the parent is gone. Never raises; logs a survivor.

    An Account Creation Request is retried on a lock timeout: it is queued, and a live RQ worker
    (this bench has them, CI does not) holds it ``FOR UPDATE`` while it processes it, which
    refuses the delete with ``QueryTimeoutError``.
    """
    import time

    from verenigingen.tests.harness_logger import get_harness_logger

    for doctype, name in rows:
        for attempt in range(attempts):
            if not (name and frappe.db.exists(doctype, name)):
                break
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                break
            except Exception as error:
                if attempt + 1 < attempts and isinstance(error, frappe.QueryTimeoutError):
                    time.sleep(pause)
                    continue
                get_harness_logger("force_delete").error(
                    f"#2209 side row {doctype} {name} survived its parent's delete: {error!r}"
                )
                break


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


def delete_chapter_member_row(row_name: str) -> None:
    """Remove one Chapter Member row without running its ``on_trash`` (#2745).

    ``on_trash`` mails the member a farewell and the board a notice, resolving the default
    company on the way. Teardown removing a row is not a member leaving, and a company that is
    broken at that moment (``test_approval_without_invoice`` restores it in an ``addCleanup``,
    after the drain) made the delete raise and leak the row. The row used to go silently with
    its Chapter's forced delete; the Chapter is now refused while its Member exists, so the
    drain reaches the row first.
    """
    frappe.db.delete("Chapter Member", {"name": row_name})
