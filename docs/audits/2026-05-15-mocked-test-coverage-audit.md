# Mocked Test Coverage Audit (PR #8, Task 1)

**Date:** 2026-05-15
**Plan:** `docs/plans/2026-05-15-event-application-mocked-test-deletion-plan.md`
**Source file under audit:** `verenigingen/tests/services/test_event_application_service.py` (3,107 LOC, 33 mock-heavy test classes)
**Comparison surface:** `verenigingen/tests/services/event_application/` (125 real-DB tests across 6 service files)

This audit covers ONLY the 8 AUDIT/DEAD targets called out in the plan. The other 25 classes in the old file are already marked COVERED in the plan's mapping table; they are not re-audited here.

## Summary

| # | Target (old class) | Verdict |
|---|---|---|
| 1 | TestDispatchRouting | GAP-ACCEPT |
| 2 | TestAssignChapterFromDivisionJoinDate | GAP-FILL |
| 3 | TestBackfillDuesSchedule | GAP-FILL |
| 4 | TestAcrDeduplication | COVERED |
| 5 | TestApplyNewMemberPromotionPath | COVERED |
| 6 | TestEnsureEmployeeForProfile | DEAD |
| 7 | TestApplyEventDispatchesApproved | GAP-ACCEPT |
| 8 | TestApprovedEventCreatesMembershipAndDues | GAP-FILL |

**GAP-FILL count: 3** (targets #2, #3, #8)
**GAP-ACCEPT count: 2** (targets #1, #7)
**COVERED count: 2** (targets #4, #5)
**DEAD count: 1** (target #6)

---

## TestDispatchRouting

**What it tests:** The `_dispatch()` table-router helper. Three test methods:
- `test_unknown_table_returns_reference_only` — unrecognised `mijnrood_table` value returns the reference-only success response.
- `test_admin_member_routes_to_member_handler` — `admin_member` table routes to `_apply_new_member`.
- `test_application_table_routes_to_member_handler` — `admin_membership_application` routes to `_apply_new_membership_application`.

**Coverage in new tests:** None. The new tests call the per-table service entry points directly (`apply_new_member`, `apply_new_membership_application`, etc.) — they never go through `apply_event` or `_dispatch`. Confirmed by `grep -rn "\.apply_event\|MijnRoodEventApplicationService()" verenigingen/tests/services/event_application/` returning zero matches.

**Decision:** GAP-ACCEPT

**Rationale:** `_dispatch()` is a trivial dict lookup (`_TABLE_HANDLERS` dict in `dispatcher.py:109-113`) followed by a `getattr` on the dispatcher with a string-built attribute name. The routing surface is 9 lines of code. The handlers themselves (`_apply_new_member`, `_apply_new_membership_application`, etc.) are each individually covered by real-DB tests. The risk of a regression in `_dispatch` itself is low: any wrong key would surface immediately in an end-to-end run.

That said, target #8 (`TestApprovedEventCreatesMembershipAndDues`) — which we're filling — DOES exercise `apply_event` end to end (just for the Approved branch). That coverage transitively guards against catastrophic dispatcher misregressions. Accepting the gap for the New/Changed branches is proportional to the risk.

---

## TestAssignChapterFromDivisionJoinDate

**What it tests:** The `join_date` parameter behaviour in `_assign_chapter_from_division()`. Four methods:
- `test_passes_valid_join_date` — valid past date string passed through to `assign_with_cleanup`.
- `test_rejects_future_join_date` — future date → `None` substituted.
- `test_rejects_invalid_join_date_format` — unparseable date → `None` substituted.
- `test_none_join_date_passes_through` — `None` passed through unchanged.

**Coverage in new tests:** `test_related_records_orchestrator.TestAssignChapterFromDivision` has three methods (`test_returns_error_when_division_does_not_resolve`, `test_assigns_member_to_chapter`, `test_idempotent_when_member_already_in_chapter`). NONE of them pass a `join_date` argument or assert anything about join_date handling. The validation/coercion logic for join_date is not exercised by the real-DB tests.

**Decision:** GAP-FILL

**Rationale:** join_date validation is observable business logic (the future-date rejection prevents synthetic data poisoning of Chapter Member history). It's small but non-trivial — parsing `"not-a-date"` could plausibly raise an exception rather than coerce to `None` in a regression scenario.

**If GAP-FILL:** Add to `verenigingen/tests/services/event_application/test_related_records_orchestrator.py` inside `TestAssignChapterFromDivision`. Sketch (3 new test methods, all real-DB):

```python
def test_passes_valid_past_join_date_to_chapter_member(self):
    """Past join_date is recorded on the Chapter Member row."""
    chapter = self.factory.create_chapter(mijnrood_division_id=4244)
    self.addCleanup(_cleanup_chapter, chapter.name)
    member = self.factory.create_member(...)
    self.addCleanup(_cleanup_member_and_customer, self, member.name)

    get_related_records_orchestrator()._assign_chapter_from_division(
        member.name, 4244, MagicMock(name="EVT"), join_date="2024-03-15"
    )

    cm_join = frappe.db.get_value(
        "Chapter Member",
        {"parent": chapter.name, "member": member.name},
        "chapter_join_date",
    )
    self.assertEqual(str(cm_join), "2024-03-15")

def test_rejects_future_join_date_falls_back_to_default(self):
    # ... pass join_date="2099-01-01", assert chapter_join_date is today or None ...

def test_rejects_unparseable_join_date_falls_back_to_default(self):
    # ... pass join_date="not-a-date", assert chapter_join_date is today or None ...
```

---

## TestBackfillDuesSchedule

**What it tests:** The `_backfill_dues_schedule()` method directly. Four methods:
- `test_happy_path_creates_schedule` — template resolved, `MembershipDuesSchedule.create_from_template` called with the right kwargs.
- `test_skips_when_template_resolution_returns_none` — None template → None result.
- `test_handles_template_resolution_error` — exception in template lookup → "skipped" message.
- `test_handles_create_from_template_error` — exception in schedule creation → "failed" message + `frappe.log_error` called.

**Coverage in new tests:** `test_related_records_orchestrator.TestEnsureMembershipAndDues.test_backfills_dues_schedule_when_membership_exists_without_schedule` (line 745) MOCKS the `_backfill_dues_schedule` helper out entirely:

```python
service._backfill_dues_schedule = MagicMock(
    return_value="Dues schedule DS-001 created for existing membership"
)
```

So it verifies the dispatcher routes to backfill, but doesn't exercise the helper's internals. PR #6's reviewer note that "the backfill test was mocked rather than real-DB" is confirmed.

**Decision:** GAP-FILL

**Rationale:** `_backfill_dues_schedule` contains real business logic: payment-period→template resolution via `get_dues_schedule_template_from_payment_period`, membership-type lookup, and `MembershipDuesSchedule.create_from_template` orchestration. The happy-path is a critical migration code path (existing memberships without schedules become functional). Skipping coverage here is exactly the kind of regression risk we're trying to retain.

**If GAP-FILL:** Add to `verenigingen/tests/services/event_application/test_related_records_orchestrator.py` as a new class `TestBackfillDuesSchedule`. Sketch (2 real-DB tests + 1 negative path):

```python
class TestBackfillDuesSchedule(EnhancedTestCase):
    """Real-DB coverage of _backfill_dues_schedule() — was previously
    mock-only in test_event_application_service.TestBackfillDuesSchedule."""

    def test_creates_dues_schedule_from_payment_period_template(self):
        # Create a member + active Membership without a dues schedule.
        # Ensure Verenigingen Settings has a quarterly template configured
        # (use existing factory helper or skip if not configured).
        # Call _backfill_dues_schedule(member_doc, membership_name,
        #     {"dues_rate": 12.50, "payment_period": "Per kwartaal"})
        # Assert a non-template Membership Dues Schedule row exists for
        # the member with the right rate.
        ...

    def test_returns_none_when_template_resolution_yields_none(self):
        # Pass a payment_period that doesn't map to any configured template.
        # Assert _backfill_dues_schedule returns None.
        ...

    def test_returns_failure_message_when_create_from_template_raises(self):
        # Pass row_data that triggers a validation error in create_from_template
        # (e.g., negative dues_rate). Assert returned string contains "failed".
        ...
```

For the error path test, prefer triggering a real validation error over `unittest.mock.patch(... side_effect=Exception(...))`. If a real failure can't be triggered easily, mock the `create_from_template` classmethod with a `# Mock justified: Error injection — the failure mode is documented but hard to reach with real data` comment.

---

## TestAcrDeduplication

**What it tests:** Per-run ACR (Account Creation Request) deduplication via the `_acr_queued_members` Set on the dispatcher. Five methods:
- `test_acr_set_cleared_on_apply_event` — set cleared at the start of every `apply_event` call.
- `test_skips_when_already_queued` — `_ensure_user_account` skips when member already in set.
- `test_adds_to_set_on_success` — successful queue adds member to set.
- `test_volunteer_creation_marks_acr_queued` — `_ensure_volunteer` adds member to set when creating account.
- `test_dual_acr_scenario_second_call_skipped` — volunteer-then-user-account double-call dedupes correctly.

**Coverage in new tests:** Comprehensive. Specifically:
- `test_related_records_orchestrator.TestEnsureUserAccount` (line ~510-560) has tests that assert membership add/skip semantics on `_acr_queued_members`.
- `test_related_records_orchestrator.TestEnsureUserAccountForVolunteer` (line ~580-610) covers the volunteer branch's dedup-skip behaviour.
- `test_volunteer_sync_service.test_ensure_volunteer*` (lines 250-273, 293-307) explicitly assert `orchestrator._acr_queued_members` is updated by `_ensure_volunteer` and that the second call skips.

The Set semantics (add on success, skip when present, cross-method coordination) are all covered by real-DB tests. Only the "set cleared at apply_event start" assertion has no direct equivalent — but `dispatcher.py:64` does `self._acr_queued_members.clear()` unconditionally on entry; if it regresses, every multi-event run would compound queued state and downstream tests in `test_volunteer_sync_service` would observe stale state across cases.

**Decision:** COVERED

**Rationale:** All observable behaviour is verified by 4+ real-DB tests across two new test files. The one micro-test for set clearing on entry to `apply_event` is unique to the mocked file, but the underlying invariant is structurally guaranteed by `apply_event`'s opening line and would surface as test pollution in the new suite if it regressed.

---

## TestApplyNewMemberPromotionPath

**What it tests:** The fallback path from `_apply_new_member` to `_try_promote_application` when an email-conflict is detected. Three methods:
- `test_conflict_triggers_promotion_check` — email conflict → `_try_promote_application` called, promoted result surfaced.
- `test_conflict_without_promotion_returns_error` — conflict + no promotion match → error returned.
- `test_idempotent_success_does_not_trigger_promotion` — existing-member success → no promotion attempt.

**Coverage in new tests:** `test_member_sync_service.TestApplyNewMember.test_email_conflict_invokes_promotion_fallback` (line 215) exercises the real promotion-fallback wiring: it creates a real `Member` with conflicting email, builds a real `MijnRood Sync Event`, calls `apply_new_member`, and asserts `orchestrator._try_promote_application` was called once and the success message surfaced.

The "idempotent success" case is covered by `TestApplyNewMember.test_idempotent_when_member_already_exists_by_member_id` (line 187) — it confirms no extra work happens on an existing-member match.

The "conflict without promotion returns error" case is implicitly covered by the fact that `try_promote_application` returns `None` when no Pending member matches (verified by `test_application_sync_service.TestTryPromoteApplication.test_returns_none_when_email_does_not_match_pending_member`).

**Decision:** COVERED

**Rationale:** The promotion-fallback wiring is verified by `test_email_conflict_invokes_promotion_fallback` with a real-DB conflict. The combination of that test + `TestTryPromoteApplication.test_returns_none_when_email_does_not_match_pending_member` covers all three observable paths from the old class.

---

## TestEnsureEmployeeForProfile

**What it tests:** `_ensure_employee_for_profile()` from `verenigingen.utils.user_role_profile_calculator`. Tests imported the helper at the top of each test body.

**Coverage in new tests:** N/A.

**Decision:** DEAD

**Rationale:** Verified — the test class imports `_ensure_employee_for_profile` from `verenigingen.utils.user_role_profile_calculator` inside each method. A `grep -n "_ensure_employee_for_profile" verenigingen/utils/user_role_profile_calculator.py` returns zero matches. The function it tests no longer exists. This matches the plan's note of "9 pre-existing ImportErrors". No replacement is needed — the function was removed from the codebase, so there is nothing to test.

---

## TestApplyEventDispatchesApproved

**What it tests:** One method — `test_approved_event_routes_to_apply_approved` — verifies that `apply_event(name)` with `event.event_type="Approved"` dispatches to `_apply_approved`.

**Coverage in new tests:** None for the `apply_event` → `_apply_approved` routing itself. The new tests call `get_application_sync_service().apply_approved(event, orchestrator)` directly (e.g., `test_application_sync_service.TestApplyApproved`), bypassing `apply_event`.

**Decision:** GAP-ACCEPT *(subsumed by target #8's GAP-FILL)*

**Rationale:** The Approved branch of the `apply_event` event-type if/elif chain is structurally similar to the other branches and constitutes 2 lines (`elif event.event_type == "Approved": result = self._apply_approved(event)`). If we fill target #8 (TestApprovedEventCreatesMembershipAndDues) as planned — which is an end-to-end test that calls `self.service.apply_event(event_name)` — then the apply_event-routing-to-_apply_approved coverage is transitively obtained. No separate gap-fill needed; the routing assertion is folded into target #8.

---

## TestApprovedEventCreatesMembershipAndDues

**What it tests:** End-to-end integration: an Approved `MijnRood Sync Event` against a Pending Member triggers `apply_event` → `_apply_approved` → promotion → `_ensure_membership_and_dues` → real `Membership` + `Membership Dues Schedule` creation. This is the regression test for the bug where `_try_promote_application` forgot to flip `member.status` to Active (which `_ensure_membership_and_dues` requires).

**Coverage in new tests:** Partial only. The new tests cover the promotion + membership creation pieces, but each in isolation:
- `test_application_sync_service.TestPromoteApplicationMember.test_promotes_pending_member_to_approved_and_active` (line 517) — promotes a Pending member to Approved/Active. BUT uses `_FakeOrchestrator`, whose `_create_related_records` is a `MagicMock` (see `_fixtures.py:39`). So Membership and Dues Schedule are NOT actually created in this test.
- `test_application_sync_service.TestTryPromoteApplication.test_promotes_pending_member_when_email_matches` (line 644) — same: `_FakeOrchestrator` swallows the related-records call.
- `test_related_records_orchestrator.TestEnsureMembershipAndDues` — creates Membership + Dues Schedule, but starts from an already-Active member; doesn't exercise the promotion path that flips status before downstream creation.

Nothing in the new tests bolts the promotion result to the downstream membership creation. The specific regression — "promotion doesn't flip member.status → membership creation silently doesn't happen" — would slip through the per-service unit tests.

**Decision:** GAP-FILL

**Rationale:** This is the marquee integration test that justified the entire refactor (per the docstring on the class). It binds promotion + downstream creation into one observable assertion: "applying an Approved event on a Pending member produces a Membership and a Dues Schedule." Losing it would erase the regression guard. The unit-test mocks (`_FakeOrchestrator._create_related_records`) explicitly do NOT cover this cross-cutting assertion.

**If GAP-FILL:** Move/recreate the test as-is in `verenigingen/tests/services/event_application/test_related_records_orchestrator.py` (or a new `test_apply_event_integration.py` if a separate module is preferred for the integration-test surface). The class is already real-DB style (uses `frappe.new_doc("Member")` directly + commits + cleanup). The only mock is the Customer-creation patch, which is acceptable per the existing docstring's rationale (test-env-dependent Selling Settings).

Pseudocode for the moved test (keep the existing implementation; just relocate):

```python
class TestApplyEventApprovedIntegration(EnhancedTestCase):
    """End-to-end: Approved MijnRood Sync Event → real Member promotion +
    real Membership + Dues Schedule creation. Regression guard for the
    bug where _try_promote_application forgot to flip status to Active."""

    def setUp(self):
        super().setUp()
        self.service = MijnRoodEventApplicationService()
        self._customer_patcher = patch(
            "verenigingen.services.customer_handling_service.CustomerHandlingService.create_customer_for_member",
            return_value=None,
        )
        self._customer_patcher.start()
        self.addCleanup(self._customer_patcher.stop)

    def test_approved_event_flips_status_and_creates_membership(self):
        # ... existing implementation from old file lines 3087-3145 ...
```

This test ALSO transitively covers target #7 (`TestApplyEventDispatchesApproved`) because it goes through `self.service.apply_event(event_name)`.

---

## Summary of gap-fills required (Task 2)

If Task 2 is executed, add the following tests:

1. **`test_related_records_orchestrator.py`** — within `TestAssignChapterFromDivision`, add 3 join_date tests (~50 LOC).
2. **`test_related_records_orchestrator.py`** — add a new `TestBackfillDuesSchedule` class with 3 real-DB tests (~70 LOC).
3. **`test_related_records_orchestrator.py`** (or new `test_apply_event_integration.py`) — port `TestApprovedEventCreatesMembershipAndDues` as-is (~70 LOC).

Total estimated LOC added: ~190 LOC. Versus the 3,107 LOC being deleted, this preserves coverage parity for the genuine gaps while accepting low-risk dispatcher-routing gaps where downstream tests provide transitive coverage.
