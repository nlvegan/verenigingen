# Design: Test Suite Phase 1 — Dead Code Deletion

**Date:** 2026-03-03
**Audit reference:** `docs/audits/test-suite-audit-2026-03-03.md`
**Scope:** Delete ~62K LOC of verified-dead test files, scripts, and archived validators
**Risk:** Zero — all targets have zero callers/imports

## Targets

### Commit 1 — Unused archived validators (~32K LOC)
Delete ~88 of 97 files in `scripts/validation/archived/`. Keep 9 files still referenced in `.pre-commit-config.yaml`:
- `block_inappropriate_mocks.py`
- `codanna_deprecated_checker.py`
- `database_field_reference_validator.py`
- `doctype_field_validator.py`
- `email_template_precommit_check.py`
- `frappe_api_confidence_validator.py`
- `frappe_hooks_validator.py`
- `method_resolution_validator.py`
- `validation_orchestrator.py`

### Commit 2 — Orphaned scripts/testing (~26K LOC)
Delete ~122 of 125 files in `scripts/testing/`. Keep 3 active files:
- `pytest_precommit_runner.py`
- `test_coverage_report.py`
- `jest-precommit-wrapper.sh`

### Commit 3 — Broken archived test (256 LOC)
Delete `archived/tests/test_payment_optimization.py` + `__pycache__`. Remove `archived/` if empty.

### Commit 4 — Demo/educational test files (~1,200 LOC)
- `vereiningen/tests/backend/comprehensive/test_comprehensive_suite_demo.py`
- `vereiningen/tests/backend/components/test_overdue_payments_mock_elimination_demo.py`
- `vereiningen/tests/integration/test_payment_api_a_plus_demo.py`
- `vereiningen/tests/integration/test_phase4d_mock_elimination_demo_simple.py`

### Commit 5 — Mollie spike/debug files (~850 LOC)
- `vereiningen/vereiningen_payments/mollie/tests/interactive_subscription_test.py`
- `vereiningen/vereiningen_payments/mollie/tests/complete_payment_test.py`
- `vereiningen/vereiningen_payments/mollie/tests/page_test_mollie.py`

### Commit 6 — Superseded `_OLD` test (~450 LOC)
- `vereiningen/tests/integration/test_query_optimization_suite_old.py`

## Safety

- Before each deletion batch: grep for imports/references
- After all commits: `pre-commit run --all-files`
- Clean `whitelist_files.txt` of any deleted file references
- Clean up empty `__pycache__` directories

## Not In Scope

- Duplicate test consolidation (Phase 2)
- Directory reorganization (Phase 3)
- Quality improvements (Phase 4)
- Coverage gap remediation (Phase 5)
