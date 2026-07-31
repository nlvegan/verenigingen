# Handoff — 2026-07-31 (evening)

Session covered: skeptical review + merge of a test branch, four PRs merged into
`develop`, two deferred bugs fixed, a red `develop` diagnosed down to two unrelated
root causes, and a design decision on payment allocation.

Written at ~22:10 UTC. Anything time-sensitive is flagged.

---

## 1. Merged today

| PR | what | merge commit |
|----|------|--------------|
| #213 | `test(roles)`: pin what a bulk role-profile recalculation does | `37fd6cbb` |
| #193 | `refactor(security)`: retire `security_wrappers` + audit script | `780da83a` |
| #214 | `fix(mollie)`: settlement reconciliation — posting, idempotency, retry bound, submit precondition | `55015515` |
| #215 | `fix(mijnrood)`: actually revoke board/team access on ROLE_ADMIN removal | `40529923` |

`develop` is at `40529923`.

#193 had been failing only because it was 5 commits behind and predated the
coverage-period fix in #212; a `develop` merge cleared it.

---

## 2. Open PRs — all from today, none merged

| PR | branch | what | CI |
|----|--------|------|----|
| #216 | `fix/mollie-failed-submit-leaves-draft` | insert+submit as one unit | red on #218's + #219's defects |
| #217 | `fix/board-manager-flattens-non-resumable` | bulk board ops stop flattening 1213/1205 | red on #218's + #219's defects |
| #218 | `fix/revenue-projection-naive-clock` | report reads the site clock | red only on #219's defect |
| #219 | `fix/mollie-overlap-test-stale-after-212` | rebuild the overlap fixture | red only on #218's defect |

**They fix each other.** Verified from the CI logs, not inferred:

* #218 shard 12 fails on exactly one test — `test_overlap_without_exact_match_skips_creation` — which #219 fixes.
* #219 shard 8 fails on exactly two tests — the revenue-projection pair — which #218 fixes.

### Recommended merge order

1. **#218 and #219 first.** Each is red solely because of the other. Merging both
   makes `develop` green.
2. **Then re-run #216 and #217** and merge on green. Their own code was never
   implicated.

Do NOT simply re-run #216/#217 after 00:10 UTC and merge on green — see §4. The
clock makes one of the two defects disappear on its own, which would look like a
pass while the bug is still there.

---

## 3. `develop` is currently red — two unrelated causes

### 3a. Naive server clock in a report (real production bug, fixed in #218)

`membership_revenue_projection.py:52` used `datetime.now()` — the **server** clock —
while everything else in Frappe is site-local.

Site timezone is `Asia/Kolkata` (UTC+5:30); this host is CEST (UTC+2); CI runners are
UTC. Whenever site and server disagree about the calendar day, the report opens on
the month that has just **ended**. Windows:

* this host: 18:30–22:00 UTC on a month's last day
* CI runners: 18:30–24:00 UTC on a month's last day

Fixed by `frappe.utils.now_datetime()`. The test needed no change — it already
asserted site time, which is why it caught it.

### 3b. A test made stale by PR #212 (fixed in #219)

`176a41dc` ("anchor duplicate detection and payment matching on the member's own
periods", PR #212, merged this morning) added `_coverage_period_from_member_sequence`.
Its **first** preference is *an invoice whose coverage already contains
`payment_date`*, returned verbatim.

`test_overlap_without_exact_match_skips_creation` built its "overlapping but not
exact" invoice by shifting the window **backward 3 days** — so the invoice spans the
payment date, becomes the anchor, and is reported as an **exact** match. Measured:

```
test coverage   : 2026-08-01 .. 2026-08-31   (before the invoice exists)
recomputed cov  : 2026-07-29 .. 2026-08-28   (after; now anchored to it)
overlap result  : has_overlap=True  exact=ACC-SINV-...
```

A backward 3-day shift spans today on every day of a period **except its last
three**. #212 merged on 31 July — inside that window — so it went green and began
failing on 1 August. It is in **neither** known-failures baseline, so this is a hard
CI failure ~28 days a month until #219 lands.

**Judgement call, flagged for a reviewer:** I concluded the *code* is right and the
*test* was stale, because reusing an existing submitted unpaid invoice that already
covers the payment date is what #212 set out to do. If the refusal was intended even
for a covering invoice, #219 is wrong and the fix belongs in
`_coverage_period_from_member_sequence` instead.

### 3c. Not a cause: shard 2

Shard 2 failed on `develop` (`test_iban_validation_formats`) and on #216
(`test_context_board_member_happy_path`) with **different tests each run**, and both
pass in isolation. Order-dependent flakes, not a regression.

Also: the `❌ get_volunteer_expense_context: FAIL - 'str' object has no attribute
'get'` lines in shard 2 logs are **not test failures**. They come from
`tests/backend/components/expense_form_test.py`, a legacy script-style harness that
catches exceptions and prints `❌ … FAIL` strings unconditionally. I initially built a
causal story around them. Ignore them.

---

## 4. Time-sensitive

At **00:10 UTC** the CI runner clock and the `Asia/Kolkata` site date reconverge, and
**both** §3a and §3b failures disappear on their own until the next month end.

That means: after midnight UTC, a re-run of #216/#217 goes green **whether or not
#218 and #219 are merged**. Merge #218/#219 on their own merits, not on a post-
midnight green tick.

Next recurrence: **31 August**, unless #218 and #219 are in.

---

## 5. Timezone — changed on test sites, NOT on veg11

`System Settings.time_zone` was `Asia/Kolkata` on all three sites — Frappe's install
default (its own source comments the fallback `# Default to India ?!`), not a choice.
Meanwhile `System Settings.country = Netherlands` and 568 of 580 Users are on
`Europe/Amsterdam`.

**Changed:** `test_site_1` and `test_site_2` → `Europe/Amsterdam`. Site and server
clocks now agree.

**Not changed:** `veg11.veganisme.org`. Still `Asia/Kolkata`.

The field is `read_only: 1` in Frappe's own `system_settings.json` — no Property
Setter, no UI path. Only way is server-side:

```python
frappe.db.set_single_value("System Settings", "time_zone", "Europe/Amsterdam")
frappe.db.commit(); frappe.clear_cache()
```
then `bench --site <site> clear-cache` and restart workers.

**Caveat if you do change veg11:** Frappe stores naive site-local datetimes. Changing
the zone reinterprets history rather than correcting it, creating a discontinuity at
the cutover. New records become correct; old ones do not.

### Measured date skew on veg11 (read-only, nothing written)

Rows whose stored `creation` date is one day ahead of the true Dutch date:

| doctype | rows | skewed | |
|---|---:|---:|---:|
| Membership | 1,238 | 402 | 32.5% |
| Membership Dues Schedule | 1,660 | 435 | 26.2% |
| Donation | 60 | 12 | 20.0% |
| Sales Invoice | 3,471 | 644 | 18.6% |
| SEPA Mandate | 94 | 11 | 11.7% |
| Member | 748 | 50 | 6.7% |
| Payment Entry | 3,694 | 31 | 0.8% |
| **total** | **10,968** | **1,585** | **14.5%** |

Business dates that followed the wrong calendar day:

| doctype | field | skewed | wrong day | right day |
|---|---|---:|---:|---:|
| Sales Invoice | `posting_date` | 644 | **627** | 0 |
| Membership | `start_date` | 402 | **248** | 0 |
| Payment Entry | `posting_date` | 31 | **31** | 0 |

The "right day" column being zero throughout is the tell: these are `today()`
resolving to tomorrow, not deliberate dates. Member naming-series months: **0**
mismatched, so numbering is intact.

**Owner said veg11 is test data, so no repair is planned.** Recorded because the same
mechanism applies to any site left on the default timezone.

---

## 6. Decision taken: payment allocation stays manual

**Context.** `_get_or_create_historical_invoice` (Mollie dues path) selects invoices
by **coverage period only**. It ignores payment description and amount.

By contrast `find_invoice_for_payment` implements remittance parsing → coverage →
amount matching, and **is** used by the Ponto webhook handler
(`ponto/api/webhook_handlers.py:445`). `dues_payment_processor.py:25` **imports it and
never calls it**.

**Owner's estimate:** ambiguous payments run to *dozens a year*.

**Decision.** Do **not** build tiered auto-allocation. At ~1/week, manual handling in
Payment Reconciliation is cheaper and safer than a rule that must be specified,
tested, and debugged the first time someone overpays.

**Agreed policy if it is ever automated:** oldest invoice first (FIFO), multiple if
the amount fits — the accounting convention, and it keeps aging honest.

**The change actually worth making** — separate *recording* the money from *deciding
what it pays*:

* Today the ambiguous case returns `None` and skips, so the payment lands nowhere.
* Instead record a submitted Payment Entry with **no allocation**. The member's total
  balance stays correct, the money is on the ledger, and it surfaces in Payment
  Reconciliation for a human. Same judgement, nothing lost while it waits.

Not implemented this session. This is the recommended next piece of work in this area.

---

## 7. Outstanding work, ranked

### High — real bugs, not yet filed or fixed

1. **`outstanding_amount == 0` treated as "paid" without checking `docstatus`.**
   Named explicitly in `_coverage_period_from_member_sequence`'s own docstring as
   "the real defect". A **draft** invoice has zero outstanding; callers
   (`mollie_payment_orchestrator._create_invoice_if_safe`, `dues_payment_processor`)
   read that as "already paid" and take it as licence to create **another** invoice
   for the period. The function is pinned to submitted-only lookups purely to keep the
   safe branch reachable. This is a duplicate-invoice path. **Highest priority.**

2. **Failed `submit()` still leaves drafts on other paths.** #216 fixes the Mollie
   settlement helpers via `_insert_and_submit`. The same insert-then-submit shape
   exists elsewhere; no audit done.

3. **~127 naive-clock call sites** (`datetime.now()` / `date.today()`) in production
   code. #218 fixes the one that had a test sharp enough to catch it. Others are
   wrong whenever site TZ ≠ server TZ. Needs a real audit, not a sweep.

### Medium

4. **Dead import**: `dues_payment_processor.py:25` imports `find_invoice_for_payment`
   and never calls it, while Ponto does. Either wire it up or drop it — it currently
   reads as if Mollie does remittance/amount matching.

5. **Unallocated-Payment-Entry change** from §6.

6. **Order-dependent shard-2 flakes.** Different test each run, all pass in isolation.
   Known repo phenomenon.

7. **veg11 timezone** — correct value is `Europe/Amsterdam`; owner's call, see §5.

### Deliberately not done

* SEPA batch path `allow_draft_on_permission_failure=True` — owner: Mollie and SEPA
  batches are unrelated in this app. Out of scope.
* `dispatcher.apply_event` "writes on a discarded transaction" — **this claim was
  wrong.** It calls `frappe.db.rollback()` at `:114` and `:138` *before* recording.
  Nothing to fix. (Came from a review finding I repeated without checking.)
* `add_board_member` / `remove_board_member` NON_RESUMABLE clauses — they already
  re-raise; only `log_action` ordering is imperfect, which harms no caller.

---

## 8. Method notes worth keeping

* **`gh pr checks --json` does not exist on this `gh` build.** It errors, and with
  `2>/dev/null` the error vanishes and an until-loop polls forever looking like CI is
  slow. Use `gh pr view --json statusCheckRollup` and test
  `select(.status!="COMPLETED")`. Testing `.conclusion != "SUCCESS"` also
  misreports IN_PROGRESS checks as failures.
* **`pkill -f` matches its own shell** and kills the invoking command (exit 144). Use
  `TaskStop`.
* **A commit can silently not land.** A formatter rewriting a staged file leaves
  `HEAD` unmoved while the hook output still tails as all-passing. Check
  `git log --oneline -1` after every commit.
* **`bench` runs the main tree, not a worktree.** The Import Path Validator also
  emits ~11 bogus "module not found" errors from inside `.claude/worktrees/*` — the
  modules exist; it resolves the app root wrongly. Work in the main tree.
* **CI logs are ANSI-coded**; strip with `sed 's/\x1b\[[0-9;]*m//g'` before grepping
  or failure counts come out wrong.
* **Verify a red test is red for the *right* reason.** A first attempt at the #216
  test failed with `docstatus=1` — the injection never fired, so the "failure" proved
  nothing.
* **Move the site timezone to move `today()`** rather than waiting for the clock —
  that is how #218 and #219 were verified under both date conditions.
* The worktree `agent-a786ec7f8e10a6b2c` was **removed** to relocate the Mollie branch
  into the main tree. Branch and commits intact.

---

## 9. Immediate next steps

1. Confirm #219's CI finished (shard 2 was still running at write time).
2. Merge **#218**, then **#219** — accepting that each is red only on the other's
   defect. Re-check `mergeStateStatus` after the first merge.
3. Re-run CI on **#216** and **#217**; merge on green.
4. Confirm `develop` is green afterwards — **this session's main process failure was
   merging four PRs without re-checking `develop` after the sequence.**
5. File the §7 items, starting with the `outstanding_amount == 0` duplicate-invoice
   bug.
