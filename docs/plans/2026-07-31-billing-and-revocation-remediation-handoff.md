# Handoff: billing coverage + revocation remediation

Date: 2026-07-31
Follows `2026-07-31-in-import-fallout-handoff-v2.md`, which is now partly superseded — §4a and
§4.1/§4.2 of that document are closed. Everything else in it still stands, including the ~213
outstanding test fixes on `test/harness-production-fidelity`.

---

## 0. State in one table

| Branch | HEAD | State |
|---|---|---|
| `fix/coverage-period-boundary` | `4ae7e973` | ✅ **MERGED** as `6089d372` (PR #212, 41 checks green) |
| `fix/mollie-settlement-reconciliation-status` | `78f0e32b` | Pushed, **no PR**. 5 behind develop, no conflicts |
| `fix/mijnrood-role-revocation` | `cd6c5be6` | Pushed, **no PR**. 5 behind develop, no conflicts |
| `fix/board-profile-withdrawal-deferral` | `9609f08e` | Pushed, **no PR**. 5 behind develop, no conflicts |
| `test/role-profile-recalculation-coverage` | `21ad380a` | **Local only, not pushed.** Off the merged `develop` |
| `refactor/retire-security-wrappers` | — | PR #193 still open, independent |
| `fix/retire-dead-membership-billing-patch` | `4f124f32` | Still ready, still unmerged |
| `test/harness-production-fidelity` | `c674d17e` | Still blocked on ~213 test fixes |

**17 open issues, #194–#211.** All filed from this work. Each carries the mechanism, `file:line`,
whether it has actually fired in production, and a suggested fix.

---

## 1. What merged, and why it mattered

PR #212 fixes the bug `develop` was failing on. The 2026-07-31 `develop` baseline failed 20 tests
across 5 modules, **all the same bug** — worth re-reading §2 of the previous handoff before
interpreting any future baseline, because `known_test_failures.txt` is empty and a run on a
non-month-end day is green for the wrong reason.

Four commits:

1. `2c544cf2` — the first coverage period runs a full billing period from the join date, not the
   surrounding calendar period.
2. `176a41dc` — duplicate detection and payment→invoice matching anchored on the member's own
   periods.
3. `261d0441` — `EligibilityChecker.check_schedule_timing()` **deleted**; coverage-end-vs-cutoff is
   the single rule for *when* to invoice.
4. `4ae7e973` — consolidation after the second review round.

### The design decision worth carrying forward

Eligibility now decides only **whether** a member is billable. **When** is decided solely by
`should_generate_invoice_for_cutoff()` comparing the member's latest coverage end against the cutoff
from `billing_cutoff_frequency`.

`check_schedule_timing` was removed because it duplicated that comparison and disagreed with it:
`next_invoice_date` is derived from the **posting** date (`billing_date_service.py:104`), so it
drifts a period backwards on every early generation. The field is demonstrably unreliable — on veg11
**431 schedules carry a `next_invoice_date` 83 days later than their coverage actually lapsed**, and
those members are billed only because a different branch short-circuits before the arithmetic runs.

`billing_cutoff_frequency` is now `Monthly` on veg11 and test_site_1, matching the monthly bank
upload cadence. **Keep it no coarser than the shortest billing frequency in use.** A coarser cutoff
asks for a Monthly member to be covered through quarter end — three periods — delivered one per run.
`should_generate_invoice_for_cutoff` caps at one period ahead of today to bound that, but the cap is
a backstop, not the design.

### Two regressions the fixes themselves introduced

Both found by the second review round, both fixed in `4ae7e973`. Recorded because the *shape*
recurs:

- **An inverted rationale.** The resolver was widened to `docstatus < 2` "to match the consumers'
  overlap detectors". Backwards: the detectors already match drafts, so widening guaranteed
  `exact_match`, and a draft's `outstanding_amount` of 0 reads as "already paid" — the Mollie
  callers' cue to create *another* invoice. Reverted; the real defect is filed as #209.
- **A bound removed with nothing replacing it.** Deleting `check_schedule_timing` left the
  eligibility snapshot as the only cutoff evaluation, and `_process_parallel` releases the
  generation lock once chunks are enqueued. `process_invoice_chunk` was *receiving* `cutoff_date`
  and ignoring it. Both processing modes now re-check at execution time.

---

## 2. The three unmerged branches

All three are pushed, none conflicts with the new `develop`, none has a PR.

**Open them one at a time.** Every workflow except `pylint.yml` is gated on
`branches: [main, develop]` for both `push` and `pull_request`, so a feature-branch push runs pylint
alone — a PR against `develop` is the only way to get real signal (`server-tests.yml` also carries
`workflow_dispatch`).

### `fix/mollie-settlement-reconciliation-status` — 3 commits

Fixes handoff-v2 §4.1: the settlement branch set a Select value that was not among the field's
options, so `save()` threw **after** `process_mollie_settlement()` had already submitted every
Payment Entry — leaving the bank transaction permanently unreconciled with no reason recorded.

Then, from two review rounds:

- `frappe.log_error(title, message)` takes **title first** and uses the second argument *as* the
  traceback. The original fix passed them the other way round and destroyed the stack. Now routed
  through `_log_error_with_traceback` with a guaranteed single-line title.
- A failed settlement stays `Pending` (retryable) when nothing was posted, and goes `Unreconciled`
  when accounting exists. The discriminator queries a submitted Payment Entry *or* fee Journal Entry
  carrying the settlement id — not `settlement_result is None`, which is wrong because Payment
  Entries are submitted before the fee JE is booked.
- **Settlement-level idempotency**, which is what makes the retryability safe: without it, a
  permanently-failing settlement re-booked a Journal Entry for the *entire payout* on every run.
- `MAX_SETTLEMENT_RETRIES = 3`, escalating to `Unreconciled` with a "giving up" reason.
- A settlement that cannot submit what it inserts is now **refused up front** rather than leaving
  invisible drafts (#210).

**Deploy: needs a fixture sync** — `custom_processing_status` options *and* a new
`custom_mollie_settlement_id` on Journal Entry. Only test_site_2 has them. Without the sync the
original incident reproduces exactly.

**Pre-deploy check:** sweep for `Payment Entry` with `custom_mollie_settlement_id` set and
`docstatus: 0`. Post-fix those settlements refuse with a comment naming the documents; someone must
decide per settlement whether to submit or delete.

### `fix/mijnrood-role-revocation` — 4 commits

Fixes handoff-v2 §4.2 (`status = "Ended"`, never a valid option) and issue #195.

The durable lesson: **the row edit is not what withdraws access — the recalculation is, and it
cannot raise.** `team_role_profile_hooks.py:143-148` and `auto_sync_on_role_change`
(`user_role_profile_calculator.py:1006`) both swallow. So `_assert_team_profile_withdrawn` and
`_assert_board_access_withdrawn` re-run the sync *in the service frame*, where the result is
observable, and raise if access survives. Access surviving a **successful** recalculation is
deliberately not an error — it was granted elsewhere and was never this path's to withdraw.

Also: the retained-access warning is gated on **observed** state (`frappe.get_roles`,
`get_user_role_profiles`) rather than config, because a config-derived message told operators to
manually revoke access the sync had correctly removed — over-revocation-by-human on a security path.
Warnings are now persisted to `error_message` and surfaced as an orange msgprint; previously the
message reached nothing but a log file.

**Deploy: needs `reload-doctype`** for the `error_message` relabel.

### `fix/board-profile-withdrawal-deferral` — 1 commit, off `develop`

Fixes #211, found while fixing #195: **board removal never withdrew the role profile, on any path.**

`handle_board_member_deletions` recalculated inside `validate()`, but the calculator reads
`Chapter Board Member` from the **database**, where the seat is still `is_active=1` because the child
rows have not been written. The additions path was given a deferred flush from `on_update` for
exactly this reason (`chapter.py:169`, docstring says so); deletions never were.

`remove_board_member_role()` was *not* no-opping on its decision — its effect was erased.
`frappe/core/doctype/user/user.py:264` `populate_role_profile_roles()` runs in the same `validate()`
and rebuilds `roles` from the stale profile. **Order is load-bearing: profile first, then role
withdrawal.**

A second stale read fell out: two seats for one volunteer removed in a single save each excluded
only themselves, saw the other active, and neither withdrew.

**Deploy: restart only.** No migration, no `reload-doctype`.

**Historical leaks are not repaired by the fix — but on veg11 there are none.** An earlier draft of
this handoff said to sweep them with `bulk_recalculate_role_profiles()`. **Do not follow that
advice without reading §2a first** — the sweep does something much larger than a board cleanup, and
on veg11 there is nothing to clean:

```
Users holding Verenigingen Chapter Board Member : 0
Active Chapter Board Member seats               : 1
```

The anomaly on veg11 is the **inverse** of the one this branch fixes: a seated board member who
never received the grant. That is the additions-path gap the fix explicitly leaves out of scope —
seating a board member inline while *creating* a chapter never enqueues, because
`_handle_document_changes` is gated on `if old_doc:`.

`Verenigingen Chapter Board Member` is still the profile behind the org-wide `Projects Manager`
escalation fixed in PR #191, so a stale grant matters wherever one exists. Check for holders on a
given site before assuming a sweep is needed.

---

## 2a. `bulk_recalculate_role_profiles` — read before running it anywhere

It is **not** a targeted cleanup tool. Run with `dry_run=True` (the default) it is safe and
informative; run without, on veg11 today, it would perform a **mass privilege withdrawal**.

Dry-run result on veg11, 2026-07-31:

```
total: 564   changed: 438   unchanged: 0   errors: 126
```

Every change is the same transition, `Verenigingen Volunteer → Verenigingen Member`, and that is a
permission change rather than a relabel:

```
Verenigingen Volunteer confers : Employee, Employee Self Service, Projects User,
                                 Verenigingen Member, Verenigingen Volunteer
Verenigingen Member confers    : All, Verenigingen Member
Withdrawn by the downgrade     : Employee, Employee Self Service, Projects User,
                                 Verenigingen Volunteer
```

**Why it proposes that.** `is_active_volunteer` requires `Volunteer.status in ("Active",
"Onboarding")`. veg11 has 564 users holding the Volunteer profile and **7** Volunteer records — all
`New`, none carrying an email to link to a User. So the calculator concludes none of them is an
active volunteer. It is doing exactly what it is designed to do, against data where the Volunteer
records do not back the profiles.

**The owner has confirmed that gap is expected on this site** (staging, imported without volunteer
data). The conclusion is therefore *not* "the profiles are wrong" — it is that **a dry run on
staging tells you nothing about what the sweep would do on production**, because the answer is
entirely a function of whether Volunteer records are populated there.

The 126 errors are `User is not a member` — a Verenigingen profile with no Member record. Those are
skipped and mutate nothing, so they keep whatever they hold.

`test/role-profile-recalculation-coverage` (`21ad380a`) makes all of the above assertable from the
suite instead of by manual probe: that the downgrade withdraws four named roles (derived from the
Role Profile documents at runtime, so it cannot go stale), that holding the profile with no
Volunteer record at all is acted on, and that the not-a-member path is skipped rather than silently
downgraded.

Note the tool was already better tested than first assumed — `test_bulk_recalculate_dry_run_targeted_filter`
already pinned that `dry_run` applies nothing, and `is_active_volunteer` was covered across every
status. The gap was interpretation, not safety.

---

## 3. Backlog, ranked

Financial and access-control first, then live-but-contained, then design.

| # | Issue | Live today? |
|---|---|---|
| 196 | `bench export-fixtures` drops **57 of 62** Custom Fields — three unprefixed entries clobber one file, three more covered by none | yes, on every export |
| 197 | Bulk payment checker discards its audit row; the `CRITICAL` alarm is dead code | yes |
| 198 | `setup_default_payment_mappings` has never created a mapping | yes |
| 199 | Bulk Edit Account Mappings no-ops behind a green toast | yes |
| 200 | `Volunteer Skill.proficiency_level` default is not one of its options | yes |
| 201 | Every skill from the web application form is lost | yes |
| 202 | Payment Plan silently becomes Weekly | yes |
| 206 | Application-approval invoice covers 366 days | yes |
| 209 | Mollie callers treat a draft's zero outstanding as "already paid" | latent |
| 203 | Mollie audit logger writes a non-existent `event_category` | latent |
| 204 | `sepa_batch_processor` prefilter hardcodes 30 days | low |
| 205 | Six frequency-blind billing constants | design, matters once prod is Monthly-heavy |
| 207 | Coverage report clips to book year while invoices span two | decision |
| 208 | MijnRood revocation does not withdraw `verenigingen_role`/`role_profile` | latent |

#194, #195, #210, #211 are fixed on the branches above and close when those merge.

**#202 warning:** two existing tests assert the buggy behaviour and will go red when it is fixed.
They pass only because the harness sets `frappe.flags.in_import`.

---

## 4. Method notes that earned their keep

**Adversarial review found what tests did not, twice.** Round one caught a Monthly billing block
that 294 green tests missed — the entire suite stopped at the first invoice. Round two caught three
regressions introduced by the round-one fixes. Both rounds were worth their cost; a third would not
have been, which is why the branches went to a single consolidation pass instead.

**Verify RED by disabling only the one thing the test targets.** Every fix here was confirmed that
way, and it repeatedly exposed non-discriminating tests — including several written in this session,
where the assertion would also have passed via an unrelated code path.

**Assert the outcome, not the row.** A revocation test that checks `row.status == "Completed"` proves
nothing; the access is withdrawn by a recalculation that can silently fail. Assert the effective role
profile against the **whole** `get_user_role_profiles()` list (never `profiles[0]` — unordered), and
assert the baseline *before* the change so a vacuous pass is impossible.

**Existing tests may encode the bug.** Found three: `status == "Ended"`, the
`"Mollie Settlement Processed"` round-trip, and the two Payment Plan guards. All green only because
`EnhancedTestCase` sets `in_import`. A red test after this kind of fix is not automatically a
regression.

**Check whether the scheduler actually runs before sizing a scheduled-job bug.** `veg11` has
`enable_scheduler = 0` and last executed 2026-05-22, which is why several findings are latent there
and real in production. It also means **nothing has generated invoices for Q3** — the 440 quarterly
members' coverage lapsed 30 June.

**Look for the gate in front of the gate.** Reasoning about `EligibilityChecker` alone produced a
confident wrong answer about runaway generation; `should_generate_for_cutoff_period` runs first.

**`bench` executes the main tree**, not a worktree, unless you prepend `PYTHONPATH=<worktree>`.
Verify with a load-path probe every time.

**On v16, setting `User.role_profile_name` alone is a no-op.** `move_role_profile_name_to_role_profiles`
discards it when the `role_profiles` child table is empty, so the canonical store is the child table
(`user_role_profile_calculator.py:855-864` writes both, guarded by `_has_multi_profile_support()`).
A test fixture that attaches a profile via the Link field silently tests nothing — that happened
while writing `21ad380a` and was caught only because the helper asserts the attach took. Read
profiles back through `get_user_role_profiles()`, never `profiles[0]` of an unordered `get_all`.

**`ignore_permissions=True` in a test is almost always the wrong reflex** — fixtures already run as
Administrator, and `test-quality-enforcer` blocks it outside setup/teardown/factory methods. It came
up twice in this work; both times removing it was correct and nothing else had to change.

---

## 5. Open questions for the owner

1. **#207** — should the coverage-analysis report keep clipping to book-year boundaries, now that
   schedule invoices routinely span two?
2. **#205** — per-frequency defaults for `invoice_days_before` / `default_due_date_days`, or leave
   the day-valued knobs and only enforce `lead < period length`? Relevant once production is
   Monthly-heavy; the due date is informational, so it does not need to scale.
3. **#208** — revocation semantics for `verenigingen_role` / `role_profile` when `add_to_team` is
   off. Undoing them correctly needs grant provenance the system does not record.
4. Whether `bulk_remove_board_members`' outer `except Exception` should stop flattening deadlocks
   into `{"success": False}` — shared with three sibling operations, so it is a BoardManager-wide
   decision.
5. Whether the 564-vs-7 Volunteer-profile gap (§2a) also exists on production. On veg11 it is
   expected staging data, so the dry run there says nothing about what the sweep would do live. If
   production has Active Volunteer records for those users, the sweep is close to a no-op; if it
   does not, it withdraws `Employee`, `Employee Self Service` and `Projects User` from several
   hundred people. Run `bulk_recalculate_role_profiles(dry_run=True)` there and read the transitions
   before deciding.
6. The seated-but-ungranted board member on veg11 (1 active seat, 0 profile holders) — worth
   confirming whether that is the chapter-creation additions gap or simply a volunteer with no user.
