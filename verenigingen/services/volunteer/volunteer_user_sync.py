"""Member.user -> Volunteer.user resync (#270).

`Volunteer.user` is NOT a pure copy of `Member.user`: a volunteer can get their
OWN dedicated account, independent of their member account, through the
Account Creation Request pipeline (`services/member/account/
account_creation_manager.py`'s Link 1, `request_type == "Volunteer"`, sourced
from `Volunteer.email` -- "Organization Email" -- not `Member.email`). So this
module must never *overwrite* an already-populated, DIVERGENT `Volunteer.user`
just because `Member.user` changed; that would destroy a legitimately
independent account. `volunteer.json`'s `fetch_from` + `fetch_if_empty` on
`user` covers "fill it in if it's blank" for every Volunteer-creation path.

What this module does, when `Member.user` CHANGES:
- If the linked Volunteer's `user` is currently BLANK, fill it with the new
  value -- this is always safe (there is nothing to lose), and it is the one
  case `fetch_if_empty` cannot reach on its own: that fetch only runs on the
  Volunteer's OWN next save, and a volunteer nobody saves again would
  otherwise stay blank forever even after its member gets a login.
- If the Volunteer's `user` currently EQUALS the member's OLD value (i.e. it
  was actually mirroring the member's account), update it to the new value --
  including to None, if the member's account was cleared. A mirror is
  supposed to track its source all the way down; the alternative (freezing
  the last non-empty value) would silently keep a revoked account's identity
  live. `member_user_email_sync.py:56` already does exactly this
  (`doc.db_set("user", None)`) on its own "linked User no longer exists" path,
  registered right before this handler in the same `on_update` list -- by the
  time this function runs, a rename or clear it made has already landed, so
  `current_volunteer_user != old_user` there and this function correctly
  no-ops on top of it.
- Otherwise (populated AND diverges from the member's OLD value) the
  Volunteer has its own account -- leave it alone.

Known scope limit: this only fires on an ORM-level `Member.save()` (the
`on_update` doc event). Several Member.user writers use raw
`frappe.db.set_value` instead (`services/member/account/
account_creation_manager.py`, `services/account/account_creation_service.py`,
`services/member/account/member_user_account_service.py`), which bypasses doc
events entirely -- the same limitation the pre-existing full_name ->
volunteer_name sync in `field_sync_service.py` already has. Not fixed here;
see #868 for a related gap in the same neighbourhood.

No re-entrancy guard is needed here: writing via `frappe.db.set_value` below
does not trigger Volunteer's own doc events, so this function cannot recurse
into itself.
"""

import frappe


def resync_volunteer_user_on_member_update(doc, method=None):
    """Registered on Member's `on_update` in hooks/doc_events.py."""
    if not doc.has_value_changed("user"):
        return

    volunteer_name = frappe.db.get_value("Volunteer", {"member": doc.name}, "name")
    if not volunteer_name:
        return

    before_save = doc.get_doc_before_save()
    old_user = before_save.get("user") if before_save else None
    current_volunteer_user = frappe.db.get_value("Volunteer", volunteer_name, "user")

    # Skip ONLY when the Volunteer already has its OWN account -- populated,
    # and not a mirror of what the member used to have. A blank value (safe to
    # fill) and a value that matches the member's OLD one (a mirror; follow it,
    # even down to None) both fall through to the write below.
    if current_volunteer_user and current_volunteer_user != old_user:
        return

    frappe.db.set_value("Volunteer", volunteer_name, "user", doc.user, update_modified=False)
