# Handoff — 2026-06-19 — 12-shard CI greening + doctype coverage sweep

## TL;DR
Two phases, both **pushed to `origin/develop` (HEAD `5931b9bf`)** and **12-shard CI
GREEN** (final run `27828970651`):

1. **Closed the prior handoff's open item** (shard-5 timeout) by bumping Server
   Tests **8 → 12 shards**. That rebucketing exposed latent **order-dependence**;
   fixed **47 tests** across 5 root causes and **baselined 7** genuinely-elusive
   ones. Gate went **54 → 7 → 2 → 0** new failures over 4 CI rounds.
2. **Codecov-driven coverage sweep** of `verenigingen/verenigingen/doctype` (the
   biggest core-logic gap): **~182 new tests across 8 controllers, ~16 real prod
   bugs fixed**, skeptical-reviewed, serial-verified, CI-green.

Develop coverage **60.92% → 61.42%**. Working tree clean except a pre-existing,
unrelated `verenigingen/public/css/email_brand.css` change (not ours).

## Commits this session (all pushed, oldest→newest)
| Commit | What |
|---|---|
| `3e440e02` | `parallel-runs: 8 → 12` in `.github/workflows/server-tests.yml` (timeout fix) |
| `b44c6c08` | fix 5 order-dependence root causes exposed by 12-sharding (47 tests) |
| `eb79e891` | Mollie dues: FY-seed fix + (attempted) clearing-account config; baseline 5 elusive |
| `7db0727c` | Mollie dues: invalidate `mollie_settings_cache` after configuring clearing account |
| `dcfb1e81` | Mollie dues: revert the Single-mutation (caused a neighbour regression); baseline the 2 dues tests |
| `bd4c94b3` | doctype coverage sweep: 8 controllers, ~182 tests, ~16 prod-bug fixes |
| `5931b9bf` | donation tests: create own Chapter (fix order-dependence in my own new tests) |

---

## Phase 1 — 8→12 shard bump and order-dependence

### Why bump shards
At 8 shards the heaviest shard exceeded the **60-min job timeout** (suite is
~3.5+ runner-hrs; `run-parallel-tests` LPT-balances by **test count**). Foppe
chose to bump shards. It's a single value: `parallel-runs` in
`server-tests.yml`; the base workflow `_base-server-tests.yml` builds the matrix
via `seq` and passes `--total-builds/--build-number` through.

### The trap: rebucketing is a BEHAVIORAL change
The gate (`scripts/testing/check_new_test_failures.py`) diffs each run's failures
against `verenigingen/tests/known_test_failures.txt` (keyed by `test_name
(dotted.path)`, **shard-independent**). But the **baseline was captured at 4
shards** — it tolerated 4→8 but broke at 4→12 because changing the bucket count
reshuffles which tests share a runner/process/DB, surfacing order-dependence.

**Every failure was the same meta-bug: a test depends on shared global/DB state it
does not establish itself; a sibling in the same bucket leaves it polluted.**
There is **no shared app-level test base** (`VereningingenTestCase`,
`EnhancedTestCase`, and the ing_checkout tests all extend `FrappeTestCase`
directly), so each fix establishes the precondition in the victim's `setUp`.

### Fixed (47 tests, commit `b44c6c08`)
1. **Currency default → USD** (`tests/payment/test_sepa_reconciliation.py`): a
   `frappe.new_doc("Bank Transaction")` inherits the global `currency` default; a
   non-EUR sibling flips it to USD → `validate_currency` throws. Fix: pin
   `bt.currency` to the bank account's `account_currency`.
2. **Template item** (`tests/backend/components/test_sepa_reconciliation.py`):
   item query picked template `_Test Variant Item`. Fix: filter
   `has_variants:0, disabled:0, is_sales_item:1`.
3. **developer_mode flag** (4 portal test classes): `@development_only` endpoints
   read `frappe.conf.developer_mode`; a sibling toggles it off. Fix: save/restore
   `frappe.conf["developer_mode"]=1` in setUp/tearDown (pattern from
   `test_setup_termination.py`; `frappe.conf` is a `frappe._dict` so
   `patch.object` does NOT work).
4. **Default tax template** (ing_checkout — BASELINED, see below).
5. **Fiscal Year** (Mollie dues — see below).

### Baselined (7 genuinely-elusive / deeply-layered — Foppe's "hybrid: fix clear,
baseline elusive"), in `known_test_failures.txt`:
- ing_checkout `TestCreatePaymentEntryWithInvoice` (3): a 16% tax inflates a
  no-taxes `_Test Company` invoice; **no `is_default` Sales Taxes template is
  attributable in app code** and clearing it in setUp did not catch the 16%
  source. (Root: `accounts_controller.set_taxes` auto-applies a company default.)
- `test_sepa_reconciliation.TestManualReconciliation.test_manual_reconciliation_creates_payment`:
  a just-inserted Bank Transaction is "not found" only under shard pollution
  (passes in isolation).
- `test_sepa_duplicate_prevention_core ...test_different_transaction_blocked`:
  cascade through `_setup_batch_linked_payment` under pollution.
- Mollie dues `TestCreatePaymentEntryForDuesEndToEnd` (2): see next.

### The Mollie-dues 3-layer saga (why those 2 ended up baselined)
The dues PE tests had a **chain** of preconditions, each fix revealing the next:
1. `FiscalYearError` (no FY for `_Test Company`) → seeded via
   `ensure_test_fiscal_year_for_all_companies()`. Worked → revealed:
2. "Mollie Clearing Account not configured in Mollie Settings". The processor
   reads it via `MollieConfigurationService.get_settings()`, which serves a
   **Redis-cached snapshot** (key `mollie_settings_cache`), NOT the live Single.
   `set_single_value` alone didn't help → also `clear_cache()`. That greened the
   2 dues tests BUT:
3. **caused a regression** — `set_single_value` left the cached **Single doc**
   pointing at a test-scoped clearing account that rolls back, so a later test's
   `settings.save()` failed `_validate_links` ("Could not find Mollie Clearing
   Account: Mollie Clearing - _TC" in `test_date_range_validation`).
**Resolution (`dcfb1e81`):** mutating a shared Single from a test pollutes others
via the document cache → reverted the Single mutation entirely (restored
`test_date_range_validation`) and **baselined the 2 dues tests**. The dues test
file is byte-identical to its pre-session original.

---

## Phase 2 — doctype coverage sweep (`bd4c94b3`, `5931b9bf`)

Method: **1 probe agent → 7 parallel agents → skeptical-code-reviewer → serial
verification → commit**. Probe (`expulsion_report_entry`, 0% cov) validated the
approach; fan-out covered the rest. ~182 new tests; 206 total across the 8
modules; all serial-verified green (parallel runs hit spurious `QueryDeadlockError`
on the shared veg11 DB — re-run serially on an idle site).

### Production bugs fixed (all surfaced by the new tests; skeptical-review APPROVED)
- **expulsion_report_entry** — entire reporting surface crashed: every path
  touching the **unshipped `Termination Appeals Process` doctype** threw (guard
  with `frappe.db.exists("DocType", ...)`); several **plain triple-quoted strings
  that should be f-strings** sent literal `{where_clause}`/`%Y` to MySQL; +
  WHERE/AND mismatches.
- **region.get_regional_coordinator** — returned a `frappe._dict`; the
  `@standard_api` wrapper (`utils/security/api_security_framework.py:992`) does
  `if hasattr(r,"to_dict"): return r.to_dict(...)`, but `frappe._dict.__getattr__`
  returns `None`, so it calls `None(...)` → **TypeError on every API call**. Fix:
  return a plain `dict`. **LATENT TRAP for any `@standard_api`/`@high_security_api`
  endpoint returning a `frappe._dict` (e.g. `get_value(as_dict=True)`).**
- **donation.generate_anbi_report_data** — `self.donation_type` (no such field) →
  `getattr`.
- **member_id_manager** — `frappe.cache().get()` returns **bytes** used in
  arithmetic at 3 sites → `cint()`; `frappe.user.has_role()` crashes because
  **`frappe.user` is a username str (LocalProxy[str]), not a User object** → use
  `frappe.get_roles()`.
- **performance_optimization_setup** — whole `after_migrate` optimization
  silently failed: `self.save()` post-submit always threw → `db_set`;
  `cache.set_value(k,v,1)` passed TTL as the positional `user` arg →
  `expires_in_sec=`; singleton never actually named `"default"` (no autoname) so
  re-created every migrate and status always "Not Applied" → set name explicitly.
- **dues_schedule_manager** — `create_direct_debit_batch` /
  `get_unpaid_membership_invoices` crashed on **orphaned Active memberships**
  (~58 on veg11; member deleted) → skip + `logger().warning`. Money-ambiguous
  issues CHARACTERIZED + flagged, NOT guessed (Membership has no `unpaid_amount`/
  `last_payment_date` fields; `get_member_bank_details` is a `{}` placeholder and
  Member has no `mandate_reference`/`bank_account` → real-member DD path is dead).
- **contact_request_automation** — `lead_doc.source` (no CRM source field) → `.get()`.
- **event_contact_campaign** — no controller bug (36 tests confirm sound).

### Two test-isolation fixes the methodology caught
- **`frappe.db.sql_ddl()` AUTO-COMMITS in MariaDB** → defeats FrappeTestCase
  rollback. performance_optimization_setup's on_submit runs CREATE INDEX, so the
  submitted `"default"` singleton leaked past rollback (docstatus=1 / status
  "Pending") → later tests early-returned Pending. Fix: setUp/tearDown purge it
  via hook-free `frappe.db.delete("Performance Optimization Setup", {"name":"default"})`.
- **donation chapter tests** (`5931b9bf`) — `frappe.get_all("Chapter", limit=1)[0]`
  assumed a Chapter exists; a fresh CI shard has none → IndexError. Fix:
  `self.create_test_chapter()` (EnhancedTestCase factory).

---

## Open / flagged (NOT done — next-session candidates)
- **`member_contact_request.create_crm_lead`** (the controller, `on_insert`) builds
  a Lead with `"notes": "<string>"`, but on veg11 the CRM Lead `notes` field is a
  **Table** (CRM Note child table) → `TypeError`, swallowed by try/except + log →
  **every Member Contact Request silently fails to create its linked CRM Lead**
  (`crm_lead` stays empty). Real bug; left out of the automation-module scope.
- **Audit `@standard_api`/`@high_security_api` endpoints returning `frappe._dict`**
  for the same `to_dict` TypeError (region just fixed one instance). Consider
  hardening the wrapper itself: `callable(getattr(result, "to_dict", None))`.
- **`pages/membership_applications/__init__.py:16`** — same broken
  `frappe.user.has_role(...)` pattern.
- **Dead stubs** to delete: `performance_optimization_setup.remove_optimizations`,
  `donation.create_mode_of_payment`, `donation.Donation.generate_anbi_report_data`
  (instance method; reporting goes through the service), `member_id_manager`
  module-level `generate_member_id(doc)` hook fn (live path is
  `core/member_id_service`).
- **veg11 data hygiene** (separate from code): ~58 orphaned Active memberships
  pointing at deleted Members; possible orphan hash-named
  `Performance Optimization Setup` docs from the old singleton-naming bug.
- **Suite still has pervasive order-dependence** (~170 baseline signatures + the 7
  baselined here). The durable fix is a real test-isolation program, not more
  baselining; lower immediate ROI than coverage.

### Next coverage targets (by miss count, test dirs excluded)
- `e_boekhouden/utils` (~5,446 misses) — heavily swept already → **dead-code
  triage first**.
- `verenigingen_payments/utils` (~3,058), `services/member` (~2,020),
  `templates/pages` (~1,520).

## Key gotchas (reusable)
- **Rebucketing CI shards is behavioral** — the `known_test_failures.txt` baseline
  is coupled to the bucket layout; any shard-count change can surface relocated
  order-dependence. Re-baseline at the chosen count or fix the isolation.
- **`frappe.db.sql_ddl()` auto-commits** → leaks committed rows past test rollback.
  Purge such rows in setUp (hook-free `frappe.db.delete`).
- **`frappe.user` is a username string**, not a User object — use
  `frappe.get_roles()` for role checks.
- **`frappe._dict` + `@standard_api`** → `hasattr(r,"to_dict")` is True but
  `r.to_dict` is None → `None(...)` TypeError. Return a plain `dict`.
- **`MollieConfigurationService.get_settings()` is Redis-cached** (key
  `mollie_settings_cache`); after writing Mollie Settings, call `clear_cache()`.
  And do NOT mutate the shared Single from a test (cached-doc dangling-link
  pollution of other tests).
- Local `bench run-tests` on ERPNext-bootstrap modules dies with
  `DuplicateEntryError: Price List 'Standard Buying'` (collides with veg11 data) —
  environment-only; CI uses a fresh site.
- Order-dependence is **NOT reproducible running a module alone** (passes in
  isolation) — the authoritative check is the full sharded CI run; verify a fix's
  *mechanism* by console-injecting the polluted global.
- Run **serial verification** after parallel coverage agents (concurrent
  `run-tests` on the shared DB → spurious `QueryDeadlockError`).
- **`git commit -m` with backticks/parens** triggers shell command-substitution and
  silently drops fragments — use `git commit -F <file>`.
- Editing any `verenigingen/**/*.py` or the workflow file triggers the push-path
  filter → server-tests auto-runs. Baseline `.txt`-only edits do NOT (path filter)
  → need `gh workflow run server-tests.yml --ref develop`.
- CI logs: `gh api repos/nlvegan/verenigingen/actions/jobs/<JOBID>/logs`
  (`gh run view --log` is empty for archived runs). The gate's new-failure list is
  between "introduces test failures not in the baseline" and "regenerate the
  baseline". Watch runs via `gh run watch <id> --exit-status` in a background shell.
