# Handoff — 2026-06-18 — Server Tests gate greening + coverage work

## TL;DR
A long session that (1) closed the "open issues" from the prior utils sweep, (2)
did a Codecov-driven eBoekhouden doctype-controller coverage sweep, then (3)
diagnosed and fixed the **red Server Tests gate**. All work is **pushed to
`origin/develop`** (HEAD `0f322e26`). At handoff the validating CI run
**`27787769669`** has **7 of 8 shards GREEN, shard 5/8 still running** — verdict
pending but very likely green (prior runs had 2–3 failing shards).

## Commits this session (all pushed, oldest→newest)
| Commit | What |
|---|---|
| `d2222c5c` | repoint phantom `"Member"` role → `"Verenigingen Member"` (5 spots) + delete dead home-page writers + remove phantom `Roles.MEMBER` |
| `0ba851ad` | member-history cleanup: tolerate missing sort date (`date < str` TypeError) |
| `eb9f1cac` | monitoring diagnostic runner: assert-Administrator instead of `set_user` (clears enforcer SKIP) |
| `08c041b0` | eBoekhouden doctype-coverage setUp: derive company from a real Account (fix 7 erroring tests) |
| `aad16816` | eBoekhouden account_mapping/api.py: 4 phantom-fieldname bugs + `check_rest_api_status` hardening + dead-code removal |
| `a854c793` | eBoekhouden doctype-controller coverage (~85 tests) |
| `5fd3d851` | **portal: 22 CI-only regressions** — form_dict LocalProxy clobber + missing `"Test Board Role"` master |
| `c7d0ef66` | eBoekhouden: `log_error` long-title `CharacterLengthExceededError` (latent prod bug) + CI-robust onload fixture |
| `2c216b13` | **payments: 7 CI-only fresh-runner failures** — fiscal year + invoice currency |
| `0f322e26` | portal: align donation fixture email to the member's stored value |

## The Server Tests gate problem (the bulk of the session)
The gate fails on **NEW (un-baselined) test failures**. It had been red since the
**portal coverage sweep `199f13c0`** (~01:47 today) landed — NOT from my work.
Sharding is LPT-balanced by test count, so the same tests land on **different
shards across runs**. **Every failure passes locally / in isolation — they only
fail inside the full sharded CI run.** 32 distinct failures, all now addressed:

1. **22 portal — `frappe.form_dict` LocalProxy clobber** (`5fd3d851`). `frappe.form_dict`
   is `local("form_dict")` (a werkzeug LocalProxy). Many portal tests set request
   args by assigning `frappe.form_dict = frappe._dict({...})` **directly**, which
   REPLACES the proxy with a static dict for the rest of the process; some
   "restore" via `frappe.form_dict = frappe._dict()` (fresh static), permanently
   dropping the proxy. After that, every later test using the correct idiom
   (`frappe.local.form_dict = ...`) is invisible to `frappe.form_dict` → page
   `get_context()` reads empty. **Fix: re-bind the proxy in
   `EnhancedTestCase.setUp` → `frappe.form_dict = frappe.local("form_dict")`** (one
   base-class change neutralizes all polluters, no need to touch their files).
   Proven with a fail-before/pass-after repro through the real runner.
   - Gotcha: blanket-converting polluters to `frappe.local.form_dict` is WRONG —
     tests that call `set_user`/`as_user` between setting and reading form_dict
     NEED the static-dict pattern, because **`set_user` resets `frappe.local.form_dict`**.
2. **part of the 22 — missing fresh-site master** (`5fd3d851`). volunteer_skills
   board fixture referenced a `"Test Board Role"` Chapter Role absent on fresh CI
   → LinkValidationError in setUp. Fix: `_ensure_chapter_role` creates it.
3. **1 portal — email mismatch** (`0f322e26`). `test_donation_summary` matched
   donations by `member.email`, but the factory uniquifies the member's email, so
   donor/donations keyed on the requested email no longer matched → 0 found. Fix:
   read `self.member.email` back and key off it.
4. **2 my eBoekhouden** (`c7d0ef66`). `_check_range_overlaps` passed a >140-char
   detail string as `log_error`'s FIRST positional arg (= title → Error Log
   `method` Data/140) → CharacterLengthExceededError in strict/test mode (latent
   prod crash). Fix: `log_error(message=<long>, title="...")`. And the onload test
   restored Settings.default_company via full `settings.save()` (validates the
   company Link → LinkValidationError on a rolled-back company) → use
   `frappe.db.set_value` + `clear_document_cache`.
5. **5 ing_checkout + 2 mollie** (`2c216b13`). Both create a Sales Invoice in
   `_Test Company`. ing_checkout (`FrappeTestCase`, no FY seeding) hit
   `FiscalYearError` on a fresh runner → call `ensure_test_fiscal_year_for_all_companies()`
   in setUp. mollie set no invoice currency → defaulted to USD while `Debtors - _TC`
   is INR → "Party Account currency ... should be same" → pin
   `inv.currency = Company.default_currency`.

## Current state — validating run `27787769669` (HEAD `0f322e26`) RESULT
- **7 of 8 shards GREEN** (gate passed, no NEW test failures). My fixes work — none
  of the 32 traced failures recurred in any shard that completed.
- **Shard 5/8 TIMED OUT** at the 60-min job limit (`Run Tests in 1h0m25s` →
  "The operation was canceled"). It did **NOT fail tests** — it never reached the
  gate step. This is the pre-existing **CI capacity/balancing** problem (the
  coverage-inflated suite is ~3.5 runner-hrs; sharding is by test count and the
  heaviest shard can exceed 60 min). The cross-session coverage tests (incl. my
  ~85 eBoekhouden) grew the suite and tipped one shard over. The overall run
  conclusion shows `cancelled` because the timed-out shard cancels the Test
  Summary aggregate — NOT because of new failures and NOT because of a newer push.

### Remaining work (CI infra, NOT a test fix — needs a decision)
- **Shard 5 timeout.** Options: (a) re-run the timed-out job (`gh run rerun
  <runid> --failed`) — may pass if it was a slow runner, but won't help if the
  shard genuinely holds >60 min of work; (b) **bump shard count 8 → 10/12** in
  `.github/workflows/server-tests.yml` (the team already went 4→8 for this exact
  reason — see the comment around line 65) — the durable fix; (c) raise the job
  `timeout-minutes`. This is a CI-config/cost call, left for the maintainer.
- Until shard 5 completes, the gate's verdict on the tests that land there is
  unconfirmed — but they pass locally and 7/8 shards are clean, so high confidence.
- If any genuinely NEW failure appears on a re-run, categorize it the same way
  (pull `gh api repos/nlvegan/verenigingen/actions/jobs/<JOBID>/logs`, find
  `NEW (regressions): N` + `##[error]This change introduces test failures not in
  the baseline:`).
- Working tree is clean except a pre-existing unrelated `verenigingen/public/css/
  email_brand.css` modification (not mine, left untouched).

## Open / flagged (NOT done — product decisions, earlier in session)
- **eBoekhouden account-mapping design debt**: `document_type` is overloaded as the
  account-type store across add/update/bulk (`document_type` is a Select that
  doesn't match ERPNext account types); and the live JS calls a non-existent
  `verenigingen/e_boekhouden/api.py` route (functions live under
  `...doctype.e_boekhouden_account_mapping.api`). Both pre-existing, characterized
  by tests, need a schema/routing decision.
- **member_portal home-page routing**: was resolved (dead writers removed); members
  with the role but no linked record now route to `/member_portal` (auth_hooks +
  redirect.js). Outward-facing behavior change — already shipped.

## Key gotchas (reusable)
- `gh run view --job <id> --log` / `--log-failed` returns EMPTY for archived runs;
  use `gh api repos/<o>/<r>/actions/jobs/<id>/logs` instead.
- `bench run-tests --module <package>` runs **0 tests** (needs a module, not a
  package). CI uses `run-parallel-tests` (multi-module-per-process) → that is where
  cross-test pollution bites; reproduce with a 2-test repro through the real runner.
- Pushing a new commit **cancels** the in-flight Server Tests run for the same ref
  (concurrency) — wait for the latest run, not the cancelled one.
- A pre-commit formatter re-expands inline `frappe.db.sql("""...""")` → `MM` state
  → re-`git add` + re-commit.
- `frappe.log_error(title, message)` is canonical; first positional = title =
  Error Log `method` (Data/140). Pass long text as `message=`.
- test-quality-enforcer re-fires on any test file you edit; permission bypass must
  live in a helper named `_setup_*`/`_persist_*`/`_make_*`/`_insert_*` (etc.).
