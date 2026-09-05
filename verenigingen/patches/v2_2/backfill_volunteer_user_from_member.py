"""Backfill BLANK `tabVolunteer.user` from the linked Member (#270).

`Volunteer.user` duplicates a fact reachable as `Volunteer.member -> Member.user`
in the common case, but it is NOT always that fact: a volunteer can also get
their own dedicated account via the Account Creation Request pipeline
(`services/member/account/account_creation_manager.py`, `request_type ==
"Volunteer"`, sourced from `Volunteer.email` -- "Organization Email" -- not
`Member.email`). A first version of this patch overwrote `v.user` unconditionally
from `m.user` and was caught in review: it silently wiped every one of those
independent accounts to NULL whenever the linked Member had none (measured
empirically against a live probe, not inferred). See the PR thread for #270.

So this patch is deliberately narrower than "make Volunteer.user match Member.user
everywhere": it only fills a row where `Volunteer.user` is currently BLANK and the
linked Member has one -- the "created by any path other than the bulk creation
service" gap the issue described. A row where both are populated but differ is left
alone, because there is no way for a migration to tell "stale mirror of an old
Member.user" apart from "deliberately independent volunteer account" after the
fact. Going forward, `volunteer.json`'s `fetch_from` + `fetch_if_empty` on `user`
covers the same blank-fill case for every Volunteer-creation path, and
`services/volunteer/volunteer_user_sync.py` covers the Member.user-changes-later
case for a Volunteer that WAS mirroring its member (the pre-#270 shape of the
original bug), while leaving a genuinely independent account untouched.

post_model_sync is fine here: this is data-only, no column or index is being added
(the `user` column already exists; fetch_from/fetch_if_empty are metadata, not DDL).
"""

import frappe

# Shared between the COUNT and the UPDATE below on purpose -- two copies of the
# same predicate can drift (the printed count would stop matching what's
# actually rewritten) if only one of them is edited later.
_BLANK_VOLUNTEER_USER_WITH_MEMBER_USER = """
    v.member IS NOT NULL AND v.member != ''
    AND (v.user IS NULL OR v.user = '')
    AND m.user IS NOT NULL AND m.user != ''
"""


def execute():
    if not frappe.db.table_exists("Volunteer") or not frappe.db.table_exists("Member"):
        return

    affected = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tabVolunteer` v
        INNER JOIN `tabMember` m ON m.name = v.member
        WHERE {_BLANK_VOLUNTEER_USER_WITH_MEMBER_USER}
        """
    )[0][0]

    if not affected:
        return

    print(f"Backfilling {affected} blank Volunteer.user value(s) from the linked Member")
    frappe.db.sql(
        f"""
        UPDATE `tabVolunteer` v
        INNER JOIN `tabMember` m ON m.name = v.member
        SET v.user = m.user
        WHERE {_BLANK_VOLUNTEER_USER_WITH_MEMBER_USER}
        """
    )
