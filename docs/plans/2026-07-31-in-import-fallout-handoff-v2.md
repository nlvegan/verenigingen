# Handoff: `in_import` harness removal — investigation complete, remediation outstanding

Date: 2026-07-31
Supersedes `2026-07-31-in-import-harness-fallout-handoff.md` (§2 taxonomy) and extends
`2026-07-31-in-import-fallout-root-cause-analysis.md`.

**Status: the investigation is finished. All 236 CI failures are root-caused.**

**SUPERSEDED IN PART — see `2026-07-31-billing-and-revocation-remediation-handoff.md`.**
§4a (B1/B2/B3), §4.1 and §4.2 are closed. §4a's fixes merged to `develop` as `6089d372`
(PR #212). §4.1 and §4.2 are fixed on branches that are pushed but not yet PR'd. Everything
else below still stands, including the ~213 outstanding test fixes in §5-§7.

**Update 2026-07-31 (later session): the coverage fix is unblocked and two of the production bugs
are fixed.** B1 and B2 are resolved, B3 is decided, and §4.1 and §4.2 have landed on their own
branches. What remains is the harness branch's ~213 test fixes (§5-§7) and the nine unfiled
production bugs. Changed sections are marked ✅ **FIXED** inline; nothing in the diagnosis has been
retracted.

---

## 0. What this exercise actually found

Removing `frappe.flags.in_import` from `EnhancedTestCase.setUp` was expected to be a test-harness
fidelity change. It turned into a production-bug discovery mechanism. **Eleven production defects
were found and confirmed by runtime probe**, two of them affecting money and one affecting access
control. The harness had been suppressing the framework validation that would have caught all of
them, in some cases for years.

Every finding below was confirmed by a direct probe (`frappe.flags.in_import` set explicitly, the
write or call performed, a known-good control alongside, then rolled back) — not by reading code
alone. Where a claim rests on reasoning rather than execution, it says so.

---

## 1. Branch and PR state

| Branch | Commit | State |
|---|---|---|
| `refactor/retire-security-wrappers` | — | **PR #193 open**, independent, green |
| `fix/coverage-period-boundary` | `84ab5ee8` | **Unblocked.** B1 and B2 fixed, B3 decided — see §4a. **10 commits behind `origin/develop`; rebase before opening a PR** |
| `fix/mollie-settlement-reconciliation-status` | `4db12397` | Ready. Fixes §4.1. On current `origin/develop`. **Needs a fixture re-sync to deploy** |
| `fix/mijnrood-role-revocation` | `163d9744` | Ready. Fixes §4.2. On current `origin/develop` |
| `fix/retire-dead-membership-billing-patch` | `4f124f32` | Ready. Retires a dead, self-defeating patch |
| `test/harness-production-fidelity` | `c674d17e` | **Blocked.** The harness change itself + ~213 test fixes outstanding |
| `test/coverage-sweep-agent-suites` | `f57e1e86` | Dead branch (PR #192 merged). Do not PR from it |

**No PR is open for the four ready branches, so almost no CI is running on them.** Every workflow
except `pylint.yml` (`on: [push, pull_request]`) is gated on `branches: [main, develop]`, for both
`push` and `pull_request` — a feature-branch push therefore runs pylint alone. `server-tests.yml`
does carry `workflow_dispatch`, which is how the §2 baseline was run; use that to get real signal
without opening a PR.

---

## 2. The decisive experiment: a `develop` baseline on a month-end day

CI run **30583855229** — `server-tests.yml` dispatched on **`develop`**, 2026-07-31, no harness
change. The previous session never had this control, and without it harness-caused and
calendar-caused failures are indistinguishable (`known_test_failures.txt` is empty, so the CI gate
reports *everything* as new).

**Result: `develop` fails 20 tests today, and all 20 are the coverage-period bug** — 5 modules,
nothing else. That cleanly separates the two populations:

- **20 failures = pre-existing**, calendar-triggered, fixed by `05656257`. Out of scope for the
  harness PR.
- **The remaining ~213 = genuinely caused by the harness change.**

Re-run this baseline before trusting any future comparison; a run on a non-month-end day will be
green on `develop` and will mislead you.

---

## 3. Corrections to the previous handoff

1. **The count is 236, not 169.** The previous session hit the very log-grep trap it documented.
   The runner emits `\x1b[41m ERROR \x1b[0m test_name (path)`. Anchor on
   `^\s*(ERROR|FAIL)\s+(test_\S+)\s+\(` after stripping ANSI and timestamps.
2. **The `posting_date` fix was reported as complete; it covers 45 of 65.** See §5 RC1.
3. **`bench` executes the main tree** (`apps/verenigingen/verenigingen`) regardless of which
   branch a git worktree has checked out. A test run from a worktree silently exercises the main
   tree's code unless you prepend `PYTHONPATH=<worktree>`. Two investigators were nearly misled by
   this; one had already defended against it. **Always verify with a load-path probe**
   (`print(module.__file__)`) before trusting a worktree test result.

---

## 4. Production bugs found (11)

Ranked by severity. None of these is caused by the harness change — the harness was *hiding* them.

### 4.1 Mollie settlement reconciliation posts entries, then reports failure — FINANCIAL — ✅ **FIXED in `4db12397`**

`verenigingen_payments/utils/bank_transaction_reconciliation.py:592` sets
`custom_processing_status = "Mollie Settlement Processed"`, which is not among the custom field's
options (`fixtures/custom_field.json:1637`). The save at `:606` throws — **after**
`process_mollie_settlement()` has already created and submitted the Payment Entries and fee
entries. Caught at `:610`, returns `False`. Unlike every sibling branch it never calls
`_mark_transaction_unreconciled`, so no comment or reason is recorded.

Net: **every Mollie settlement auto-reconciliation posts its accounting and then leaves the bank
transaction permanently unreconciled**, with only a bare `log_error` line. Re-runs are blocked from
double-posting by `_is_mollie_payment_processed`, so the transaction can never clear.

*Fixed as:* `Mollie Settlement Processed` added to the fixture options — **not** an existing option.
Reusing `Fully Reconciled` would have corrupted a live reader:
`templates/pages/sepa_reconciliation_dashboard.html:243` counts that exact value as "auto-matched",
so every Mollie settlement would have been miscounted in the SEPA dashboard. Every reader was
grepped first; none dispatches on the value, so adding one is additive-safe. Both `except` handlers
now call `_mark_transaction_unreconciled` with the real reason, matching the sibling branches.

**Deploy requirement: the Select options live in per-site `Custom Field` rows, so this needs
`bench --site <site> migrate` (which runs `sync_fixtures`) or an explicit
`sync_fixtures("verenigingen")`. Without it the field still rejects the value.** Fresh installs
(CI) pick it up automatically. No schema change, no backfill.

*Line drift found while fixing:* the write is at `:592` as stated, but the `save()` is at `:607`
(not `:606`), the `except` at `:611` (not `:610`), and the fixture options at
`custom_field.json:1636` (not `:1637`).

**Still open on this path — deliberately not fixed:** it remains non-atomic. Payment Entries and the
fee Journal Entry are inserted and *submitted* before anything downstream can fail, so an operator
now sees a recorded "Unreconciled" on a deposit whose accounting already exists. Worse,
`_is_mollie_payment_processed` (`:1187`) blocks a re-run from re-posting, so a retry after a
*partial* failure silently skips the already-booked payments. The real fix is a savepoint around the
branch, or deferring the submit until after the Bank Transaction save. Separately,
`_mark_transaction_unreconciled` swallows its own failures (`:643-647`, bare `except` → `log_error`),
so if that save also throws the reason is lost again — shared by all branches.

### 4.2 MijnRood role revocation never removes the volunteer from the team — ACCESS CONTROL — ✅ **FIXED in `163d9744`**

`mijnrood_sync/services/event_application/volunteer_sync_service.py:577` sets
`row.status = "Ended"`; `Team Member.status` allows only `Active/Inactive/Completed/On Leave`, and
`git log -S` confirms "Ended" was never valid. The `except` at `:594-602` converts the throw into a
string that `_apply_role_actions` (`:679-681`) merely appends to a message list, then
unconditionally reports `"ROLE_ADMIN removed from member {0}"`. Nothing raises.

Net: when ROLE_ADMIN is revoked upstream, the Team Member row stays `status=Active, is_active=1`,
`to_date` is never set, and the `on_team_members_change` role-profile recalculation never runs —
**the user keeps the team-derived role profile after their role was revoked.** Compare the
`Projects Manager` escalation already on record.

*Fixed as:* `"Completed"` (`is_active=0` / `to_date` were already correct), and the `except` now
re-raises instead of stringifying, with a `NON_RESUMABLE_DB_ERRORS: raise` clause ahead of it so a
deadlock skips the `log_error()` write.

**Which layer to raise from — the answer, since this is the repo's known wrong-layer trap.** All six
frames from `_end_team_membership` up to `apply_event` were traced and **none of them catch**; they
accumulate strings, and `member_sync_service.apply_changed_member:230-233` returns a hardcoded
`{"success": True}`. A return value signalling failure is therefore dead code by construction. The
only frame that inspects an exception is `apply_event`'s `except` (`dispatcher.py:89-100`), which
records `error_message` and leaves `event.status` at `Approved` rather than `Applied`. Raising from
`_end_team_membership` is the lowest point that reaches it.

*Verification standard used:* the tests assert the User's **effective role profile**
(`get_user_role_profiles()`), not `row.status` — asserting the `Verenigingen Staff` baseline first so
a vacuous pass is impossible — because the row edit is not what withdraws access;
`on_team_members_change` is. Failure is injected with real DB state (a dangling `Team.chapter` link)
rather than a mock.

*No data migration needed:* `SELECT status, COUNT(*) FROM "tabTeam Member"` on veg11 returns zero
rows for the invalid value, and none could ever have persisted since the save always threw.

**Two follow-ups this created or exposed, deliberately not fixed:**
- **Availability regression.** `_end_team_membership` does not prune orphan `team_member` rows the
  way `_ensure_team_membership:499` does. One dangling volunteer reference now blocks the whole Team
  save, so a revocation can hard-fail on data unrelated to the member being revoked. Loud beats
  silent for a privilege revocation, but corrupt team data will surface this.
- **`_end_chapter_board_membership` is the same revocation shape and is still log-and-stringify** —
  a `bulk_remove_board_members` failure becomes a message that `_handle_division_contact_change:717`
  appends and reports as success. The obvious next target. The grant-side `_ensure_*` helpers share
  the pattern but fail safe.

### 4.3 First coverage period was calendar-anchored — FINANCIAL — **FIXED in `05656257`**

Two defects in one. A member joining on the last day of their billing period produced
`coverage_start == coverage_end`, which the guard rejected; `calculate_next_coverage_period`
`frappe.throw()`s it, so invoice generation aborted, and since
`invoice_error_handler_service.py:434` does not match that message against any manual-review
pattern, after three failures the schedule was **silently auto-advanced and the period never
billed**. 12 join-dates a year on Monthly, 4 on Quarterly, Dec 31 on Annual.

Less visibly, **every** mid-period joiner got a short first period, charged at the full
`dues_rate` — nothing in the pipeline prorates (`invoice_generator.py:726` always uses `qty=1`).

*Decision taken:* the first period now runs a full billing period from the join date, matching
`Membership.set_renewal_date`, `enforce_minimum_period`, the sequential branch, and `billing_day`.
The absence of proration anywhere is itself the evidence that periods were meant to be full length.

---

## 4a. Blockers on the coverage fix (`6d0e990d`) — ✅ **ALL THREE RESOLVED in `84ab5ee8`**

The fix is correct in direction and was approved at the policy level (running year, not calendar
year). Three items were raised by skeptical review, the first two blocking. All three are now
addressed; the diagnoses below stand as written, with the resolution appended to each.

### 🚨 B1. Monthly billing regresses to in-arrears with a ~4-week block every month — ✅ **FIXED**

`verenigingen/verenigingen/doctype/membership_dues_schedule/membership_dues_schedule.py:384-390`
special-cases Monthly:

```python
if self.billing_frequency == "Monthly":
    proposed_coverage_start, proposed_coverage_end = self.calculate_current_billing_period()
else:
    proposed_coverage_start, proposed_coverage_end = self.calculate_next_coverage_period()
```

`calculate_current_billing_period()` is the **calendar month containing today**. Once coverage is
anniversary-aligned it straddles two calendar months, so that probe permanently overlaps the
member's own latest invoice via `DuplicateInvoiceDetector` (inclusive on both ends), and
`EligibilityChecker.check_for_duplicates` blocks generation. Simulated against the real functions:

```
Monthly join 2026-06-03   OLD                     NEW
  posted 06-03  coverage 06-03..06-30    posted 06-03  coverage 06-03..07-02
  posted 07-01  coverage 07-01..07-31    posted 08-01  coverage 07-03..08-02   <-- 29 days late
  posted 08-01  coverage 08-01..08-31    posted 09-01  coverage 08-03..09-02
```

A member joining 3 June is billed for 3 July–2 Aug on **1 August** — 96% of the service period has
elapsed before the invoice, and therefore the SEPA collection, exists. Steady state, not transient.
It does not hard-fail (the orchestrator matches `"coverage overlap"` and logs at `info`), which is
exactly why the suite stayed green. During the blocked window the schedule is retried daily and
the Coverage Analysis report shows these members as gapped.

Only Monthly is affected; every other frequency takes the `else` branch. veg11 has **zero** Monthly
instance schedules today but **10 Monthly templates and 20 Monthly membership types**, so one
signup arms it.

*Fixed as:* the Monthly special-case is dropped; all frequencies now probe the sequential proposal.
`calculate_current_billing_period()` had no other caller (grepped `.py`/`.js`/`.json`) and was
removed rather than left as a calendar-shaped trap. The RED test is
`TestMonthlyDuplicateProbe.test_second_monthly_period_is_not_blocked_by_the_surrounding_calendar_month`
in `test_membership_dues_schedule.py`, and it failed with exactly the predicted probe
(`2026-07-01 to 2026-07-31` against the member's own `2026-06-03..07-02` invoice).

**Read this before doubting the fix.** Dropping the special-case *looks* like it should cause
runaway generation, and one session lost time re-deriving that: `check_schedule_timing` allows
generation once `today >= next_invoice_date - invoice_days_before`, `invoice_days_before` defaults
to 30 (`template_creation_service.py:102` sets it explicitly, so it is rarely None),
`update_schedule_dates` computes `next_invoice_date` from the **posting date** rather than the
coverage end for every frequency except Daily (`billing_date_service.py:85-106`, whose comment
already names this as a drift hazard), and the sequential proposal never overlaps the member's own
latest invoice by construction. For Monthly that arithmetic really does authorise a new invoice the
day after the last one — but **it never gets that far**:
`BulkInvoiceGenerationService` calls `should_generate_for_cutoff_period(cutoff_date)` at `:326`
*before* `can_generate_invoice()`, and that returns `latest_coverage_end < cutoff_date` where
`cutoff_date` comes from `billing_cutoff_frequency` in Verenigingen Settings (end of the current
month by default). Coverage extending past the cutoff short-circuits as `already_covered`. The admin
path (`invoice_management.py:94`) independently filters `next_invoice_date <= today + 7`, and
`manual_invoice_generation.py:155` passes `force=True` deliberately. Generation is bounded to one
period ahead on every path.

Corrected timeline for the 3 June joiner: invoice #1 on 06-03 covering 06-03…07-02; blocked as
`already_covered` for the rest of June; invoice #2 on **07-01** covering 07-03…08-02. Steady state
is a two-day lead, not a 29-day lag.

### 🚨 B2. Payment→invoice matching by coverage period breaks permanently — ✅ **FIXED**

`coverage_calculator.py:528-626` `calculate_coverage_for_payment_date()` still returns **calendar**
periods, and its consumers compare them to the invoice's `custom_coverage_*` for **exact
equality**:

- `mollie/services/dues_payment_processor.py:363-395` — overlaps two invoices, matches neither, so
  it logs "manual review required" and returns None. **The recurring Mollie payment is neither
  matched to an invoice nor given one.**
- `services/mollie_payment_orchestrator.py:272-288` and `:697-745` — same shape; status downgraded
  to `partial`/`incomplete`.
- `find_invoice_for_payment` Strategy 2 (used by `ponto/api/webhook_handlers.py:474`) falls through
  to a weaker 3-month amount-window heuristic.

This was already broken for the *first* period under the old code, but the schedule self-realigned
to the calendar from invoice #2, bounding the damage to one period. The change makes it
**permanent for the member's lifetime**. My downstream audit checked `coverage_overlap_detector`
for inclusivity — correctly — but never checked whether its *callers* generate the periods they
compare against.

*Fixed as:* derived from the member's actual sequence, at the source, so all four consumers are
healed at once and exact equality keeps working. `calculate_coverage_for_payment_date()` now
resolves, in order: a submitted invoice whose coverage already contains the payment date (no
arithmetic, so it is exactly what the consumers compare against); else a roll forward from the day
after the latest coverage end (the same rule the sequential branch uses, so an invoice created for
that period stays gap-free); else a roll from the membership start date (matching the
`first_invoice` branch); else the previous calendar behaviour. The roll is bounded — a payment
outside the sequence falls back rather than spinning.

Fixing it at the source rather than relaxing the consumers' equality check was deliberate: **these
same dates drive the create-invoice paths**, so a calendar answer would not merely fail to match,
it would write calendar-aligned invoices overlapping the member's own sequence.

Two supporting changes went in with it:
- The period-length arithmetic moved to `billing_period_calculator.calculate_coverage_end()`, with
  `CoverageCalculator._calculate_coverage_end()` delegating, so the sequence and the payment matcher
  cannot drift apart.
- §4.11 (`_get_membership_start_date` has no `ORDER BY`) is fixed here too — it anchors the same
  computation.

*Verification:* 312 tests across 13 suites on test_site_1, including the pre-existing calendar-period
tests (`test_priority1/2/3`, `test_coverage_period_exact_match`), which pass **unchanged** and pin
that behaviour is preserved wherever alignment already is calendar.

### ⚠️ B3. The member base is bifurcated — ✅ **DECIDED: leave the existing members calendar-aligned**

Calendar anchoring was a **deliberate** decision in `1fa2bf33` (2025-12-01): *"use the billing
period containing the reference date … rather than starting from today mid-period"*. The same hunk
added the `membership_start` truncation that defeated its own goal — so it was self-defeating, but
it was a decision, not an oversight.

Production on veg11:

```
custom_coverage_start_date  custom_coverage_end_date  count
2026-04-01                  2026-06-30                 440   <-- one uniform Q2 batch
```

440 quarterly members share one coverage period, and `book_year` is the calendar year. After this
change new joiners get private periods while the existing 595 stay calendar-aligned **forever**
(the sequential branch preserves whatever alignment exists). Also:
`report/membership_dues_coverage_analysis` deliberately clips billing periods to book-year
boundaries, but schedule-generated invoices will now routinely span two book years — two
invoice-creating paths with incompatible rules.

*Decision taken (owner, 2026-07-31):* **leave them.** The existing members keep their calendar
alignment — the sequential branch preserves whatever alignment exists, so no migration runs and no
existing billing date moves. Only new joiners get periods of their own. The bifurcation is accepted,
not overlooked.

*Consequence left open:* `report/membership_dues_coverage_analysis` still clips billing periods to
book-year boundaries, while schedule-generated invoices for new joiners will routinely span two book
years. Two invoice-creating paths with incompatible rules, unchanged. This needs its own decision;
it is not blocking the coverage fix.

### Supporting evidence the review added in favour of the change

- `sepa_batch_processor.py:816-848` `validate_coverage_period` is explicitly titled *"rolling
  periods"* and checks period **length** (28–31 days Monthly, 365±2 Annual). The old short first
  period would have been flagged by SEPA verification; the new behaviour satisfies it.
- `services/member/approval/application_payments.py:41-59` — the invoice created at application
  approval **already** used the running-period model. The two first-invoice paths were inconsistent;
  this aligns them. *(Separate pre-existing bug: that path uses `add_years(start, 1)` with no
  `-1` day, producing a 366-day inclusive period — visible on veg11 as 9 rows
  `2026-06-25 .. 2027-06-25`.)*
- Because the application invoice already exists and is submitted, `get_latest_coverage_end_date`
  finds it and the first *generated* invoice takes the sequential branch. **The `first_invoice`
  branch therefore only runs for imported/admin-created members**, or where the application invoice
  was not submitted. That narrows both the original bug and B1's blast radius — but neither to zero.

### Lesser review findings, already addressed

- The fallback-parity claim is false for **partially-configured Custom** schedules
  (`calculate_billing_period` defaults a missing number to 1 while honouring the unit;
  `_calculate_coverage_end` defaults it to one month and discards the unit). Unreachable only
  because `validate_custom_frequency` rejects such schedules first. Test docstring now says so.
- `test_calendar_fallback_…` never called `calculate_next_coverage_period`, so it could not have
  been RED and does not pin the branch it claimed to. Renamed and re-documented honestly; a true
  end-to-end fallback test needs a member with no submitted Active membership, which the factory
  does not currently arrange. **Still outstanding.**
- The annual/renewal cross-check passes on `develop` on 1 January (when
  `membership_start == period_start`). One day a year it is not a regression test.
- The auto-advance consequence applies to **Monthly only**; for Quarterly/Annual the throw is
  caught earlier by `EligibilityChecker.check_for_duplicates`' bare `except`, which blocks without
  advancing. The original commit message over-generalised; corrected.
- End-of-month ratchet: `add_months` clamps, so a Monthly member joining the 31st drifts to the
  28th over three months and sticks. Bounded and converges, but they lose their anniversary day.

---

### 4.4 Bulk payment checker discards its own compliance audit row, and its alarm is dead code

`verenigingen_payments/mollie/services/bulk_payment_checker.py:721-725` hardcodes
`severity = "INFO"` / `"WARNING"` against a lowercase-only Select (`API Audit Log.severity`).
`_validate_selects` strips whitespace but does not case-fold, so the insert at
`utils/security/audit_logging.py:374` throws.

The swallow is three layers deep (`:384`, `:295`, `:234`) and `log_security_event` **returns an
event_id as if it succeeded**. Consequently the `except` at `bulk_payment_checker.py:754`, written
specifically to raise "Audit Logging Failure - CRITICAL" and bump a monitoring counter for exactly
this condition, **has never fired**.

Live path: the `mollie_bulk_payment_discovery` desk page and `mollie_payments_debug.py:907/1002`.

*Fix:* use `AuditSeverity.INFO` / `.WARNING`. Separately, consider making `log_event` return a
falsy sentinel so caller-level audit-failure alerting is not permanently inert.

### 4.5 `setup_default_payment_mappings` has never worked

`e_boekhouden/utils/eboekhouden_payment_mapping.py:145-148` iterates
`("Receivable", "Payable", "Bank", "Cash")` into `E-Boekhouden Payment Mapping.account_type`, whose
options are only `Bank\nCash`. It throws on the **first** iteration; the outer `except` at
`:200-201` returns `success: False`. **Zero mappings are ever created.**

### 4.6 Bulk Edit Account Mappings silently no-ops while showing a green success toast

`e_boekhouden/doctype/e_boekhouden_account_mapping/api.py:590` writes the caller's `account_type`
into `document_type` (options: Sales Invoice / Purchase Invoice / Expense Claim / Journal Entry).
The live dialog (`public/js/eboekhouden_migration_config.js:846-859`) offers **only** ERPNext
account types, none of which is a valid `document_type`. The per-row `except` (`:596-599`) swallows
it and `success: True` is returned regardless; the JS then reports
`Updated {0} mappings` using `updates.length`, not `updated_count` (`js:892-895`).

Probe: `account_type='Bank'` → `{'success': True, 'updated_count': 0}`, value unchanged.
Only priority-only edits actually work.

**Same overload one field over:** `api.py:211/221` writes the free-text `notes` parameter into
`transaction_category`, also a Select. Any notes string outside the 13 category values makes
`add_account_mapping` throw.

### 4.7 `Volunteer Skill.proficiency_level` default is not one of its own options

`verenigingen/verenigingen/doctype/volunteer_skill/volunteer_skill.json:32` — default `"3"`,
options `1 - Beginner … 5 - Expert`. **Any** Volunteer save with a skill row that omits
`proficiency_level` now fails, including adding a row in the desk grid. Production code happens
always to set it, which is why it went unnoticed.

### 4.8 Every skill submitted through the web application form is lost

`public/js/membership_application.js:893-896` sends `{skill_name, skill_level}`;
`volunteer.py:799-801` reads `name`/`skill`/`category`/`level`. **Every skill lands as
`volunteer_skill="Unknown"`.** Entirely unrelated to this branch; found in passing.

### 4.9 Payment Plan silently becomes weekly instead of being rejected

`payment_plan.py:35` guards `if not self.frequency`, but `frequency` is a Select with no explicit
default, so `_set_defaults()` fills it with the **first option** (`Weekly`) and the guard never
fires on insert. A Payment Plan created via API with `plan_type="Equal Installments"` and no
frequency silently becomes a weekly schedule. The author clearly intended rejection.
(`sepa_retry_batch.py:33` has the identical shape for `operation_type`.)

### 4.10 Mollie audit logger writes a category that does not exist — LATENT

`verenigingen_payments/mollie/utils/audit.py` writes `event_category="webhook"` at `186, 209, 228,
251` and `"api"` at `283`; the DocType has `webhook_processing`, never `webhook`. Per the field's
git history this has always been wrong, so **those five public API methods have never persisted a
row**. No live callers today — the only production caller hardcodes the valid value. A loaded
landmine on the documented public audit API rather than active data loss.

*Bonus:* `test_mollie_audit_unit.py:203` asserts the row is **absent** when logging is disabled.
Since the row is always absent, that test passes for the wrong reason and can never fail.

### 4.11 `_get_membership_start_date` has no `ORDER BY` — LATENT — ✅ **FIXED in `84ab5ee8`**

`services/billing/coverage_calculator.py:496` selects `start_date` from `Membership` filtered on
`{member, status: Active, docstatus: 1}` with no ordering. With more than one active membership the
row is arbitrary. Surfaced while writing tests; no active-duplicate rows exist on the live site
today, so it is latent.

---

## 5. Test-side root causes — the remaining ~213 failures

These are the actual remediation work for the harness branch. None is a production bug.

| # | Root cause | Blocks | Status |
|---|---|---:|---|
| RC1 | `set_posting_time` unset → ERPNext overwrites `posting_date` | 65 | **45 fixed, 20 outstanding** |
| RC2 | Invalid Select values written by test data | 98 | outstanding (1 was a production bug, §4) |
| RC3 | Autoname regeneration — tests hardcode `name` | 12 + 9 | outstanding |
| RC4 | Isolation cascade from RC2 | 11 | should fall out of RC2 |
| RC6 | `_set_defaults()` → `currency` defaults to INR | 3 | outstanding |
| — | Behavioural, individually diagnosed | 30 | see §6 |

### RC1 — 20 blocks still uncovered

`f57e1e86` added `set_posting_time: 1` to the two builders in `enhanced_test_factory.py`. Three
modules build Sales Invoices directly with `frappe.new_doc("Sales Invoice")` and never touch the
factory:

- `tests/backend/components/test_payment_processing_api` (7)
- `tests/backend/integration/test_payment_report_integration` (7)
- `tests/backend/components/test_payment_processing_api_real` (6)

These are the worst cases — they deliberately backdate 45 days to build "overdue" fixtures, so
without the flag the fixtures are not overdue and the assertions are vacuous.

Probe confirming the mechanism, on the same factory builder the tests use:

```
A in_import=True                  : requested=2026-01-12 persisted=2026-01-12 :: HONORED
B in_import=False                 : requested=2026-01-12 persisted=2026-07-31 :: OVERWRITTEN
C in_import=False set_posting_time: requested=2026-01-12 persisted=2026-01-12 :: HONORED
```

*Production impact: none.* The only production writers use `today()`. The one genuinely backdated
write (`expense_submission_service.py:504`) targets Expense Claim, which never calls
`validate_posting_time()`.

### RC2 — the dominant case is one schema rename

`contribution_mode` was renamed to `Fixed / Income-Based / Flexible`; test code still writes
`Tier` (42) and `Custom` (8), including a stale comment in `tests/fixtures/sepa_test_factory.py:182`
asserting the old vocabulary is correct. **This was already known** —
`tests/utils/skip_reasons.py` documents it verbatim, and tests were *skipped* for it rather than
fixed. The harness change simply caught the ones nobody had skipped.

Remaining fields: `Permissions Level=Membership` (8), `Campaign Type=General` (6),
`Payment Type=One-off` (5), `Status=Pending` (5), plus ~12 singles. Each is a lookup against the
DocType's `options` list.

### RC3 — autoname

`frappe/model/naming.py:158` skips autoname under `in_import`, so an explicitly-assigned `name`
survived insert. Affects `tests/chapter/test_role_profile_managers.py` (9) and
`tests/backend/components/test_chapter_assignment_edge_cases.py` (9, including all 7 of its
`AssertionError`s — the assignment returns an accurate "Member X not found", the tests just report
it as `assertTrue(..., "First assignment should succeed")`). Fix: use the inserted doc's `.name`.

### RC4 — cascade, one module

`tests/integration/test_sepa_mandate_authentication_security.py` writes `status="Inactive"` and
`"Pending"` (both invalid, RC2). The throw aborts `setUp` *after* the first mandate is inserted;
`tearDown` does not run when `setUp` raises, so the row survives and all 11 later tests collide on
`mandate_id`. The id is also a **constant** — `f"ACTIVE-{member.name[:8]}"` is always
`ACTIVE-Assoc-Me`. Fix the Select values first; the duplicates should vanish. Then make the id
unique regardless.

---

## 6. Individually diagnosed behavioural failures

- **6 tests** (`test_financial_utils_coverage`, `test_dues_schedule_manager`) — RC1 fallout.
  Collapsing every invoice onto one date breaks date-range filters and creates an
  `ORDER BY posting_date DESC` tie. **Already fixed by `f57e1e86`; re-run rather than triage.**
- **7 tests** — RC5, fixed by `05656257`.
- **2 tests** (`test_frequency_required_for_equal_installments`,
  `test_validate_operation_requires_type`) — the guard is unreachable on insert because
  `_set_defaults()` fills the Select with its first option (§4.9). Delete or invert the tests; the
  production hazard is a separate ticket.
- **1 test** (`test_termination_execution_workflow`) — **production is correct.**
  `enforce_minimum_period` defaults to 1, so `commitment_end_date` is now computed and the
  termination is properly rejected. The old harness was silently disabling the commitment rule.
  *Expect more of these:* any test building a Membership Type via `frappe.get_doc(dict)` now gets
  the rule enforced for the first time.
- **1 test** (`test_duplicate_name_collision_is_handled_without_raising_to_caller`) — ERPNext's own
  de-duplication is gated on the same flag (`erpnext/selling/doctype/customer/customer.py:120`), so
  the collision the test staged no longer happens. The new behaviour is correct; invert the test.
- **1 test** (`test_create_from_member_skills_as_list_of_dicts`) — the test supplies an invalid
  skill category. Test-only.
- **1 test** (`test_500_rows_completes_in_reasonable_time`) — **not diagnosed.** See §7.

---

## 7. Known-unresolved

**`test_procurios_mandate_import.test_500_rows_completes_in_reasonable_time` (`0 != 250`).**
Not RC1/RC2/RC3. A local reproduction was obtained and then *refuted by its own control* — it
reproduces identically with `in_import=True`, and the local mechanism turned out to be an RQ worker
on this box racing the test's own synchronous call, which CI cannot hit (CI starts redis service
containers only, never `bench start`). In a CI-faithful configuration the test passes. What the CI
evidence still constrains: `import_status == "Completed"`, so all 250 create-rows landed in a skip
or error bucket. Candidates: the broad `except` at `procurios_mandate_import.py:270`, or the
`conflict` / `no_member` buckets.

*Suggested next step:* add `doc.skipped_summary` / `doc.error_log` to the assertion message so the
next CI run answers it in one line.

**Separately, that test self-poisons:** it uses hardcoded fixture ids (`SCL-NEW-0`…) against a
`unique` column while the code path under test commits
(`_finalize_import_results` → `frappe.db.commit()`, `:407`). Any partially-completed run leaves
committed rows that make every later run fail. Every other fixture in the enhanced factory appends
a per-process unique suffix; these do not.

---

## 8. Traps — read before starting

**`bench` runs the main tree, not your worktree.** See §3.3. Verify with `print(module.__file__)`.

**A green local run proves nothing about this change.** `sites/test_site_1..4/site_config.json`
preset `throttle_user_limit`, and the long-lived sites carry committed state that masks
data-validity failures. A full local run showed 0 failures across 11,293 tests while CI showed 236.
Use CI, or a targeted probe.

**The probe pattern that works.** Set `frappe.flags.in_import` explicitly, perform the write, pair
every failing case with a known-good control, roll back. Two investigators produced *false*
reproductions that only their controls caught.

**Some existing tests ASSERT the bug, and will go red when you fix it.** Because
`EnhancedTestCase.setUp` sets `in_import`, an invalid Select value round-trips inside the suite, and
tests were written against what came back. Two found so far:
`test_volunteer_sync_service.test_ends_active_team_membership` asserted
`row.status == "Ended"`, and `tests/sepa/test_sepa_bank_reconciliation_coverage.py:395` asserted
`"Mollie Settlement Processed"` round-trips through `BankTransactionCreator.create_from_dict`. A red
test after this kind of fix is not automatically a regression — check whether the assertion encoded
the defect. Wrap the assertions that matter in `production_validation()` so they stay honest
regardless of when `ee45ffc8` lands.

**A guard in front of the guard.** Before concluding that removing a check causes runaway behaviour,
find every gate the caller applies *first*. `BulkInvoiceGenerationService` filters on
`should_generate_for_cutoff_period()` before `can_generate_invoice()` is ever called; reasoning from
the eligibility checker alone produces a confident and wrong answer. See B1.

**Select fields with no explicit default get their FIRST OPTION.**
`frappe/model/create_new.py:117` — applied to the doc and to every new child row. This is the
single most productive mechanism in this sweep; it is why guards like §4.9 became unreachable.

**`_validate_selects()` is gated on `frappe.flags.in_import` alone** (`base_document.py:1093`) —
not `in_test`, not `in_patch`. A patch that writes an invalid Select value *will* throw.

**`frappe.enqueue()` checks module-level `frappe.in_test`, not `frappe.flags.in_test`**
(`background_jobs.py:143,152`). Setting only the flag leaves enqueue live.

**`in_bulk_import` is not a substitute for `in_import`** — it suppresses strictly more (the event
emitters gate on it and never check `in_import`). Tried and reverted; broke 3 tests.

**Every `in_import` gate in ERPNext/HRMS**, since the handoff taxonomy did not account for the last
two:

| Location | Effect when the flag was set |
|---|---|
| `erpnext/selling/doctype/customer/customer.py:120` | duplicate-name `" - N"` suffixing disabled |
| `erpnext/utilities/transaction_base.py:31` | explicit `posting_date` honored (RC1) |
| `erpnext/controllers/accounts_controller.py:935` | due-date-before-posting-date check relaxed |
| `erpnext/accounts/doctype/journal_entry/journal_entry.py:199` | **not yet accounted for** |
| `erpnext/accounts/doctype/payment_entry/payment_entry.py:1211` | explicit `title` honored — **not yet accounted for** |

**`pgrep -f` / `pkill -f` match their own shell** in this harness. Use
`ps -eo pid,etime,cmd | grep "[b]ench_helper"` and `while kill -0 "$PID"`.

**Pre-commit:** `SKIP=whitelist-type-safety` is standing. In a worktree, `make-test-quick`,
`import-path-validator` and `frappe-hooks-validator` fail for environmental reasons (no bench dir,
no `node_modules`, and the hooks validator derives the app dir from the cwd basename).

**A misleading comment to ignore.** `verenigingen_payments/doctype/sepa_mandate/sepa_mandate.py`,
`set_scheme_default()` claims "Frappe v16 no longer applies a field's JSON default on a raw
`get_doc({...}).insert()`". That is a misdiagnosis of this same `in_import` suppression. The
workaround is harmless; the belief is not, and may have been copied elsewhere.

---

## 9. Recommended order

Items 1-4 of the original order are done or ready; what is left is renumbered below.

1. Land **PR #193** (independent, green).
2. Land **`4f124f32`** (dead patch retirement) — independent, reviewed and approved.
3. ~~Finish `6d0e990d`~~ — ✅ done in `84ab5ee8`. **Rebase onto `origin/develop` (10 behind) before
   opening the PR**, and dispatch `server-tests.yml` on the branch — a plain push runs pylint only.
4. ~~File §4.1 and §4.2~~ — ✅ fixed directly instead, on `4db12397` and `163d9744`. Both sit on
   current `origin/develop`. **`4db12397` needs a fixture re-sync (`bench migrate`) to deploy.**
5. File the **nine remaining production bugs** (§4.4-§4.10, plus the two follow-ups §4.1 and §4.2
   left behind: the non-atomic Mollie posting path and `_end_chapter_board_membership`). None is
   blocked by the harness work.
6. Harness branch: RC1 remainder (20) → RC3 (21) → RC2 (97) → RC4 (11, should fall out) → RC6 (3).
7. Re-run the 12 shards, and re-run the `develop` baseline on the same day for comparison. Note that
   the 20 coverage-period failures `develop` had on 2026-07-31 are fixed by `05656257`/`84ab5ee8`,
   so a future baseline should be clean for a different reason than "not a month-end day".
8. Resolve §7 or accept it into `known_test_failures.txt` with a written reason.
9. Decide the coverage-analysis report's book-year clipping (see B3).

## 10. Standing method note

RC1 and the coverage bug both surfaced *only* because the run crossed a date boundary. Both are
silent on any other day. When fixing anything here, **assert the value directly** rather than
relying on a downstream validation to notice, and prefer `force_date`-style injection over
dependence on `today()`.
