# Orchestrator Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the transitional `orchestrator` parameter from the 6 MijnRood event_application services, rewire `orchestrator._foo()` calls to direct `get_xxx_service()._foo()` calls, rehome the `_acr_queued_members` dedup state onto `related_records_orchestrator`, and delete the ~28 dead dispatcher shim methods.

**Architecture:** Pure mechanical refactor — no behaviour change. The 129 existing real-DB integration tests are the regression net; every task ends green. The interlocked member↔application import cycle is unlocked by first making all `orchestrator` parameters optional (`=None`), then rewiring service internals one service at a time, then deleting the now-vestigial parameter and dispatcher shims.

**Tech Stack:** Frappe Framework, Python 3.12+, pytest via `bench run-tests`, `EnhancedTestCase`.

**Reference spec:** `docs/plans/2026-05-15-orchestrator-decoupling-design.md`

---

## Why the ordering is what it is

`member_sync_service` and `application_sync_service` call each other (member → application's `try_promote_application`; application → member's `apply_new_member` + `find_existing_member_or_conflict`). You cannot rewire one before the other without a broken intermediate state. The unlock: **Task 2 makes every `orchestrator` parameter optional (`orchestrator=None`)** as a pure signature edit. After that, any service can call any peer with or without the argument, so the internal rewiring (Tasks 3-6) can proceed one service at a time with the suite green throughout. Task 7 cleans the dispatcher. Task 8 deletes the vestigial parameter once nothing passes it.

---

## File Structure

**Modify:**
- `verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py` — gains the dedup Set + 3-method interface; loses `orchestrator` params
- `verenigingen/mijnrood_sync/services/event_application/volunteer_sync_service.py` — loses `orchestrator` params; rewires to `related_records`
- `verenigingen/mijnrood_sync/services/event_application/member_sync_service.py` — loses `orchestrator` params; rewires to 4 peers
- `verenigingen/mijnrood_sync/services/event_application/application_sync_service.py` — loses `orchestrator` params; rewires to `member_sync` + `related_records`
- `verenigingen/mijnrood_sync/services/event_application/dispatcher.py` — drops `, self` from `_apply_*` calls; deletes ~28 shims; rehomes `reset_acr_dedup` into `apply_event`
- All 6 service test files under `verenigingen/tests/services/event_application/`
- `verenigingen/tests/services/event_application/_fixtures.py` — `_FakeOrchestrator` removed once unused

**Not touched:**
- `termination_sync_service.py` — has no `orchestrator` parameter (self-contained); only its *callers* change
- `mapping_service.py` — has no `orchestrator` parameter
- `_sync_division_to_chapter` in `dispatcher.py` — stays (per the design's "minimal" scope); Task 7 includes a grep check that it does not depend on a deleted shim

---

## Task 1: Add the ACR dedup interface to related_records_orchestrator

Additive only — no behaviour change, no caller uses it yet.

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py`

- [ ] **Step 1: Add the dedup Set to `__init__`**

Find the `MijnRoodRelatedRecordsOrchestrator.__init__` method (currently `def __init__(self): self.logger = logger`). Change it to:

```python
    def __init__(self):
        self.logger = logger
        # Per-event ACR dedup: tracks which members have already had an
        # Account Creation Request queued during the current apply_event
        # invocation. Reset by the dispatcher via reset_acr_dedup() at the
        # start of each event. Previously lived on the dispatcher god-class
        # as _acr_queued_members.
        self._acr_queued_members: set[str] = set()
```

- [ ] **Step 2: Add the 3-method public interface**

Add these three methods immediately after `__init__`:

```python
    def reset_acr_dedup(self) -> None:
        """Clear the per-event ACR dedup set.

        Called by the dispatcher at the start of every apply_event
        invocation so dedup state never leaks between events.
        """
        self._acr_queued_members.clear()

    def is_acr_queued(self, member_name: str) -> bool:
        """True if an ACR has already been queued for this member in the
        current event."""
        return member_name in self._acr_queued_members

    def mark_acr_queued(self, member_name: str) -> None:
        """Record that an ACR has been queued for this member."""
        self._acr_queued_members.add(member_name)
```

- [ ] **Step 3: Verify the module parses**

Run:
```bash
cd ~/frappe-bench && env/bin/python -c "import ast; ast.parse(open('apps/verenigingen/verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py').read()); print('OK')"
```
Expected: `OK`.

- [ ] **Step 4: Run the related_records test suite (regression check — additive change must not break anything)**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_related_records_orchestrator
```
Expected: 30 tests pass.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py
git commit -m "feat(mijnrood-sync): add ACR dedup interface to MijnRoodRelatedRecordsOrchestrator"
```

---

## Task 2: Make every `orchestrator` parameter optional

Pure signature edit across 3 service files. `orchestrator` → `orchestrator=None`. No behaviour change — callers still pass it positionally/by keyword; it simply becomes optional. This unlocks the member↔application cycle for Tasks 3-6.

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application/member_sync_service.py`
- Modify: `verenigingen/mijnrood_sync/services/event_application/application_sync_service.py`
- Modify: `verenigingen/mijnrood_sync/services/event_application/volunteer_sync_service.py`
- Modify: `verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py`

- [ ] **Step 1: Find every method with an `orchestrator` parameter**

Run:
```bash
grep -rn "orchestrator" verenigingen/mijnrood_sync/services/event_application/*.py | grep "def \|orchestrator)" | grep -v "dispatcher.py"
```

The methods with an `orchestrator` parameter are:
- `member_sync_service.py`: `apply_new_member(self, event, orchestrator)`, `apply_changed_member(self, event, orchestrator)`
- `application_sync_service.py`: `apply_new_membership_application(self, event, orchestrator)`, `apply_changed_membership_application(self, event, orchestrator)`, `apply_approved(self, event, orchestrator)`, `promote_application_member(self, old_data, new_data, row_data, event, orchestrator)`, `try_promote_application(self, event, row_data, orchestrator)`
- `volunteer_sync_service.py`: `_ensure_volunteer(self, member_name, config, orchestrator, event=None)`, `_apply_role_actions(self, member_name, config, division_ids=None, event=None, orchestrator=None)` *(already optional)*, `_handle_admin_role_change(self, ..., orchestrator=None)` *(already optional)*, `_handle_division_contact_change(self, ..., orchestrator=None)` *(already optional)*, `_process_member_roles(self, ..., orchestrator=None)` *(already optional)*
- `related_records_orchestrator.py`: `_create_related_records(self, member_name, row_data, event=None, orchestrator=None)` *(already optional)*, `_ensure_user_account(self, member_name, orchestrator)`, `_ensure_user_account_for_volunteer(self, member_name, orchestrator)`

- [ ] **Step 2: Make the non-optional ones optional**

For each method where `orchestrator` is currently a *required* positional parameter, change it to `orchestrator=None`. The methods needing this edit (the ones NOT already marked optional above):

`member_sync_service.py`:
```python
# before:  def apply_new_member(self, event, orchestrator) -> dict:
def apply_new_member(self, event, orchestrator=None) -> dict:
# before:  def apply_changed_member(self, event, orchestrator) -> dict:
def apply_changed_member(self, event, orchestrator=None) -> dict:
```

`application_sync_service.py`:
```python
def apply_new_membership_application(self, event, orchestrator=None) -> dict:
def apply_changed_membership_application(self, event, orchestrator=None) -> dict:
def apply_approved(self, event, orchestrator=None) -> dict:
def promote_application_member(self, old_data, new_data, row_data, event, orchestrator=None) -> dict:
def try_promote_application(self, event, row_data, orchestrator=None) -> Optional[dict]:
```

`volunteer_sync_service.py`:
```python
# _ensure_volunteer: orchestrator is positional before event — keep order, just add default
def _ensure_volunteer(self, member_name, config, orchestrator=None, event=None) -> Optional[str]:
```

`related_records_orchestrator.py`:
```python
def _ensure_user_account(self, member_name, orchestrator=None) -> Optional[str]:
def _ensure_user_account_for_volunteer(self, member_name, orchestrator=None) -> Optional[str]:
```

Preserve every docstring and the rest of each signature exactly. Only the `orchestrator` parameter gains `=None`.

- [ ] **Step 3: Verify all four modules parse**

Run:
```bash
cd ~/frappe-bench && for f in member_sync_service application_sync_service volunteer_sync_service related_records_orchestrator; do env/bin/python -c "import ast; ast.parse(open('apps/verenigingen/verenigingen/mijnrood_sync/services/event_application/$f.py').read()); print('$f OK')"; done
```
Expected: 4 × `OK`.

- [ ] **Step 4: Run the full event_application test surface**

Run each of the 6 modules:
```bash
cd ~/frappe-bench && for m in test_mapping_service test_member_sync_service test_application_sync_service test_volunteer_sync_service test_termination_sync_service test_related_records_orchestrator; do bench --site veg11.veganisme.org run-tests --module verenigingen.tests.services.event_application.$m; done
```
Expected: 16, 10, 23, 44, 6, 30 = 129 pass.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/member_sync_service.py \
        verenigingen/mijnrood_sync/services/event_application/application_sync_service.py \
        verenigingen/mijnrood_sync/services/event_application/volunteer_sync_service.py \
        verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py
git commit -m "refactor(mijnrood-sync): make orchestrator parameter optional across services"
```

---

## Task 3: Rewire related_records_orchestrator internals

related_records uses `orchestrator` only for the dedup Set. Rewire those to `self`, and its internal `_ensure_user_account` call to drop the argument.

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py`
- Modify: `verenigingen/tests/services/event_application/test_related_records_orchestrator.py`

- [ ] **Step 1: Rewire the dedup calls inside `_ensure_user_account`**

In `_ensure_user_account`, find the two `orchestrator._acr_queued_members` sites and change them:

```python
# before:  if member_name in orchestrator._acr_queued_members:
if self.is_acr_queued(member_name):
# before:  orchestrator._acr_queued_members.add(member_name)
self.mark_acr_queued(member_name)
```

- [ ] **Step 2: Rewire the dedup calls inside `_ensure_user_account_for_volunteer`**

Same two changes in `_ensure_user_account_for_volunteer`:

```python
# before:  if member_name in orchestrator._acr_queued_members:
if self.is_acr_queued(member_name):
# before:  orchestrator._acr_queued_members.add(member_name)
self.mark_acr_queued(member_name)
```

- [ ] **Step 3: Rewire the `_ensure_user_account` call inside `_create_related_records`**

In `_create_related_records`, find:
```python
account_msg = self._ensure_user_account(member_name, orchestrator)
```
Change to:
```python
account_msg = self._ensure_user_account(member_name)
```

- [ ] **Step 4: Confirm `orchestrator` is now unused in this module**

Run:
```bash
grep -n "orchestrator" verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py
```
Expected: matches appear ONLY in (a) the `orchestrator=None` parameter declarations on `_create_related_records` / `_ensure_user_account` / `_ensure_user_account_for_volunteer`, and (b) the module docstring. No `orchestrator._something` usages remain. The parameter is now vestigial — it is removed in Task 8.

- [ ] **Step 5: Run the related_records test module to find what broke**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_related_records_orchestrator
```

Tests that will break and how to fix them:
- **`TestEnsureUserAccount` / `TestEnsureUserAccountForVolunteer`** — tests that set up dedup state via `orchestrator._acr_queued_members = {...}` or `= set()` and pass `orchestrator` to the method. Rework: the dedup state now lives on the real `get_related_records_orchestrator()` singleton. In `setUp` (or at the start of each test), call `get_related_records_orchestrator().reset_acr_dedup()` to start clean. To pre-seed the "already queued" case, call `get_related_records_orchestrator().mark_acr_queued(member.name)`. To assert a member was marked, use `get_related_records_orchestrator().is_acr_queued(member.name)`. Drop the `orchestrator` argument from the `_ensure_user_account` / `_ensure_user_account_for_volunteer` calls (the parameter is still accepted as optional, but the tests no longer need to pass it — passing nothing is cleaner and matches the post-Task-8 end state).
- Any test that passed `_FakeOrchestrator()` purely to satisfy the signature: drop the argument.

**Important:** because the dedup Set now lives on a singleton shared across tests, every test in `TestEnsureUserAccount` and `TestEnsureUserAccountForVolunteer` MUST call `get_related_records_orchestrator().reset_acr_dedup()` in `setUp` to avoid cross-test pollution. Add a `setUp` that does `super().setUp()` then the reset.

- [ ] **Step 6: Apply the test rework, re-run until green**

Rework the broken tests per Step 5. Re-run the module until all 30 pass.

- [ ] **Step 7: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py \
        verenigingen/tests/services/event_application/test_related_records_orchestrator.py
git commit -m "refactor(mijnrood-sync): rewire related_records dedup to self, drop orchestrator usage"
```

---

## Task 4: Rewire volunteer_sync_service

volunteer_sync uses `orchestrator` for one cross-service call (`_ensure_user_account_for_volunteer`) and one dedup write. Rewire both to `related_records`.

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application/volunteer_sync_service.py`
- Modify: `verenigingen/tests/services/event_application/test_volunteer_sync_service.py`

- [ ] **Step 1: Add the top-level import for the related_records accessor**

`volunteer_sync_service` does not import `related_records_orchestrator` and `related_records` does not import `volunteer_sync` — no cycle. Add a top-level import near the existing imports:

```python
from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
```

- [ ] **Step 2: Rewire the two `orchestrator` sites inside `_ensure_volunteer`**

In `_ensure_volunteer`, find:
```python
acr_msg = orchestrator._ensure_user_account_for_volunteer(member_name)
```
Change to:
```python
acr_msg = get_related_records_orchestrator()._ensure_user_account_for_volunteer(member_name)
```

And find:
```python
orchestrator._acr_queued_members.add(member_name)
```
Change to:
```python
get_related_records_orchestrator().mark_acr_queued(member_name)
```

- [ ] **Step 3: Rewire the orchestrator pass-through in `_apply_role_actions`**

`_apply_role_actions` calls `self._ensure_volunteer(member_name, config, orchestrator, event=event)`. Since `_ensure_volunteer` no longer uses `orchestrator`, change the call to drop it:
```python
# before: vol_msg = self._ensure_volunteer(member_name, config, orchestrator, event=event)
vol_msg = self._ensure_volunteer(member_name, config, event=event)
```

`_handle_admin_role_change`, `_handle_division_contact_change`, `_process_member_roles` currently thread `orchestrator=orchestrator` into `_apply_role_actions`. Since nothing downstream uses it anymore, those `orchestrator=orchestrator` keyword arguments can be dropped from the `_apply_role_actions(...)` calls. Remove them.

- [ ] **Step 4: Confirm `orchestrator` is now unused in this module**

Run:
```bash
grep -n "orchestrator" verenigingen/mijnrood_sync/services/event_application/volunteer_sync_service.py
```
Expected: matches appear ONLY in the `orchestrator=None` parameter declarations (`_ensure_volunteer`, `_apply_role_actions`, `_handle_admin_role_change`, `_handle_division_contact_change`, `_process_member_roles`). No `orchestrator._something` and no `orchestrator=orchestrator` pass-through remains.

- [ ] **Step 5: Run the volunteer test module, rework broken tests**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_volunteer_sync_service
```

Expected breakage and fixes:
- **`TestEnsureVolunteer`** — tests that mock `orchestrator._ensure_user_account_for_volunteer` and assert it was called. Rework: the real `get_related_records_orchestrator()._ensure_user_account_for_volunteer` is now called. Either (a) `patch.object(MijnRoodRelatedRecordsOrchestrator, "_ensure_user_account_for_volunteer")` and assert on that, or (b) drop the mock-interaction assertion and assert on observable behaviour. The test `test_skips_role_assignment_when_team_configured` specifically asserted `orchestrator._ensure_user_account_for_volunteer.assert_called_once_with(member.name)` — retarget it with `patch.object(MijnRoodRelatedRecordsOrchestrator, "_ensure_user_account_for_volunteer")` (import `MijnRoodRelatedRecordsOrchestrator` from `related_records_orchestrator`). Add `# Mock justified: Infrastructure - ACR queueing covered by its own suite` above the patch.
- Tests that asserted `member.name in orchestrator._acr_queued_members` (the dedup write in `_ensure_volunteer`) — retarget to `get_related_records_orchestrator().is_acr_queued(member.name)`, and reset via `get_related_records_orchestrator().reset_acr_dedup()` in `setUp`.
- Tests that constructed `_FakeOrchestrator` only to satisfy the signature: drop the argument from `_ensure_volunteer(...)` / `_apply_role_actions(...)` / `_process_member_roles(...)` calls.
- `TestApplyRoleActions`, `TestHandleAdminRoleChange`, `TestHandleDivisionContactChange`, `TestProcessMemberRoles` — these tests mock the service's OWN sub-methods (`service._ensure_volunteer = MagicMock(...)`) and pass `_FakeOrchestrator`. Drop the `orchestrator` argument from the method calls; the sub-method mocks are unaffected.

Re-run until all 44 pass.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/volunteer_sync_service.py \
        verenigingen/tests/services/event_application/test_volunteer_sync_service.py
git commit -m "refactor(mijnrood-sync): rewire volunteer_sync to call related_records directly"
```

---

## Task 5: Rewire member_sync_service

member_sync calls 4 peer services. `application_sync` is the cycle partner — its accessor MUST be imported lazily (inside the method body). The other three (`volunteer`, `termination`, `related_records`) do not import `member_sync`, so their accessors can be top-level imports.

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application/member_sync_service.py`
- Modify: `verenigingen/tests/services/event_application/test_member_sync_service.py`

- [ ] **Step 1: Add top-level imports for the acyclic peers**

Near the existing imports in `member_sync_service.py`, add:
```python
from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
from verenigingen.mijnrood_sync.services.event_application.termination_sync_service import (
    get_termination_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    get_volunteer_sync_service,
)
```

Do NOT add a top-level import for `application_sync_service` — that is the cycle. It is imported lazily in Step 3.

- [ ] **Step 2: Rewire the non-cycle `orchestrator` calls in `apply_new_member` and `apply_changed_member`**

`apply_new_member` body:
```python
# before: related_msgs = orchestrator._create_related_records(member_name, row_data, event)
related_msgs = get_related_records_orchestrator()._create_related_records(member_name, row_data, event)
# before: role_msgs = orchestrator._process_member_roles(member_name, new_data, event=event)
role_msgs = get_volunteer_sync_service()._process_member_roles(member_name, new_data, event=event)
```

`apply_changed_member` body:
```python
# before: termination_result = orchestrator._check_and_handle_termination(event, old_data, new_data, changed_fields)
termination_result = get_termination_sync_service()._check_and_handle_termination(
    event, old_data, new_data, changed_fields
)
# before: chapter_result = orchestrator._handle_division_field_change(member_name, changed_fields, event, field_name="division_id")
chapter_result = get_related_records_orchestrator()._handle_division_field_change(
    member_name, changed_fields, event, field_name="division_id"
)
# before: messages.extend(orchestrator._create_related_records(updated_name, row_data, event))
messages.extend(get_related_records_orchestrator()._create_related_records(updated_name, row_data, event))
# before: role_msgs = orchestrator._process_member_roles(member_name, new_data, old_data=old_data, event=event)
role_msgs = get_volunteer_sync_service()._process_member_roles(
    member_name, new_data, old_data=old_data, event=event
)
```

Preserve the exact positional/keyword argument forms shown — only the receiver (`orchestrator` → `get_xxx_service()`) changes.

- [ ] **Step 3: Rewire the cycle call (`_try_promote_application`) with a lazy import**

In `apply_new_member`, find:
```python
promotion_result = orchestrator._try_promote_application(event, row_data)
```
Change to:
```python
from verenigingen.mijnrood_sync.services.event_application.application_sync_service import (
    get_application_sync_service,
)

promotion_result = get_application_sync_service().try_promote_application(event, row_data)
```

The lazy import goes immediately before the call, inside the method body. Note the method name change: the dispatcher shim was `_try_promote_application`; the real service method is `try_promote_application` (no leading underscore — confirm by reading `application_sync_service.py`).

- [ ] **Step 4: Confirm `orchestrator` is now unused in this module**

Run:
```bash
grep -n "orchestrator" verenigingen/mijnrood_sync/services/event_application/member_sync_service.py
```
Expected: matches appear ONLY in the `orchestrator=None` parameter declarations of `apply_new_member` and `apply_changed_member`. No `orchestrator._something` remains.

- [ ] **Step 5: Run the member test module, rework broken tests**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service
```

Expected breakage and fixes:
- Tests in `TestApplyNewMember` / `TestApplyChangedMember` that constructed `_FakeOrchestrator`, mocked `orchestrator._create_related_records` / `orchestrator._process_member_roles` / `orchestrator._try_promote_application` / `orchestrator._check_and_handle_termination` / `orchestrator._handle_division_field_change`, and asserted those mocks were called.
- Rework: replace the `_FakeOrchestrator` mock-interaction style with `patch.object` on the real peer service classes. For example, a test that did `orchestrator._create_related_records = MagicMock(return_value=[])` and asserted it was called becomes `@patch.object(MijnRoodRelatedRecordsOrchestrator, "_create_related_records", return_value=[])`. Import the peer service classes (`MijnRoodRelatedRecordsOrchestrator`, `MijnRoodVolunteerSyncService`, `MijnRoodTerminationSyncService`, `MijnRoodApplicationSyncService`) at the top of the test file. Add `# Mock justified: Routing - testing dispatcher logic, peer services covered by their own suites` above each patch.
- The promotion-fallback test (`test_email_conflict_invokes_promotion_fallback`) mocked `orchestrator._try_promote_application`. Retarget to `@patch.object(MijnRoodApplicationSyncService, "try_promote_application", ...)`.
- Drop the `orchestrator` argument from all `apply_new_member(...)` / `apply_changed_member(...)` calls in the tests. (The parameter is still optional, but tests should stop passing it — matches the post-Task-8 end state.)

Re-run until all 10 pass.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/member_sync_service.py \
        verenigingen/tests/services/event_application/test_member_sync_service.py
git commit -m "refactor(mijnrood-sync): rewire member_sync to call peer services directly"
```

---

## Task 6: Rewire application_sync_service

application_sync calls `member_sync` (the cycle partner — lazy import) and `related_records` (acyclic — top-level import).

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application/application_sync_service.py`
- Modify: `verenigingen/tests/services/event_application/test_application_sync_service.py`

- [ ] **Step 1: Add the top-level import for related_records**

Near the existing imports in `application_sync_service.py`, add:
```python
from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
```

Do NOT add a top-level import for `member_sync_service` — that is the cycle. It is imported lazily in Step 3.

- [ ] **Step 2: Rewire the related_records `orchestrator` calls**

`apply_new_membership_application` body:
```python
# before: orchestrator._assign_chapter_from_division(member.name, preferred_div_id, event)
get_related_records_orchestrator()._assign_chapter_from_division(member.name, preferred_div_id, event)
```

`apply_changed_membership_application` body:
```python
# before: chapter_msg = orchestrator._handle_division_field_change(member_name, changed_fields, event, field_name="preferred_division_id")
chapter_msg = get_related_records_orchestrator()._handle_division_field_change(
    member_name, changed_fields, event, field_name="preferred_division_id"
)
```

`promote_application_member` body:
```python
# before: related_msgs = orchestrator._create_related_records(updated_name, row_data, event)
related_msgs = get_related_records_orchestrator()._create_related_records(updated_name, row_data, event)
```

- [ ] **Step 3: Rewire the cycle calls (`_find_existing_member_or_conflict`, `_apply_new_member`) with lazy imports**

`apply_new_membership_application` and `apply_changed_membership_application` both call `orchestrator._find_existing_member_or_conflict(...)`. `apply_approved` calls `orchestrator._apply_new_member(event)`. All three target `member_sync_service`, the cycle partner.

In each of those three methods, add a lazy import before the call:
```python
from verenigingen.mijnrood_sync.services.event_application.member_sync_service import (
    get_member_sync_service,
)
```

Then rewire:
```python
# before: existing_name, existing_result = orchestrator._find_existing_member_or_conflict(...)
existing_name, existing_result = get_member_sync_service().find_existing_member_or_conflict(...)
# before: return orchestrator._apply_new_member(event)
return get_member_sync_service().apply_new_member(event)
```

Note the method name changes: the dispatcher shim was `_find_existing_member_or_conflict` / `_apply_new_member`; the real service methods are `find_existing_member_or_conflict` / `apply_new_member` (no leading underscore — confirm by reading `member_sync_service.py`).

- [ ] **Step 4: Rewire the `promote_application_member` orchestrator pass-through**

`try_promote_application` and `apply_approved` call `self.promote_application_member(..., orchestrator)`. Since `promote_application_member` no longer uses `orchestrator`, drop the argument from those internal calls:
```python
# before: return self.promote_application_member(old_data_stub, new_data_stub, row_data, event, orchestrator)
return self.promote_application_member(old_data_stub, new_data_stub, row_data, event)
# before: return self.promote_application_member(old_data or {}, new_data, row_data, event, orchestrator)
return self.promote_application_member(old_data or {}, new_data, row_data, event)
```

- [ ] **Step 5: Confirm `orchestrator` is now unused in this module**

Run:
```bash
grep -n "orchestrator" verenigingen/mijnrood_sync/services/event_application/application_sync_service.py
```
Expected: matches appear ONLY in the `orchestrator=None` parameter declarations and the module docstring. No `orchestrator._something` and no `orchestrator` argument pass-through remains.

- [ ] **Step 6: Run the application test module, rework broken tests**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_application_sync_service
```

Expected breakage and fixes:
- Tests that mocked `orchestrator._find_existing_member_or_conflict`, `orchestrator._assign_chapter_from_division`, `orchestrator._create_related_records`, `orchestrator._apply_new_member`, `orchestrator._handle_division_field_change`.
- Rework: retarget to `patch.object` on the real peer classes (`MijnRoodMemberSyncService`, `MijnRoodRelatedRecordsOrchestrator`). For example, the idempotency test that did `orchestrator._find_existing_member_or_conflict = MagicMock(return_value=(...))` becomes `@patch.object(MijnRoodMemberSyncService, "find_existing_member_or_conflict", return_value=(...))`. The `apply_approved` fall-through test that asserted `orchestrator._apply_new_member.assert_called_once_with(event)` becomes `@patch.object(MijnRoodMemberSyncService, "apply_new_member", ...)`.
- Import the peer service classes at the top of the test file. Add `# Mock justified: Routing - peer services covered by their own suites` above each patch.
- `TestApprovedEventEndToEnd` (added in PR #8) calls `apply_event` end-to-end — it does NOT pass `orchestrator` and should be unaffected. Verify it still passes.
- Drop the `orchestrator` argument from all `apply_*` / `promote_application_member` / `try_promote_application` calls in the tests.

Re-run until all 23 pass.

- [ ] **Step 7: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/application_sync_service.py \
        verenigingen/tests/services/event_application/test_application_sync_service.py
git commit -m "refactor(mijnrood-sync): rewire application_sync to call peer services directly"
```

---

## Task 7: Clean up the dispatcher

After Tasks 3-6 the services no longer call `orchestrator._foo()`. The ~28 pure-shim methods on the dispatcher have no callers and are deleted. The genuine dispatch layer stays.

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/event_application/dispatcher.py`

- [ ] **Step 1: Drop `, self` from the `_apply_*` dispatch-layer calls**

The per-table dispatch methods currently pass `self` as the orchestrator. Find each and drop it. The methods and their new bodies:

```python
def _apply_new_member(self, event) -> dict:
    """..."""  # keep docstring
    return get_member_sync_service().apply_new_member(event)

def _apply_changed_member(self, event) -> dict:
    """..."""
    return get_member_sync_service().apply_changed_member(event)

def _apply_new_membership_application(self, event) -> dict:
    """..."""
    return get_application_sync_service().apply_new_membership_application(event)

def _apply_changed_membership_application(self, event) -> dict:
    """..."""
    return get_application_sync_service().apply_changed_membership_application(event)

def _apply_approved(self, event) -> dict:
    """..."""
    return get_application_sync_service().apply_approved(event)
```

`_apply_new_division` and `_apply_changed_division` call `self._sync_division_to_chapter(...)` — leave them unchanged (`_sync_division_to_chapter` stays). `_apply_new`, `_apply_changed`, `_apply_deleted` and `_dispatch` — leave their structure; they route by table/action and call the per-table methods above.

- [ ] **Step 2: Grep-check that `_sync_division_to_chapter` does not depend on a soon-to-be-deleted shim**

Run:
```bash
sed -n '/def _sync_division_to_chapter/,/^    def /p' verenigingen/mijnrood_sync/services/event_application/dispatcher.py | grep -n "self\._"
```

For every `self._<name>` call inside `_sync_division_to_chapter`, check whether `<name>` is in the deletion list (Step 4 below). If it is, rewire that call to the owning service first (e.g. `self._assign_chapter_from_division(...)` → `get_related_records_orchestrator()._assign_chapter_from_division(...)`). If the only `self._` calls are to methods that stay (`_dispatch`, `_apply_*`, `apply_event`, or `_sync_division_to_chapter` itself), no rewiring is needed. Document what was found.

- [ ] **Step 3: Rehome the ACR dedup reset into `apply_event`**

In `apply_event`, find the line that clears the dedup set at the start of the method:
```python
self._acr_queued_members.clear()
```
Replace it with:
```python
get_related_records_orchestrator().reset_acr_dedup()
```

Ensure `get_related_records_orchestrator` is imported at the top of `dispatcher.py` (it may already be from prior PRs; if not, add the import).

Then remove the `_acr_queued_members` initialisation from `__init__`:
```python
# before:
#     def __init__(self):
#         super().__init__(service_name="MijnRoodEventApplicationService")
#         self._acr_queued_members: set[str] = set()
# after:
    def __init__(self):
        super().__init__(service_name="MijnRoodEventApplicationService")
```

- [ ] **Step 4: Delete the dead shim methods**

Delete these ~28 methods from the `MijnRoodEventApplicationService` class. They are pure delegations whose only callers were the extracted services via `orchestrator._foo()` — now rewired — and the mocked test file deleted in PR #8.

`_find_existing_member_or_conflict`, `_create_related_records`, `_apply_mijnrood_comments`, `_ensure_address`, `_ensure_mollie_data`, `_ensure_membership_and_dues`, `_backfill_dues_schedule`, `_update_existing_dues_schedule`, `_ensure_user_account`, `_ensure_user_account_for_volunteer`, `_assign_chapter_from_division`, `_handle_division_field_change`, `_promote_application_member`, `_try_promote_application`, `_check_and_handle_termination`, `_process_member_roles`, `_handle_admin_role_change`, `_handle_division_contact_change`, `_apply_role_actions`, `_ensure_volunteer`, `_ensure_user_role`, `_ensure_chapter_board_membership`, `_ensure_team_membership`, `_prune_orphan_team_members`, `_end_team_membership`, `_end_chapter_board_membership`, `_notify_board_membership_change`, `_parse_mijnrood_roles`.

**Before deleting each one, confirm it has no remaining caller:**
```bash
for m in _find_existing_member_or_conflict _create_related_records _apply_mijnrood_comments _ensure_address _ensure_mollie_data _ensure_membership_and_dues _backfill_dues_schedule _update_existing_dues_schedule _ensure_user_account _ensure_user_account_for_volunteer _assign_chapter_from_division _handle_division_field_change _promote_application_member _try_promote_application _check_and_handle_termination _process_member_roles _handle_admin_role_change _handle_division_contact_change _apply_role_actions _ensure_volunteer _ensure_user_role _ensure_chapter_board_membership _ensure_team_membership _prune_orphan_team_members _end_team_membership _end_chapter_board_membership _notify_board_membership_change _parse_mijnrood_roles; do
  n=$(grep -rn "self\.$m\b\|\.$m(" verenigingen/mijnrood_sync/ --include=dispatcher.py | grep -v "def $m" | wc -l)
  echo "$m: $n remaining call(s)"
done
```
Expected: `0 remaining call(s)` for every method. If any shows a non-zero count, investigate that caller before deleting — it may be `_sync_division_to_chapter` (handle per Step 2) or a genuinely missed rewire.

- [ ] **Step 5: Verify the dispatcher parses and imports cleanly**

Run:
```bash
cd ~/frappe-bench && env/bin/python -c "import ast; ast.parse(open('apps/verenigingen/verenigingen/mijnrood_sync/services/event_application/dispatcher.py').read()); print('parse OK')"
cd ~/frappe-bench && env/bin/python -c "from verenigingen.mijnrood_sync.services.event_application_service import get_event_application_service, MijnRoodEventApplicationService; print('import OK')"
```
Expected: `parse OK` then `import OK`.

- [ ] **Step 6: Run the full event_application test surface**

```bash
cd ~/frappe-bench && for m in test_mapping_service test_member_sync_service test_application_sync_service test_volunteer_sync_service test_termination_sync_service test_related_records_orchestrator; do bench --site veg11.veganisme.org run-tests --module verenigingen.tests.services.event_application.$m; done
```
Expected: 16, 10, 23, 44, 6, 30 = 129 pass.

- [ ] **Step 7: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/dispatcher.py
git commit -m "refactor(mijnrood-sync): delete dead orchestrator shims from dispatcher"
```

---

## Task 8: Remove the vestigial `orchestrator` parameter + retire `_FakeOrchestrator`

After Task 7, nothing passes `orchestrator` to any service method. Delete the now-dead parameter from all signatures and remove the `_FakeOrchestrator` fixture.

**Files:**
- Modify: all 4 service files that have `orchestrator=None` parameters (`member_sync_service.py`, `application_sync_service.py`, `volunteer_sync_service.py`, `related_records_orchestrator.py`)
- Modify: `verenigingen/tests/services/event_application/_fixtures.py`

- [ ] **Step 1: Confirm nothing passes `orchestrator` anymore**

Run:
```bash
grep -rn "orchestrator" verenigingen/mijnrood_sync/services/event_application/ verenigingen/tests/services/event_application/ | grep -v "def .*orchestrator" | grep -v "#"
```
Expected: no `orchestrator=` keyword arguments and no positional `orchestrator` passing at any call site. Only parameter *declarations* (`def …(…, orchestrator=None…)`) and possibly docstring text remain. If any call site still passes it, that is a missed rewire from Tasks 3-6 — fix it before continuing.

- [ ] **Step 2: Delete the `orchestrator=None` parameter from every service method signature**

Remove `orchestrator=None` (and any leftover docstring lines describing the transitional parameter) from:
- `member_sync_service.py`: `apply_new_member`, `apply_changed_member`
- `application_sync_service.py`: `apply_new_membership_application`, `apply_changed_membership_application`, `apply_approved`, `promote_application_member`, `try_promote_application`
- `volunteer_sync_service.py`: `_ensure_volunteer`, `_apply_role_actions`, `_handle_admin_role_change`, `_handle_division_contact_change`, `_process_member_roles`
- `related_records_orchestrator.py`: `_create_related_records`, `_ensure_user_account`, `_ensure_user_account_for_volunteer`

For `_ensure_volunteer`, the signature was `(self, member_name, config, orchestrator=None, event=None)` → `(self, member_name, config, event=None)`.

Also update the module docstrings of the 4 files — each has a paragraph describing the transitional `orchestrator` parameter (e.g. related_records' docstring mentions "Methods that touch the dedup set accept an `orchestrator` parameter"). Replace those paragraphs with a one-line note that the services call each other via `get_xxx_service()` accessors. Keep it brief.

- [ ] **Step 3: Remove `_FakeOrchestrator` from the shared fixtures**

Run:
```bash
grep -rn "_FakeOrchestrator" verenigingen/tests/
```

If — after the Task 3-6 test rework — no test still imports or uses `_FakeOrchestrator`, delete the `_FakeOrchestrator` class from `verenigingen/tests/services/event_application/_fixtures.py` and remove the now-unused `from unittest.mock import MagicMock` import if it is no longer referenced in that file. Keep `StatusMappingSetupMixin` — it is unaffected. Update the `_fixtures.py` module docstring to drop the `_FakeOrchestrator` description.

If any test still references `_FakeOrchestrator`, that test was not fully reworked in Tasks 3-6 — go back and finish its rework so the fixture can be deleted. The end state has zero `_FakeOrchestrator` references.

- [ ] **Step 4: Verify all modules parse**

Run:
```bash
cd ~/frappe-bench && for f in member_sync_service application_sync_service volunteer_sync_service related_records_orchestrator; do env/bin/python -c "import ast; ast.parse(open('apps/verenigingen/verenigingen/mijnrood_sync/services/event_application/$f.py').read()); print('$f OK')"; done
```
Expected: 4 × `OK`.

- [ ] **Step 5: Run the full event_application test surface**

```bash
cd ~/frappe-bench && for m in test_mapping_service test_member_sync_service test_application_sync_service test_volunteer_sync_service test_termination_sync_service test_related_records_orchestrator; do bench --site veg11.veganisme.org run-tests --module verenigingen.tests.services.event_application.$m; done
```
Expected: 16, 10, 23, 44, 6, 30 = 129 pass.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/mijnrood_sync/services/event_application/member_sync_service.py \
        verenigingen/mijnrood_sync/services/event_application/application_sync_service.py \
        verenigingen/mijnrood_sync/services/event_application/volunteer_sync_service.py \
        verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py \
        verenigingen/tests/services/event_application/_fixtures.py
git commit -m "refactor(mijnrood-sync): drop vestigial orchestrator parameter and _FakeOrchestrator fixture"
```

---

## Task 9: Final verification + push

**Files:** none modified — verification only.

- [ ] **Step 1: Confirm zero `orchestrator` references remain in the services**

Run:
```bash
grep -rn "orchestrator" verenigingen/mijnrood_sync/services/event_application/*.py | grep -v "dispatcher.py"
```
Expected: no matches (or only incidental matches in unrelated comments — verify visually).

- [ ] **Step 2: Confirm the dispatcher shrank and the dispatch layer is intact**

Run:
```bash
grep -c "def " verenigingen/mijnrood_sync/services/event_application/dispatcher.py
grep -n "def apply_event\|def _dispatch\|_TABLE_HANDLERS\|def _sync_division_to_chapter" verenigingen/mijnrood_sync/services/event_application/dispatcher.py
```
Expected: the method count dropped by ~28; `apply_event`, `_dispatch`, `_TABLE_HANDLERS`, `_sync_division_to_chapter` all still present.

- [ ] **Step 3: Run the broader sync test discovery to catch indirect callers**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services
```
Expected: no test discovery errors or new failures attributable to this refactor. Pre-existing unrelated failures elsewhere in the suite are acceptable.

- [ ] **Step 4: Smoke-test the external entry point**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org console <<'EOF'
from verenigingen.mijnrood_sync.services.event_application_service import get_event_application_service
svc = get_event_application_service()
print(type(svc).__name__, "— apply_event callable:", callable(getattr(svc, "apply_event", None)))
EOF
```
Expected: `MijnRoodEventApplicationService — apply_event callable: True`.

- [ ] **Step 5: Pre-commit on all touched files**

```bash
cd ~/frappe-bench/apps/verenigingen && pre-commit run --files \
  verenigingen/mijnrood_sync/services/event_application/related_records_orchestrator.py \
  verenigingen/mijnrood_sync/services/event_application/volunteer_sync_service.py \
  verenigingen/mijnrood_sync/services/event_application/member_sync_service.py \
  verenigingen/mijnrood_sync/services/event_application/application_sync_service.py \
  verenigingen/mijnrood_sync/services/event_application/dispatcher.py \
  verenigingen/tests/services/event_application/_fixtures.py \
  verenigingen/tests/services/event_application/test_related_records_orchestrator.py \
  verenigingen/tests/services/event_application/test_volunteer_sync_service.py \
  verenigingen/tests/services/event_application/test_member_sync_service.py \
  verenigingen/tests/services/event_application/test_application_sync_service.py
```
Expected: all hooks pass. If a hook reformatted a file, re-stage and amend the relevant commit or add a follow-up `style:` commit — do not use `--no-verify`.

- [ ] **Step 6: Push**

```bash
SKIP=jest-testing,javascript-doctype-validator git push
```

---

## Success Criteria

1. No `orchestrator` parameter remains in any of the 6 service modules.
2. The ~28 dead shim methods are gone from `dispatcher.py`; `apply_event`, `_dispatch`, `_TABLE_HANDLERS`, the `_apply_*` dispatch layer, and `_sync_division_to_chapter` remain.
3. `_acr_queued_members` lives on `MijnRoodRelatedRecordsOrchestrator` with `reset_acr_dedup` / `is_acr_queued` / `mark_acr_queued`; the dispatcher no longer holds it.
4. `_FakeOrchestrator` is removed from `_fixtures.py`; `StatusMappingSetupMixin` stays.
5. All 129 real-DB integration tests pass.
6. `apply_event` remains the working external entry point (DocType controller unaffected).
7. Pre-commit hooks pass on every touched file.
