# Orchestrator Decoupling — Design

**Date:** 2026-05-15
**Status:** Approved — ready for implementation plan
**Scope:** Post-Phase-1 cleanup of the MijnRood event_application refactor. Removes the transitional `orchestrator` parameter from the 6 extracted services, deletes the dead dispatcher shim methods, and rehomes the per-event `_acr_queued_members` dedup state.

## Background

Phase 1 of the Tier C refactor (PRs 1-7) decomposed the 2,433-LOC `MijnRoodEventApplicationService` god-class into 6 focused services plus a dispatcher. During extraction, every service that needed a not-yet-extracted helper received the calling god-class instance as an `orchestrator` parameter and called back into it (`orchestrator._foo(...)`). This was a deliberate transitional scaffold — see the Phase 1 PR plans.

Now that all 6 services exist, every `orchestrator._foo()` call resolves to a method that lives in one of those services. The `orchestrator` parameter and the ~28 dispatcher shim methods it routes through are pure transitional debt. They are harmless (1-line delegations, fully tested) but no longer serve a purpose.

## Goals

1. Remove the `orchestrator` parameter from all ~15 service methods that declare it.
2. Rewire every `orchestrator._foo(...)` call to a direct `get_xxx_service()._foo(...)` call.
3. Delete the ~28 dead pure-shim methods from the dispatcher.
4. Rehome the `_acr_queued_members` per-event dedup Set off the dispatcher.

## Non-Goals

- Restructuring `apply_event` / `_dispatch` / `_TABLE_HANDLERS` — the genuine dispatch layer stays ("minimal — rewire only").
- Extracting `_sync_division_to_chapter` (~110 LOC of chapter-sync logic still in the dispatcher) — out of scope; it stays.
- Result-idiom unification (the dropped Phase 3) — not in scope.
- Thread-safety of singleton-held state — unchanged from today, explicitly out of scope per the Phase 1 audit.
- Collapsing the 30+ shims into a flat `apply_event` switch — rejected in favor of "minimal."

## Current State

### Cross-service call sites (the `orchestrator._foo()` calls to rewire)

| Caller | Call | Resolves to |
|---|---|---|
| `member_sync_service` | `orchestrator._try_promote_application(event, row_data)` | `application_sync_service.try_promote_application` |
| `member_sync_service` | `orchestrator._create_related_records(...)` | `related_records_orchestrator._create_related_records` |
| `member_sync_service` | `orchestrator._process_member_roles(...)` | `volunteer_sync_service._process_member_roles` |
| `member_sync_service` | `orchestrator._check_and_handle_termination(...)` | `termination_sync_service._check_and_handle_termination` |
| `member_sync_service` | `orchestrator._handle_division_field_change(...)` | `related_records_orchestrator._handle_division_field_change` |
| `application_sync_service` | `orchestrator._find_existing_member_or_conflict(...)` | `member_sync_service.find_existing_member_or_conflict` |
| `application_sync_service` | `orchestrator._assign_chapter_from_division(...)` | `related_records_orchestrator._assign_chapter_from_division` |
| `application_sync_service` | `orchestrator._create_related_records(...)` | `related_records_orchestrator._create_related_records` |
| `application_sync_service` | `orchestrator._apply_new_member(event)` | `member_sync_service.apply_new_member` |
| `volunteer_sync_service` | `orchestrator._ensure_user_account_for_volunteer(member_name)` | `related_records_orchestrator._ensure_user_account_for_volunteer` |
| `related_records_orchestrator` | `self._ensure_user_account(member_name, orchestrator)` | self (drops orchestrator arg) |

### `_acr_queued_members` usage (5 sites)

| File | Site | Operation |
|---|---|---|
| `related_records_orchestrator.py` | line ~249 | read (`member_name in ...`) |
| `related_records_orchestrator.py` | line ~264 | write (`.add(...)`) |
| `related_records_orchestrator.py` | line ~464 | read |
| `related_records_orchestrator.py` | line ~479 | write |
| `volunteer_sync_service.py` | line ~140 | write |

Plus the dispatcher: `__init__` creates the Set; `apply_event` clears it at the start of every invocation.

## Design

### 1. Cross-service rewiring

Each `orchestrator._foo(...)` call becomes `get_xxx_service()._foo(...)`. The `get_xxx_service()` singleton accessors already exist (one per service). Methods that currently declare `orchestrator` as a parameter drop it.

Methods losing the `orchestrator` parameter:
- `member_sync_service`: `apply_new_member`, `apply_changed_member`
- `application_sync_service`: `apply_new_membership_application`, `apply_changed_membership_application`, `apply_approved`, `promote_application_member`, `try_promote_application`
- `volunteer_sync_service`: `_ensure_volunteer`, `_apply_role_actions`, `_handle_admin_role_change`, `_handle_division_contact_change`, `_process_member_roles`
- `related_records_orchestrator`: `_create_related_records`, `_ensure_user_account`, `_ensure_user_account_for_volunteer`

### 2. Circular imports

`member_sync_service` ↔ `application_sync_service` is a genuine import cycle (member calls application's `try_promote_application`; application calls member's `apply_new_member` + `find_existing_member_or_conflict`).

**Mitigation:** lazy imports inside method bodies — the established codebase convention ("lazy imports throughout to avoid circular dependencies"). All cross-service `get_xxx_service` imports go inside the method body that needs them, not at module top level. This is already how the services import `MemberImportService`, `create_volunteer_from_member`, etc.

### 3. `_acr_queued_members` rehoming (Approach A)

The Set moves onto `MijnRoodRelatedRecordsOrchestrator` as instance state (`self._acr_queued_members`), with a 3-method public interface:

```python
def reset_acr_dedup(self) -> None:
    """Clear the per-event ACR dedup set. Called by the dispatcher at the
    start of every apply_event invocation."""
    self._acr_queued_members.clear()

def is_acr_queued(self, member_name: str) -> bool:
    """True if an ACR has already been queued for this member in the
    current event."""
    return member_name in self._acr_queued_members

def mark_acr_queued(self, member_name: str) -> None:
    """Record that an ACR has been queued for this member."""
    self._acr_queued_members.add(member_name)
```

The Set is initialized in `MijnRoodRelatedRecordsOrchestrator.__init__` (`self._acr_queued_members: set[str] = set()`).

**Consumers:**
- `related_records_orchestrator._ensure_user_account` / `_ensure_user_account_for_volunteer`: use `self.is_acr_queued(...)` / `self.mark_acr_queued(...)`.
- `volunteer_sync_service._ensure_volunteer`: `get_related_records_orchestrator().mark_acr_queued(member_name)`.
- Dispatcher `apply_event`: `get_related_records_orchestrator().reset_acr_dedup()` at the start (replacing `self._acr_queued_members.clear()`).

The dispatcher's `__init__` no longer creates `_acr_queued_members`.

**Behaviour note:** the Set lives on a singleton, reset per `apply_event`. This is identical to today's behaviour (the dispatcher is also a singleton via `get_event_application_service()`, and the Set was reset per `apply_event`). No behavioural change; same thread-safety profile.

### 4. Dispatcher changes

- The `_apply_*` dispatch-layer methods (`_apply_new`, `_apply_changed`, `_apply_deleted`, `_apply_approved`, and the 6 per-table `_apply_*_member` / `_apply_*_division` / `_apply_*_membership_application`) drop the `, self` argument from their service calls. They stay as methods — they are the dispatch layer.
- The ~28 pure orchestrator-callback shim methods are **deleted**: `_find_existing_member_or_conflict`, `_create_related_records`, `_apply_mijnrood_comments`, `_ensure_address`, `_ensure_mollie_data`, `_ensure_membership_and_dues`, `_backfill_dues_schedule`, `_update_existing_dues_schedule`, `_ensure_user_account`, `_ensure_user_account_for_volunteer`, `_assign_chapter_from_division`, `_handle_division_field_change`, `_promote_application_member`, `_try_promote_application`, `_check_and_handle_termination`, `_process_member_roles`, `_handle_admin_role_change`, `_handle_division_contact_change`, `_apply_role_actions`, `_ensure_volunteer`, `_ensure_user_role`, `_ensure_chapter_board_membership`, `_ensure_team_membership`, `_prune_orphan_team_members`, `_end_team_membership`, `_end_chapter_board_membership`, `_notify_board_membership_change`, `_parse_mijnrood_roles`. These have no callers once the rewiring is done (their only callers were the extracted services via `orchestrator._foo()`, and the mocked test file that referenced them was deleted in PR #8).
- `_acr_queued_members` removed from `__init__`; `apply_event` start calls `reset_acr_dedup()`.
- `_sync_division_to_chapter` **stays**. **Plan-time check:** grep `_sync_division_to_chapter`'s body for any `self._<shim>` call to a method on the deletion list. If found, rewire that specific call to the owning service before deleting the shim.

### 5. Test rework

~30 tests across the 6 service test files construct a `_FakeOrchestrator` and pass it to service methods. After decoupling:
- Service-method calls in tests drop the orchestrator argument.
- Tests that asserted `orchestrator._foo` was called (mock-interaction assertions) retarget to patching the real `get_xxx_service()` accessor or the real service method.
- `_acr_queued_members` tests (currently `orchestrator._acr_queued_members = set()` / membership checks) switch to `get_related_records_orchestrator().reset_acr_dedup()` for setup and `.is_acr_queued(...)` for assertions.
- `_FakeOrchestrator` in `tests/services/event_application/_fixtures.py` loses most of its purpose. It is removed if no test still needs it, or reduced to whatever genuinely remains. `StatusMappingSetupMixin` in the same file is unaffected.

### 6. Scope and sequencing

**One PR.** The rewire is interlocked: changing a service method's signature forces its callers' call sites to change in the same commit, and the member↔application cycle means both move together. A partial rewire would leave a non-compiling intermediate state. The PR is executed service-by-service via subagents with TDD discipline — after each service's rewire, the full 129-test surface runs to catch regressions early.

Suggested task order (low-coupling first):
1. Add the dedup interface (`reset_acr_dedup` / `is_acr_queued` / `mark_acr_queued` + the Set) to `related_records_orchestrator` — additive, no behaviour change yet.
2. Rewire `related_records_orchestrator` internals to use `self.is_acr_queued` / `self.mark_acr_queued`; drop `orchestrator` from its methods.
3. Rewire `termination_sync_service` — no `orchestrator` param today (self-contained), so this is a no-op verification step; skip if confirmed clean.
4. Rewire `volunteer_sync_service` — drop `orchestrator`; rewire to `get_related_records_orchestrator()`.
5. Rewire `member_sync_service` — drop `orchestrator`; rewire to the 4 peer services (lazy imports).
6. Rewire `application_sync_service` — drop `orchestrator`; rewire to `member_sync` + `related_records` (lazy imports).
7. Dispatcher: drop `, self` from dispatch-layer calls; delete the ~28 dead shims; remove `_acr_queued_members` from `__init__`; wire `reset_acr_dedup()` into `apply_event`.
8. Test rework + `_FakeOrchestrator` removal + full verification.

Each step commits independently where it leaves the suite green; steps 4-7 may need to land together if intermediate states don't compile (the plan will determine exact commit boundaries).

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| `member_sync` ↔ `application_sync` circular import | Lazy imports inside method bodies — established codebase convention. |
| Large test churn (~30 tests touch `_FakeOrchestrator`) | Service-by-service execution; run the full 129-test surface after each service rewire. |
| `_sync_division_to_chapter` secretly depends on a shim slated for deletion | Plan-time grep of its body; rewire any such call to the owning service before deleting the shim. |
| Intermediate non-compiling state during the interlocked rewire | Plan determines commit boundaries; steps that don't leave the suite green are bundled into one commit. |
| External caller breakage | Only `apply_event` is called externally (DocType controller `mijnrood_sync_event.py`). The `_`-prefixed shims have no external callers — the mocked test file that used them was deleted in PR #8. Verified safe to delete. |

## Success Criteria

1. Zero `orchestrator` parameters remain in any of the 6 service modules.
2. The ~28 dead shim methods are removed from `dispatcher.py`.
3. `apply_event`, `_dispatch`, `_TABLE_HANDLERS`, and the `_apply_*` dispatch-layer methods remain intact and functional.
4. `_acr_queued_members` lives on `MijnRoodRelatedRecordsOrchestrator` with the `reset_acr_dedup` / `is_acr_queued` / `mark_acr_queued` interface; the dispatcher no longer holds it.
5. All 129 real-DB integration tests pass.
6. `apply_event` remains the working external entry point (DocType controller unaffected).
7. Pre-commit hooks pass on every touched file.
