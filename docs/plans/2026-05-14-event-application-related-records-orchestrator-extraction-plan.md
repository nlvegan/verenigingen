# Event Application — Related Records Orchestrator Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `_create_related_records` + 10 related helpers (~700 LOC) from `event_application_service.py` (now 1,315 LOC after PR #5) into a new `MijnRoodRelatedRecordsOrchestrator` under `mijnrood_sync/services/event_application/`. This is Phase 1, PR #6 — second-largest after PR #4.

**Architecture:** New `related_records_orchestrator.py` housing 11 methods spanning address creation, Mollie linkage, membership + dues, user account creation, MijnRood comments, and chapter assignment/transfer. The god-class loses ~700 LOC and keeps 11 one-line shims. `_ensure_user_account` and `_ensure_user_account_for_volunteer` accept an `orchestrator` parameter so they can use `orchestrator._acr_queued_members` (per-event dedup state stays on god-class).

**Reference spec:** `docs/plans/2026-05-12-event-application-service-refactor-design.md`

---

## Carry-forward lessons (CRITICAL — propagate from PR #2-5)

1. `EnhancedTestDataFactory.create_member` uniquifies BOTH `email` AND `last_name`. Use stored values.
2. `_cleanup_member_and_customer(member_name)` MUST call `frappe.db.commit()` after deletes — confirmed pattern in PR #4/#5.
3. `test-quality-enforcer` whitelist: `_create_*` / `_cleanup_*` method prefixes pass; other prefixes get flagged for inline `ignore_permissions=True`.
4. Mock usage in tests requires `# Mock justified: …` comment above `with patch(...)` blocks.
5. `permission-bypass-validator` requires `# Security: …` comments above PRODUCTION `ignore_permissions=True` — preserve any existing comments verbatim when copying methods.
6. Pre-commit may reformat — re-stage and re-commit. No `--no-verify`.
7. Pyright "could not be resolved" / "not accessed" stale-index warnings on new module paths — ignore.

**New for PR #6:**

8. `_ensure_user_account` and `_ensure_user_account_for_volunteer` use `self._acr_queued_members` (a Set initialized in god-class `__init__` and cleared at the start of every `apply_event`). In the new service these become `orchestrator._acr_queued_members.add(...)` / `member_name in orchestrator._acr_queued_members`. Both methods need an `orchestrator` parameter. The `_acr_queued_members` Set STAYS on the god-class — do not move it.
9. PR #4's `volunteer_sync_service._ensure_volunteer` calls `orchestrator._ensure_user_account_for_volunteer(member_name)`. After PR #6, that orchestrator call hits the god-class's now-one-line shim → new service's method → uses `orchestrator._acr_queued_members.add(...)`. The orchestrator parameter is threaded all the way through. Verify no break.
10. The PR #4 carry-over `_FakeOrchestrator` in `_fixtures.py` already has `_ensure_user_account_for_volunteer = MagicMock(...)` from PR #4 — confirmed in the prior plan. No changes needed there.

---

## File Structure

**Create:**
- `verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py` — `MijnRoodRelatedRecordsOrchestrator` + `get_related_records_orchestrator`
- `verenigingen/tests/services/event_application/test_related_records_orchestrator.py` — real-DB integration tests

**Modify:**
- `verenigingen/mijnrood_sync/services/event_application_service.py` — replace 11 method bodies with delegation shims; drop orphaned imports

---

## Scope: methods to extract

| Method | LOC | Notes |
|---|---|---|
| `_create_related_records` | 44 | Entry point; calls 6 other methods in this PR |
| `_apply_mijnrood_comments` | 19 | Pure helper, no orchestrator deps |
| `_ensure_address` | 42 | Creates Address + Dynamic Link |
| `_ensure_mollie_data` | 39 | Sets `mollie_customer_id` on member |
| `_ensure_membership_and_dues` | 70 | Creates Membership + delegates to backfill |
| `_backfill_dues_schedule` | 56 | Internal helper for ensure_membership_and_dues |
| `_update_existing_dues_schedule` | 36 | Updates dues rate |
| `_ensure_user_account` | 53 | Uses `orchestrator._acr_queued_members` |
| `_ensure_user_account_for_volunteer` | 52 | Uses `orchestrator._acr_queued_members`; called from PR #4 |
| `_assign_chapter_from_division` | 58 | Chapter assignment via mapping service |
| `_handle_division_field_change` | 27 | Routes division_id changes to `_assign_chapter_from_division` |

Total: ~496 LOC across 11 methods. After accounting for docstrings + signatures preserved as shims, the god-class loses ~470 LOC.

---

## Task 1: Scaffold + `_apply_mijnrood_comments` (simplest)

`_apply_mijnrood_comments` is the simplest — a pure helper that appends MijnRood comments to a Member's notes field, idempotent on substring match.

**Files:**
- Create: `verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py`
- Create: `verenigingen/tests/services/event_application/test_related_records_orchestrator.py`

- [ ] **Step 1:** Write failing tests:

```python
"""Real-DB integration tests for MijnRoodRelatedRecordsOrchestrator.

Tests cover address/Mollie/membership/dues creation + chapter assignment
+ user account queueing + MijnRood comment append. Each method tested
against a real DB; the orchestrator parameter (god-class's
_acr_queued_members) is stubbed via _FakeOrchestrator.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.event_application._fixtures import _FakeOrchestrator


def _cleanup_member_and_customer(test, member_name):
    """Module-level helper for cross-class reuse."""
    for cust in frappe.get_all("Customer", filters={"member": member_name}, pluck="name"):
        try:
            frappe.db.set_value("Customer", cust, "member", None, update_modified=False)
            frappe.delete_doc("Customer", cust, ignore_permissions=True, force=True)
        except Exception:
            pass
    try:
        if frappe.db.exists("Member", member_name):
            frappe.delete_doc("Member", member_name, ignore_permissions=True, force=True)
    except Exception:
        pass
    frappe.db.commit()


class TestApplyMijnRoodComments(EnhancedTestCase):
    """Appends MijnRood comments to Member.notes, idempotent."""

    def test_returns_none_when_comment_is_empty(self):
        member = self.factory.create_member(
            first_name="EmptyComment", last_name="Test",
            email="empty-comment@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {"mijnrood_comments": ""}
        )
        self.assertIsNone(result)

    def test_returns_none_when_comment_missing(self):
        member = self.factory.create_member(
            first_name="NoComment", last_name="Test",
            email="no-comment@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {}
        )
        self.assertIsNone(result)

    def test_appends_comment_to_member_notes(self):
        member = self.factory.create_member(
            first_name="Append", last_name="Comment",
            email="append-comment@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {"mijnrood_comments": "imported from MijnRood"}
        )
        self.assertIsNotNone(result)
        notes = frappe.db.get_value("Member", member.name, "notes") or ""
        self.assertIn("imported from MijnRood", notes)

    def test_idempotent_when_comment_already_present(self):
        member = self.factory.create_member(
            first_name="DupComment", last_name="Test",
            email="dup-comment@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)
        frappe.db.set_value("Member", member.name, "notes",
            "MijnRood notitie: same comment", update_modified=False)
        frappe.db.commit()

        result = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {"mijnrood_comments": "same comment"}
        )
        self.assertIsNone(result)
```

- [ ] **Step 2:** Run — expect `ModuleNotFoundError`.

- [ ] **Step 3:** Create the service:

```python
"""MijnRoodRelatedRecordsOrchestrator — creates ancillary records after Member creation/update.

Extracted from event_application_service.py as Phase 1, PR #6 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service owns the "everything that happens after a Member is
created/updated" pipeline:
- Address creation
- Mollie customer linkage
- Membership + Dues Schedule creation/backfill
- User account creation (with per-event dedup)
- MijnRood comment append
- Chapter assignment via division_id

The dedup Set (_acr_queued_members) STAYS on the god-class because it is
per-event state initialized in MijnRoodEventApplicationService.__init__
and cleared at the start of every apply_event call. Methods that touch
the dedup set accept an `orchestrator` parameter and use
`orchestrator._acr_queued_members`.
"""

import logging
from typing import Optional

import frappe
from frappe import _

logger = logging.getLogger("verenigingen.mijnrood_sync.event_application.related_records")


class MijnRoodRelatedRecordsOrchestrator:
    """Creates ancillary records (address, Mollie, membership, dues, etc.) for a synced Member."""

    def __init__(self):
        self.logger = logger

    def _apply_mijnrood_comments(self, member_name: str, row_data: dict) -> Optional[str]:
        """Append MijnRood comments to the Member's notes field.

        Skips if the comment text is already present in notes (idempotent).

        Returns:
            Human-readable status message, or None if skipped.
        """
        comment = (row_data.get("mijnrood_comments") or "").strip()
        if not comment:
            return None

        current_notes = frappe.db.get_value("Member", member_name, "notes") or ""
        if comment in current_notes:
            return None

        prefix = "MijnRood notitie"
        new_notes = (
            f"{current_notes}\n\n{prefix}: {comment}".strip()
            if current_notes
            else f"{prefix}: {comment}"
        )
        # Security: System-initiated note append from authoritative MijnRood data
        frappe.db.set_value("Member", member_name, "notes", new_notes, update_modified=False)
        self.logger.info("Appended MijnRood comment to member %s", member_name)
        return _("MijnRood comment appended")


_service_instance: Optional[MijnRoodRelatedRecordsOrchestrator] = None


def get_related_records_orchestrator() -> MijnRoodRelatedRecordsOrchestrator:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodRelatedRecordsOrchestrator()
    return _service_instance
```

Note: copy `_apply_mijnrood_comments` body verbatim from `event_application_service.py` lines 181-200. The above includes the `# Security: …` comment because `frappe.db.set_value` with `update_modified=False` is also a kind of permission bypass — keep the existing comment.

- [ ] **Step 4:** Run — 4 tests pass.

- [ ] **Step 5:** Commit: `feat(mijnrood-sync): scaffold MijnRoodRelatedRecordsOrchestrator with _apply_mijnrood_comments`

---

## Task 2: `_ensure_address`

Copy from `event_application_service.py` lines 200-244 (~42 LOC) verbatim into the new service. No orchestrator parameter needed.

**Tests** (append to test file):

`TestEnsureAddress` — 3 tests:
- returns None when row_data has no address fields
- creates Address + Dynamic Link when member has no address yet
- returns None / no-op when member already has the same address

Address fields used: `address_line1`, `city`, `postal_code`, `country` (check source for the exact list). Create Address + dynamic link via `frappe.get_doc({"doctype": "Address", ...}).insert(ignore_permissions=True)` if needed for the third test setup (use a `_create_*` helper).

- [ ] Commit: `feat(mijnrood-sync): add _ensure_address to MijnRoodRelatedRecordsOrchestrator`

---

## Task 3: `_ensure_mollie_data`

Copy from `event_application_service.py` lines 244-283 (~39 LOC) verbatim. No orchestrator parameter.

**Tests** (append):

`TestEnsureMollieData` — 3 tests:
- returns None when row_data has no `custom_mollie_customer_id`
- syncs Mollie customer id to member
- returns None when member already has the same Mollie id

- [ ] Commit: `feat(mijnrood-sync): add _ensure_mollie_data to MijnRoodRelatedRecordsOrchestrator`

---

## Task 4: `_assign_chapter_from_division` + `_handle_division_field_change`

Copy both from `event_application_service.py` lines 552-636 verbatim. No orchestrator parameter — both use `get_mapping_service()` from PR #1 (already importable).

You'll need to add to the new service's imports:
```python
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
)
from verenigingen.mijnrood_sync.utils import safe_int
```

**Tests** (append):

`TestAssignChapterFromDivision` — 3 tests:
- returns error message when division_id doesn't resolve
- assigns chapter to member
- returns None when member is already in the chapter

`TestHandleDivisionFieldChange` — 2 tests:
- returns None when changed_fields doesn't include the named field
- calls `_assign_chapter_from_division` when changed_fields includes it

- [ ] Commit: `feat(mijnrood-sync): add chapter assignment to MijnRoodRelatedRecordsOrchestrator`

---

## Task 5: `_ensure_user_account` + `_ensure_user_account_for_volunteer`

Both use `self._acr_queued_members` (god-class state). Both need `orchestrator` parameter:

```python
def _ensure_user_account(self, member_name: str, orchestrator) -> Optional[str]:
    ...
    if member_name in orchestrator._acr_queued_members:
        return None
    ...
    orchestrator._acr_queued_members.add(member_name)
    ...

def _ensure_user_account_for_volunteer(self, member_name: str, orchestrator) -> Optional[str]:
    ...
    # Same pattern
```

Copy bodies verbatim from `event_application_service.py` lines 445-549, changing only `self._acr_queued_members` → `orchestrator._acr_queued_members` (4 sites total: 2 reads, 2 writes).

**Tests** (append):

`TestEnsureUserAccount` — 2 tests:
- returns None when global `create_member_accounts` setting is off
- queues ACR when setting is on and member has no user (mock `queue_account_creation_for_member` — `# Mock justified: Infrastructure - ACR queueing tested by its own suite`)

`TestEnsureUserAccountForVolunteer` — 2 tests:
- returns None when member already has a user
- returns None when member is already in `orchestrator._acr_queued_members` (dedup)

For the dedup test:
```python
orchestrator = _FakeOrchestrator()
orchestrator._acr_queued_members = {member.name}  # pre-populate
result = ... ._ensure_user_account_for_volunteer(member.name, orchestrator)
self.assertIsNone(result)
```

- [ ] Commit: `feat(mijnrood-sync): add user account helpers to MijnRoodRelatedRecordsOrchestrator`

---

## Task 6: `_ensure_membership_and_dues` + `_backfill_dues_schedule` + `_update_existing_dues_schedule`

The Membership + Dues trinity. `_ensure_membership_and_dues` is the entry, the other two are internal helpers. All three call each other via `self._foo(...)` — same-service calls, no signature change needed.

Copy lines 283-444 verbatim.

**Tests** (append):

`TestEnsureMembershipAndDues` — 3 tests:
- returns error when `membership_type` not in row_data
- creates Membership + Dues Schedule when none exists
- returns None / backfill message when member already has active Membership

`TestUpdateExistingDuesSchedule` — 2 tests:
- updates dues rate on existing schedule
- returns None when schedule doesn't exist or rate is unchanged

For setup, ensure a Membership Type fixture exists. Use `self.factory.ensure_membership_type("Related Records Test Type")`.

- [ ] Commit: `feat(mijnrood-sync): add membership/dues methods to MijnRoodRelatedRecordsOrchestrator`

---

## Task 7: `_create_related_records` entry point

The orchestration entry point. Copy from `event_application_service.py` lines 135-179 (~44 LOC) verbatim with signature change to accept `orchestrator`:

```python
def _create_related_records(
    self, member_name: str, row_data: dict, event=None, orchestrator=None
) -> list[str]:
```

Inside the body:
- `self._assign_chapter_from_division(...)` → `self._assign_chapter_from_division(...)` (same service)
- `self._ensure_address(...)` → `self._ensure_address(...)` (same)
- `self._ensure_mollie_data(...)` → `self._ensure_mollie_data(...)` (same)
- `self._ensure_membership_and_dues(...)` → `self._ensure_membership_and_dues(...)` (same)
- `self._ensure_user_account(member_name)` → `self._ensure_user_account(member_name, orchestrator)` ⚠
- `self._apply_mijnrood_comments(...)` → `self._apply_mijnrood_comments(...)` (same)

The orchestrator threading is only required for `_ensure_user_account` (the only sub-method that needs the dedup set).

**Tests** (append):

`TestCreateRelatedRecords` — 3 tests:
- Calls each sub-method per the configured row_data (use `service._ensure_address = MagicMock(...)` etc. with `# Mock justified: Routing - testing dispatcher logic, sub-methods covered elsewhere`)
- Returns concatenated messages from all sub-methods
- Empty row_data → empty messages list

- [ ] Commit: `feat(mijnrood-sync): add _create_related_records entry point to MijnRoodRelatedRecordsOrchestrator`

---

## Task 8: Wire god-class, verify, push

- [ ] **Step 1:** Add the import to `event_application_service.py`:

```python
from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
```

- [ ] **Step 2:** Replace 11 method bodies with one-line shims. Preserve signatures + docstrings.

```python
# _create_related_records
return get_related_records_orchestrator()._create_related_records(
    member_name, row_data, event=event, orchestrator=self
)

# _apply_mijnrood_comments
return get_related_records_orchestrator()._apply_mijnrood_comments(member_name, row_data)

# _ensure_address
return get_related_records_orchestrator()._ensure_address(member_name, row_data)

# _ensure_mollie_data
return get_related_records_orchestrator()._ensure_mollie_data(member_name, row_data)

# _ensure_membership_and_dues
return get_related_records_orchestrator()._ensure_membership_and_dues(member_name, row_data)

# _backfill_dues_schedule
return get_related_records_orchestrator()._backfill_dues_schedule(member_doc, membership_name, row_data)

# _update_existing_dues_schedule
return get_related_records_orchestrator()._update_existing_dues_schedule(member_name, new_rate)

# _ensure_user_account
return get_related_records_orchestrator()._ensure_user_account(member_name, self)

# _ensure_user_account_for_volunteer
return get_related_records_orchestrator()._ensure_user_account_for_volunteer(member_name, self)

# _assign_chapter_from_division
return get_related_records_orchestrator()._assign_chapter_from_division(
    member_name, division_id, event, join_date=join_date
)

# _handle_division_field_change
return get_related_records_orchestrator()._handle_division_field_change(
    member_name, changed_fields, event, field_name=field_name
)
```

- [ ] **Step 3:** Clean up orphaned imports. Likely orphans after PR #6:
- `safe_int` may still be used elsewhere — check `grep -c "safe_int" event_application_service.py`. If still used, keep.
- All other imports — verify before deleting.

- [ ] **Step 4:** Verify file parses.

- [ ] **Step 5:** Run the full test surface:
- New PR #6 tests
- PR #1-5 regressions (44 + 6 + 22 + 10 + 16)
- Existing mocked baseline (140/150)

If existing mocked tests need retargeting (the 11 methods moved off `MijnRoodEventApplicationService`), apply minimal `patch.target` updates following the established pattern.

- [ ] **Step 6:** Pre-commit + commit + push:

```bash
git commit -m "$(cat <<'EOF'
refactor(mijnrood-sync): delegate related records to MijnRoodRelatedRecordsOrchestrator

Replaces the bodies of 11 methods (_create_related_records,
_apply_mijnrood_comments, _ensure_address, _ensure_mollie_data,
_ensure_membership_and_dues, _backfill_dues_schedule,
_update_existing_dues_schedule, _ensure_user_account,
_ensure_user_account_for_volunteer, _assign_chapter_from_division,
_handle_division_field_change) with one-line delegations to the new
MijnRoodRelatedRecordsOrchestrator.

The god-class shrinks by ~470 LOC. Public method shims remain so the
dispatcher and PR #2/#4 cross-service callers (which call these helpers
via the orchestrator) continue to work without import-path churn.

_acr_queued_members stays on the god-class because it is per-event
state (cleared at the start of every apply_event call). _ensure_user_account
and _ensure_user_account_for_volunteer accept an orchestrator parameter
and use orchestrator._acr_queued_members for dedup.

This is Phase 1, PR #6 of the Tier C decomposition documented at
docs/plans/2026-05-12-event-application-service-refactor-design.md.
EOF
)"

SKIP=jest-testing,javascript-doctype-validator git push
```

---

## Success Criteria

1. `verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py` exists with `MijnRoodRelatedRecordsOrchestrator` (11 methods) and `get_related_records_orchestrator`.
2. `event_application_service.py` retains 11 public shim methods (≤ 5 lines each) and `_acr_queued_members` on the god-class.
3. New related-records tests (~25-30) pass against a real DB. MagicMock used only for orchestrator stub + ACR infrastructure + sub-method routing tests.
4. PR #1-5 regression tests still pass.
5. `test_event_application_service.py` baseline (140/150) preserved.
6. Pre-commit hooks pass on every touched file.
7. God-class LOC count drops by ~470 (from 1,315 to ~845).
