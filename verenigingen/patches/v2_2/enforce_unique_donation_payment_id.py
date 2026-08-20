"""Prepare `tabDonation` for the unique index on `payment_id` (#345 part A).

A Mollie payment id identifies exactly one donation. Without a database
constraint two concurrent webhook deliveries both read "no donation for this
charge" and both insert; the money still books once -- the Bank Transaction and
Journal Entry creators are idempotent by reference -- but
PeriodicDonationAgreement.link_donation appends one child row per donation, so
the agreement's total_donated doubles for that period.

This is a pre_model_sync patch ON PURPOSE, and it does NOT create the index.
Declaring `unique: 1` on Donation.payment_id makes the schema sync build the
index during `bench migrate`; this patch only makes the data fit it first. The
split is what gets the constraint onto a FRESH install: frappe/installer.py
calls set_all_patches_as_completed() at install time, writing a Patch Log row
for every patch without running it, so a patch that created the index itself
would never reach a new site -- and CI builds its site with `reinstall` plus
`install-app`, never `migrate`. The already-dead
v2_1/add_mollie_payment_entry_unique_index is what that mistake looks like:
its index exists on no deployment on this bench.

Running before the sync also turns a halt into a resolution. The sync does not
fail obscurely -- mariadb/schema.py catches the 1062 and throws "payment_id
field cannot be set as unique in tabDonation, as there are non-unique existing
values" -- but that names only the field and the table, never the offending
donations, and it stops the migration dead. This patch names each one and
clears it, so migrate completes.

Two data steps, in order:

1. Normalise '' -> NULL. MariaDB permits many NULLs in a unique index but only
   one ''; most donations have no Mollie payment at all.
2. Auto-resolve duplicates: the earliest-created row keeps its payment_id and
   later ones have theirs cleared. NO ROW IS EVER DELETED and no other field is
   touched -- every cleared value is written to a comment on the donation it
   came from, so the change is auditable and reversible by hand.

The alternative to step 2 -- halting migrate for a human to resolve, as
enforce_unique_volunteer_per_member does -- was considered and not taken (see
the design spec, decision D4). It is available here in a way it is not there
because clearing a payment_id loses no relationship: the donation, its donor
and its ledger entries all survive untouched.
"""

import frappe


def execute():
    if not frappe.db.table_exists("Donation"):
        return

    blanked = _normalise_empty_payment_ids()
    cleared = _resolve_duplicates()

    if blanked or cleared:
        print(
            f"Donation.payment_id prepared for its unique index "
            f"({blanked} blank value(s) normalised to NULL, {cleared} duplicate(s) cleared)"
        )


def _normalise_empty_payment_ids() -> int:
    count = frappe.db.sql("SELECT COUNT(*) FROM `tabDonation` WHERE payment_id = ''")[0][0]
    if count:
        frappe.db.sql("UPDATE `tabDonation` SET payment_id = NULL WHERE payment_id = ''")
    return count


def _resolve_duplicates() -> int:
    """Keep the earliest donation's payment_id; clear the rest, recording each."""
    duplicated = frappe.db.sql(
        """
        SELECT payment_id
        FROM `tabDonation`
        WHERE payment_id IS NOT NULL AND payment_id != ''
        GROUP BY payment_id
        HAVING COUNT(*) > 1
        """,
        as_dict=True,
    )

    cleared = 0
    for row in duplicated:
        names = frappe.db.sql(
            """
            SELECT name FROM `tabDonation`
            WHERE payment_id = %s
            ORDER BY creation ASC, name ASC
            """,
            row.payment_id,
            as_dict=True,
        )
        keeper, losers = names[0].name, [n.name for n in names[1:]]
        for name in losers:
            # Comment before the clear. Not for crash-safety -- insert() does not
            # commit, so a later failure rolls the Comment back with it -- but so
            # the two always agree: there is no ordering in which a payment_id is
            # cleared and its Comment is missing. print() rather than
            # logger().warning(), which writes nothing under bench run-tests.
            print(f"  {name}: clearing payment_id {row.payment_id} (kept on {keeper})")
            frappe.get_doc(
                {
                    "doctype": "Comment",
                    "comment_type": "Info",
                    "reference_doctype": "Donation",
                    "reference_name": name,
                    "content": (
                        f"payment_id '{row.payment_id}' cleared by "
                        f"enforce_unique_donation_payment_id; it is kept on donation {keeper}."
                    ),
                }
            ).insert(ignore_permissions=True)
            frappe.db.set_value("Donation", name, "payment_id", None, update_modified=False)
            cleared += 1

    return cleared
