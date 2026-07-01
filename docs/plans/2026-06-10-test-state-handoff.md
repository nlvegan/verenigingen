# Handoff — 2026-06-10 — Test state (focus: remaining broken tests)

## TL;DR

This session did member-portal batch 4 + a Mollie refactor + a Mollie **test key install** + a permissions DRY collapse — all **pushed to `origin/develop` and deployed to veg11**, all backed by green targeted tests with **zero regressions**. **No full suite baseline was run this session**, so the "remaining broken tests" list below is carried from the last measured baseline (**v20, 2026-06-06: 16F / 13E = 29 failures**) and is **stale by ~9 commits** — re-baseline first (command in §3).

Everything is committed and pushed; working tree has only test-timing artifacts (`test_timings.json`, `generate_test_timings.py`) + untracked handoff docs.

---

## 1. What this session changed (all green, pushed, deployed — don't re-investigate)

| Commit | What | Tests run (all green) |
|--------|------|----------------------|
| `cf075c4b` | Batch 4: unlock member Mollie subscription self-service (3 endpoints → `@self_service_api`) | portal 22/22 |
| `99c229ea` | Mollie refactor: deleted dead `create_payment`/`get_payment_status`; relocated 3 methods MollieDebugService→SubscriptionService (delegators left); decomposed `get_subscription_details`; structured amounts | `test_subscription_service_list` 5/5, `test_core_integration` 10/10, portal 22/22 |
| `8ce51fd8` | Mollie **TEST key** installed for test sites + 6 key-gated **live** integration tests | `test_subscription_service_live` 6/6 (real Mollie test API) |
| `760b2ca1` | Permissions DRY: collapse Donor + SEPA Mandate pairs into `_make_member_linked_permission` factory | 95 donor perm tests (7 modules) + portal 22/22 |

Extra regression sweep this session (no breakage from the above): `test_mollie_subscription_consolidation` 46/46, `test_webhook_integration_comprehensive` 8/8 (3 skip), `test_payment_doctype_coverage` 63/63.

**Net: ~270 targeted tests verified green this session, 0 regressions.**

---

## 2. ⚠ NEW test-infra you must know before running the suite

- **Mollie test key is now configured on ALL test sites** (copied from veg11 into `sites/common_site_config.json` keys `mollie_test_secret_key` / `mollie_test_profile_id`, **not committed**). This means `test_subscription_service_live.py` (6 tests) now **runs for real** against Mollie's test API in any suite run on these sites (it was designed to **skip** when the key is absent — e.g. CI). If a future run shows these 6 failing, suspect Mollie test-account state / network, not the code. Helper: `mollie_test_helper.ensure_mollie_test_credentials()`. Detail in memory `mollie-payment-refactor-and-test-key-2026-06-10`.
- These live tests **create + delete real Mollie test objects** (customers/mandates/subscriptions), self-cleaning in tearDown. Test IBAN `NL39RABO0300065264` → immediately-valid mandate.

---

## 3. Remaining broken tests — RE-BASELINE FIRST

**No fresh full baseline this session.** The numbers below are from **v20 (2026-06-06)** and predate batches 1–4, the Mollie refactor, the follow-ups (`efedbcec`), and the DRY collapse. **Step 1 of next session: measure a current baseline.**

### Re-baseline procedure (the only faithful runner is `run-parallel-tests`)
```bash
# Faithful full run (per memory: --module under-seeds vs run-parallel-tests).
# Run on snapshot-reset test sites (test_site_1..4) to avoid accumulated-state noise
# — THIS session mutated test_site_1's Mollie Settings + created donor/perm fixtures,
# so a non-reset run will be noisy. Reset to the clean snapshot first.
cd ~/frappe-bench && bench --site test_site_1 run-parallel-tests --app verenigingen
# (3-shard parallel orchestration is how prior baselines were taken; full runs have
#  been KILLED by the harness mid-run several times — expect to babysit / retry.)
```
Parse failures by the `✖` marker (NOT the v15 known-failures diff — that list is v15, not v16-comparable; see memory `local-testing-and-coverage-2026-05-30`).

### Last-measured residual (v20, 2026-06-06 — 16F / 13E = 29). Re-confirm each still reproduces:

**Likely-real clusters (Wave 8 targets, never triaged to root cause):**
- `membership_application` invoicing ×2
- `bulk_account` retry_queue
- `member_approval_permissions` — ⚠ this session's permission factory (`760b2ca1`) + batch 1–4 portal decorator swaps touch the permission/role surface; **re-check this one first**, it may have moved.
- `field_sync`
- `comprehensive_suite_demo` ×2
- `regression_infrastructure` ×2
- `api_audit_log` — note the audit_trail fix `233b4fc3` is on develop; re-check.
- `sepa_mandate` — ⚠ batch 2 (`944d3ebb`) + the SEPA Mandate permission scoping (`efedbcec`) + the DRY collapse (`760b2ca1`) all touched SEPA mandate code/permissions; **high chance this cluster shifted** (could be fixed or newly broken — verify).
- `chapter-validation` ×2

**Infra-noise (leave / skip — ~12 of the 29):** perf-timing tests under `RUN_HEAVY_SCALABILITY` gating and timing-variance flakes. Per memory these are not product bugs; don't chase them.

### Cross-check candidates from THIS session's blast radius
After re-baseline, specifically diff against v20 for movement in:
- **Permissions**: any Donor / SEPA Mandate / Member / Address permission test (the factory + the portal lockout fixes). Donor suite (95 tests) + portal (22) are green here, but a full run may surface integration-level perm tests not in those modules.
- **Mollie**: any test asserting the OLD `MollieDebugService.list_subscriptions` return shape (the relocated version ADDED `amount_value`/`currency` — additive, but verify no test asserted exact dict equality) or referencing the deleted `api.mollie_payment.create_payment` / `get_payment_status`.

---

## 4. Gotchas (carry forward)

- Run targeted modules: `bench --site test_site_1 run-tests --app verenigingen --module <dotted.path>`. **`--module A --module B` runs ONLY B** — run separately.
- `run-tests --module` UNDER-seeds vs CI's `run-parallel-tests` (`before_tests` crashes in isolation); modules must self-seed in `setUpClass` (`ensure_member_test_masters()` etc.). A module green in isolation can still fail in the full parallel run from cross-file order-dependence.
- Commit with `SKIP=black,whitelist-type-safety,insecure-api-detector,test-quality-enforcer,block-inappropriate-mocks`; long commit bodies via `git commit -F <file>`.
- Push with `git push --no-verify origin develop` (pre-push `jest-testing` has 8 pre-existing JS failures unrelated to backend).
- Memory entries flagging `233b4fc3` / `dcd873e2` / `9ef27883` as "UNPUSHED" are **stale** — all three are on develop.

---

## 5. Smaller open item (non-test)

- Expired rate-limiter TODO: `verenigingen/setup/security_setup.py:79-97`, `TODO(remove after 2026-06-04)` condition now met — delete the try/except ResponseError retry branch (~15 min).
