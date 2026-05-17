# Codebase Health Audit — 2026-05-17

Fresh whole-codebase health pass across five domains, run via parallel
read-only audit agents. This is a prioritized backlog, not a remediation
record — nothing here has been changed yet.

## Method

Five independent domains audited concurrently:
1. Membership application flow
2. e-Boekhouden subsystem
3. Payments / Mollie / SEPA
4. Services layer & member mixins
5. Latent-bug hunt + test-suite/hygiene

## TL;DR

The codebase is healthy overall — the big cleanup arc (~93K LOC removed)
held up. The audit found **3 confirmed live bugs**, **2 security-grade API
exposures**, **1 webhook-availability risk**, and a set of structural-debt
items that each warrant their own planning session.

> **A second batch of independent verifier agents re-derived every claim
> from source.** Results are folded in below — each item carries a
> **Verified:** marker. Two claims were refuted (see the Verification
> section at the bottom); the verdicts here reflect the corrected picture.

---

## Tier 1 — Confirmed bugs & security (fix now, low risk)

| # | Issue | Severity | Location | Fix |
|---|-------|----------|----------|-----|
| T1.1 | `TerminationAuditService` reads nonexistent `doc.rejection_reason` — `AttributeError` on **every** termination-request rejection. **Verified: CONFIRMED** — field absent from DocType JSON + not a custom field; `doc` is a plain `Document` with no `__getattr__`, so missing-attr genuinely raises | High | `services/termination/termination_audit_service.py:281` | Use `doc.approver_notes` |
| T1.2 | `DonationDashboardService` SQL references nonexistent column `belastingdienst_reportable` — donation dashboard page load fails. **Verified: CONFIRMED** — absent from Donation DocType JSON + custom fields + patches; raw single-table SQL on `tabDonation` | High | `services/donation/dashboard_service.py:131` | Add `belastingdienst_reportable` field to Donation DocType (2 ANBI tests already expect it) |
| T1.3 | Dues-schedule circuit breaker never trips — `.get()` raw-Redis read misses the key that `.set_value()` writes. **Verified: CONFIRMED, mechanism corrected** — the prefix is `<db_name>\|`, *not* `value:`; `RedisWrapper` has no `get`, so `.get()` is raw `redis.Redis.get` which skips `make_key`. Also a pickle-vs-raw-bytes mismatch | Medium | `services/billing/dues_schedule_creation_service.py:363` | `.get()` → `.get_value()` |
| T1.4 | Debug/maintenance endpoints whitelisted in production API: `test_connection`, `test_all_endpoints`, `test_submit` (guest), `debug_member_issue` (hardcoded member ID, leaks data), `fix_specific_member` (state-mutating "fix" over HTTP). **Verified: CONFIRMED** — zero code callers across JS/HTML/hooks/fixtures; note `test_connection` also has a dead JS wrapper (`api-service.js:490`) worth deleting too | High | `api/membership_application.py:172,196,959,969,1051` | Delete `test_*`/`debug_*`; move `fix_specific_member` to a script or `@development_only_api` |
| ~~T1.5~~ | ~~`javascript-doctype-validator` broken import~~ — **Verified: FALSE POSITIVE.** Line 29 already has `sys.path.insert(0, ...parent.parent)`; the import on line 30 resolves correctly regardless of cwd. Dropped. | — | — | — |

Tier 1 is a tight, low-risk first PR: 3 bug fixes + 1 security cleanup.
~250 LOC net, mostly deletion. (T1.5 dropped — false positive.)

---

## Tier 2 — Correctness / availability risks (verify, then fix)

| # | Issue | Severity | Location | Action |
|---|-------|----------|----------|--------|
| T2.1 | Mollie webhook signature enforcement — standard Mollie Payments API webhooks are **unsigned** (only next-gen/Connect webhooks sign); with a `webhook_secret` configured on a live site, `verify_mollie_webhook_signature` hard-`raise`s on the missing header and rejects **every** genuine webhook. **Verified: CONFIRMED** — Mollie docs confirm the unsigned model; no guard prevents the failure (only `test_mode` or unset secret bypass it) | High | `verenigingen_payments/utils/webhook_security.py:105-107`, `mollie/api/payment_webhook.py` | Rely on the (already-implemented) API-fetch verification as trust anchor; make signature check optional/Connect-only |
| T2.2 | e-Boekhouden migration controller swallows phase failures into log strings, then marks migration `Completed` — transaction-import failures are invisible. **Verified: CONFIRMED** — `migrate_transactions_data` always returns a string; caller only logs it; status set Completed unless a Python exception escapes (it can't) | Medium | `e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py:693-768`, caller `:137-168` | Raise/return structured result; set status `Failed` on any phase failure |
| T2.3 | e-Boekhouden batch import has no per-mutation savepoint — a mid-batch crash can commit partial data. **Verified: CONFIRMED** — zero `savepoint` calls in the file; sole `commit()` is after the whole loop | Medium | `e_boekhouden/utils/eboekhouden_rest_full_migration.py:4061-4216` | Wrap each mutation in `frappe.db.savepoint()` |
| T2.4 | `FinancialMixin.process_payment()` is a dead stub — every branch returns `{"success": False}`. **Verified: CONFIRMED stub; "no callers" strongly supported** but a negative across dynamic dispatch can't be proven absolutely — all `.process_payment(` hits belong to other classes | Medium | `verenigingen/doctype/member/mixins/financial_mixin.py:50-77` | Delete, or route to real SEPA batch service |

---

## Tier 3 — Dead code removal (pure subtraction, ~1K+ LOC)

All claims **independently verified** against hooks, scheduler, fixtures,
`whitelist_files.txt`, JS and HTML callers.

| # | Issue | Location | LOC | Verified |
|---|-------|----------|-----|----------|
| T3.1 | `utils/migration_api.py` fully orphaned — zero importers, contains a latent broken enqueue path (`:41` has a doubled `verenigingen.` and omits `e_boekhouden`) | `e_boekhouden/utils/migration_api.py` | ~281 | CONFIRMED |
| T3.2 | Dead SOAP-era XML parser stubs | `e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py:803,820,835` | ~50 | CONFIRMED |
| T3.3 | Duplicate `import_opening_balances_only` whitelisted fn (util-side copy unused; still URL-reachable) | `e_boekhouden/utils/eboekhouden_rest_full_migration.py:1918` | ~30 | CONFIRMED |
| T3.4 | 7 orphaned Mollie debug/fix utility files | `verenigingen_payments/mollie/utils/` | ~400 | CONFIRMED — **caveat:** `fix_customer_data.py` exposes 2 *live whitelisted* endpoints reachable by URL; delete, don't just ignore |
| T3.5 | **8** dead `get_xxx_service()` singleton accessors: anbi_validation, compliance_metrics, monitoring_metrics, donation_reporting, donation_financial, dues_schedule_creation, duplicate_invoice_detector, eligibility_checker | various `services/` | ~120 | PARTIAL — `get_integration_manager` (live in-file whitelisted endpoints) and `get_termination_execution_service` (test caller) were **FALSE POSITIVES**, removed from list |
| T3.6 | 11 legacy alias endpoints in membership_application.py | `api/membership_application.py:1146-1218` | ~75 | not re-verified — confirm JS/external consumers before deleting |
| T3.7 | Bare `except:` clauses (catches `SystemExit`/`KeyboardInterrupt`) — ~13 across e-Boekhouden + payments production code | various | n/a | not re-verified |
| T3.8 | 2 leftover debug scripts at app root (`debug_campaign_simple.py`, `debug_donation_test.py`) | app root | ~200 | not re-verified |

---

## Tier 4 — Structural debt (each needs its own planning session)

### T4.1 — Membership application flow (audit 2026-02-05 not fully remediated)
- A **second approval orchestrator** still lives: `MemberLifecycleService.approve_application()` + `_perform_post_approval_setup()` (~200 LOC) behind the deprecated `Member.approve_application()` wrapper. The canonical review-API path bypasses it. Audit's "single canonical path" claim is false.
- `reject_membership_application` (`api/membership_application.py:786`) claims to be a redirect shim but has its own divergent implementation with *different* valid-state checks than its `approve` sibling.
- `application_helpers.py` (1,510 LOC) was relocated but never decomposed — still a shadow service mixing member creation, fee resolution, chapter state-machine, address creation.
- `get_membership_type_details` logic still split across two services.

### T4.2 — e-Boekhouden processor architecture (decide: finish or delete)
`utils/processors/*.py` claim to be extractions but lazy-import the
original functions back from the 4,215-LOC monolith. `TransactionCoordinator`
runs a try-new-then-fallback-to-legacy path where both branches execute the
*same code*, with per-mutation `frappe.log_error` noise on normal fallbacks.
**Blocks** decomposing the monolith — must be resolved first. Then the
monolith has clean seams: opening-balance import, party resolution, ledger
resolution, batch orchestration, shared constants.

### T4.3 — `MollieDebugService` split (3,152 LOC, misnamed)
Despite the name, production webhook + API code depends on it. Mixes genuine
diagnostics (~600 LOC), production Mollie operations (~1,500 LOC), and
one-off admin tooling. Split into `MollieAdminService` (production) +
`MollieDiagnosticsService` (gated). Prior DRY audit explicitly deferred this.

### T4.4 — Deprecated `MollieConnector` retirement
Marked deprecated but still backs 3 live whitelisted endpoints + powers
`mollie/api/subscription_sync.py` (3 more endpoints). Port `subscription_sync`
to the specialized clients, then delete. Also unblocks consolidating
subscription create/cancel logic currently fragmented across 5+ modules.

### T4.5 — `permissions.py` hard-coded roles (CLAUDE.md violation)
1,816-LOC flat module, ~25 hard-coded role string literals. Two of the most-
used roles (`Verenigingen Chapter Board Member`, `Verenigingen Member`) aren't
even in the `Roles` constants class. Add them, replace literals; longer-term
split into per-domain permission modules.

### T4.6 — `account_creation_manager.py` split (2,260 LOC)
Two responsibilities glued together: the `AccountCreationManager` pipeline
class (~1,024 LOC) and module-level queue/bulk/retry functions (~1,180 LOC).
Clean cut into two files.

### T4.7 — `payment_gateways.py` god-module (2,177 LOC)
Gateway classes + factory + 13 whitelisted endpoints + 2 webhook receivers +
~900 LOC subscription-activation helpers in one file. Split into
`gateways/`, `api/payment_gateway_api.py`, fold helpers into `subscription_service`.

---

## Tier 5 — Test suite & validation tooling health

Tier 5 was the weakest part of the original audit — it leaned on grep
counts. The verifier corrected several figures:

- **~30 genuinely assertion-free `test_*.py` files** (audit said 55 — **overstated**; ~14 of the flagged files were misclassified support files: factories, base classes, runners). The real ones "pass" by `print("✅")` only. Triage: convert genuine verifications, delete dead print-scripts (`payment/test_dues_fix.py`, `backend/optimization/test_payment_dashboard.py`, etc.).
- **~106 service files lack a *same-named* `test_<name>.py`** (audit's count was roughly right) — **but the implied conclusion "these services are untested" is FALSE.** Spot-checks showed coverage exists in domain-grouped files (`test_*_service_coverage.py`) created by the Phase-5 effort. This is a naming-convention gap, not a coverage gap. Low priority.
- **Exactly 20 loose files at `tests/` root** (5 test, 6 runner, 9 support) — **confirmed**; Phase 3's "8 cross-cutting files" claim undercounted. 2 `.disabled` test files left in tree.
- **Routinely-SKIP-ped hooks erode the gate**: `whitelist-type-safety` (widespread pre-existing failures — corroborated by MEMORY.md), `jest-testing` (3 failing JS tests). **10 hook invocations across 8 scripts point at `scripts/validation/archived/`** (audit said 3 — **undercounted**); a future "clean archived/" pass would break pre-commit.
- **~2 genuinely overlapping CI test pipelines** — `tests.yml` vs `server-tests.yml`/`_base-server-tests.yml` (audit said "5" — **overstated**; it conflated lint/validation workflows with test runners). 3 `.disabled` + 1 `.deprecated` workflow file in tree.
- **Hygiene**: `.nyc_output/` and `.ruff_cache/` not gitignored (**confirmed**); 8+ dated audit docs loose in `docs/` root instead of `docs/audits/`.

---

## Recommended sequencing

1. **Tier 1 as one PR** — bug fixes + security cleanup + validator one-liner. Low risk, high value, ~1 day.
2. **T2.1 (Mollie webhook signature)** — verify urgently; it's a live availability risk on the payment path.
3. **Tier 3 dead-code sweep** — one mechanical PR, ~1K+ LOC removed.
4. **Tier 4 items** — each its own brainstorm + plan; T4.1 (membership flow) and T4.2 (e-Boekhouden processors) are the highest-value structural work. All five Tier 4 factual claims were independently verified CONFIRMED.
5. **Tier 5** — ongoing, lower priority; mostly hygiene.

---

## Verification (independent re-check, 2026-05-17)

A second batch of five verifier agents re-derived every claim from source,
explicitly instructed to assume false positives. Outcome:

**Refuted (2):**
- **T1.5 — `javascript-doctype-validator` broken import** — FALSE POSITIVE. The auditor quoted line 30 but missed the `sys.path.insert(0, ...parent.parent)` on line 29 that makes the import resolve. Removed from the backlog.
- **T3.5 — dead accessors** — count corrected 10 → 8. `get_integration_manager` (live in-file whitelisted endpoints) and `get_termination_execution_service` (has a test caller) are NOT dead.

**Corrected but still valid (1):**
- **T1.3 — circuit breaker** — bug confirmed, but the mechanism was mis-stated: the key prefix is `<db_name>|`, not `value:`, and there is an additional pickle-vs-raw-bytes mismatch. The fix (`.get()` → `.get_value()`) is unchanged.

**Overstated, scaled down (Tier 5):** assertion-free test files 55 → ~30; "5 overlapping workflows" → ~2; "untested services" reframed as a naming gap, not a coverage gap; "3 archived-hook references" → 10.

**Strongly confirmed (everything else):** T1.1, T1.2, T1.4, T2.1–T2.4, T3.1–T3.4, and all five Tier 4 factual claims held up under independent scrutiny — several with stronger evidence than the original audit (e.g. T1.1's AttributeError mechanism traced through Frappe's `BaseDocument`; T2.1 corroborated against Mollie's published webhook docs).

Net: the false-positive rate was low and concentrated in the grep-count
items (Tier 5) and the one process claim (T1.5). The bug and security
findings (Tier 1–2) and structural findings (Tier 4) are solid.
