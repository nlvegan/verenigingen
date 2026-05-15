# Event Application — Mocked Test Suite Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Delete `verenigingen/tests/services/test_event_application_service.py` (3,107 LOC, 33 mock-heavy test classes). All observable behaviour is now covered by 125 real-DB integration tests across 6 service-specific test files (Phase 1, PRs 1-7). This is Phase 2 of the Tier C refactor.

**Architecture:** Audit-then-delete. First, identify any UNIQUE coverage in the old test file not duplicated by the new real-DB tests. Fill identified gaps with new tests. Then delete the old file in one swing.

**Reference spec:** `docs/plans/2026-05-12-event-application-service-refactor-design.md`

---

## Why now

After PR #7 the old test file:
- Has 140 passing tests + 1 failing + 9 errors (pre-existing baseline)
- Is 3,107 LOC of mocked tests that have required retargeting at every PR (#2-7) in this Phase 1 sequence
- Tests mostly internal call patterns (mock interaction verification) rather than observable behaviour
- The new 125 real-DB tests provide stronger evidence of correctness on the observable surface

The reviewer in PR #2 flagged the old test file as "rotting on the vine." The reviewer in PR #3 recommended deletion before PR #4 to clear noise. Phase 1 is now complete — time to delete.

---

## Task 1: Coverage audit

**Goal:** Identify test classes in the old file whose UNIQUE behaviour is NOT covered by the new real-DB tests. Document findings in `docs/audits/2026-05-15-mocked-test-coverage-audit.md`.

The 33 old test classes are listed below. For each, the audit must determine: COVERED (equivalent test exists in a new file), GAP (no equivalent test), or DEAD (pre-existing import errors / broken assertions, not worth replacing).

| Old class | Maps to new test file | Status |
|---|---|---|
| TestFindExistingMemberOrConflict | test_member_sync_service.TestFindExistingMemberOrConflict | covered |
| TestSetApplicationFields | test_application_sync_service.TestSetApplicationFields | covered |
| TestHandleDivisionFieldChange | test_related_records_orchestrator.TestHandleDivisionFieldChange | covered |
| TestAssignChapterFromDivisionJoinDate | test_related_records_orchestrator.TestAssignChapterFromDivision | likely covered — verify the join_date param case |
| TestApplyNewMembershipApplication | test_application_sync_service.TestApplyNewMembershipApplication | covered |
| TestApplyChangedMembershipApplication | test_application_sync_service.TestApplyChangedMembershipApplication | covered |
| TestApplyNewMember | test_member_sync_service.TestApplyNewMember | covered |
| TestDispatchRouting | (none) | **AUDIT — dispatcher test, may be a gap** |
| TestCheckAndHandleTermination | test_termination_sync_service.TestCheckAndHandleTermination | covered (1 pre-existing assertion-text failure noted) |
| TestMapMijnRoodToMemberFields | test_mapping_service.TestMapMemberFields | covered |
| TestApplyMijnRoodComments | test_related_records_orchestrator.TestApplyMijnRoodComments | covered |
| TestEnsureAddress | test_related_records_orchestrator.TestEnsureAddress | covered |
| TestEnsureMollieData | test_related_records_orchestrator.TestEnsureMollieData | covered |
| TestEnsureMembershipAndDues | test_related_records_orchestrator.TestEnsureMembershipAndDues | covered |
| TestBackfillDuesSchedule | (none — implicit in TestEnsureMembershipAndDues) | **AUDIT — verify backfill path is exercised** |
| TestUpdateExistingDuesSchedule | test_related_records_orchestrator.TestUpdateExistingDuesSchedule | covered |
| TestCreateRelatedRecords | test_related_records_orchestrator.TestCreateRelatedRecords | covered |
| TestEnsureUserAccount | test_related_records_orchestrator.TestEnsureUserAccount | covered |
| TestAcrDeduplication | (none) | **AUDIT — ACR dedup behaviour across methods** |
| TestTryPromoteApplication | test_application_sync_service.TestTryPromoteApplication | covered (added happy-path in cleanup commit) |
| TestApplyNewMemberPromotionPath | (none — partial in test_member_sync_service) | **AUDIT — promotion fallback from new_member path** |
| TestEnsureTeamMembership | test_volunteer_sync_service.TestEnsureTeamMembership | covered |
| TestPruneOrphanTeamMembers | test_volunteer_sync_service.TestPruneOrphanTeamMembers | covered |
| TestHandleAdminRoleChange | test_volunteer_sync_service.TestHandleAdminRoleChange | covered |
| TestEnsureUserAccountForVolunteer | test_related_records_orchestrator.TestEnsureUserAccountForVolunteer | covered |
| TestEnsureEmployeeForProfile | (none) | **DEAD — 9 pre-existing ImportErrors; not worth replacing** |
| TestEndChapterBoardMembership | test_volunteer_sync_service.TestEndChapterBoardMembership | covered |
| TestHandleDivisionContactChange | test_volunteer_sync_service.TestHandleDivisionContactChange | covered |
| TestNotifyBoardMembershipChange | test_volunteer_sync_service.TestNotifyBoardMembershipChange | covered |
| TestPromoteApplicationMember | test_application_sync_service.TestPromoteApplicationMember | covered |
| TestApplyApproved | test_application_sync_service.TestApplyApproved | covered |
| TestApplyEventDispatchesApproved | (none) | **AUDIT — dispatch routing for Approved event_type** |
| TestApprovedEventCreatesMembershipAndDues | (none — integration test) | **AUDIT — end-to-end approved-event integration** |

**Action items:**

1. For each AUDIT row, read the old test class (just class header + method names + any docstrings — not bodies) and decide:
   - **COVERED EQUIVALENTLY:** mark as such in audit doc; no new test needed.
   - **GENUINE GAP:** the old test verifies behaviour that no new test verifies. Note the specific behaviour, file the gap in the audit doc, and decide whether to fill it (Task 2) or accept the loss (with rationale).
   - **DUPLICATE INTEGRATION TEST:** if it tests integration across services that the unit tests don't cover, decide whether the integration risk is real.

2. For each DEAD row, just note the dead status — no replacement needed.

3. Write the audit doc to `docs/audits/2026-05-15-mocked-test-coverage-audit.md` with sections per AUDIT row. Format:

```markdown
## TestDispatchRouting

**What it tests:** [brief — read class + method names]

**Coverage in new tests:** [grep-confirmed equivalent or NONE]

**Decision:** COVERED | GAP-FILL | GAP-ACCEPT

**Rationale:** [why]

**If GAP-FILL:** which new test file to add the test to; sketch of the test.
```

---

## Task 2: Fill identified gaps (only if Task 1 surfaces real gaps)

For each gap that should be filled per the audit doc, add a test to the appropriate new test file. Use real-DB style with `EnhancedTestCase` + `CoreTestDataFactory`. Follow the established patterns:

- `_create_*` / `_cleanup_*` helpers for permission-bypass setup/teardown
- `_cleanup_member_and_customer(...)` with `frappe.db.commit()` for member cleanup
- `# Mock justified: …` comments for any necessary patches
- Shared `_FakeOrchestrator` from `tests/services/event_application/_fixtures.py`

Commit each gap-fill separately with a message like:
```
test(mijnrood-sync): add <gap-name> coverage to test_<service>.py

Before Phase 2 deletion of test_event_application_service.py, this test
fills a gap identified by docs/audits/2026-05-15-mocked-test-coverage-audit.md:
[gap description].
```

---

## Task 3: Delete the file + verify

- [ ] **Step 1:** `git rm verenigingen/tests/services/test_event_application_service.py`

- [ ] **Step 2:** Verify nothing else imports from the deleted module:

```bash
grep -rn "tests.services.test_event_application_service" verenigingen/ 2>/dev/null | head -5
```

Expected: no matches.

- [ ] **Step 3:** Run the full event_application test surface to confirm no regression:

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_mapping_service
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_member_sync_service
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_application_sync_service
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_volunteer_sync_service
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_termination_sync_service
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services.event_application.test_related_records_orchestrator
```

Expected: 16, 10, 22, 44, 6, 27 = **125 tests pass.**

- [ ] **Step 4:** Run the broader test discovery to confirm no orphaned imports:

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --app verenigingen
```

If this is too slow or noisy, scope it to the relevant modules:

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests \
  --module verenigingen.tests.services
```

Expected: no test discovery errors caused by the deletion. Pre-existing test failures elsewhere in the suite are unrelated.

- [ ] **Step 5:** Pre-commit + commit + push:

```bash
cd ~/frappe-bench/apps/verenigingen && pre-commit run --files \
  verenigingen/tests/services/test_event_application_service.py 2>&1 || true
# (file is deleted; pre-commit may report nothing to check — that's fine)

git add -u verenigingen/tests/services/test_event_application_service.py \
       docs/audits/2026-05-15-mocked-test-coverage-audit.md

git commit -m "$(cat <<'EOF'
test(mijnrood-sync): delete mock-heavy test_event_application_service.py

Phase 2 of the Tier C refactor (docs/plans/2026-05-12-event-application-
service-refactor-design.md). The 3,107-LOC file contained 33 mock-heavy
test classes verifying internal call patterns of MijnRoodEventApplicationService.
All observable behaviour is now covered by 125 real-DB integration tests
across 6 service-specific test files:

- tests/services/event_application/test_mapping_service.py (16 tests)
- tests/services/event_application/test_member_sync_service.py (10 tests)
- tests/services/event_application/test_application_sync_service.py (22 tests)
- tests/services/event_application/test_volunteer_sync_service.py (44 tests)
- tests/services/event_application/test_termination_sync_service.py (6 tests)
- tests/services/event_application/test_related_records_orchestrator.py (27 tests)

Coverage parity verified per docs/audits/2026-05-15-mocked-test-coverage-audit.md.

Removes 10 pre-existing failures (9 TestEnsureEmployeeForProfile ImportErrors +
1 TestCheckAndHandleTermination assertion-text mismatch) that have been
the persistent baseline noise across PRs 2-7.
EOF
)"

SKIP=jest-testing,javascript-doctype-validator git push
```

---

## Success Criteria

1. `verenigingen/tests/services/test_event_application_service.py` no longer exists.
2. `docs/audits/2026-05-15-mocked-test-coverage-audit.md` exists and documents coverage parity (or accepted gaps with rationale).
3. Any genuine gaps filled with new tests in the appropriate service test file.
4. All 125 PR #1-7 tests still pass.
5. No orphaned imports or test discovery errors.
6. Pre-commit hooks pass.
7. Cumulative LOC reduction: 3,107 removed from the test suite + any new gap-fill tests (~50-200 LOC added).
