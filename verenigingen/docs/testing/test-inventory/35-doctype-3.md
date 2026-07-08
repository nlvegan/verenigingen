# Test Inventory — Domain DT3: Co-located DocType Controller Tests (Part 3)

> **Audit complete (26/26 files).** READ-ONLY classification of every class-level `def test_*`
> across the co-located DocType controller tests from `mijnrood_csv_import` … `volunteer`.
> Each method gets exactly one intent type: HAPPY (nominal success) / UNHAPPY (expects
> error/rejection) / EDGE (boundary/empty/null/duplicate/fallback/malformed) / OTHER
> (smoke/tautological/schema-meta/skip-dominated/mock-into-tautology).

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| mijnrood_csv_import/test_mijnrood_csv_import_coverage.py | 7 | 3 | 1 | 3 | 0 |
| mijnrood_csv_import/test_mijnrood_csv_import_gapfill.py | 15 | 4 | 3 | 8 | 0 |
| mijnrood_csv_import/test_mijnrood_csv_import_orchestration_gaps.py | 9 | 3 | 3 | 3 | 0 |
| mijnrood_csv_import/test_mijnrood_csv_import_orchestration.py | 6 | 5 | 0 | 1 | 0 |
| mijnrood_csv_import/test_mijnrood_csv_import_pipeline.py | 28 | 13 | 5 | 10 | 0 |
| mijnrood_csv_import/test_mijnrood_csv_import.py | 49 | 14 | 16 | 18 | 1 |
| mijnrood_csv_import/test_mijnrood_csv_import_reports.py | 7 | 1 | 1 | 5 | 0 |
| mt940_import/test_mt940_import_coverage.py | 7 | 1 | 1 | 5 | 0 |
| mt940_import/test_mt940_import.py | 25 | 8 | 7 | 10 | 0 |
| performance_optimization_setup/test_performance_optimization_setup.py | 19 | 10 | 5 | 3 | 1 |
| periodic_donation_agreement/test_periodic_donation_agreement_coverage.py | 41 | 19 | 14 | 8 | 0 |
| procurios_csv_import/test_procurios_csv_import_coverage.py | 8 | 3 | 1 | 4 | 0 |
| region/test_region.py | 51 | 17 | 16 | 18 | 0 |
| team/test_team_coverage.py | 21 | 12 | 3 | 6 | 0 |
| team/test_team.py | 9 | 9 | 0 | 0 | 0 |
| verenigingen_email_configuration/test_verenigingen_email_configuration_coverage.py | 23 | 10 | 4 | 9 | 0 |
| verenigingen_payments_settings/test_verenigingen_payments_settings.py | 0 | 0 | 0 | 0 | 0 |
| verenigingen_settings/test_verenigingen_settings.py | 6 | 1 | 1 | 1 | 3 |
| vip_import/test_vip_import.py | 47 | 18 | 3 | 25 | 1 |
| vip_import/test_vip_import_coverage.py | 9 | 5 | 0 | 4 | 0 |
| volunteer/test_volunteer.py | 30 | 15 | 1 | 1 | 13 |
| volunteer/test_volunteer_aggregated.py | 1 | 1 | 0 | 0 | 0 |
| volunteer/test_volunteer_coverage.py | 39 | 21 | 3 | 14 | 1 |
| volunteer_activity/test_volunteer_activity.py | 4 | 2 | 1 | 1 | 0 |
| volunteer_assignment/test_volunteer_assignment.py | 5 | 4 | 1 | 0 | 0 |
| volunteer_interest_category/test_volunteer_interest_category.py | 4 | 3 | 1 | 0 | 0 |
| **DOMAIN TOTALS** | **470** | **202** | **91** | **157** | **20** |

## Observations

- **Coverage shape: HAPPY-led but with a genuinely strong EDGE tier.** Domain totals across 26
  files = 470 methods → 202 HAPPY / 91 UNHAPPY (~19%) / 157 EDGE (~33%) / 20 OTHER (~4%). The
  two large coverage sweeps drive the EDGE mass on purpose: `vip_import/test_vip_import.py`
  (25/47 EDGE) and `volunteer/test_volunteer_coverage.py` (14/39 EDGE) deliberately fill the
  skip/duplicate/null/fallback/truncation branches the older sibling tests skip. Real asserted
  rejection (UNHAPPY) stays a minority because "member not found / absent identifier / empty CSV"
  cases correctly fold into EDGE per the methodology (graceful skip, not a raise).
- **Weakest file by a wide margin: `volunteer/test_volunteer.py` (30 methods, 13 OTHER = 43%).**
  Confirmed against `volunteer.json`, the fields `phone`, `address`, `development_goals`,
  `emergency_contact_*`, `training_records`, and `languages_spoken` do NOT exist on the Volunteer
  DocType, so `test_volunteer_contact_information`, `_development_tracking`, `_emergency_contact`,
  `_training_records`, and `_language_skills` either no-op under `hasattr` guards or assert an
  in-memory attribute that is never persisted (tautological). Add `_permission_system` /
  `_role_based_access` (accept any string incl. `"1=0"` — pass-either-way), `_board_integration`
  (fully `skipTest`), `_aggregated_assignments` (shape-only + known-bug TODO), `_security_validation`
  (negative check swallowed by `except Exception: pass`), `_status_tracking` (manual set/assert),
  and the two schema-contract meta tests → 13 inert methods. This file needs pruning/rewrite.
- **Strongest files: the 2026 coverage sweeps.** `volunteer/test_volunteer_coverage.py` and
  `vip_import/test_vip_import.py` build real DB records via the enhanced factory, mock only
  collaborators (a `MagicMock` import_doc, an injected `db.set_value` failure) while the real
  `_process_single_row` / `_create_volunteer` / controller-validation logic runs, and pin concrete
  values across a disciplined happy/edge/unhappy spread. These plus the mijnrood/vip `_coverage.py`
  files are where the meaningful negative-and-boundary coverage of this domain actually lives.
- **Mock discipline is good; one delegation-tautology flagged.** Only
  `test_create_volunteers_batch_uses_service` (vip) patches the very service under test and asserts
  the mock's own return + `assert_called_once` (classified OTHER — verifies wiring, regression-inert
  on business values). Everywhere else mocking is confined to boundaries.
- **UNHAPPY is concentrated in genuine rejections/throws:** underage volunteer creation, file-size
  over limit, queue-capacity-full on submit, duplicate-email uniqueness, circular interest-category
  reference, end-before-start dates, and nonexistent member link — all `assertRaises`. This is the
  real asserted-failure core (91 methods) and is spread sensibly across the import and volunteer
  controllers.
- **Base classes are consistent.** New volunteer/mijnrood/vip-coverage files use `EnhancedTestCase`
  (enhanced factory, real records, rollback cleanup); the pure-unit VIP files
  (`vip_import/test_vip_import.py`) use plain `FrappeTestCase` for the `VIPDataValidator` and
  no-DB helper functions, which is appropriate. No hand-rolled fixture anti-patterns.

## Zero-method / missing files

- **`verenigingen_payments_settings/test_verenigingen_payments_settings.py` — 0 class-level test
  methods** (empty test scaffold; carried in the table as a 0/0/0/0/0 row). The only truly empty
  file in the domain.
- All other 25 files contain ≥1 class-level `def test_*` and were audited.
- **Non-empty but effectively inert** (kept in their files' counts, flagged above, not "missing"):
  the five schema-absent field tests in `test_volunteer.py`, plus `test_volunteer_board_integration`
  (fully `skipTest`-ped). These execute but assert nothing meaningful against the real schema.
- No stray module-level `def test_*` outside test classes were found in these 9 files; the
  `if __name__ == "__main__": unittest.main()` block in `vip_import.py` is not a test.
