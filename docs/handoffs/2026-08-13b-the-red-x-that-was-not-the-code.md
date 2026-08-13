# Handoff 2026-08-13b — the red X that was not the code

Seven PRs merged, four issues closed, an eight-PR queue drained. The previous session
ended by filing #319 — CI shards failing **before running any test** because a `wget` was
throttled — and listing it fifth. This session started by treating it as first, and that
single ordering decision is the whole story: three PRs had been sitting unmergeable behind
an infrastructure failure that was indistinguishable, from the outside, from a code
failure.

**The through-line: a red check is a claim about your code, and it has to be verified like
any other claim.** #318's shard 3 died three separate times, including on a targeted
`gh run rerun --failed`, and never once on its own code.

The previous handoff's rule ("mutate the claim, or the evidence is only that the test
runs") held again, and twice this session the *green* was the thing that lied.

---

## 1. What merged

| PR | | Merge |
|---|---|---|
| #321 | CI: a throttled wkhtmltopdf download no longer fails shards before any test runs | `b5ec9ad0` |
| #322 | the pre-push hook stops targeting the live site | `2ff88805` |
| #318 | SEPA reconciliation cleans up the rows it commits | `7fdea48f` |
| #315 | settings restore + the harness owns its settings company | `269b764a` |
| #324 | the ERPNext integration suite owns its company | `637f2b7e` |
| #323 | harness setup failures are fatal | `f6e625ed` |
| #317 | email capture: retarget one patch, delete two, fail loudly | `10d3e833` |

## 2. Issues closed

| | |
|---|---|
| #319 | wkhtmltopdf download → shards failing before any test ran |
| #313 | pre-push hook ran the suite against **veg11** |
| #312 | settings restoration never ran; three email patches never started |
| #314 | `tests/utils/__init__` swallowed the one thing it exists to do |

Still open and advanced, not closed: **#308** (two of five sites fixed), **#291**,
**#309**, **#255**, **#316**.

---

## 3. The merge order changed, and why

The previous handoff proposed **#318 → rebase #315 → #317**. That was right about
dependencies and wrong about what was blocking: #318 could not reach green *at all* while
#319 was live.

Executed instead: **#321 first**, then the original chain rebased onto it. Every rebased
PR went green on the first attempt afterwards.

Worth keeping: **when a PR's red shards are infrastructure, rebasing the queue onto the
infrastructure fix is the merge path, not a detour.** Re-running is the detour. One rerun
cycle was spent before the log was read properly.

## 4. #319 — what actually made it fail

`wget` **retries network failures but not HTTP error responses.** A 5xx returns **exit 8**
on the first attempt and aborts; `--tries` alone can never help. Only
`--retry-on-http-error=429,500,502,503,504` changes that (wget ≥ 1.20; ubuntu-latest ships
1.21). Exit 4 is a network failure after retries are exhausted.

All 12 shards fetched the same 17 MB release asset on every push — a self-inflicted
throttle. Three parts, the last mattering most:

1. **Cache** the asset, so a warm run never touches the network.
2. **Retry**, with `--retry-on-http-error`.
3. **Pin the checksum.** An unverified body is worse than a failed download: a truncated
   file or an HTML error page would otherwise be handed to `apt`, or **saved into the
   cache and inherited by every later run**.

`-q` is why six occurrences took four log-dives — it suppressed the reason, leaving only
`Process completed with exit code 8`. Now `-nv`, plus an `::error::` stating outright that
this is infrastructure and no test has run.

**Diagnosis recipe.** A shard whose `Setup Environment` failed and whose `Run Tests` is
**skipped** is infrastructure. Check before re-running or blaming the diff:

    gh api repos/<o>/<r>/actions/jobs/<id> \
      -q '.steps[]|select(.conclusion=="failure" or .conclusion=="skipped")'

## 5. #313 — the hook that tested production

`pytest_precommit_runner.py` read `sites/currentsite.txt`, a file this bench never writes,
and fell through to a hardcoded `veg11.veganisme.org`. The `if` never fired, so **every
`git push` from the installed checkout ran the suite against the live site.**

It now resolves `default_site` from `common_site_config.json`, `currentsite.txt` second,
and has **no hardcoded fallback at all** — it **refuses** any site outside
`test_site_1..5`. It skips from a linked worktree rather than dying on
`Error: No such option: --site`, and **prints its target site**: it ran against production
for as long as it did partly because nothing it printed ever said where it was pointed.

`SKIP=pytest-coverage-critical` is **no longer needed**. #322 was itself pushed without
it — that was the proof, not a claim.

Its CI step now discovers `test_*.py` rather than one pinned filename. Pinning it is how a
second test module silently never runs, which the comment above that very step already
warned about.

## 6. #314 — and the two sites the issue did not know about

Both callers of `disable_workflow_action_emails()` wrapped it in a handler that turned "it
never happened" into a log line. The consequence is in that module's own docstring: Frappe
renders a PDF synchronously inside every Member insert and can raise
`OSError: ... HostNotFoundError` in every test touching a Member.

Six sites made fatal. **Two were not in the issue** — a second `_seed_default_team_roles()`
swallow and a second erpnext-defaults swallow. The **AST source guard** written for this PR
found them.

That guard exists because **re-wrapping a call site in `try`/`except` changes no observable
result on a healthy box.** No behavioural test can see it. When a property is about the
shape of the code rather than its behaviour, the test has to read the code.

`disable_workflow_action_emails()` now asserts its own postcondition: its entire purpose is
a side effect on another module's namespace, and "it did not raise" is not evidence the
side effect took.

## 7. The two greens that lied

Both were caught by CI, and neither could have been caught locally. This is the most
useful thing in this document.

**#324 — my fix did not cure the three failing tests, it exposed them.** After switching
`_ensure_test_company` from a borrow to an owned EUR company, CI failed with

    Party Account Debtors - TPIC currency (EUR) and document currency (INR) should be same

Both sides had been borrowed. On a fresh shard the old lookup fell through to
`get_all("Company", limit=1)`, which returns the **oldest** company — `_Test Company`, INR
— and an INR invoice under an INR company agreed **by coincidence**. Fixing only the
company half turned a latent inconsistency into a visible failure. That is the correct
outcome, and `test_site_1` could never have shown it: the module passed there both before
and after, because that site carries `Test Company` *with* a committed chart of accounts.

The fix pins `currency` and `conversion_rate` on all four invoices, so neither side is
inherited from whatever the site happens to hold.

**#323 — a red shard in payments code the PR does not touch.** `test_find_member_by_customer_id`
failed with `found = None`. Cause: the PR **adds one test file**, and that re-packs every
shard (#291). Measured with the repo's own replicator rather than assumed:

| | shard | position |
|---|---|---|
| develop | 11 | 102/110 |
| branch | **2** | 107/109 |

Shard **2** is exactly the one that failed. The underlying defect is **#255** — the
`MemberPaymentMatcher` singleton loads once and never refreshes — reproduced in three
lines:

    warmed with 3 members
    STALE  -> None
    RESET  -> Assoc-Member-2026-08-50150

The suite was missing the reset its siblings already do
(`test_mollie_dues_processor_coverage_b3.py:249-250`). **That fixes CI only.** #255 is a
production defect — a long-lived worker keeps its stale snapshot until restart — and stays
open, now carrying the measurement it asked for: **536 of 748** Members on veg11 hold a
`mollie_customer_id`, so the cached load is one `get_all` over ~536 narrow rows, which
argues for dropping the singleton rather than building TTL invalidation.

## 8. Measured, not assumed

- **`wget` has no `file://` support.** The first version of #321's download test pointed at
  a local file, "failed" correctly, and proved nothing — the download leg never ran.
  Re-run against `python3 -m http.server`, it holds.
- **None of #314's handlers fires today** on a seeded `test_site_1`
  (`VERENIGINGEN_TEST_LOG_LEVEL=DEBUG`: one INFO line, nothing else). Making them fatal
  changed no passing run there; CI's fresh sites were the actual test.
- **`test_site_1` carries 90+ companies**, including both `Test Company` and
  `TEST-Payment-Integration-Company` — which is precisely why #308's borrow passes there.
- **`MollieConfigurationService.get_clearing_account()` matches on the Single, not the
  account name.** #308 says the Mollie sweep "needs an account whose name contains
  'Mollie'"; the code reads `Mollie Settings.mollie_clearing_account` and throws if unset,
  and the test pins that Single itself. **Left unfixed and documented on the issue** rather
  than changed on a mechanism that could not be confirmed.

## 9. Traps hit

- **A `git rebase` that aborts on unstaged changes leaves the following `&&` chain unrun**
  — but a `git log` on the next line still prints, showing the *old* head. Caught only by
  reading the SHA. Same family as the formatter-aborts-commit trap.
- **A rebase that auto-merges without conflict is the case to distrust.** #317's rebase was
  clean, and #317 still carried the *old* `self.factory._restore_verenigingen_settings()`
  — #312's bug — while #315 had fixed it to `self.`. Verified the resolved file rather than
  the exit code; the fix survived. A silent revert there would have left CI green while
  every test's settings restore failed again.
- **`^OK$` does not match through ANSI colour codes.** A passing run looked like it
  produced no result line. Strip with `sed 's/\x1b\[[0-9;]*m//g'` before grepping.
- **`show_test_shards.py` reports the count-based fallback, not CI's layout, unless the
  worktree path contains `/apps/`** — and it says so loudly, which is the only reason the
  shard comparison in §7 is trustworthy. Use `git worktree add --detach <s>/apps/verenigingen`.
- **`gh pr merge` at `UNSTABLE` is not the same as at `CLEAN`.** With three PRs × 12 shards
  competing, the aggregate `Test Summary` job sat queued for 10+ minutes after all shards
  were green. Waiting is correct; the state resolves.

## 10. Open threads

- **#309's main list is the big one.** The logger prerequisite (#311) and the
  workflow-email strand (#314) are done; the **12 factory handlers remain**, with line
  ~3606 (root `Department "All Departments"`) still the highest-value single one.
- **~15 further swallows in `tests/setup/__init__.py`** were deliberately left. Same class,
  but they need the per-handler triage #309 did for the factory. The fiscal-year one has an
  extra hazard: its un-restriction runs only on the success path.
- **#308 has three sites left** — Mollie clearing account (mechanism documented on the
  issue, unverified), e-Boekhouden orphan PLE, and the general class: **35** occurrences of
  `get_all`/`get_list("Company", limit=1)` across the test tree.
- **#255** — fix the production side, and measure the settlement-batch case before choosing
  between "drop the singleton" and "TTL + `on_update` invalidation".
- **#316** remains the largest: ~146 files inheriting a frappe base class directly and
  still borrowing the settings company.
- **#291 is now demonstrably reproducible.** §7's shard table is the recipe. Any PR that
  adds a test file re-packs every shard, so "unrelated red shard on a PR that adds a test
  file" should be checked with `show_test_shards.py --find` **before** anything else.
