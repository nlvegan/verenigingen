"""Report members holding more than one Active SEPA Mandate (#584).

`SEPAMandate.validate_single_active_mandate` now rejects a second Active mandate for
a member. Rows that predate that guard are not rewritten by it, so this patch finds
them and says so.

It REPORTS; it does not throw, and that is the difference from
`enforce_unique_volunteer_per_member`, which is the obvious model for this and the
wrong one. That patch has to raise because declaring `unique: 1` on Volunteer.member
makes the following schema sync build a unique index, and on duplicate data the sync
dies on a raw MySQL 1062 naming nothing an operator can act on -- the patch converts
that into a diagnosis it alone can give.

Nothing equivalent happens here. The constraint is a `validate` hook, not an index:
MariaDB has no partial unique index, so "one Active mandate per member" cannot be
expressed as `unique: 1` on a column at all. No sync will fail, and the runtime
degrades safely rather than silently --

  - `get_invoice_mandate_info` REFUSES an ambiguous member instead of debiting the
    most recently created IBAN, and logs the candidates;
  - saving any of the offending mandates raises, naming the one in the way.

So a throw here would block a migration to prevent nothing, and would do it on
installs whose only symptom is a batch that declines to guess. Reporting is
proportionate; the list is what an operator needs either way.

It also does NOT pick a survivor. Which mandate a member intends to be charged on is
a data decision -- the wrong choice debits a closed account -- and it is exactly the
decision #584 exists to stop code from making by itself.
"""

import frappe


def execute():
    if not frappe.db.table_exists("SEPA Mandate"):
        return

    duplicates = frappe.db.sql(
        """
        SELECT member,
               COUNT(*) AS count,
               GROUP_CONCAT(mandate_id ORDER BY creation) AS mandates
        FROM `tabSEPA Mandate`
        WHERE status = 'Active' AND member IS NOT NULL AND member != ''
        GROUP BY member
        HAVING count > 1
        ORDER BY count DESC
        """,
        as_dict=True,
    )

    if not duplicates:
        return

    shown = duplicates[:20]
    lines = [f"  - {d.member}: {d.count} active mandates ({d.mandates})" for d in shown]
    if len(duplicates) > len(shown):
        lines.append(f"  ... and {len(duplicates) - len(shown)} more")

    message = (
        f"{len(duplicates)} member(s) hold more than one Active SEPA Mandate.\n\n"
        + "\n".join(lines)
        + "\n\nSince #584 a member may hold only one. These rows are not rewritten "
        "automatically: which mandate a member intends to be charged on is a data "
        "decision, and choosing wrongly debits the wrong account. Until each of these "
        "members has a single Active mandate, direct debit batches will REFUSE to "
        "select an IBAN for them (rather than guess), and saving any of the mandates "
        "will raise. Cancel the superseded ones."
    )

    # print() as well as log_error: this runs under `bench migrate`, where stdout is
    # what the operator is actually watching, and `frappe.logger()` would write to a
    # file nobody reads (measured -- see CLAUDE.md).
    print(message)
    frappe.log_error(title="SEPA: members with multiple active mandates (#584)", message=message)
