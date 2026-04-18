# MijnRood Application → Member Approval Correlation — Design

**Date:** 2026-04-18
**Status:** Draft
**Area:** `verenigingen/mijnrood_sync/`

## Problem

When a membership applicant is approved in MijnRood, the source system:

1. **Deletes** the row from `admin_membership_application`.
2. **Creates** a new row in `admin_member` with a different primary key (the two tables are in independent auto-increment series).

Our polling service currently sees this as two unrelated events:

- `Deleted` on `admin_membership_application`
- `New` on `admin_member`

Both land in the review queue as independent items. The actual promotion logic happens at apply time via a fallback inside `_apply_new_member` called `_try_promote_application`, which pairs the two by email + `application_status=Pending`. This works, but:

- Reviewers see two events for one logical action and must mentally pair them.
- `_apply_deleted` is a no-op for application deletions — confusing.
- Promotion logic is split across `_apply_deleted` (no-op), `_apply_new_member` (ad-hoc fallback), and the reviewer's head.
- **Existing bug:** `_try_promote_application` only flips `application_status` to `Approved`; it does not touch `member.status`. `_ensure_membership_and_dues` short-circuits if `member.status != "Active"`, so Membership + Dues Schedule are not created on promotion — they only get created if a later `Changed` event happens to re-run the path.

Rejections in MijnRood (application deleted, no new member) are intentionally left as today's default behavior — the Deletion event stays in the review queue for manual handling.

## Goal

Collapse the delete+new pair into a single, explicit event at poll time, centralize the promotion logic, and fix the status-flip bug.

## Approach

### Placement

Add a correlation pass to `MijnRoodPollingService.run_sync()`, after all tables are polled and before the sync log is finalized:

```
run_sync()
  for each table in tables_to_sync:
    _poll_table(client, table, sync_run_id)
  _poll_division_contacts(...)
  _correlate_application_approvals(sync_run_id)     # NEW
  finalize log + settings
```

The correlator is implemented in a new module, `verenigingen/mijnrood_sync/services/application_approval_correlator.py`. It operates only on sync-event rows already persisted by the current run (scoped by `sync_run_id`) and never talks to MijnRood.

**Public contract:**

- **Input:** `sync_run_id`
- **Output:** count of pairs collapsed (included in the sync log's `last_sync_message` and the returned `totals` dict as a new `approved` key)
- **Side effects:** inserts one `Approved` event per pair, marks the two raw events as `Ignored` with a cross-reference note

Apply-time logic adds a new `_apply_approved` handler dispatched from `apply_event()` alongside `_apply_new` / `_apply_changed` / `_apply_deleted`. The existing `_try_promote_application` is retained as the cross-run safety net but delegates to a shared `_promote_application_member(...)` helper so both paths stay in sync.

### Data model changes

One addition to the `MijnRood Sync Event` DocType:

1. **New `event_type` option: `Approved`** — added to the existing Select field: `New\nChanged\nDeleted\nApproved`.

No new fields. Existing JSON fields carry the payload:

- `old_data` — deleted application row (from `admin_membership_application`)
- `new_data` — new member row (from `admin_member`)
- `mijnrood_table` — `admin_member` (canonical target of the promotion)
- `mijnrood_row_id` — the new member's MijnRood id
- `change_summary` — e.g. *"Application approved: Jane Doe (app #42 → member #1234)"*
- `change_tags` — includes `"Approved"`

`polling_service.compute_change_tags` is extended so the new event type produces a readable tag.

**Migration:** a patch to reload the DocType JSON so the new `event_type` option is available. No data migration of existing rows.

### Pairing algorithm

Scoped to a single `sync_run_id`.

**Candidate sets:**

- *Deletions:* `event_type='Deleted'` AND `mijnrood_table='admin_membership_application'` AND `sync_run_id=<this run>` AND `status='Pending'`.
- *Creations:* `event_type='New'` AND `mijnrood_table='admin_member'` AND `sync_run_id=<this run>` AND `status='Pending'`.

**Pass 1 — Mollie match (strongest):**
For each Deletion with a non-empty `mollie_customer_id`, pair with the Creation that has the same `mollie_customer_id`. Treat as confirmed regardless of other field drift (email may have been corrected on approval).

**Pass 2 — Email match (remaining unpaired):**
Match by normalized email (lowercase + strip). Pair only if **all** of the following hold:

- Last name matches (case-insensitive, stripped).
- Both sides' `mollie_customer_id`, when both are populated, agree — a Mollie mismatch **vetoes** an email-based pair.
- `date_of_birth` agrees when both sides have it (one-sided DOB is tolerated).
- First-name mismatch is logged but non-blocking.

**Pass 3 — Ambiguity:**

- `>1` candidate on either side → no pair, log a warning.
- `0` candidates → no pair (likely a rejection).

**On a confident pair:**

1. Insert one `Approved` event (populated as described under "Data model changes").
2. Update the two raw events: `status='Ignored'`, `review_notes='Superseded by <approved event name>'`.
3. Increment a run-level counter surfaced in the sync log summary.

**Idempotency:** the correlator pairs only events with `status='Pending'`. Events already collapsed are `Ignored` and skipped on re-run.

**No cross-run correlation in v1.** `run_sync` is transactionally bounded; a crash rolls the whole run back. If a split does happen in the wild, the retained `_try_promote_application` safety net catches it at apply time.

### Apply logic (`_apply_approved`)

```
_apply_approved(event):
  new_data = load event.new_data                  # admin_member row
  old_data = load event.old_data                  # deleted application row
  row_data = _map_mijnrood_to_member_fields(new_data)

  member_name = _locate_application_member(
      old_data, new_data, event.linked_member
  )
  if not member_name:
      # Safety fallback — shouldn't happen in practice
      return _apply_new_member(event)

  _promote_application_member(member_name, old_data, new_data, row_data, event)
  return {"success": True, "message": ...}
```

`_locate_application_member` tries in order:

1. `event.linked_member` (set by the correlator from the Pending Member the application event created).
2. Member whose `application_id == f"MR-APP-{old_data['id']}"` (matches what `_apply_new_membership_application` sets).
3. Member by normalized email match.
4. `None` → fall through to `_apply_new_member`.

`_promote_application_member(member_name, old_data, new_data, row_data, event)` (shared with `_try_promote_application`):

1. `MemberImportService.create_or_update_member(row_data, ...)` to sync all drifted fields and overwrite `member_id`.
2. Set:

   ```
   member.application_status = "Approved"
   member.status             = "Active" if new_data.current_membership_status_id
                                         in get_active_status_ids()
                                         else <current value, with a warning logged>
   member.review_notes       = "Approved via MijnRood (event {name}). "
                               "Application id {old_id} → member_id {new_id}."
   ```

   (MijnRood status ids `1`=`lid` and `2`=`aspirant` both map to Verenigingen `Active`. A promotion with any other status id is unexpected; we log it and leave `member.status` alone rather than guessing.)

3. `_create_related_records(member_name, row_data, event)` — chapter, address, Mollie, **Membership + Dues Schedule** (now actually runs because status is Active), user account, notes.
4. `_process_member_roles(member_name, new_data, event=event)`.
5. Set `event.linked_member = member_name`.

### Bug fix bundled with the feature

The status-flip omission in today's `_try_promote_application` is fixed by routing both paths through `_promote_application_member`, which always sets `member.status` from MijnRood's status id before calling `_create_related_records`. This closes the gap where Membership + Dues Schedule were not created on promotion.

## Edge cases

| Scenario | Behavior |
|---|---|
| Application approved (normal case) | Correlator pairs → `Approved` event → promotes Pending Member, creates membership + dues |
| Application rejected (deletion only, no new member) | Deletion event unpaired → stays as-is, reviewer decides (current behavior) |
| Same-email collision (>1 new member or >1 deletion) | Ambiguous → raw events left alone, warning logged |
| Email changed between application and approval, Mollie ID same | Pass 1 pairs them, email drift tolerated |
| Both sides missing Mollie, last-name mismatch | Pass 2 fails → raw events stay, `_try_promote_application` catches at apply time |
| Cross-run split | Correlator misses → `_try_promote_application` catches at apply time |
| Pending Member can't be located on apply | Falls through to `_apply_new_member` (no data loss) |
| Correlator crashes mid-run | Raw events remain with `status='Pending'`; next run's correlator is idempotent |

## Testing

**Unit tests (new correlator module):**

- Mollie-only match pairs correctly with email drift.
- Email-only match pairs with last-name agreement and no Mollie on either side.
- Email match with Mollie mismatch → veto (no pair).
- Multiple candidates on either side → no pair.
- Zero matches (rejection) → Deletion event untouched.
- Idempotent re-run → no double-pairing.

**Integration tests (`_apply_approved`):**

- Pending Member located via `linked_member` → promoted, Membership + Dues Schedule created.
- Pending Member located via `application_id` fallback.
- Pending Member located via email fallback.
- `member.status` correctly set from `new_data.current_membership_status_id`.
- Regression test: `_ensure_membership_and_dues` now actually creates Membership + Dues Schedule on promotion.

**End-to-end:**

- Simulate a sync run where MijnRood has one application deleted + one new member in the same polling cycle. Assert the review queue ends up with one `Approved` event (Pending) and two `Ignored` events with cross-reference notes.

## Out of scope

- Cross-run correlation (handled by the retained apply-time fallback).
- Volunteer role provisioning changes (untouched).
- Rejection handling beyond current behavior.
- UI work on the sync event review list beyond ensuring the new `Approved` event type renders sensibly with existing tag/summary logic.

## Files touched (anticipated)

- `verenigingen/mijnrood_sync/services/polling_service.py` — call correlator in `run_sync`; extend `compute_change_tags`.
- `verenigingen/mijnrood_sync/services/application_approval_correlator.py` — **new**.
- `verenigingen/mijnrood_sync/services/event_application_service.py` — add `_apply_approved`, extract `_promote_application_member`, retain `_try_promote_application` as thin wrapper; dispatch update in `apply_event`.
- `verenigingen/mijnrood_sync/doctype/mijnrood_sync_event/mijnrood_sync_event.json` — add `Approved` option to `event_type`.
- Patches/migrations — reload the DocType JSON.
- Test files under `verenigingen/tests/` (mijnrood/sync subdirectory).
