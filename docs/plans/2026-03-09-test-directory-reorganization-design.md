# Design: Test Suite Phase 3 — Directory Reorganization

**Date:** 2026-03-09
**Audit reference:** `docs/audits/test-suite-audit-2026-03-03.md`
**Scope:** Move ~200 top-level test files into domain subdirectories + clean up iterative suffixes
**Risk:** Low-Medium — `git mv` preserves history; tests aren't imported by production code
**LOC impact:** ~0 net (organizational only, plus small deletions of dead runners)

## Problem

After Phase 1+2 deleted 71.5K LOC of dead/duplicate files, 215 test files (~91K LOC) remain directly in `vereiningen/tests/` — a flat "dumping ground" with no domain organization. Files are named with iterative suffixes (`_comprehensive`, `_enhanced`, `_proper`, `_real`, `_fixed`) from a development pattern where old variants were never deleted.

## Strategy

1. **Move** ~200 top-level files into domain subdirectories (hybrid: use existing dirs + create new domain dirs for large groups)
2. **Rename** ~20 sole-variant files to remove stale suffixes
3. **Delete** ~7 dead test runner scripts
4. **Keep** ~10 cross-cutting/infrastructure files at top level

## Target Directory Mapping

### New Directories (created for large domain groups)

| Target | Source Files | LOC | Description |
|--------|-------------|-----|-------------|
| `tests/sepa/` | 30 | ~14K | SEPA mandates, direct debit, IBAN, Ponto banking |
| `tests/payment/` | 56 | ~18K | Payment processing, billing, Mollie clients, invoices, dues, fees, prorating |
| `tests/member/` | 25 | ~11K | Member lifecycle, accounts, applications, merges, profiles |
| `tests/chapter/` | 20 | ~10K | Chapter boards, permissions, team roles, role profiles |
| `tests/donor/` | 17 | ~9K | Donor management, ANBI compliance, donation agreements |
| `tests/email/` | 8 | ~3K | Email delivery, newsletters, notifications, XSS protection |

### Existing Directories (receiving additional files)

| Target | New Files | LOC | Already Has |
|--------|-----------|-----|-------------|
| `tests/security/` | 16 | ~7K | 6 existing files |
| `tests/financial/` | 7 | ~3K | 2 existing files |
| `tests/backend/validation/` | 13 | ~5K | 5 existing files |
| `tests/e_boekhouden/` | 1 | ~2K | 18 existing files |

### Top-Level (kept)

| File | LOC | Reason |
|------|-----|--------|
| `__init__.py` | 12 | Package init |
| `base_test_case.py` | 7 | Base class |
| `frappe_mock.py` | 236 | Shared mock utilities |
| `test_runner.py` | 23 | Test orchestrator |
| `test_hooks_modules.py` | 1010 | Cross-cutting hooks validation |
| `test_operation_result.py` | 1195 | Cross-cutting pattern tests |
| `test_frappe_core_integration_boundaries.py` | 694 | Framework boundary tests |
| `test_all_imports.py` | 220 | Import smoke test |
| `test_harness.py` | 428 | Test infrastructure |
| `test_utils.py` | 5 | Utility stubs |
| `mollie_test_orchestrator.py` | 354 | Mollie test coordination |

### Deletions (dead runners/stubs)

| File | LOC | Reason |
|------|-----|--------|
| `test_framework_enhanced.py` | 16 | Stub (16 LOC, no real tests) |
| `test_enhanced_factory.py` | 201 | Superseded by CoreTestDataFactory |

## Suffix Cleanup

### Safe Renames (sole variant, no base version exists)

| Current Name | New Name | Dir |
|-------------|----------|-----|
| `test_api_endpoints_comprehensive.py` | `test_api_endpoints.py` | validation/ |
| `test_chapter_join_request_comprehensive.py` | `test_chapter_join_request.py` | chapter/ |
| `test_sepa_performance_optimizations_comprehensive.py` | `test_sepa_performance_optimizations.py` | sepa/ |
| `test_financial_reconciliation_comprehensive.py` | `test_financial_reconciliation.py` | backend/components/ |
| `test_membership_status_comprehensive.py` | `test_membership_status.py` | backend/components/ |
| `test_dd_batch_edge_cases_comprehensive.py` | `test_dd_batch_edge_cases.py` | backend/comprehensive/ |
| `test_doctype_validation_comprehensive.py` | `test_doctype_validation.py` | backend/comprehensive/ |
| `test_api_optimization_comprehensive.py` | `test_api_optimization.py` | backend/performance/ |
| `test_cost_center_creation_comprehensive.py` | `test_cost_center_creation.py` | e_boekhouden/ |
| `test_authentication_flows_comprehensive.py` | `test_authentication_flows.py` | integration/ |
| `test_monitoring_system_comprehensive.py` | `test_monitoring_system.py` | integration/ |
| `test_employee_user_link_security_fixed.py` | `test_employee_user_link_security.py` | integration/ |
| `test_membership_approval_real.py` | `test_membership_approval.py` | integration/ |
| `test_sepa_payment_workflow_real.py` | `test_sepa_payment_workflow.py` | integration/ |
| `test_toctou_comprehensive.py` | `test_toctou.py` | security/ |
| `test_suspension_api_import_fallback_real.py` | `test_suspension_api_import_fallback.py` | backend/workflows/ |
| `test_financial_workflows_complete.py` | `test_financial_workflows.py` | workflows/ |

### Suffix Stays (base version exists — collision)

Files like `test_billing_transitions_proper.py` (base `test_billing_transitions.py` exists), `test_chapter_board_permissions_comprehensive.py` (base + 2 other variants exist), etc. — these keep their current names. Further consolidation is out of scope for Phase 3.

## Migration Approach

- One commit per domain group (10 commits total)
- `git mv` for all moves (preserves history)
- Each commit: move files → add `__init__.py` if new dir → verify no broken imports
- No backward-compat shims (test files aren't imported by production code)
- Cross-domain files placed by primary domain (e.g., `test_payment_failure_email_templates.py` → `payment/`)

## Commits

1. Create new domain directories + `__init__.py` files
2. Move SEPA/Banking files (~30 files)
3. Move Payment/Billing/Mollie files (~56 files)
4. Move Member/Membership files (~25 files)
5. Move Chapter/Board files (~20 files)
6. Move Donor/ANBI files (~17 files)
7. Move Security files (~16 files)
8. Move Email + Volunteer + Expense + E-Boekhouden + Validation files (~42 files)
9. Rename sole-variant suffixed files (~17 renames in existing subdirs)
10. Delete dead runners + verify + clean whitelist

## Not In Scope

- Merging the duplicate directory pairs (`integration/` vs `backend/integration/`, etc.)
- Consolidating multi-variant test groups (16 SEPA mandate variants, etc.)
- Converting mock-heavy tests to real DB (Phase 4)
- Adding missing test coverage (Phase 5)
