# event_application_service.py Refactor — Design

**Date:** 2026-05-12
**Status:** COMPLETE (2026-05-15) — Phases 1-2 shipped; Phase 3 dropped; orchestrator decoupling done.
**Scope:** Tier C audit follow-up. Decomposes the MijnRood sync event-application god-class, rewrites its test suite, and unifies result idioms across the touched code.

> **Completion note (2026-05-15).** Phase 1 (PRs 1-7) and Phase 2 (PR 8) shipped as
> designed: the 2,433-LOC god-class is now a 19-LOC re-export shim over 6 services
> plus a dispatcher, and the 3,145-LOC mock test file was replaced by ~129 real-DB
> integration tests. **Phase 3 (result-idiom unification) was dropped** — a pre-flight
> audit found the "three competing idioms" premise did not survive the extraction
> (`OperationResult` had effectively vanished; what remained were different return
> types for genuinely different kinds of method, not competing idioms). Forcing
> `OperationResult` onto the ~40 `Optional[str]` helpers would have been ceremony.
> A follow-on **orchestrator decoupling** (design: `2026-05-15-orchestrator-decoupling-design.md`)
> removed the transitional `orchestrator` parameter and the dispatcher shim methods.

## Background

The MijnRood sync audit (five parallel agents, 2026-05-11) identified `verenigingen/mijnrood_sync/services/event_application_service.py` as a CRITICAL-severity tech-debt site:

- 2,433 LOC, 43 methods, one class
- Mixes dispatch, mapping, persistence, role assignment, termination workflow, related-records orchestration, and notifications
- Five overlapping entry points for member creation/promotion (mirroring the "three competing approval orchestrators" anti-pattern from MEMORY)
- Three result idioms coexist inside this service alone: `OperationResult`, plain `dict({"success": …})`, and `result.success / result.method_used` from a repository pattern
- Test coverage is wide (3,107 LOC, 150 methods in `tests/services/test_event_application_service.py`) but shallow — patches `frappe` wholesale via `MagicMock`, so real validation, permission, hook, and link-check paths are never exercised

Tier A and Tier B audit follow-ups (commits `70d801ae`, `728aa281`, `7008660d`) landed surgical fixes. Tier C is the architectural cleanup.

## Goals

1. Decompose the god-class into focused services, each callable in isolation with a clear public surface.
2. Replace the mock-heavy test suite with real-DB integration tests written incrementally per extracted service.
3. Standardize result types on `OperationResult` across the new services and adjacent callers.

## Non-Goals

- Data migration of any kind. Pure code reorganization.
- DocType schema changes.
- Refactor of `polling_service.py`, `application_approval_correlator.py`, or other MijnRood services.
- Test rewrites for code outside `event_application_service.py` except where Phase 3 unifies result types at boundaries.
- Fixing the underlying data-integrity bug masked by `_prune_orphan_team_members` (orphan FKs from hard-deleted volunteers).

## Target Architecture

New sub-package `verenigingen/mijnrood_sync/services/event_application/`:

```
event_application/
├── __init__.py                       # re-exports + singleton accessor
├── dispatcher.py                     # apply_event() + _TABLE_HANDLERS routing (~300 LOC)
├── mapping_service.py                # MijnRood row → member field dict; status/role/division lookups
├── member_sync_service.py            # _apply_new_member, _apply_changed_member, _find_existing_member_or_conflict
├── application_sync_service.py       # _apply_new_membership_application, _promote_application_member, _apply_approved
├── volunteer_sync_service.py         # role/team/board assignment, _prune_orphan_team_members
├── termination_sync_service.py       # _check_and_handle_termination + status-transition routing
└── related_records_orchestrator.py   # _create_related_records (address, Mollie, membership, dues)
```

`event_application_service.py` itself shrinks to a re-export shim so existing callers (`polling_service`, `mijnrood_sync_event.py`, batch_approve flow) continue to work without import-path churn:

```python
# event_application_service.py (post-refactor)
from verenigingen.mijnrood_sync.services.event_application import get_service, apply_event  # noqa: F401
```

Pattern follows `SEPAMandateMixin` — the "gold standard" delegation pattern in the codebase (per MEMORY note on Member mixins).

### Service responsibilities

| Service | Owns | Reads from | Writes |
|---|---|---|---|
| `mapping_service` | Pure-function row → field-dict translation; status_id / role_id / division_id resolution against config | `MijnRood Status Mapping`, `MijnRood Role Mapping`, `MijnRood Sync State` (for raw_data fallback) | Nothing |
| `member_sync_service` | Create / update Member; resolve existing-member-or-conflict | Mapping service output | `Member`, `Contact` |
| `application_sync_service` | New application creation; promotion to Member | `Membership Application` | `Membership Application`, delegates to `member_sync_service` for promotion |
| `volunteer_sync_service` | Volunteer creation/update; team membership; chapter board ops; orphan-team pruning | Role mapping | `Volunteer`, `Team`, `Chapter Board Member`, `User` (roles) |
| `termination_sync_service` | Routes terminated-status transitions to `TerminationExecutionService` | Status mapping | `Membership Termination Request` |
| `related_records_orchestrator` | Address, Mollie linkage, Membership, dues schedule creation | Other services | `Address`, `Mollie Customer`, `Membership`, `Membership Dues Schedule` |
| `dispatcher` | `apply_event(event_name)`, `_apply_new/_changed/_deleted/_approved`, `_TABLE_HANDLERS`, error→`event.error_message` mapping | All other services | `MijnRood Sync Event` (status + error_message) |

Each service exposes a `get_xxx_service()` singleton accessor with a module-level `_service_instance` — preserving the existing project convention (audit noted this is "consistent with project pattern").

## Phasing

### Phase 1 — Refactor with parallel tests (~5-7 PRs, multi-day)

One service extracted per PR. For each PR:

1. Move methods from `event_application_service.py` to the new service module.
2. Write new real-DB integration tests using `EnhancedTestCase` + `CoreTestDataFactory` (factory consolidation is complete per MEMORY; deterministic generation works).
3. Leave existing `test_event_application_service.py` (3,107 LOC of mocks) untouched.
4. Dispatcher in `event_application_service.py` continues to route to the extracted service via its singleton accessor.

Order (low-blast-radius first):

1. `mapping_service` — pure functions, no DB writes, easiest to test in isolation
2. `member_sync_service` — touches Member but bounded
3. `application_sync_service` — touches Membership Application
4. `volunteer_sync_service` — touches Volunteer / Team / User-Role
5. `termination_sync_service` — touches MTR; already delegates the hard work to `TerminationExecutionService`
6. `related_records_orchestrator` — orchestrates the other six; extracted last because it depends on them
7. `dispatcher` — what's left becomes `apply_event` + routing; original file becomes a 5-line re-export shim

### Phase 2 — Delete old mocked tests (1 PR, ~1 day)

Once all new services have real-DB tests with coverage parity, delete `tests/services/test_event_application_service.py` in one swing. New tests live next to each service under `tests/services/event_application/`.

**Coverage parity** is defined as: every public method on each new service has at least one happy-path + one failure-path test running against a real DB, and the bypass-flag paths (`ignore_permissions`, `_system_update`, `_csv_import`, `flags.skip_termination_validation`) are each exercised by at least one test.

### Phase 3 — Result idioms unification (1 PR, ~1 day)

Standardize on `OperationResult` across the new services and adjacent callers (`apply_event`, `polling_service`, `application_approval_correlator`). Plain `dict({"success": …, "message": …})` and `result.success / result.method_used` patterns are adapted at the boundaries.

**Total:** ~8 PRs, ~2-3 weeks elapsed depending on review cadence.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Bypass flags (`ignore_permissions`, `_system_update`, `_csv_import`, `flags.skip_termination_validation`) are load-bearing and must survive the refactor | Each new service must preserve them; new real-DB tests must exercise the bypass paths. If a test triggers permission failure, set the flag — don't remove it. |
| Three result idioms during the Phase 1–3 window | Acceptable; Phase 3 closes the gap. Dispatcher adapts at the boundary during the transition. |
| Old mocked tests are kept alive during Phase 1 — risk of false confidence | They function as a leading indicator of behaviour regressions. Don't delete mid-Phase-1 even if redundant. |
| `apply_event` exception contract (catches all errors, sets `event.error_message`) must keep working | Dispatcher preserves the catch + error_message contract verbatim. The Tier A unmapped-status fix and operator UX (re-trigger Approved events with error_message) keep working. |
| Singleton-pattern thread safety (audit note) | Out of scope. Preserve the existing module-level `_service_instance` pattern per project convention. |
| Phase 1 PR ordering — wrong order makes individual PRs un-revertable | Strict linear ordering (mapping → member → application → volunteer → termination → orchestrator → dispatcher). Each PR mergeable on its own. |

## Implementation Constraints

- No new DocTypes, no JSON schema changes.
- No breaking changes to public callers: existing `event_application_service.get_service()` and `apply_event(event_name)` keep working via the dispatcher shim.
- Phase 1 PRs are linearly dependent but each ships value (one concern fewer in the god-class). No "draft refactor" PRs.
- Pre-commit hooks must pass on each PR (Black, ruff, AST field analyzer, permission-bypass-validator). Known-broken hooks (`jest-testing`, `javascript-doctype-validator`) skipped per project convention.
- All real-DB tests must run under non-Admin role for permission-sensitive flows (per MEMORY: feedback_tests_run_as_admin).

## Open Questions Deferred to Phase 1 Detail-Plan

- **Member vs. Application boundary**: the promotion path (`_try_promote_application` → `_promote_application_member`) crosses both services. Phase 1 PR #3 must establish the seam.
- **`_prune_orphan_team_members` placement**: volunteer concern or team concern? Audit noted it papers over a deeper data-integrity bug (orphan FKs from hard-deleted volunteers). We don't fix that bug here, but the placement decision is real.
- **Status mapping miss behaviour**: Tier A made unmapped status IDs raise `ValueError`. Confirm the new mapping service preserves that exact contract.

## Success Criteria

1. `event_application_service.py` is ≤ 20 LOC (re-export shim only) at end of Phase 1.
2. Each new service is ≤ 500 LOC (target; exceeding requires a justification note in the PR).
3. Each new service has dedicated real-DB integration tests using `CoreTestDataFactory`, running under the appropriate role context.
4. `tests/services/test_event_application_service.py` is deleted at end of Phase 2.
5. All bypass flags from the original code path are preserved and exercised by tests.
6. All services in `event_application/` return `OperationResult` at end of Phase 3; immediate callers adapt at the seam.
7. No regression in existing MijnRood sync end-to-end behaviour (manual smoke test plus existing integration test coverage outside `event_application_service`).
