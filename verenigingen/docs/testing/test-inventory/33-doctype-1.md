# Test Inventory 33 — Co-located DocType Controller Tests, Part 1 (DT1)

> Audit complete (26/26 files). READ-ONLY classification of every
> class-level `def test_*` in 26 co-located DocType test files
> (`account_creation_request` … `member_contact_request`).
> Categories: HAPPY / UNHAPPY / EDGE / OTHER.

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| account_creation_request/test_account_creation_request_coverage.py | 25 | 10 | 8 | 6 | 1 |
| analytics_alert_rule/test_analytics_alert_rule_coverage.py | 28 | 15 | 2 | 6 | 5 |
| api_audit_log/test_api_audit_log.py | 8 | 3 | 3 | 2 | 0 |
| brand_settings/test_brand_settings_endpoints.py | 8 | 4 | 0 | 4 | 0 |
| brand_settings/test_brand_settings.py | 27 | 13 | 2 | 10 | 2 |
| bulk_operation_tracker/test_bulk_operation_tracker.py | 0 | 0 | 0 | 0 | 0 |
| chapter_join_request/test_chapter_join_request_coverage.py | 22 | 10 | 4 | 5 | 3 |
| chapter_join_request/test_chapter_join_request.py | 13 | 3 | 3 | 4 | 3 |
| chapter_member/test_chapter_members.py | 6 | 2 | 0 | 3 | 1 |
| chapter_role/test_chapter_role.py | 3 | 1 | 0 | 1 | 1 |
| chapter/test_chapter_coverage.py | 41 | 19 | 7 | 10 | 5 |
| chapter/test_chapter_head.py | 6 | 2 | 1 | 3 | 0 |
| chapter/test_chapter.py | 19 | 13 | 1 | 1 | 4 |
| chapter/test_chapter_volunteer_integration.py | 3 | 1 | 1 | 1 | 0 |
| contribution_amendment_request/test_contribution_amendment_request_coverage.py | 24 | 6 | 11 | 7 | 0 |
| critical_operation_rule/test_critical_operation_rule_extra.py | 19 | 8 | 6 | 5 | 0 |
| critical_operation_rule/test_critical_operation_rule.py | 8 | 4 | 1 | 3 | 0 |
| donation_campaign/test_donation_campaign_coverage.py | 27 | 7 | 6 | 12 | 2 |
| donation/test_donation_coverage.py | 17 | 5 | 1 | 11 | 0 |
| donation/test_donation.py | 29 | 17 | 8 | 4 | 0 |
| donor/test_donor_coverage.py | 19 | 12 | 0 | 7 | 0 |
| donor/test_donor.py | 7 | 3 | 1 | 3 | 0 |
| event_contact_campaign/test_event_contact_campaign.py | 36 | 16 | 6 | 14 | 0 |
| expense_category/test_expense_category.py | 9 | 3 | 3 | 3 | 0 |
| expulsion_report_entry/test_expulsion_report_entry.py | 17 | 6 | 3 | 8 | 0 |
| member_contact_request/test_contact_request_automation.py | 15 | 8 | 1 | 5 | 1 |
| **DOMAIN TOTALS** | **436** | **191** | **79** | **138** | **28** |

## Observations

- **Coverage skew: HAPPY-heavy, UNHAPPY thin.** Across all 26 files the mix is
  HAPPY 191 (44%) / EDGE 138 (32%) / UNHAPPY 79 (18%) / OTHER 28 (6%).
  Asserted-failure/rejection testing is the thinnest slice — and even that
  overstates it, because much genuine rejection intent is folded into EDGE:
  graceful-fallback return values (`status: "warning"/"info"`, empty lists,
  `1=0` permission conditions), duplicate/replay guards, and empty/null/boundary
  cases. This matches the app-wide ~17% UNHAPPY headline.
- **Strongest files.** `chapter/test_chapter_coverage.py` (41), the newly-audited
  `event_contact_campaign/test_event_contact_campaign.py` (36 — a disciplined
  spread covering date validation, round-robin distribution, and full
  `get_permission_query_conditions` + `has_permission` role matrices), and
  `donation/test_donation.py` (29 — real `validate()` purpose/ANBI branches plus
  whitelisted `create_donor_from_donation` / `generate_anbi_agreement_number`).
  `contribution_amendment_request` (24) is the outlier for negative-path depth
  (11/24 UNHAPPY).
- **Regression tripwires are high-value EDGE.** `expulsion_report_entry` is
  largely a guard suite for the unshipped "Termination Appeals Process" doctype
  (5 methods assert graceful degradation of save/statistics/governance-report/
  member-history that previously crashed), and `donation` pins the
  `belastingdienst_reportable` + ANBI-field regressions. These are meaningful
  boundary tests, not filler.
- **Weak / dead / tautological.** `bulk_operation_tracker/test_bulk_operation_tracker.py`
  has zero class-level test methods (see below). The one OTHER in the new batch
  is `test_get_analytics_returns_expected_structure` in
  `test_contact_request_automation.py` — shape-only (`assertIn` on dict keys, no
  values pinned). `expense_category` tests are all `skipTest`-guarded on
  company/expense-account availability, so they silently no-op on a bare site.
- **Mock discipline is good.** Patches in the new files are confined to true
  collaborators (`frappe.sendmail`, `frappe.enqueue`) while real controller and
  `validate()` logic runs against the DB — no mock-into-tautology observed.
- **Base classes: conventional but mixed.** `EnhancedTestCase` (donation),
  `VereningingenTestCase` (donor_coverage, event_contact_campaign, expulsion,
  contact_request_automation), plain `FrappeTestCase` (donor) and one hand-rolled
  `unittest.TestCase` with manual account setup/teardown (`expense_category`) —
  the only non-factory fixture pattern in this batch.

## Zero-method / missing files

- **`bulk_operation_tracker/test_bulk_operation_tracker.py`** — present but
  contains no class-level `def test_*` method (counted as 0/0/0/0/0). It is an
  empty/stub test file and exercises nothing.
- **`member_contact_request/test_member_contact_request_coverage.py`** — exists
  but is deliberately excluded from this report (owned by another inventory
  report) and is therefore not counted in the totals above.
- All 26 counted files were located and classified; no target file was missing
  from disk.
