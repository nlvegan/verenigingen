"""Clear `Member Payment History` rows whose Membership Dynamic Link cannot resolve.

A retired payment-history writer (`payment_mixin_optimized.py`, deleted during the
PR #174-#179 writer unification) set `reference_doctype = "Membership"` together with
a `reference_name` that is actually a **Membership Dues Schedule** name. Frappe's
`_validate_links()` looks the name up in `tabMembership`, never finds it, and raises

    LinkValidationError: Could not find Row #1: Reference Name: Schedule-...-Lid-001

That makes the *parent Member* unsavable by any full-document path — the failure has
nothing to do with whatever field the caller was actually trying to change. It first
surfaced as MijnRood Sync Event MR-SYNC-2026-00087 ("Member update failed") while
applying a plain address change; on veg11 all 430 membership-invoice payment-history
rows carried the bad link, i.e. 430 members could not be saved at all.

Why null rather than repoint
----------------------------
On veg11 every one of the 430 names *does* resolve as a `Membership Dues Schedule`, and
`reference_doctype` is a plain Data field, so repointing would validate. It is still
wrong: `PaymentHistoryEntryBuilder.build_from_query_row` only ever emits
`("Membership", SI.membership)` or `(None, None)`, so a Dues Schedule reference would be
a third shape no writer produces and no reader expects. Every affected row already
carries its invoice, and none of those invoices has `membership` set — so `(None, None)`
is precisely what the canonical writer would emit for these rows. `payment_history` is
also a derived cache (`PaymentHistoryService.load_payment_history_batched` clears and
rebuilds it), so a repointed value would be discarded on the next refresh anyway.

Nothing is truly lost: the discarded pairs are written to an Error Log entry first, and
the schedule remains derivable from the member.

Deliberately conservative — rows whose `reference_name` *does* resolve to a real
Membership are left untouched, so this is idempotent and safe to re-run.
"""

import frappe

_STALE_PREDICATE = """
    ph.reference_doctype = 'Membership'
    AND ph.reference_name IS NOT NULL
    AND ph.reference_name != ''
    AND m.name IS NULL
"""


def clear_stale_links(parent: str | None = None) -> tuple[int, int]:
    """Null unresolvable Membership references on Member Payment History rows.

    Args:
        parent: Restrict to a single Member. Tests pass this so they cannot
            silently repair rows belonging to other fixtures on a shared site;
            the patch itself runs unscoped.

    Returns:
        (rows_cleared, members_affected)
    """
    scope = " AND ph.parent = %(parent)s" if parent else ""
    params = {"parent": parent} if parent else {}

    stale = frappe.db.sql(
        f"""
        SELECT ph.parent, ph.reference_name
        FROM `tabMember Payment History` ph
        LEFT JOIN `tabMembership` m ON m.name = ph.reference_name
        WHERE {_STALE_PREDICATE} {scope}
        """,
        params,
        as_dict=True,
    )
    if not stale:
        return 0, 0

    members = {row.parent for row in stale}

    # Record what is being discarded before discarding it. The names resolve as
    # Membership Dues Schedules today, so leave a trail rather than making a
    # future maintainer reconstruct it.
    frappe.log_error(
        title="Patch: cleared stale Membership payment-history links",
        message="\n".join(f"{row.parent}\t{row.reference_name}" for row in stale),
    )

    frappe.db.sql(
        f"""
        UPDATE `tabMember Payment History` ph
        LEFT JOIN `tabMembership` m ON m.name = ph.reference_name
        SET ph.reference_doctype = NULL,
            ph.reference_name = NULL
        WHERE {_STALE_PREDICATE} {scope}
        """,
        params,
    )

    return len(stale), len(members)


def execute():
    rows, members = clear_stale_links()
    if not rows:
        return

    # print() is what `bench migrate` surfaces; these loggers default to ERROR,
    # so an .info() call here would go nowhere.
    print(
        f"Cleared {rows} unresolvable Membership link(s) from Member Payment History across {members} member(s)"
    )

    # migrate() clears the cache itself, but this is also reachable from a console
    # or a test, where stale cached Member docs would still carry the bad rows.
    frappe.clear_cache()
    frappe.db.commit()
