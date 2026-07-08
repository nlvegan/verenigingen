# Test Inventory — Handoff

---
## ✅ FALSE-CONFIDENCE GAP CLASS — REMEDIATED (2026-07-08, all 10 modules done)

The systemic **false-confidence** weakness this inventory surfaced (0-assert / tautological /
skip-dominated / mock-into-tautology tests — the ~650 "Other" methods and the named offenders in
each report) has been **remediated across all 10 risk-ordered modules** on branch
`refactor/test-false-confidence-remediation` (Waves 1–4). Full per-module breakdown, commits, and
the exact deleted/rewritten/added counts live in
`../test-remediation/REMEDIATION-TRACKER.md` — that tracker is the source of truth.

**Aggregate (Waves 1–4, all counts test-files-only — ZERO production files modified in the entire branch):**
- **~18 test files + ~55 standalone tautological/dead methods deleted** (each re-grepped for callers;
  dead prod targets logged to `../test-remediation/backlog-dead-code.md`, missing features to
  `backlog-missing-coverage.md` — never silently dropped).
- **~85 methods + 4 empty scaffolds rewritten** to call REAL production code (validators, status
  services, PaymentProcessor, SEPA mod-97, chapter postal-matching, etc.) instead of in-test
  reimplementations / mocks-of-the-function-under-test.
- **~27 new tests added** — ~10 genuine UNHAPPY gap-fill (real raise/throw/permission-denial, not
  graceful-fallback) + 17 scaffold tests for previously-untested bookkeeping/tracker doctypes.
- **Every rewrite and every new test mutation-verified** (green → break the prod target → confirm RED
  → revert). **Coverage Δ ≥ 0 for every module** (deletions were zero-coverage or covered-elsewhere).
- **Each wave passed an independent `skeptical-code-reviewer` adjudication** reading the prod code
  under test; all 10 modules APPROVED with 0 Critical/Important findings.

Remaining known gaps are **not** false-confidence — they are genuine missing-coverage / dead-prod-code
items deferred to the two backlog files (e.g. `PaymentContextResolver.Member.payment_id` bug making
strategy-4 unreachable; server-side exclusive-default enforcement; HRMS Expense-Claim treasurer flow;
SEPA audit-trail auto-wiring). Those need PRODUCTION changes and were correctly kept out of this
test-files-only roadmap.
---

**Status as of this session.** A test-type inventory (Happy / Unhappy / Edge / Other)
was run by parallel test-engineer agents, 3 domains at a time. All reports are
**persisted in this folder** (`verenigingen/docs/testing/test-inventory/`), which is
in the git working tree (currently **untracked** — `git add` when you want them
version-controlled).

## Where everything lives
- `00-TRACKER.md` — master status board: every domain, file counts, per-domain
  H/U/E/O totals, grand total, progress log. **Start here.**
- `01`–`20` `*.md` — per-domain reports, each with a per-file table
  (`| File | Total | Happy | Unhappy | Edge | Other |`) + observations.
- `99-SUMMARY.md` — cross-cutting synthesis (patterns, weak-test catalogue, gaps).
- `HANDOFF.md` — this file.

## What is DONE (37 reports · 1,132 files · 20,180 test methods)
| Segment | Reports | Files | Methods |
|---|---|---|---|
| Phase 1 — main-app services | 01–11 | 205 | 3,540 |
| Phase 1b — shared infrastructure | 15, 16 | 47 | 787 |
| Phase 1c — security framework | 17 | 38 | 897 |
| Phase 2 — payments app | 12a–14 | 100 | 1,755 |
| Phase 3 — tests/payment + backend/components | 18, 19, 20 | 245 | 4,695 |
| Phase 4 — member / portal / chapter / integration | 21, 22, 23, 24 | 171 | 2,637 |
| Phase 5 — e_boekhouden (accounting sync) | 25a, 25b, 25c | 87 | 1,944 |
| Phase 6 — report / unit / donor / api | 26, 27, 28, 29 | 91 | 1,425 |
| Phase 7 — backend/unit/api + validation + integration | 30, 31, 32 | 51 | 746 |
| Phase 8 — co-located doctype controllers + mijnrood_sync | 33, 34, 35, 36 | 97 | 1,754 |
| **TOTAL** | | **1,132** | **20,180** |

**Type mix (strikingly stable across every segment):**
Happy **41.0%** · Unhappy **16.7%** · Edge **35.5%** · Other **6.8%**.
(Phase 8 alone: 738H/300U/618E/98O = 42.1/17.1/35.2/5.6% — right on the app-wide curve.)

See `METHODOLOGY.md` for how the audit was run (categories, agent contract, why "no sub-agents").
Headline: solid happy+edge coverage; **unhappy/negative-path is the systemic thin spot (~17%)**,
and ~650 methods are weak/dead (Other).

## What is NOT yet audited — ~132 files, bucket C only (of ~1,264 total; ~90% done)
**Bucket A — Co-located DocType controller tests — ✅ DONE (Phase 8, reports 33/34/35).**
All 76 `verenigingen/verenigingen/doctype/*/test_*.py` classified: 1,243t · 526H/219U/406E/92O.

**Bucket B — mijnrood_sync sub-app + stray co-located — ✅ DONE (Phase 8, report 36).**
21 files (`verenigingen/mijnrood_sync/**` incl. services + doctypes + top-level client/sftp/ssh/tasks,
`e_boekhouden/services/tests` ×2, `events/subscribers` ×1): 511t · 212H/81U/212E/6O.
NOTE: an earlier estimate listed a `utils/migration` stray in bucket B — it was not part of report 36;
confirm/sweep it during bucket C if it exists.

**Bucket C — remaining `tests/` subtrees (~130) — the only bucket left:** `tests/` loose top-level (19),
`backend/comprehensive` (14), `volunteer` (12), `workflows` (11), `backend/workflows` (9),
`email` (8), `events` (7), `www` (5), `membership` (5), `financial` (5), `fixtures` (4),
`backend/{security 4, features 4, business_logic 3, unit/controllers 3}`, `scalability` (3),
`unit/utils` (2), `performance` (2), + small dirs (safety, resilience, repositories,
frontend/integration, e2e, billing, backend/unit/doctype).

Resume with the same wave-of-3–4 pattern; number new reports `33+`. See `METHODOLOGY.md`.

## How to resume (same method)
1. Read `00-TRACKER.md` to see status.
2. Pick a tree, split into ~20–30-file domains (bigger trees → 2–3 agents).
3. Dispatch **general-purpose** agents, **3 at a time**, with this contract:
   - READ-ONLY; classify each class-level `def test_*` as HAPPY/UNHAPPY/EDGE/OTHER.
   - **Do the work themselves — forbid spawning sub-agents** (that blew the session-token
     budget on the first Phase-3 attempt).
   - **Write the report incrementally** (header first, append each file's row as classified)
     so partial progress survives an interruption.
   - Output to `verenigingen/docs/testing/test-inventory/NN-<domain>.md`.
4. After each wave: update `00-TRACKER.md` (status + H/U/E/O), then refresh the grand
   total + `99-SUMMARY.md`.

## Highest-value gap-filling targets found so far (concrete, start here)
These are the worst offenders surfaced across reports — quick wins for raising real coverage:

**Delete / rewrite — tests that assert nothing (dead or debug scripts):**
- `tests/services/test_donation_refactoring_integration.py` — print-based manual harness, 0 `def test_*`.
- `sepa/test_enhanced_sepa_integration.py` — non-unittest print script, swallows all failures.
- mollie `test_payment_entry.py`, `test_subscription_creation.py`, `test_subscription_fixes.py`,
  `test_webhook_directly.py` — debug scripts, hit real API / hardcoded prod records, 0 asserts.
- `tests/payment/test_dues_schedule_system.py`, `test_payment_plan_system.py` — module-level print debug, 0 asserts.
- `tests/backend/optimization/*` (all 5) — non-collected copy-paste smoke, only print timings.
- `tests/backend/performance/test_api_performance.py` — 9/9 tautological (asserts stdlib arithmetic).

**Tautologies / can't-fail (rewrite to assert real behavior):**
- `backend/unit/services/test_approval_unification.py` — 17/17 AST-string / getattr refactor asserts.
- `verenigingen_payments/tests/test_api_regression.py` — 14/15 `isinstance`-OR-exception tolerant;
  `hasattr(...__name__)` disjunct always true.
- mollie `test_payment_context_resolver.py` — 7/14 assertion-free "doesn't crash".
- `tests/utils/test_notification_helpers.py` — 6/23 re-implement prod logic in-test; one `assertTrue(True)`.
- `doctype/sepa_audit_log/test_sepa_audit_log.py` — lone `assertTrue(True)` placeholder;
  `sepa_mandate/test_sepa_mandate_comprehensive.py` — 5 save-then-assert-nothing placeholders.
- e_boekhouden `test_cost_center_ui_integration.py` — 8/12 OTHER (3 patch the whitelisted fn they
  then call and assert the mock's return; 4 UI "simulations" with no production surface).
- e_boekhouden `test_party_resolver.py` — patches `frappe` wholesale, 9/35 config-shape/delegation
  tautologies (its real-DB twin `test_party_resolver_coverage.py` is the meaningful one).
- e_boekhouden `test_transaction_type_classification.py::test_unknown_numeric_type_raises_error`
  and `test_payment_processor_sweep::TestLinkBankTransactionToPayment` — lock in a known bug /
  test dead code with no production caller (see report 25c). Members/dutch-business tests from
  Phase 4 (`test_dutch_business_logic_integration.py` 14/40, `test_member_status_transitions_enhanced.py`
  3× bare `pass`) and chapter's archived-DocType skips (`test_chapter_board_permissions_comprehensive.py`
  8/12 skipped) also belong on this list.
- **tests/unit reimplements production logic in-test** (green but regression-inert): `test_payment_direction.py`
  (12/12 re-implement the `is_incoming` expression), `test_member_lifecycle_unit.py` (12/15 inline
  helpers), `test_sepa_business_logic_unit.py` (12/13 inline validators); `test_member_lifecycle_production_issues_discovered.py`
  is 7/7 pure `print()` (0 asserts); the `*_mock_elimination.py` pair swallows failure branches in try/except.
- **Shape-only API tests**: `tests/api/test_sepa_health.py` (10/10 key-presence+type only), `test_security_monitoring_dashboard.py`
  (7 envelope-shape/`0<=x<=100` tautologies); report `test_is_membership_related_always_true` (asserts an always-True fn).
- **Known-bug tripwires** (intentional, keep but track): `tests/api` `test_broken_link_detection_is_currently_dead_code`
  and the `link.type` vs `link_type` pin — mirror the e_boekhouden ones in report 25c.
- **Consolidation candidate (not weak, just duplicated):** `tests/donor` has 7 overlapping
  `test_donor_permissions*.py` + `test_donor_security_*.py` files; `_enhanced.py` and `_enhanced_fixed.py`
  are near-identical (same test names).
- **Phase 7 dead/weak:** `backend/unit/api/test_chapter_api.py` (13/17 Other — `assertIsNotNone` +
  `try/except: pass` that pass even if the endpoint doesn't exist); `backend/validation/test_api_endpoints.py`
  (all 5 classes `@unittest.skip` — pseudo-tests on nonexistent endpoints, self-mock results);
  `backend/integration/test_eboekhouden_integration.py` (12/12 skipped, "outdated schema") and
  `test_erpnext_expense_integration.py` (13 archived-DocType skips + 8 setup-only);
  `test_javascript_api_integration.py` (5/7 are static `grep` source-lints misfiled as integration);
  `validation/test_fuzzy_logic_modernization_validation.py` (4/20 `try/except: pass`, several
  "negative_case_*" assert the positive path).
- **Phase 8 (co-located doctype + mijnrood_sync) dead/weak:**
  - Empty scaffolds (0 class-level test methods — real coverage gaps): `doctype/bulk_operation_tracker/test_bulk_operation_tracker.py`,
    `doctype/verenigingen_payments_settings/test_verenigingen_payments_settings.py`,
    `mijnrood_sync/doctype/mijnrood_sync_log/test_mijnrood_sync_log.py`,
    `mijnrood_sync/doctype/mijnrood_sync_state/test_mijnrood_sync_state.py` (write-only bookkeeping doctypes, untested).
  - `doctype/membership_termination_request/test_membership_termination_request_critical.py` — 8/8 OTHER; a
    "critical"-named file that pins nothing regression-catching. `test_membership_termination_request.py` is 8/16 OTHER.
  - `doctype/volunteer/test_volunteer.py` — 30 methods, 13 OTHER (43%): five tests assert attrs that are NOT
    Volunteer fields per `volunteer.json` (`phone`, `address`, `development_goals`, `emergency_contact_*`,
    `training_records`, `languages_spoken`) → vacuous / never-persisted; plus pass-either-way permission tests
    (accept `"1=0"`), a fully `skipTest`-ped board-integration test, and shape-only/schema-contract meta tests.
  - `doctype/expense_category/test_expense_category.py` — all methods `skipTest`-guarded, silently no-op on a bare site.
  - Small tautologies: `test_membership.py::test_payment_sync` (db_set roundtrip), `test_membership_type.py::test_default_membership_type`
    (asserts flags it just set, documenting unimplemented behavior), `mijnrood_sync` `TestStaticMappingConstants`
    (4 static-constant drift guards, no code path), `test_create_volunteers_batch_uses_service` (mock-into-tautology).
  - Strongest Phase-8 files (meaningful, keep as models): `doctype/member/test_member_id_manager.py` (24, 0 OTHER —
    atomic-counter + self-heal-on-drift + cache-bytes tripwires), `doctype/event_contact_campaign/test_event_contact_campaign.py`
    (full permission-query/role matrices), and the mijnrood_sync security core `test_sftp_client.py` / `test_ssh_auth.py`
    (SQL-injection guards, path traversal, oversized files, changed-host-key MITM tripwire — the domain's densest UNHAPPY).

**Under-tested negative paths (add unhappy tests):**
- Core money-path services with ~0 unhappy: member fee-change-history (both), payment-history realdb,
  billing-date, bank-reconciliation-coverage.
- SEPA FRST→RCUR sequence-type on real collections — only ~1 end-to-end transition test.
- Advisory-lock contention (member import) — success path only, never contention/timeout.
- Field-sync failure/rejection paths (`test_field_sync_integration.py`) — config inspected, sync never run to fail.
- `tests/backend/components` UNHAPPY is only 10% and clustered in 2 security files — most feature/report
  tests assert success shape only.

**Pattern to grep-audit repo-wide (low regression value):**
- `*_never_throws_exceptions` loops asserting only `assertIsNotNone(result.success)` (always a bool).
- `if result["success"]:`-guarded assertions that pass on the failure branch.
- `@unittest.skip` clusters — e.g. `tests/payment/test_payment_integration_workflows.py` (8/8 skipped),
  `security/test_security_penetration.py` (8/12 skipped).

## Caveats on the numbers
- Counts are class-level `def test_*` (nested helper defs excluded). A few files noted small
  grep-vs-real discrepancies in their reports.
- Happy/Unhappy/Edge boundary is a judgement call where services return `False`/error-dicts instead of
  raising — those were mostly counted EDGE, so **true asserted-failure coverage is even thinner than the 17%**.
- Phase 3's first run produced **no output** (session-token limit); the values here are from the
  clean re-run. Two BC1 spot-check fragments from the failed run were re-verified and matched.
