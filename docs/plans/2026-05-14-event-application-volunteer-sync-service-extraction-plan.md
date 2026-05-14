# Event Application — Volunteer Sync Service Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract role/volunteer/team/chapter-board concerns from `event_application_service.py` (now 1,925 LOC after PR #3) into a new `MijnRoodVolunteerSyncService` under `mijnrood_sync/services/event_application/`. This is Phase 1, PR #4 of the Tier C refactor — the largest PR in the sequence.

**Architecture:** New `volunteer_sync_service.py` housing 13 methods spanning role processing, volunteer creation, team membership, chapter board ops, and orphan pruning. The god-class loses ~720 LOC and keeps 5 one-line public shims so the dispatcher and PR #2/#3 cross-service callers continue to work. Same transitional `orchestrator` parameter pattern for not-yet-extracted cross-cutting helpers (`_ensure_user_account_for_volunteer`, which depends on the god-class's `_acr_queued_members` dedup state).

**Tech Stack:** Frappe Framework, Python 3.12+, pytest via `bench run-tests`, `EnhancedTestCase` for real-DB integration tests.

**Reference spec:** `docs/plans/2026-05-12-event-application-service-refactor-design.md`
**Prior PR plans:** PR #1 (mapping), PR #2 (member sync), PR #3 (application sync) — see `docs/plans/`.

---

## Carry-forward lessons (CRITICAL — propagate from PR #2 + PR #3)

1. `EnhancedTestDataFactory.create_member` uniquifies BOTH `email` AND `last_name`. Use stored values (`member.email`, `member.last_name`).
2. DocType fieldname is `event_type`, `mijnrood_row_id` is required Int. Reuse `_make_event` helper pattern.
3. `MemberImportService.create_or_update_member()` commits + creates a Customer via `after_save` that survives `EnhancedTestCase` rollback. Use `_cleanup_member_and_customer` helper pattern.
4. `test-quality-enforcer` flags inline `lambda: frappe.delete_doc(...)` — use named helpers.
5. `permission-bypass-validator` requires `# Security: …` comments above `ignore_permissions=True` in production code (NOT test fixture cleanup).
6. Pre-commit may reformat via Black/ruff/isort. Re-stage and re-commit — no `--no-verify`.
7. Pyright "could not be resolved" / "not accessed" stale-index warnings on new module paths are tooling noise — ignore.

**New for PR #4:**

8. `_ensure_user_account_for_volunteer` is **NOT** extracted — it stays in the god-class because it uses `self._acr_queued_members` (an instance Set on the orchestrator). PR #4's `_ensure_volunteer` calls it via `orchestrator._ensure_user_account_for_volunteer(member_name)`.
9. The factory may NOT have a `create_volunteer` helper. Use `frappe.get_doc({"doctype": "Volunteer", ...}).insert(ignore_permissions=True)` directly in tests, OR create a Member then call `create_volunteer_from_member(member_name=member.name, ...)` from `verenigingen.verenigingen.doctype.volunteer.volunteer`. Investigate before writing test setUp.
10. Chapter and Team test setup is non-trivial. `self.factory.create_chapter(**kwargs)` accepts kwargs and forwards to the doc. For Team, use `frappe.get_doc({"doctype": "Team", "team_name": ..., "status": "Active", ...}).insert(ignore_permissions=True)` with addCleanup.

---

## File Structure

**Create:**
- `verenigingen/tests/services/event_application/_fixtures.py` — shared `_FakeOrchestrator` + `StatusMappingSetupMixin`
- `verenigingen/mijnrood_sync/services/event_application/volunteer_sync_service.py` — `MijnRoodVolunteerSyncService` + `get_volunteer_sync_service`
- `verenigingen/tests/services/event_application/test_volunteer_sync_service.py` — real-DB integration tests

**Modify:**
- `verenigingen/tests/services/event_application/test_member_sync_service.py` — replace local `_FakeOrchestrator` with import from `_fixtures`
- `verenigingen/tests/services/event_application/test_application_sync_service.py` — replace local `_FakeOrchestrator` with import; use `StatusMappingSetupMixin` for `setUp` boilerplate
- `verenigingen/mijnrood_sync/services/event_application_service.py` — replace 13 method bodies with delegation shims; delete private helpers

**Do not touch:**
- `_ensure_user_account_for_volunteer` (god-class private helper, uses `_acr_queued_members` state) — stays
- `verenigingen/tests/services/test_event_application_service.py` — only minimal mock retargeting if needed

---

## Scope: methods to extract

| Method | LOC | Notes |
|---|---|---|
| `_parse_mijnrood_roles` | 19 | `@staticmethod`; pure JSON parsing |
| `_ensure_user_role` | 26 | Frappe lookups; no orchestrator deps |
| `_prune_orphan_team_members` | 32 | Helper for `_ensure_team_membership`; pure |
| `_ensure_volunteer` | 92 | Calls `orchestrator._ensure_user_account_for_volunteer`; calls service-internal `_ensure_user_role` |
| `_ensure_user_role` | (see above) | |
| `_ensure_chapter_board_membership` | 80 | Calls `get_mapping_service().resolve_division_id()` |
| `_ensure_team_membership` | 84 | Calls service-internal `_prune_orphan_team_members` |
| `_end_team_membership` | 66 | Saves Team with `ignore_permissions` |
| `_end_chapter_board_membership` | 94 | Uses `chapter_doc.board_manager.bulk_remove_board_members` |
| `_notify_board_membership_change` | 48 | Publishes realtime + calls `notify_administrators` |
| `_apply_role_actions` | 46 | Dispatcher; calls 3 ensure-methods |
| `_handle_admin_role_change` | 40 | Calls `_apply_role_actions`, `_end_team_membership` |
| `_handle_division_contact_change` | 42 | Calls `_apply_role_actions`, `_end_chapter_board_membership`, `_notify_board_membership_change` |
| `_process_member_roles` | 50 | Entry point; calls `_parse_mijnrood_roles` + both `_handle_*` methods |

Total: ~720 LOC across 13 methods. All move to the new service; all 13 keep 1-line shims on the god-class.

---

## Task 1: Extract shared fixtures (reviewer-flagged cleanup)

**Goal:** Promote `_FakeOrchestrator` to a shared module before PR #4 spawns a third copy. Also extract a `StatusMappingSetupMixin` so PR #4 (and beyond) can avoid duplicating ~20-line `setUp` boilerplate.

**Files:**
- Create: `verenigingen/tests/services/event_application/_fixtures.py`
- Modify: `verenigingen/tests/services/event_application/test_member_sync_service.py`
- Modify: `verenigingen/tests/services/event_application/test_application_sync_service.py`

- [ ] **Step 1:** Create `_fixtures.py`:

```python
"""Shared test fixtures for the event_application service test suite.

_FakeOrchestrator: stand-in for MijnRoodEventApplicationService.
    Records calls to cross-cutting helpers that have not yet been
    extracted from the god-class. Each PR in the Phase 1 sequence
    extends this stub as new orchestrator methods are needed.

StatusMappingSetupMixin: mixin that handles the MijnRood Sync Settings
    status_mapping append/restore boilerplate. Subclass must call
    super().setUp() and define cls.STATUS_ID + cls.MEMBERSHIP_TYPE_LABEL.
"""

from unittest.mock import MagicMock

import frappe


class _FakeOrchestrator:
    """Stand-in for MijnRoodEventApplicationService.

    Each attribute is a MagicMock with a sane default return value. Tests
    override per-instance attributes when they need specific behaviour.
    """

    def __init__(self):
        # PR #2 surface — member sync orchestrator deps
        self._create_related_records = MagicMock(return_value=[])
        self._process_member_roles = MagicMock(return_value=[])
        self._try_promote_application = MagicMock(return_value=None)
        self._check_and_handle_termination = MagicMock(return_value=None)
        self._handle_division_field_change = MagicMock(return_value=None)
        # PR #3 additions
        self._find_existing_member_or_conflict = MagicMock(return_value=(None, None))
        self._assign_chapter_from_division = MagicMock(return_value=None)
        self._apply_new_member = MagicMock(
            return_value={"success": True, "message": "fallback from stub"}
        )
        # PR #4 additions
        self._ensure_user_account_for_volunteer = MagicMock(return_value=None)


class StatusMappingSetupMixin:
    """Mixin for tests that need a MijnRood status_mapping row.

    Subclass must define:
        STATUS_ID: int — the mijnrood_status_id to inject
        MEMBERSHIP_TYPE_LABEL: str — the name of the Membership Type to ensure

    Call super().setUp() / super().tearDown() if subclass overrides them.
    """

    STATUS_ID: int = 9000
    MEMBERSHIP_TYPE_LABEL: str = "Default Mapping Test Type"

    def setUp(self):
        super().setUp()
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type(self.MEMBERSHIP_TYPE_LABEL)
        settings.append(
            "status_mapping",
            {
                "mijnrood_status_id": self.STATUS_ID,
                "label": f"{self.MEMBERSHIP_TYPE_LABEL} (status_id={self.STATUS_ID})",
                "membership_type_string": "test",
                "is_active": 1,
                "verenigingen_membership_type": membership_type.name,
            },
        )
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache().delete_value("mijnrood_status_mapping")
        self.addCleanup(self._cleanup_status_mapping)

    def _cleanup_status_mapping(self):
        s = frappe.get_single("MijnRood Sync Settings")
        s.status_mapping = self._original_status_mapping
        s.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache().delete_value("mijnrood_status_mapping")
```

- [ ] **Step 2:** Update `test_member_sync_service.py`:
  - Delete the local `_FakeOrchestrator` class (PR #2 version).
  - Add `from verenigingen.tests.services.event_application._fixtures import _FakeOrchestrator` near the existing imports.

- [ ] **Step 3:** Update `test_application_sync_service.py`:
  - Delete the local `_FakeOrchestrator` class.
  - Add `from verenigingen.tests.services.event_application._fixtures import _FakeOrchestrator` import.
  - Keep the existing per-class `setUp` for now (do not retrofit `StatusMappingSetupMixin` — that's optional cleanup not required by this task).

- [ ] **Step 4:** Run both PR #2 and PR #3 test files to confirm no regression:

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_application_sync_service
```
Expected: 10/10 and 22/22 still pass.

- [ ] **Step 5:** Commit:

```bash
git add verenigingen/tests/services/event_application/_fixtures.py \
        verenigingen/tests/services/event_application/test_member_sync_service.py \
        verenigingen/tests/services/event_application/test_application_sync_service.py
git commit -m "refactor(tests): promote _FakeOrchestrator to shared fixtures module"
```

---

## Task 2: Scaffold + `_parse_mijnrood_roles`

**Goal:** Create the service module with a static `_parse_mijnrood_roles` method. Pure JSON parsing — no DB writes — easiest to TDD.

**Files:**
- Create: `verenigingen/mijnrood_sync/services/event_application/volunteer_sync_service.py`
- Create: `verenigingen/tests/services/event_application/test_volunteer_sync_service.py`

- [ ] **Step 1:** Write the failing tests file:

```python
"""Real-DB integration tests for MijnRoodVolunteerSyncService.

Pure-function tests (_parse_mijnrood_roles) don't need a real DB but
live here for cohesion. Tests for ensure_volunteer / ensure_*_membership
/ end_*_membership / _process_member_roles use EnhancedTestCase with
real Chapter + Team + Volunteer + User fixtures.
"""

import json

import frappe

from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    get_volunteer_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.event_application._fixtures import _FakeOrchestrator


class TestParseMijnRoodRoles(EnhancedTestCase):
    """Static-method JSON parser for the MijnRood roles column."""

    def test_returns_empty_set_for_none(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles(None)
        self.assertEqual(result, set())

    def test_returns_empty_set_for_empty_string(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles("")
        self.assertEqual(result, set())

    def test_parses_json_array_string(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles('["ROLE_ADMIN", "ROLE_DIVISION_CONTACT"]')
        self.assertEqual(result, {"ROLE_ADMIN", "ROLE_DIVISION_CONTACT"})

    def test_passes_through_python_list(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles(["ROLE_ADMIN"])
        self.assertEqual(result, {"ROLE_ADMIN"})

    def test_filters_non_role_entries(self):
        # Only entries starting with "ROLE_" survive — other strings dropped
        result = get_volunteer_sync_service()._parse_mijnrood_roles(
            '["ROLE_ADMIN", "SOMETHING_ELSE", "ROLE_DIVISION_CONTACT"]'
        )
        self.assertEqual(result, {"ROLE_ADMIN", "ROLE_DIVISION_CONTACT"})

    def test_returns_empty_set_for_malformed_json(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles("not-valid-json")
        self.assertEqual(result, set())
```

- [ ] **Step 2:** Run — expect `ModuleNotFoundError`.

- [ ] **Step 3:** Create the service module:

```python
"""MijnRoodVolunteerSyncService — applies MijnRood role events.

Extracted from event_application_service.py as Phase 1, PR #4 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service owns:
- Role parsing (_parse_mijnrood_roles)
- Volunteer creation (_ensure_volunteer)
- Frappe role assignment (_ensure_user_role)
- Chapter board membership (_ensure_chapter_board_membership,
  _end_chapter_board_membership, _notify_board_membership_change)
- Team membership (_ensure_team_membership, _end_team_membership,
  _prune_orphan_team_members)
- Role-action dispatch (_apply_role_actions)
- Top-level role transition routing (_handle_admin_role_change,
  _handle_division_contact_change)
- Role-processing entry point (_process_member_roles)

It delegates back to the calling event-application orchestrator only
for _ensure_user_account_for_volunteer, which depends on the
orchestrator's _acr_queued_members instance-state and stays in the
god-class. That parameter will go away when the god-class's per-run
dedup state moves to a context object in PR #6.
"""

import json
import logging
from typing import Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.mijnrood_sync.field_mapping import get_role_mapping
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
)

logger = logging.getLogger("verenigingen.mijnrood_sync.event_application.volunteer_sync")


class MijnRoodVolunteerSyncService:
    """Applies MijnRood role/team/board events to Verenigingen records."""

    def __init__(self):
        self.logger = logger

    @staticmethod
    def _parse_mijnrood_roles(roles_value) -> set[str]:
        """Parse the MijnRood roles JSON column into a set of role strings.

        The roles column contains a JSON array like '["ROLE_ADMIN"]' or null.
        """
        if not roles_value:
            return set()

        if isinstance(roles_value, str):
            try:
                parsed = json.loads(roles_value)
            except (json.JSONDecodeError, ValueError):
                return set()
        elif isinstance(roles_value, list):
            parsed = roles_value
        else:
            return set()

        return {r for r in parsed if isinstance(r, str) and r.startswith("ROLE_")}


_service_instance: Optional[MijnRoodVolunteerSyncService] = None


def get_volunteer_sync_service() -> MijnRoodVolunteerSyncService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodVolunteerSyncService()
    return _service_instance
```

- [ ] **Step 4:** Run — 6 tests pass.

- [ ] **Step 5:** Commit:

```bash
git commit -m "feat(mijnrood-sync): scaffold MijnRoodVolunteerSyncService with _parse_mijnrood_roles"
```

---

## Task 3: `_ensure_user_role` + `_prune_orphan_team_members`

Two small independent methods. Tests + impl + commit in one go.

**Tests to add (append to `test_volunteer_sync_service.py`):**

- `TestEnsureUserRole` — 3 tests:
  - returns None when member has no user
  - returns None and skips when role already assigned
  - adds role to existing user and returns success message
  - returns error message when role doesn't exist

- `TestPruneOrphanTeamMembers` — 2 tests:
  - returns 0 when all team_members rows reference existing volunteers
  - prunes rows whose volunteer no longer exists

For `TestPruneOrphanTeamMembers`, construct an in-memory Team doc with `team_doc.append("team_members", {"volunteer": "vol-name", ...})`. To trigger an orphan, append a row with `"volunteer": "vol-does-not-exist"` (string that doesn't match any existing Volunteer.name).

**Method bodies to add to the service:**

Copy verbatim from `event_application_service.py` lines 1162-1187 (`_ensure_user_role`) and lines 1355-1386 (`_prune_orphan_team_members`). Both methods take only DB args — no orchestrator parameter needed.

- [ ] Commit: `feat(mijnrood-sync): add _ensure_user_role + _prune_orphan_team_members to MijnRoodVolunteerSyncService`

---

## Task 4: `_ensure_volunteer`

Calls `orchestrator._ensure_user_account_for_volunteer` (god-class) and service-internal `_ensure_user_role`.

**Tests to add (append):**

- `TestEnsureVolunteer` — 4 tests:
  - creates volunteer when none exists (use `create_volunteer_from_member` path)
  - skips creation and assigns Frappe role when volunteer already exists and config has `verenigingen_role` (no team)
  - skips role assignment and calls orchestrator._ensure_user_account_for_volunteer when volunteer exists and config has `add_to_team`
  - returns failure message when create_volunteer_from_member returns success=False

Use `self.factory.create_member(...)` then `from verenigingen.verenigingen.doctype.volunteer.volunteer import create_volunteer_from_member, get_volunteer_for_member` and call manually OR use `from verenigingen.verenigingen.doctype.volunteer.volunteer import create_volunteer_from_member` directly in `setUp`. Tests cleanup: `_cleanup_member_and_customer(member.name)` + `_cleanup_volunteer_for_member(member_name)` (delete Volunteer + linked User).

**Method body:** Copy verbatim from `event_application_service.py` lines 1069-1160 with these changes:
- Signature: `def _ensure_volunteer(self, member_name, config, orchestrator, event=None) -> Optional[str]:` — add `orchestrator` param
- `self._ensure_user_account_for_volunteer(member_name)` → `orchestrator._ensure_user_account_for_volunteer(member_name)`
- `self._ensure_user_role(...)` → `self._ensure_user_role(...)` (no change — same service)
- `self._acr_queued_members.add(member_name)` → `orchestrator._acr_queued_members.add(member_name)` — orchestrator's state, not ours
- Otherwise verbatim

- [ ] Commit: `feat(mijnrood-sync): add _ensure_volunteer to MijnRoodVolunteerSyncService`

---

## Task 5: Chapter board ops (`_ensure_chapter_board_membership` + `_end_chapter_board_membership` + `_notify_board_membership_change`)

These three are tightly coupled (notify only fires when end runs; both look up via division_id).

**Tests to add (append):**

- `TestEnsureChapterBoardMembership` — 4 tests:
  - returns error message when division_id doesn't resolve to a Chapter
  - returns error message when member has no Volunteer record
  - returns error message when chapter_role doesn't exist
  - returns None when volunteer is already on the chapter board
  - adds new board member and returns success message

- `TestEndChapterBoardMembership` — 3 tests:
  - returns None when member has no volunteer
  - returns None when volunteer is not on the board
  - removes board member via BoardManager.bulk_remove_board_members

- `TestNotifyBoardMembershipChange` — 1 test:
  - publishes realtime + calls notify_administrators (mock `frappe.publish_realtime` and `notify_administrators`; assert called with expected args)

For chapter tests: `self.factory.create_chapter(mijnrood_division_id=42)` then directly insert a Volunteer doc + append to chapter.board_members in setUp. Cleanup: delete Chapter + Volunteer.

**Method bodies:** Copy verbatim from `event_application_service.py` lines 1189-1268, 1456-1548, 1550-1594. None take orchestrator params (no orchestrator deps).

- [ ] Commit: `feat(mijnrood-sync): add chapter board ops to MijnRoodVolunteerSyncService`

---

## Task 6: Team ops (`_ensure_team_membership` + `_end_team_membership`)

Both depend on `_prune_orphan_team_members` (already in service from Task 3).

**Tests to add (append):**

- `TestEnsureTeamMembership` — 4 tests:
  - returns error when member has no volunteer
  - returns error when team doesn't exist
  - returns error when team status is not Active
  - returns None when volunteer is already on team (active)
  - adds new team member and returns success message

- `TestEndTeamMembership` — 2 tests:
  - returns None when member has no volunteer
  - returns None when volunteer is not on team
  - ends active team membership (sets status=Ended, is_active=0, to_date=today)

For team tests: create Team via `frappe.get_doc({"doctype": "Team", "team_name": ..., "status": "Active"}).insert(ignore_permissions=True)` in setUp; cleanup with addCleanup.

**Method bodies:** Copy verbatim from `event_application_service.py` lines 1270-1353, 1388-1454. Note `_ensure_team_membership` calls `self._prune_orphan_team_members(team_doc, team_name)` — that stays as `self.` since both methods are in the same service.

- [ ] Commit: `feat(mijnrood-sync): add team ops to MijnRoodVolunteerSyncService`

---

## Task 7: Role dispatcher + handlers + entry point

Four methods: `_apply_role_actions`, `_handle_admin_role_change`, `_handle_division_contact_change`, `_process_member_roles`. They chain top-down.

**Tests to add (append):**

- `TestApplyRoleActions` — 2 tests:
  - config with `create_volunteer=True` calls `_ensure_volunteer`
  - config with `add_to_chapter_board=True` + division_ids calls `_ensure_chapter_board_membership` per division

- `TestHandleAdminRoleChange` — 2 tests:
  - ROLE_ADMIN added → calls `_apply_role_actions`
  - ROLE_ADMIN removed + config has team → calls `_end_team_membership`; returns "ROLE_ADMIN removed" message
  - ROLE_ADMIN unchanged → returns []

- `TestHandleDivisionContactChange` — 2 tests:
  - new_division_ids set + config has ROLE_DIVISION_CONTACT → calls `_apply_role_actions`
  - divisions removed → calls `_end_chapter_board_membership` per removed division + `_notify_board_membership_change`

- `TestProcessMemberRoles` — 2 tests:
  - returns [] when role mapping config is empty
  - calls both `_handle_admin_role_change` and `_handle_division_contact_change` with parsed roles

For these tests it's acceptable to MOCK the called methods on the service instance directly (e.g. `service._ensure_volunteer = MagicMock(return_value="vol msg")`) since the routing logic is what's being tested, not the underlying actions. The downstream method tests in Tasks 4-6 already cover the real-DB behavior.

**Method bodies:** Copy verbatim from `event_application_service.py` lines 888-1067, with these changes:
- `_apply_role_actions(..., orchestrator=None, event=None)` — add orchestrator param; pass to `_ensure_volunteer`
- All other `self._foo(...)` calls stay as `self._foo(...)` (same service)

- [ ] Commit: `feat(mijnrood-sync): add role processing entry point to MijnRoodVolunteerSyncService`

---

## Task 8: Wire god-class, verify, push

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application_service.py`

- [ ] **Step 1:** Add the import:

```python
from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    get_volunteer_sync_service,
)
```

- [ ] **Step 2:** Replace 13 method bodies with one-line shims. Preserve signatures + docstrings.

For each method, the body becomes a delegation. Most need `self` (the orchestrator) only for cross-service helper access:

```python
# _process_member_roles — entry point
return get_volunteer_sync_service()._process_member_roles(
    member_name, mijnrood_data, old_data=old_data, event=event
)

# _handle_admin_role_change
return get_volunteer_sync_service()._handle_admin_role_change(
    member_name, current_roles, old_roles, role_config, event=event
)

# _handle_division_contact_change
return get_volunteer_sync_service()._handle_division_contact_change(
    member_name, new_division_ids, old_division_ids, role_config, event=event
)

# _apply_role_actions
return get_volunteer_sync_service()._apply_role_actions(
    member_name, config, division_ids=division_ids, event=event, orchestrator=self
)

# _ensure_volunteer
return get_volunteer_sync_service()._ensure_volunteer(member_name, config, self, event=event)

# _ensure_user_role
return get_volunteer_sync_service()._ensure_user_role(member_name, role)

# _ensure_chapter_board_membership
return get_volunteer_sync_service()._ensure_chapter_board_membership(
    member_name, division_id, chapter_role, event=event
)

# _ensure_team_membership
return get_volunteer_sync_service()._ensure_team_membership(member_name, team_name, event=event)

# _prune_orphan_team_members
return get_volunteer_sync_service()._prune_orphan_team_members(team_doc, team_name)

# _end_team_membership
return get_volunteer_sync_service()._end_team_membership(member_name, team_name, event=event)

# _end_chapter_board_membership
return get_volunteer_sync_service()._end_chapter_board_membership(member_name, division_id, event=event)

# _notify_board_membership_change
return get_volunteer_sync_service()._notify_board_membership_change(
    member_name, removed_division_ids, event=event
)

# _parse_mijnrood_roles (static method)
return MijnRoodVolunteerSyncService._parse_mijnrood_roles(roles_value)
```

Note: `_parse_mijnrood_roles` is decorated `@staticmethod` in the god-class. Since `get_volunteer_sync_service()._parse_mijnrood_roles(...)` would call it as an instance method, prefer the direct class reference. Add the import:

```python
from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    MijnRoodVolunteerSyncService,
    get_volunteer_sync_service,
)
```

- [ ] **Step 3:** Check for orphaned imports. Run:

```bash
grep -n "from verenigingen.mijnrood_sync.field_mapping import" verenigingen/mijnrood_sync/services/event_application_service.py
```

If `get_role_mapping` is no longer used by the god-class (it's only used by `_process_member_roles` body which moved to the service), drop the import. Verify with `grep -c "get_role_mapping" verenigingen/mijnrood_sync/services/event_application_service.py`.

- [ ] **Step 4:** Verify file parses:

```bash
cd ~/frappe-bench && env/bin/python -c "import ast; ast.parse(open('apps/verenigingen/verenigingen/mijnrood_sync/services/event_application_service.py').read()); print('OK')"
```

- [ ] **Step 5:** Run the full test suite:

```bash
# New service tests
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_volunteer_sync_service

# PR #3 regression
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_application_sync_service

# PR #2 regression
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service

# PR #1 regression
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_mapping_service

# Existing mocked baseline (must remain 140/150)
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.test_event_application_service
```

- [ ] **Step 6:** If existing mocked tests have NEW failures (beyond the 10 pre-existing baseline), retarget mocks following the PR #2/#3 pattern. Likely candidates: tests that patch `service._ensure_volunteer`, `service._apply_role_actions`, etc. via `patch.object`. Those continue to work because shim methods still exist. Tests patching `service._process_member_roles` body internals may need retargeting to `MijnRoodVolunteerSyncService._process_member_roles`.

- [ ] **Step 7:** Pre-commit + commit:

```bash
cd ~/frappe-bench/apps/verenigingen && pre-commit run --files \
  verenigingen/mijnrood_sync/services/event_application_service.py

git add verenigingen/mijnrood_sync/services/event_application_service.py
# Include any retargeted test files
git commit -m "$(cat <<'EOF'
refactor(mijnrood-sync): delegate volunteer sync to MijnRoodVolunteerSyncService

Replaces the bodies of 13 role/volunteer/team/chapter-board methods
(_process_member_roles, _handle_admin_role_change,
_handle_division_contact_change, _apply_role_actions, _ensure_volunteer,
_ensure_user_role, _ensure_chapter_board_membership,
_ensure_team_membership, _prune_orphan_team_members, _end_team_membership,
_end_chapter_board_membership, _notify_board_membership_change,
_parse_mijnrood_roles) with one-line delegations to the new
MijnRoodVolunteerSyncService.

The god-class shrinks by ~720 LOC. Public method shims remain so the
dispatcher and PR #2's member_sync_service (which call _process_member_roles
via the orchestrator) continue to work without import-path churn.

_ensure_user_account_for_volunteer stays in the god-class because it
depends on the orchestrator's _acr_queued_members per-instance dedup
state. PR #4's _ensure_volunteer calls it via the orchestrator parameter.

This is Phase 1, PR #4 of the Tier C decomposition documented at
docs/plans/2026-05-12-event-application-service-refactor-design.md.
EOF
)"
```

- [ ] **Step 8:** Push:

```bash
SKIP=jest-testing,javascript-doctype-validator git push
```

---

## Success Criteria

1. `verenigingen/mijnrood_sync/services/event_application/volunteer_sync_service.py` exists with `MijnRoodVolunteerSyncService` (13 methods) and `get_volunteer_sync_service`.
2. `event_application_service.py` retains 13 public shim methods (≤ 5 lines each) and no longer contains the bodies of any of the 13 extracted methods. `_ensure_user_account_for_volunteer` stays.
3. New volunteer-sync tests (~25-30) pass against a real DB via `EnhancedTestCase`. MagicMock used only for the orchestrator stub (`_ensure_user_account_for_volunteer`) and for inner-routing tests (Task 7) where the service's own methods are stubbed.
4. Shared `_FakeOrchestrator` lives in `tests/services/event_application/_fixtures.py`; PR #2 and PR #3 test files import from there (no local copies).
5. PR #1/#2/#3 regression tests still pass.
6. `test_event_application_service.py` baseline (140/150) preserved; any new failures resolved via minimal mock retargeting.
7. Pre-commit hooks pass on every touched file.
8. God-class LOC count drops by ~720 (from 1,925 to ~1,205).
