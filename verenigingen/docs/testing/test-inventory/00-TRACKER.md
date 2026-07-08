# Test Suite Inventory — Type Classification (happy / unhappy / edge)

Scope: **services layers** of the main app (`verenigingen/services/*`) and the
payments app (`verenigingen/verenigingen_payments/*`). Each domain is audited by
a test-engineer agent that classifies every test method as:
- **HAPPY** — nominal success path
- **UNHAPPY** — expected errors, validation failures, permission denials, throws
- **EDGE** — boundaries, empty/null, concurrency, idempotency, unusual data
- **OTHER** — setup/smoke/import-safety/tautological (flagged)

Each agent writes `NN-<domain>.md` to this folder and returns a summary.

Legend: ⬜ pending · 🟨 running · ✅ done

## PHASE 1 — Main app services

| ID | Domain | Files | Status | Output |
|----|--------|-------|--------|--------|
| A1 | Member core services (identity/status/validation/role) | 16 | ✅ | 01-member-core.md — 305t: 135H/44U/115E/11O |
| A2 | Member approval/application/creation + event_application | 17 | ✅ | 02-member-approval.md — 311t: 139H/39U/124E/9O |
| A3 | Donation & Donor services | 11 | ✅ | 03-donation-donor.md — 146t: 59H/22U/57E/8O |
| A4 | Member financial/fee/dues/history + billing dates | 13 | ✅ | 04-member-financial.md — 173t: 64H/18U/76E/15O |
| A5 | Termination + Chapter + Volunteer services | 12 | ✅ | 05-term-chapter-vol.md — 258t: 141H/43U/67E/7O |
| A6 | Billing (co-located services/billing) + customer/invoice | 26 | ✅ | 06-billing.md — 527t: 232H/77U/175E/43O |
| A7 | backend/unit/services — part 1 (member-focused) | 18 | ✅ | 07-backend-unit-svc-1.md — 254t: 106H/42U/69E/37O |
| A8 | backend/unit/services — part 2 (approval/payment/donation) | 18 | ✅ | 08-backend-unit-svc-2.md — 259t: 118H/63U/68E/10O |
| A9 | SEPA services — mandate lifecycle/validation | 13 | ✅ | 09-sepa-mandate.md — 267t: 114H/36U/114E/3O |
| A10a | SEPA — batch/validation/reconciliation core | 12 | ✅ | 10a-sepa-batch.md — 198t: 96H/23U/65E/14O |
| A10b | SEPA — sequence/performance/security/week/integration | 15 | ✅ | 10b-sepa-adv.md — 195t: 103H/17U/48E/27O |
| A10c | Ponto (bank/oauth/webhook/payment clients) | 12 | ✅ | 10c-ponto.md — 279t: 97H/85U/87E/10O |
| A11 | integration/services + unit/services + tests/services/payment + mollie_sync/polling | 20 | ✅ | 11-svc-integration.md — 368t: 151H/70U/128E/19O |

## PHASE 2 — Payments app (verenigingen_payments) services
(Note: ponto has no tests inside the payments app — Ponto tests live in main-app tests/sepa, audited in A10c.)

| ID | Domain | Files | Status | Output |
|----|--------|-------|--------|--------|
| P1a | mollie/tests — part 1 (amount/bulk/core/dues/orchestrator) | 22 | ✅ | 12a-mollie-1.md — 368t: 133H/81U/145E/9O |
| P1b | mollie/tests — part 2 (debug/payment-entry/processors/webhook/subscription) | 22 | ✅ | 12b-mollie-2.md — 402t: 159H/98U/134E/11O |
| P1c | mollie/tests — part 3 + mollie/api + mollie/services/shared + mollie/utils | 24 | ✅ | 12c-mollie-3.md — 245t: 115H/50U/66E/14O |
| P2 | ing_checkout/tests (client/mandate/webhook/transaction) | 14 | ✅ | 13-ing.md — 238t: 103H/64U/64E/7O |
| P3 | verenigingen_payments/{api,core,services,tests,tests/utils_shared,utils} + doctype tests | 26 | ✅ | 14-payments-core.md — 502t: 203H/65U/187E/47O |

## PHASE 3 — Main-app payment domain + backend components — COMPLETE ✅
| ID | Domain | Files | Status | Output |
|----|--------|-------|--------|--------|
| PAY1 | tests/payment — sorted files 1–85 | 85 | ✅ | 18-payment-1.md — 1809t: 623H/323U/809E/54O |
| PAY2 | tests/payment — sorted files 86–170 | 85 | ✅ | 19-payment-2.md — 1936t: 792H/390U/677E/77O |
| BC1 | tests/backend/components | 75 | ✅ | 20-backend-components.md — 950t: 538H/93U/288E/31O |

**Phase 3 subtotal:** 245 files · 4,695t · 1,953H/806U/1,774E/162O

## PHASE 4 — member / portal / chapter / integration — COMPLETE ✅
| ID | Domain | Files | Status | Output |
|----|--------|-------|--------|--------|
| MEM | tests/member | 54 | ✅ | 21-member.md — 1040t: 481H/159U/331E/69O |
| PORT | tests/backend/portal | 41 | ✅ | 22-portal.md — 555t: 236H/208U/111E/0O |
| CHAP | tests/chapter | 38 | ✅ | 23-chapter.md — 701t: 299H/109U/251E/42O |
| INTEG | tests/integration (excl. services/) | 38 | ✅ | 24-integration.md — 341t: 144H/55U/81E/61O |

**Phase 4 subtotal:** 171 files · 2,637t · 1,160H/531U/774E/172O

## PHASE 5 — e_boekhouden (accounting sync) — COMPLETE ✅
| ID | Domain | Files | Status | Output |
|----|--------|-------|--------|--------|
| EBKH1 | tests/e_boekhouden — sorted 1–29 | 29 | ✅ | 25a-eboekhouden-1.md — 721t: 256H/90U/334E/41O |
| EBKH2 | tests/e_boekhouden — sorted 30–58 | 29 | ✅ | 25b-eboekhouden-2.md — 572t: 179H/80U/283E/30O |
| EBKH3 | tests/e_boekhouden — sorted 59–87 | 29 | ✅ | 25c-eboekhouden-3.md — 651t: 264H/57U/316E/14O |

**Phase 5 subtotal:** 87 files · 1,944t · 699H/227U/933E/85O

## PHASE 6 — report / unit / donor / api — COMPLETE ✅
| ID | Domain | Files | Status | Output |
|----|--------|-------|--------|--------|
| REP | tests/report | 29 | ✅ | 26-report.md — 421t: 140H/20U/192E/69O |
| UNIT | tests/unit (excl. services/) | 23 | ✅ | 27-unit.md — 430t: 165H/54U/106E/105O |
| DON | tests/donor | 20 | ✅ | 28-donor.md — 296t: 116H/68U/86E/26O |
| API | tests/api | 19 | ✅ | 29-api.md — 278t: 101H/50U/95E/32O |

**Phase 6 subtotal:** 91 files · 1,425t · 522H/192U/479E/232O

## PHASE 7 — backend/unit/api + validation + integration — COMPLETE ✅
| ID | Domain | Files | Status | Output |
|----|--------|-------|--------|--------|
| BUAPI | tests/backend/unit/api | 15 | ✅ | 30-backend-unit-api.md — 298t: 115H/60U/91E/32O |
| VALID | tests/backend/validation | 19 | ✅ | 31-backend-validation.md — 229t: 75H/36U/73E/45O |
| BINTEG | tests/backend/integration | 17 | ✅ | 32-backend-integration.md — 219t: 71H/34U/60E/54O |

**Phase 7 subtotal:** 51 files · 746t · 261H/130U/224E/131O

## PHASE 8 — co-located DocType controller tests + mijnrood_sync — COMPLETE ✅
(Bucket A = the standard Frappe `doctype/*/test_*.py` pattern, never reached by the tests/-tree sweeps. Bucket B = mijnrood_sync sub-app + stray co-located service tests.)

| ID | Domain | Files | Status | Output |
|----|--------|-------|--------|--------|
| DT1 | doctype/ controllers — sorted 1–26 (account_creation…member_contact_request) | 26 | ✅ | 33-doctype-1.md — 436t: 191H/79U/138E/28O |
| DT2 | doctype/ controllers — sorted 27–50 (member/mixins…member_utils) | 24 | ✅ | 34-doctype-2.md — 337t: 133H/49U/111E/44O |
| DT3 | doctype/ controllers — sorted 51–76 (mijnrood_csv_import…volunteer) | 26 | ✅ | 35-doctype-3.md — 470t: 202H/91U/157E/20O |
| MJ | mijnrood_sync sub-app + e_boekhouden/services/tests + events/subscribers | 21 | ✅ | 36-mijnrood-sync.md — 511t: 212H/81U/212E/6O |

**Phase 8 subtotal:** 97 files · 1,754t · 738H/300U/618E/98O
(Bucket A = 76 doctype files across DT1/DT2/DT3 = 1,243t; Bucket B = 21 files = 511t.)

---
## ROLLUP (Phases 1 & 2 — services layers) — COMPLETE ✅

18 domains · **305 test files** · **5,295 test methods**

| Segment | Files | Total | Happy | Unhappy | Edge | Other |
|---------|------:|------:|------:|--------:|-----:|------:|
| Phase 1 — main app services | 205 | 3,540 | 1,555 | 579 | 1,193 | 213 |
| Phase 2 — payments app | 100 | 1,755 | 713 | 358 | 596 | 88 |
| **TOTAL** | **305** | **5,295** | **2,268** | **937** | **1,789** | **301** |
| **% mix** | | | **42.8%** | **17.7%** | **33.8%** | **5.7%** |

## PHASE 1b — Shared infrastructure (added batch)

| ID | Domain | Files | Status | Output |
|----|--------|-------|--------|--------|
| I1 | Infrastructure svc + framework + optimization/performance + infra utils | 24 | ✅ | 15-infra-framework.md — 314t: 147H/45U/97E/25O |
| I2 | Shared utils / helpers (tests/utils + backend/unit/utils) | 23 | ✅ | 16-shared-utils.md — 473t: 206H/47U/198E/22O |

**Shared-infra subtotal:** 47 files · 787t · 353H/92U/295E/47O

## PHASE 1c — Security framework (added)
| ID | Domain | Files | Status | Output |
|----|--------|-------|--------|--------|
| S1 | tests/security (auth/authz/rate-limit/CSRF/permissions/toctou/pentest) | 38 | ✅ | 17-security.md — 897t: 316H/161U/281E/139O |

## GRAND TOTAL (through Phase 8) — 1,132 files · **20,180 test methods**
Happy 8,270 (41.0%) · Unhappy 3,376 (16.7%) · Edge 7,167 (35.5%) · Other 1,367 (6.8%)
(Was, through Phase 7: 1,035 files · 18,426t · 7,532H/3,076U/6,549E/1,269O.)

## Progress log
- (init) Tracker created. Launching Wave 1 = A1, A2, A3.
- Wave 1 ✅ A1/A2/A3 · Wave 2 ✅ A4/A5/A6 · Wave 3 ✅ A7/A8/A9
- Wave 4 ✅ A10a/A10b/A10c · Wave 5 ✅ A11/P1a/P1b · Wave 6 ✅ P1c/P2/P3
- Shared-infra ✅ I1/I2 · Security ✅ S1
- Phase 3 ✅ PAY1/PAY2/BC1 (first attempt died on session limit with no output; re-run wrote all 3 incrementally).
- Phase 4 ✅ MEM/PORT/CHAP/INTEG (4 concurrent agents, no sub-spawn, incremental writes).
- Phase 5 ✅ EBKH1/EBKH2/EBKH3 (e_boekhouden, 3 concurrent agents).
- Phase 6 ✅ REP/UNIT/DON/API (4 concurrent agents).
- Phase 7 ✅ BUAPI/VALID/BINTEG (backend/unit/api + validation + integration, 3 concurrent agents).
- Phase 8 ✅ DT1/DT2/DT3/MJ (buckets A+B; 4 concurrent agents). First attempt died on the weekly session limit mid-write (partial WIP tables, no totals/observations, tracker not updated); re-run completed the missing tail files in each report and finalized all four. Bucket A = all 76 co-located `doctype/*/test_*.py`; Bucket B = 21 mijnrood_sync + stray co-located service tests.
- STILL UNAUDITED — **~132 files** — only bucket C remains (see HANDOFF.md + METHODOLOGY.md):
  - **C. Remaining tests/ subtrees** (~130): tests/ top-level (19), backend/comprehensive (14), volunteer (12), workflows (11), backend/workflows (9), email (8), events (7), www (5), membership (5), financial (5), fixtures (4), backend/{security 4, features 4, business_logic 3, unit/controllers 3}, scalability (3), unit/utils (2), performance (2), + small dirs (safety, resilience, repositories, frontend/integration, e2e, billing, backend/unit/doctype).
  - (Buckets A + B are now DONE — Phase 8. If the earlier `utils/migration` stray was expected in B, confirm it during bucket C.)
