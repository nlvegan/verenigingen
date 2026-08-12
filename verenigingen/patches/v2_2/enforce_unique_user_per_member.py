"""Prepare `tabMember` for the unique index on `user` (#269).

This is a pre_model_sync patch ON PURPOSE, for the same reason as its sibling
enforce_unique_volunteer_per_member (#267): declaring `unique: 1` on Member.user makes
the schema sync build a unique index during `bench migrate`, and if the table already
holds two members for one user that sync dies on a raw MySQL 1062 naming nothing an
operator can act on. Running first turns that into a precise diagnosis, and normalises
the one data shape that would break the index for reasons unrelated to duplicates.

It does NOT create the index -- the sync does, from the DocType JSON. That split matters
for fresh installs: frappe/installer.py:333 marks every patch as completed on install
without running it, so a DDL-only patch would never reach a new site.

It also does NOT merge duplicates. Choosing which Member survives, and repointing the
memberships, dues schedules, SEPA mandates, volunteer and chapter rows that hang off the
loser, is a data decision rather than a migration's call.
"""

import frappe


def execute():
    if not frappe.db.table_exists("Member"):
        return

    _normalise_empty_user_links()
    _abort_on_duplicates()


def _normalise_empty_user_links():
    """Turn `user = ''` into NULL.

    MySQL permits any number of NULLs under a unique index but only ONE empty string, so
    a population of members with no login stored as '' would collide with each other and
    look exactly like a duplicate-user problem. Frappe writes NULL for an unset Link
    today, but rows written by older code, imports or direct SQL may not have. Measured
    2026-08-12: veg11 has 0 such rows, which is why this is cheap insurance rather than a
    known cleanup.
    """
    affected = frappe.db.sql("SELECT COUNT(*) FROM `tabMember` WHERE user = ''")[0][0]
    if not affected:
        return

    print(f"Normalising {affected} Member row(s) with an empty-string user to NULL")
    frappe.db.sql("UPDATE `tabMember` SET user = NULL WHERE user = ''")


def _abort_on_duplicates():
    """Stop the migration with an actionable list rather than let the schema sync fail.

    Deliberately raises. This patch cannot stop the sync that follows it, so the choice
    is between failing here with the affected users named and failing there with
    "Duplicate entry" and nothing else.

    Why one Member per User matters beyond tidiness: 42 production call sites resolve this
    link with a single-row `frappe.db.get_value("Member", {"user": user}, "name")` and none
    iterate. That lookup emits ORDER BY creation DESC, so a duplicate silently hands every
    one of them the NEWEST row -- including the permission paths in permissions.py,
    project_permissions.py and dues_schedule_permission_service.py. Authorization answers
    would depend on row order. See #269, and #257/#267 for the same failure class.
    """
    duplicates = frappe.db.sql(
        """
        SELECT user, COUNT(*) AS count, GROUP_CONCAT(name ORDER BY creation) AS members
        FROM `tabMember`
        WHERE user IS NOT NULL AND user != ''
        GROUP BY user
        HAVING count > 1
        ORDER BY count DESC
        """,
        as_dict=True,
    )

    if not duplicates:
        return

    shown = duplicates[:20]
    lines = [f"  - {d.user}: {d.count} members ({d.members})" for d in shown]
    if len(duplicates) > len(shown):
        lines.append(f"  ... and {len(duplicates) - len(shown)} more")

    detail = "\n".join(lines)
    message = (
        f"Cannot enforce one Member per User: {len(duplicates)} user(s) are linked to more "
        f"than one member.\n\n"
        f"{detail}\n\n"
        "Member.user is now declared unique, so this migration cannot proceed until each user "
        "links to a single Member record. Resolve the extras by hand -- repointing memberships, "
        "dues schedules, SEPA mandates and volunteer records to the surviving member is a data "
        "decision this patch will not make for you. Clearing `user` on the rows that should not "
        "own the login is usually the smaller change. See issue #269."
    )

    frappe.log_error(message=message, title="Member User Uniqueness Migration - Duplicates Found")
    frappe.throw(message)
