# Chapter Board Member-Lifecycle Notifications — Design

**Date:** 2026-04-20
**Status:** Approved (brainstorm), pending implementation plan
**Author:** foppe (via collaborative brainstorm)

## Problem

Chapter boards are inconsistently informed about membership movements in their chapter:

| Scenario | Current behaviour |
|---|---|
| 1. Member requests to join | ✅ Board notified (`member_manager._notify_board_of_join_request`) |
| 2. Member approved / assigned to chapter | ❌ Only the member is notified, not the board |
| 3. Member transferred between chapters | ⚠️ Off by default — requires explicit `notify=True` *and* the `send_chapter_assignment_notifications` setting enabled |

Boards need visibility into who enters and leaves their chapter to coordinate onboarding, team assignments, and local communications.

## Goals

1. Notify the receiving chapter's board when a member is assigned to it (any path).
2. Notify **both** boards on a transfer, with distinct "transferred in" / "transferred out" messaging.
3. Notify the departing chapter's board when a member leaves (non-transfer).
4. Preserve existing suppression escape hatches (bulk import, explicit suppression).
5. Default to ON so the feature works out of the box, while preserving explicit opt-outs.

## Non-goals

- Role-filtered delivery (e.g., only Secretary). All active board members receive notifications, matching the existing Scenario 1 pattern. Filtering can be added later as its own feature.
- Changing Scenario 1 (join request) — already works.
- Notifying members of other members' movements.

## Design

### Trigger points — ChapterMember doc-event hooks

All notifications are fired from the `ChapterMember` DocType's lifecycle hooks. This is the canonical place in Frappe to react to a state change, and every code path that changes chapter membership (approval flow, admin UI edits, transfer helper, direct-service calls) ultimately inserts or deletes a `ChapterMember` row.

| Hook | Emits |
|---|---|
| `after_insert` | "member joined" OR "transferred in" |
| `on_trash` | "member left" OR "transferred out" |

The existing `ChapterMember.after_insert` already sends a welcome email to the joining member — we add a sibling call that notifies the board. No new hooks, just new branches.

### Transfer vs. plain join/leave disambiguation

`transfer_member_between_chapters()` calls `leave_chapter()` then `assign_member_to_chapter()` — from the doc-event hook's perspective, this looks identical to a user leaving one chapter and (unrelatedly) joining another. To distinguish:

```python
# services/chapter/chapter_membership_manager.py
def transfer_member_between_chapters(member, from_chapter, to_chapter, ...):
    frappe.flags.chapter_transfer = {
        "member": member,
        "from": from_chapter,
        "to": to_chapter,
    }
    try:
        leave_chapter(member, from_chapter, ...)
        assign_member_to_chapter(member, to_chapter, ...)
    finally:
        frappe.flags.chapter_transfer = None
```

Hook logic:

```python
# chapter_member.py — after_insert branch
xfer = frappe.flags.get("chapter_transfer")
if xfer and xfer["member"] == self.member and xfer["to"] == self.parent:
    template = "chapter_board_member_transferred_in"
    context = {..., "from_chapter": xfer["from"]}
else:
    template = "chapter_board_member_joined"

# on_trash mirrors this for transferred_out vs. left
```

The `finally` clears the flag even if the transfer fails mid-way, so a subsequent unrelated insert/trash can't pick up a stale flag.

### Suppression rules

A notification fires **only when all** of these hold:

1. `Verenigingen Settings.send_chapter_assignment_notifications` is truthy. Default flips from 0 → 1 for new installs; a migration patch sets the value to 1 where currently unset (NULL), but preserves explicit 0 values.
2. `frappe.flags.is_bulk_import` is not set.
3. `frappe.flags.suppress_chapter_notifications` is not set.

No notification on `on_update` — churn on unrelated field edits must not page the board.

### Recipients

All rows in `Chapter.board_members` where `is_active=1`, resolved to the board member's email via the existing helper (`member_manager._get_board_member_emails` or equivalent). Deduped. Inactive rows skipped. Matches Scenario 1 behaviour exactly.

### Templates

Four new templates in `verenigingen/templates/emails/`, each with an accompanying translation in the existing Dutch/English i18n setup:

| Template | Subject (EN) | Trigger |
|---|---|---|
| `chapter_board_member_joined` | New member in {{chapter}} | after_insert, no transfer flag |
| `chapter_board_member_left` | Member left {{chapter}} | on_trash, no transfer flag |
| `chapter_board_member_transferred_in` | {{name}} transferred to {{chapter}} | after_insert, transfer flag matches |
| `chapter_board_member_transferred_out` | {{name}} transferred from {{chapter}} | on_trash, transfer flag matches |

Context per email: member name, member ID (with Desk link), chapter name, membership type, joined/left date, and for transfers the other chapter.

### Delivery

Via `EmailService.send_notification()` with `notification_type="chapter_board_member_lifecycle"` so existing preference filtering, rate-limiting, and logging apply consistently.

Enqueued (not inline) via `frappe.enqueue` to the `short` queue. This keeps approval/transfer request latency flat and prevents SMTP failures from rolling back the business operation.

## Data flow

### Approval path (Scenario 2)

1. `approve_member_request()` creates membership → `MembershipCreationService` → assigns chapter → inserts `ChapterMember` row.
2. `ChapterMember.after_insert` fires.
3. No transfer flag → `chapter_board_member_joined` template.
4. Suppression check (settings + flags) passes.
5. Board emails resolved.
6. `frappe.enqueue(EmailService.send_notification, ...)` per recipient.

### Transfer path (Scenario 3)

1. `transfer_member_between_chapters()` sets `frappe.flags.chapter_transfer`.
2. `leave_chapter()` deletes old `ChapterMember` row → `on_trash` fires → transfer flag matches → `chapter_board_member_transferred_out` sent to old board.
3. `assign_member_to_chapter()` inserts new `ChapterMember` row → `after_insert` fires → transfer flag matches → `chapter_board_member_transferred_in` sent to new board.
4. `finally` clears the flag.

### Plain leave

1. Admin (or service) deletes `ChapterMember` row directly.
2. `on_trash` fires → no transfer flag → `chapter_board_member_left`.

## Settings change

- **DocType JSON**: `send_chapter_assignment_notifications` default changes from 0 → 1.
- **Migration patch**: iterate existing `Verenigingen Settings` singletons; if the field is NULL/unset, set to 1. If explicitly 0, leave as-is. Log outcome.
- Patch placed in `verenigingen/patches/` and registered in `patches.txt`.

## Testing

Integration tests (real DB, `CoreTestDataFactory`, no mocks for business logic — per project test policy).

1. **Approval path** — applicant with chapter preference, approve, assert one `Email Queue` row per active board member with `chapter_board_member_joined` template.
2. **Direct ChapterMember insert** — admin creates ChapterMember outside approval flow, assert same "joined" notification.
3. **Plain leave** — remove a ChapterMember without transfer flag, assert `chapter_board_member_left`.
4. **Transfer** — call `transfer_member_between_chapters()`, assert old board receives `transferred_out`, new board receives `transferred_in`, and neither receives plain `joined` / `left`.
5. **Suppression** — each of `is_bulk_import`, `suppress_chapter_notifications`, and `send_chapter_assignment_notifications=0` independently blocks emails.
6. **Recipients** — only `is_active=1` board rows receive email; inactive skipped; duplicates deduped.
7. **Flag hygiene** — raise an exception inside `transfer_member_between_chapters()` and assert `frappe.flags.chapter_transfer` is cleared after.

Email assertions via `frappe.db.get_all("Email Queue", filters={...})` — the pattern already used elsewhere in the verenigingen test suite.

## Risk / rollout

- **Low migration risk**: patch only touches one settings field, preserves explicit opt-outs.
- **Low runtime risk**: notifications are enqueued, failures don't block business operations.
- **User-visible behaviour change**: boards will start receiving emails on upgrade. Release note should mention this and point to the setting to disable.
- **Template localization**: Dutch translations must land with the templates (site is Dutch-first). English templates as fallback.

## Out of scope (future work)

- Per-chapter-role filtering of recipients.
- Digest/daily-summary delivery mode.
- In-app notifications (currently email only; matches existing pattern).
- Notifying a member's team when they leave the chapter.
