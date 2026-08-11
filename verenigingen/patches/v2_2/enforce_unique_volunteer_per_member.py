"""Prepare `tabVolunteer` for the unique index on `member` (#267).

This is a pre_model_sync patch ON PURPOSE. Declaring `unique: 1` on
Volunteer.member makes the schema sync build a unique index during `bench migrate`;
if the table already holds two volunteers for one member, that sync dies on a raw
MySQL 1062 naming nothing an operator can act on. Running first turns that into a
precise diagnosis, and normalises the one data shape that would break the index for
reasons unrelated to duplicates.

It does NOT create the index -- the sync does, from the DocType JSON. That split
matters for fresh installs: frappe/installer.py:333 marks every patch as completed
on install without running it, so a DDL-only patch would never reach a new site.

It also does NOT merge duplicates. Eight doctypes link to Volunteer (Chapter Board
Member, Team Member, Volunteer Activity, Member Volunteer Expenses, Event Contact
Campaign Member, Movement Member, Member, plus fixtures); choosing a survivor and
repointing those rows is a data decision, not a migration's call.
"""

import frappe


def execute():
    if not frappe.db.table_exists("Volunteer"):
        return

    _normalise_empty_member_links()
    _abort_on_duplicates()


def _normalise_empty_member_links():
    """Turn `member = ''` into NULL.

    MySQL permits any number of NULLs under a unique index but only ONE empty
    string, so a population of unlinked volunteers stored as '' would collide with
    each other and look exactly like a duplicate-member problem. Frappe writes NULL
    for an unset Link today, but rows written by older code, imports or direct SQL
    may not have.
    """
    affected = frappe.db.sql("SELECT COUNT(*) FROM `tabVolunteer` WHERE member = ''")[0][0]
    if not affected:
        return

    print(f"Normalising {affected} Volunteer row(s) with an empty-string member to NULL")
    frappe.db.sql("UPDATE `tabVolunteer` SET member = NULL WHERE member = ''")


def _abort_on_duplicates():
    """Stop the migration with an actionable list rather than let the sync fail.

    Deliberately raises. The alternative -- log and continue, as
    add_bank_transaction_reference_unique_index does -- is not available here: that
    patch owns its index and can decline to create it, whereas this one cannot stop
    the schema sync that follows. Failing here at least says which members are
    affected; failing in the sync says only "Duplicate entry".
    """
    duplicates = frappe.db.sql(
        """
        SELECT member, COUNT(*) AS count, GROUP_CONCAT(name ORDER BY creation) AS volunteers
        FROM `tabVolunteer`
        WHERE member IS NOT NULL AND member != ''
        GROUP BY member
        HAVING count > 1
        ORDER BY count DESC
        """,
        as_dict=True,
    )

    if not duplicates:
        return

    shown = duplicates[:20]
    lines = [f"  - {d.member}: {d.count} volunteers ({d.volunteers})" for d in shown]
    if len(duplicates) > len(shown):
        lines.append(f"  ... and {len(duplicates) - len(shown)} more")

    detail = "\n".join(lines)
    message = (
        f"Cannot enforce one Volunteer per Member: {len(duplicates)} member(s) have more than one.\n\n"
        f"{detail}\n\n"
        "Volunteer.member is now declared unique, so this migration cannot proceed until each "
        "member has a single Volunteer record. Merge or delete the extras by hand -- repointing "
        "Chapter Board Member, Team Member, Volunteer Activity and expense rows to the surviving "
        "record is a data decision this patch will not make for you. See issue #267."
    )

    frappe.log_error(message=message, title="Volunteer Uniqueness Migration - Duplicates Found")
    frappe.throw(message)
