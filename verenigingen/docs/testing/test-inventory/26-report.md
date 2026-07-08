# Test Inventory — Domain 26: tests/report

Audit complete. 29 files, 421 test methods classified.

Classification legend: HAPPY = nominal success/expected output · UNHAPPY = expects error/throw/validation-failure/permission-denial · EDGE = boundary/empty/null/ordering/date-range/filter-combo · OTHER = smoke/import-safety/shape-only/tautological/skip-dominated.

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_account_creation_status.py | 13 | 5 | 0 | 5 | 3 |
| test_anbi_periodic_agreements.py | 14 | 3 | 0 | 10 | 1 |
| test_bulk_operations_performance_report.py | 12 | 1 | 0 | 8 | 3 |
| test_chapter_dues_split.py | 11 | 4 | 0 | 6 | 1 |
| test_chapter_expense_report_gapfill.py | 12 | 3 | 5 | 4 | 0 |
| test_chapter_members.py | 10 | 1 | 2 | 6 | 1 |
| test_database_table_size_analysis.py | 13 | 3 | 0 | 6 | 4 |
| test_expiring_memberships.py | 9 | 1 | 0 | 6 | 2 |
| test_member_age_groups.py | 6 | 1 | 0 | 3 | 2 |
| test_member_pronoun_distribution.py | 6 | 2 | 0 | 3 | 1 |
| test_member_end_date_reconstruction.py | 21 | 10 | 2 | 7 | 2 |
| test_membership_dues_coverage_analysis.py | 33 | 16 | 5 | 8 | 4 |
| test_membership_dues_coverage_analysis_gapfill.py | 26 | 16 | 0 | 10 | 0 |
| test_members_without_active_memberships.py | 24 | 7 | 0 | 12 | 5 |
| test_members_without_chapter.py | 21 | 6 | 0 | 11 | 4 |
| test_members_without_dues_schedule.py | 16 | 6 | 0 | 8 | 2 |
| test_members_without_dues_schedule_gapfill.py | 18 | 8 | 2 | 7 | 1 |
| test_members_without_payment_info.py | 18 | 5 | 0 | 9 | 4 |
| test_mijnrood_member_reconciliation_gapfill.py | 12 | 5 | 0 | 6 | 1 |
| test_mollie_balance_report.py | 5 | 0 | 0 | 3 | 2 |
| test_mollie_subscription_audit.py | 4 | 0 | 2 | 0 | 2 |
| test_orphaned_child_table_records.py | 4 | 1 | 0 | 0 | 3 |
| test_new_members.py | 14 | 4 | 0 | 8 | 2 |
| test_overdue_member_payments.py | 31 | 13 | 0 | 13 | 5 |
| test_pending_membership_applications.py | 22 | 7 | 0 | 11 | 4 |
| test_recent_chapter_changes.py | 15 | 6 | 0 | 5 | 4 |
| test_team_members.py | 7 | 1 | 2 | 3 | 1 |
| test_users_by_team.py | 8 | 1 | 0 | 4 | 3 |
| test_volunteer_activity_by_tag.py | 16 | 4 | 0 | 10 | 2 |
| **DOMAIN TOTALS** | **421** | **140** | **20** | **192** | **69** |

## Observations

- **Real value-asserting, not shape-only.** Despite the report domain's temptation toward tautology, the overwhelming majority (~83%, 332/421 across Happy+Unhappy+Edge) assert real row values, computed fields, classifications, filter effects, or throws. Genuinely shape-only/tautological tests account for only ~69/421 (16% OTHER), and those are mostly the boilerplate `test_get_columns_structure` / `test_execute_returns_five_tuple` pair present once per file plus chart-shape smoke.

- **Edge-heavy domain (192/421, 46%).** This reflects the reports' nature: nearly every report has a battery of filter, exclusion, empty-data, and date-range tests. Filters and "excluded by default" cases dominate. Empty-data guards (`get_summary([]) == []`, `get_chart_data([]) is None`) are near-universal and correctly classified EDGE since they assert correct boundary behavior, not just structure.

- **Strongest files** (deep business-logic coverage): `test_membership_dues_coverage_analysis.py` (33 tests — gap classification thresholds, book-year math, billing-period splitting, filter validation throws) and its `_gapfill` sibling (26, all Happy/Edge, zero filler); `test_member_end_date_reconstruction.py` (21 — confidence inference from SEPA/Mollie/invoice/payment signals plus apply-suggestion rejects); `test_overdue_member_payments.py` (31 — status-indicator bands, grace-period states, aggregation).

- **Unhappy tests are concentrated and legitimate (20 total).** They cluster in: filter-validation throws (`membership_dues_coverage_analysis` — reversed dates, nonexistent member/chapter, bad frequency/severity), permission-restriction hiding (`chapter_expense_report_gapfill` — 5 non-admin visibility-denial tests), missing-required-filter throws (`chapter_members`, `team_members`, `mollie_subscription_audit`), and apply-action rejects (`member_end_date_reconstruction`, `members_without_dues_schedule_gapfill`). No report over-relies on throw-testing.

- **Weakest / filler-leaning files.** `test_mollie_balance_report.py` (5 tests, 0 Happy — all disabled/empty/shape because the live Mollie backend is unavailable in tests) and `test_mollie_subscription_audit.py` (4 tests, only credential-raises + column shape) are the thinnest; both are external-API-gated so limited real assertion is expected. `test_orphaned_child_table_records.py` (4, mostly shape) is also light but has one real seeded-orphan detection test.

- **A few tautology leaks flagged.** In `test_recent_chapter_changes.py`, `test_days_threshold_excludes_old_modifications` and `test_to_date_with_from_date_builds_between_filter` only assert `isInstance(data, list)` (classified OTHER, not EDGE, since they verify nothing about the filter they name). `test_overdue_member_payments.py::test_is_membership_related_always_true` is explicitly tautological (asserts a function that always returns True).

- **Base class & consistency.** All files use `VereningingenTestCase` (Enhanced factory base) with the `assertNoErrorLog()` guard wrapping `execute()` calls — a consistent, disciplined pattern across the whole domain. No `@unittest.skip`-dominated or dead files found; the single `skipTest` is a legitimate month-boundary guard in `test_chapter_dues_split.py::test_default_date_range_is_current_month`.

## Notes on completeness

- All 29 files audited; no zero-method or missing files. Every file contained at least 4 class-level `def test_*` methods.
- `_gapfill` files are coverage-completion siblings that target uncovered branches of an already-tested report; they skew Happy/Edge with near-zero OTHER filler (e.g. `membership_dues_coverage_analysis_gapfill` = 0 OTHER), which is the healthiest sub-pattern in the domain.
