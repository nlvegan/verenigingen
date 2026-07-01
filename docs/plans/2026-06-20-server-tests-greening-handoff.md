# Server Tests greening — handoff (2026-06-20)

## TL;DR
`Server Tests (GitHub Hosted)` gate on **develop** is RED. It went red at
**`6efbaf41`** ("fix(billing): clamp dues invoice due_date to posting_date", this
morning) — the **last green run was 27855929730 (~01:21)**. Today's coverage
sweeps (4 batches, ~365 new tests) did NOT start the fire but **reshuffled the
12-shard bucket layout**, exposing more latent failures.

The gate (`scripts/testing/check_new_test_failures.py`) fails when a shard has
test failures **not in** `verenigingen/tests/known_test_failures.txt` (baseline is
2309 lines — there's a large long-standing red baseline). It does NOT mean the
whole suite is red; it means NEW (non-baselined) failures appeared.

**Already fixed (mine):** the 6 role/account sweep tests that depended on the
Frappe v16 `User.role_profiles` child table (absent on the older CI Frappe) —
guarded with a `has_field` skip in **`af51b1f4`**. Those are off the list.

## Remaining new failures — 21 across 4 shards (run 27874068873)

| Shard | Job ID | Tests | Likely cause |
|------:|--------|-------|--------------|
| 5 | 82490583656 | `test_membership_approval.TestMembershipApprovalRealIntegration`: `test_approval_default_template_fallback`, `test_approval_dict_result_handling`, `test_approval_uses_applicant_selected_template` | order-dependence OR fallout from the IBAN-history dedup change in `member_approval_service.py` (`5e9f72b5`) — CHECK FIRST |
| 8 | 82490583661 | `test_regression_invoice_due_date_calculation::test_REGRESSION_quarterly_due_date_before_posting_for_retroactive_coverage` | the morning's `6efbaf41` regression test fails in the CI env (passes on veg11). in_import/due-date behavior differs; this file was also refactored in `f0f39b93` to use `production_validation()` |
| 11 | 82490583649 | ~16: `verenigingen_payments/api/test_dd_batch_api` (most of TestDDBatchAPI), `test_dd_batch_optimizer.TestOptimizerIntegration` (create_optimal_batches, eligible_invoices x2), `vip_import/test_vip_import::test_create_volunteer_underage_throws` | **untouched in 5 days, not in baseline** → classic rebucketing-induced order-dependence (shared global state established by a neighbor test that now lands in a different shard/order) |
| 12 | 82490583668 | `verenigingen_payments/mollie/.../test_mollie_bulk_payment_creation.TestGetWebhookUrl::test_url_targets_webhook_method_and_has_env_param` | order-dependence (single test) |

(Per-shard counts at the time: shard5=3, shard8=1, shard11=16, shard12=1.)

## Why this is "rebucketing order-dependence" (the dominant cause)
The matrix splits all app tests into 12 shards. The baseline `known_test_failures.txt`
is **keyed by test-id but implicitly coupled to which shard a test lands in** (a
test only fails when it runs AFTER the neighbor that pollutes/sets up shared global
state). Adding ~365 tests today changed the bucket composition, so tests that were
"accidentally green" (their setup-provider happened to run first) now run in a new
order and fail — and they're not in the baseline for this layout. This exact
pattern is documented in prior greening rounds (see the "Server Tests 12-shard
greening" memory: 54→7→2→0 over several CI rounds).

Tell-tale: these tests **pass when run alone / on veg11** but fail only inside the
full shard.

## Triage plan (recommended order)

1. **Shard 5 approval (3) — rule out a real regression first.** My
   `member_approval_service.create_member_iban_history` dedup fix (`5e9f72b5`)
   touched the approval path. Run the integration approval suite locally:
   `bench --site veg11.veganisme.org run-tests --module verenigingen.tests.integration.test_membership_approval --lightmode`
   - If GREEN locally → order-dependence (treat like shard 11).
   - If RED locally → real regression from the IBAN change; fix it.

2. **Shard 11 SEPA-DD cluster (16) — order-dependence.** Confirm each passes in
   isolation, then find the missing shared-state setup the tests rely on (the
   common pattern: a test assumes a Direct Debit Batch / mandate / member created
   by a sibling). Either make each test self-seed its precondition (preferred,
   fixes the root cause), or baseline the elusive ones. Files:
   `verenigingen/verenigingen_payments/api/test_dd_batch_api.py`,
   `.../test_dd_batch_optimizer.py`, `verenigingen/.../vip_import/test_vip_import.py`.

3. **Shard 8 due-date regression (1).** `test_REGRESSION_quarterly_due_date_...`
   passes on veg11 (verified today) but fails on CI. Pull the CI traceback (commands
   below) and compare — likely a fiscal-year / currency / company-setup difference
   in the CI test bootstrap, or an in_import nuance. May just need the test to
   self-seed its company/FY, or be baselined if CI-env-specific.

4. **Shard 12 mollie (1).** Single test; almost certainly order-dependence — run
   in isolation, self-seed or baseline.

## Decision framework (Foppe's prior preference)
"**Hybrid: fix the clear ones, baseline the elusive ones.**" Don't sink hours into
a single order-dependence tail — if a test is genuinely green in isolation and the
shared-state provider is hard to pin, add it to the baseline and move on.

## How to regenerate the baseline (if baselining)
See the docstring of `scripts/testing/check_new_test_failures.py`. Editing
`verenigingen/tests/known_test_failures.txt` does NOT auto-trigger Server Tests
(paths filter) — after editing, manually dispatch:
`gh workflow run server-tests.yml --ref develop` (or the workflow's actual filename).

## Useful commands / gotchas
- **Fetch a shard's full CI log:** `gh api repos/nlvegan/verenigingen/actions/jobs/<JOB_ID>/logs > /tmp/shard.log`
  (NOT `gh run view --job <id> --log` — that returned empty here).
- **Extract the new-failure list:** `sed -n '/introduces test failures not in the baseline/,/looks flaky/p' /tmp/shard.log`
- **List runs:** `gh run list --workflow "Server Tests (GitHub Hosted)" --branch develop --limit 8`
- **Re-run a flaky job:** the gate hint says "If a NEW failure looks flaky, re-run the job."
- Order-dependence is NOT reproducible running a module alone (it passes); reproduce by
  running the whole shard or by console-injecting the polluted global state.
- Local `bench run-tests` on ERPNext-dep modules can die with
  `DuplicateEntryError ('Price List', 'Standard Buying')` (erpnext BootStrapTestData vs
  veg11 data) — use a real test site or veg11 `--lightmode`.

## Context: today's pushed work (all on develop, all green on veg11)
- `f0f39b93` production_validation() helper; `7add76a7`/`22fe88ec`/`266e91aa`/`626465a0` Mollie checkout repair + run_mandate_sync restore; `55d4200e` delete dead workflows.
- `9a906170`/`50d6fcb8`/`3484854c` doctype-gap 3-agent sweep (+2 bugs).
- `99f93c7d`/`5e9f72b5`/`fef6d5aa` services/member 3-agent sweep (+2 bugs: IBAN-history dedup, donor sync-status undercount).
- `8fe7fa04` invoice_generator branch coverage.
- `af51b1f4` THIS handoff's role_profiles CI fix.

All other CI checks (Code Validation, Security, Pylint, QA, CodeQL, Verenigingen CI) are GREEN; Server Tests is the only red gate.
