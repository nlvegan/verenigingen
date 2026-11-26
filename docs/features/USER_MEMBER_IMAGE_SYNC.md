# User-Member Profile Picture Synchronization

## Overview

A photo change on a Member or on its linked User is copied to the other record. This is done by the
generic field sync service, `verenigingen/services/field_sync_service.py`, which also syncs names
and email. There is no image-specific module (an earlier `utils/user_member_image_sync.py` was never
registered in `doc_events` and was deleted, #3161).

## Mechanism

`field_sync_service.sync_fields` is registered as an `on_update` handler for both doctypes in
`verenigingen/hooks/doc_events.py` (`"Member"` and `"User"`). Check with
`frappe.get_hooks("doc_events")`.

`FIELD_SYNC_CONFIG` in that service holds the mappings:

- `Member` -> `User`: `image` -> `user_image` (the User is found through `Member.user`)
- `User` -> `Member`: `user_image` -> `image` (the Member is found with `Member.user == User.name`)

### Safeguards

- **Recursion flag**: both directions share `frappe.flags.syncing_member_user_fields`. While one
  direction is saving the other record, the echo `on_update` sees the flag and returns. The flag is
  cleared in a `finally`.
- **Change detection**: a field is synced only when its value changed on the source document in this save (`has_value_changed`).
- **Missing records**: a Member without a User, or a User without a Member, is skipped silently.
- **Permissions**: the target is saved with `ignore_permissions=True`.
- **Failures** are caught so the source save is never blocked, and are logged with
  `logging.getLogger(__name__).error`, which is not visible in CI or Error Log (#3172).

## Testing

`verenigingen/tests/member/test_user_member_image_sync.py`:

```bash
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.member.test_user_member_image_sync
```

Covers Member -> User, User -> Member, the loop guard (the `syncing_member_user_fields` flag),
missing user, missing member, and no sync without a change.

## Troubleshooting

```python
member = frappe.get_doc("Member", "MEMBER-001")
print(member.user, member.image)
print(frappe.db.get_value("User", member.user, "user_image"))
```
